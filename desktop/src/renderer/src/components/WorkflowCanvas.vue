<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Maximize2, ZoomIn, ZoomOut } from 'lucide-vue-next'
import WorkflowNode from './WorkflowNode.vue'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'

interface WorkflowNode {
  id: string
  action_id: string
  config: Record<string, unknown>
  position?: { x: number; y: number }
}

interface WorkflowEdge {
  source: string
  target: string
  condition?: string
  source_handle?: string
}

interface WorkflowItem {
  id: string
  name: string
  nodes?: WorkflowNode[]
  edges?: WorkflowEdge[]
}

interface ValidationIssue {
  code: string
  message: string
  node_id?: string
  severity?: string
}

const props = defineProps<{
  workflow: WorkflowItem | null
  issues?: ValidationIssue[]
  interactive?: boolean
}>()

const canvasRef = ref<HTMLElement | null>(null)
const dimensionsReady = ref(false)
let resizeObserver: ResizeObserver | null = null

const NODE_WIDTH = 232
const NODE_HEIGHT = 112
const NODE_GAP = 28

function validPosition(position: { x: number; y: number } | undefined, index: number): { x: number; y: number } {
  const x = Number(position?.x)
  const y = Number(position?.y)
  return {
    x: Number.isFinite(x) ? x : 80 + (index % 3) * 260,
    y: Number.isFinite(y) ? y : 70 + Math.floor(index / 3) * 160
  }
}

function overlaps(a: { x: number; y: number }, b: { x: number; y: number }): boolean {
  return a.x < b.x + NODE_WIDTH + NODE_GAP
    && a.x + NODE_WIDTH + NODE_GAP > b.x
    && a.y < b.y + NODE_HEIGHT + NODE_GAP
    && a.y + NODE_HEIGHT + NODE_GAP > b.y
}

function separatedPosition(position: { x: number; y: number }, occupied: Array<{ x: number; y: number }>): { x: number; y: number } {
  const candidate = { ...position }
  let attempts = 0
  while (occupied.some((item) => overlaps(candidate, item)) && attempts < 100) {
    const row = Math.floor(attempts / 4)
    const column = attempts % 4
    candidate.x = position.x + column * (NODE_WIDTH + NODE_GAP)
    candidate.y = position.y + (row + 1) * (NODE_HEIGHT + NODE_GAP)
    attempts += 1
  }
  return candidate
}

const emit = defineEmits<{
  nodeSelect: [nodeId: string]
  nodeAdd: [actionId: string, position: { x: number; y: number }]
  nodeDelete: [nodeId: string]
  connect: [connection: { source: string; target: string; sourceHandle?: string | null }]
  disconnect: [edgeId: string]
  nodePositionChange: [nodeId: string, position: { x: number; y: number }]
}>()

// 转换节点数据
const nodes = computed(() => {
  if (!props.workflow?.nodes) return []

  const occupied: Array<{ x: number; y: number }> = []
  return props.workflow.nodes.map((node, index) => {
    const hasIssue = props.issues?.some(issue => issue.node_id === node.id)
    // Keep an explicitly saved position exactly where the user dropped it.
    // Only auto-separate nodes that have never been positioned.
    const hasPosition = Number.isFinite(Number(node.position?.x)) && Number.isFinite(Number(node.position?.y))
    const position = hasPosition
      ? validPosition(node.position, index)
      : separatedPosition(validPosition(node.position, index), occupied)
    occupied.push(position)

    return {
      id: node.id,
      type: 'custom',
      position,
      data: {
        label: node.id,
        action_id: node.action_id,
        config: node.config,
        state: hasIssue ? 'attention' : 'ready'
      }
    }
  })
})

// 转换边数据
const edges = computed(() => {
  if (!props.workflow?.edges) return []

  return props.workflow.edges.map(edge => ({
    id: `${edge.source}-${edge.source_handle || 'default'}-${edge.target}`,
    source: edge.source,
    target: edge.target,
    type: edge.condition ? 'smoothstep' : 'default',
    label: edge.condition === 'true' ? '满足' : edge.condition === 'false' ? '不满足' : '',
    animated: false,
    style: {
      stroke: edge.condition ? '#fbbf24' : '#64748b',
      strokeWidth: 2
    },
    labelStyle: {
      fill: '#fcd34d',
      fontSize: '12px',
      fontWeight: 600
    }
  }))
})

// Vue Flow 事件处理
const {
  onConnect,
  onNodeDragStop,
  onNodeClick,
  onEdgeClick,
  onPaneClick,
  screenToFlowCoordinate,
  fitView,
  zoomIn,
  zoomOut,
  setInteractive
} = useVueFlow()

watch(
  () => props.interactive !== false,
  (enabled) => setInteractive(enabled),
  { immediate: true }
)

onConnect((params) => {
  emit('connect', {
    source: params.source as string,
    target: params.target as string,
    sourceHandle: params.sourceHandle
  })
})

onNodeDragStop((event) => {
  emit('nodePositionChange', event.node.id, event.node.position)
})

onNodeClick((event) => {
  emit('nodeSelect', event.node.id)
})

onPaneClick(() => {
  emit('nodeSelect', '')
})

onEdgeClick((event) => {
  emit('disconnect', event.edge.id)
})

function onDragOver(event: DragEvent): void {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onDrop(event: DragEvent): void {
  event.preventDefault()
  const actionId = event.dataTransfer?.getData('application/x-workflow-action') || event.dataTransfer?.getData('text/plain')
  if (!actionId) return
  const target = event.currentTarget as HTMLElement | null
  const bounds = target?.getBoundingClientRect()
  if (!bounds || bounds.width <= 0 || bounds.height <= 0) return
  const position = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  if (!Number.isFinite(position.x) || !Number.isFinite(position.y)) return
  emit('nodeAdd', actionId, { x: Math.round(position.x - 110), y: Math.round(position.y - 55) })
}

function updateDimensions(): void {
  const element = canvasRef.value
  if (!element) return
  const bounds = element.getBoundingClientRect()
  dimensionsReady.value = Number.isFinite(bounds.width) && Number.isFinite(bounds.height) && bounds.width > 1 && bounds.height > 1
}

async function fitCanvas(): Promise<void> {
  await fitView({ padding: 0.2, duration: 220 })
}

onMounted(async () => {
  await nextTick()
  updateDimensions()
  if (canvasRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(updateDimensions)
    resizeObserver.observe(canvasRef.value)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div ref="canvasRef" class="workflow-canvas" @dragenter.capture.prevent="onDragOver" @dragover.capture="onDragOver" @drop.capture="onDrop">
    <VueFlow
      v-if="dimensionsReady"
      :nodes="nodes"
      :edges="edges"
      :nodes-draggable="props.interactive !== false"
      :nodes-connectable="props.interactive !== false"
      :pan-on-drag="props.interactive !== false ? [1, 2] : false"
      :default-zoom="1"
      :min-zoom="0.2"
      :max-zoom="4"
      :default-viewport="{ x: 0, y: 0, zoom: 1 }"
      :fit-view-on-init="true"
      class="vue-flow-wrapper"
    >
      <!-- 自定义节点 -->
      <template #node-custom="customNodeProps">
        <WorkflowNode v-bind="customNodeProps" />
      </template>

      <div class="canvas-floating-toolbar" @pointerdown.stop @click.stop>
        <button type="button" class="canvas-fit-button" title="适配全部节点" aria-label="适配全部节点" @click.stop="fitCanvas">
          <Maximize2 :size="14" />
          <span>适配</span>
        </button>
        <button type="button" title="放大" aria-label="放大" @click.stop="zoomIn({ duration: 160 })">
          <ZoomIn :size="14" />
        </button>
        <button type="button" title="缩小" aria-label="缩小" @click.stop="zoomOut({ duration: 160 })">
          <ZoomOut :size="14" />
        </button>
      </div>

      <!-- 背景 -->
      <Background
        pattern-color="#334155"
        :gap="20"
        :size="1"
      />

      <div v-if="!nodes.length" class="workflow-canvas-empty">
        <div class="workflow-canvas-empty-icon">+</div>
        <strong>把节点拖到这里</strong>
        <span>从左侧节点库选择一个动作开始搭建流程</span>
      </div>
    </VueFlow>
    <div v-if="!dimensionsReady" class="workflow-canvas-loading">正在准备画布…</div>
  </div>
</template>


<style scoped>
.workflow-canvas { position: relative; width: 100%; height: 100%; min-width: 0; min-height: 0; background: var(--workflow-bg, #0b1220); }
.vue-flow-wrapper { width: 100%; height: 100%; min-height: 0; border: 0; }
.canvas-floating-toolbar { position: absolute; top: 12px; right: 12px; z-index: 5; display: inline-flex; align-items: center; gap: 2px; min-height: 32px; padding: 3px; border: 1px solid rgba(100,116,139,.42); border-radius: 7px; background: rgba(15,23,42,.88); box-shadow: 0 7px 18px rgba(2,6,23,.24); backdrop-filter: blur(8px); }
.canvas-floating-toolbar button { display: grid; width: 26px; height: 26px; padding: 0; place-items: center; border: 0; border-radius: 4px; color: rgba(226,232,240,.7); background: transparent; cursor: pointer; }
.canvas-floating-toolbar .canvas-fit-button { display: inline-flex; width: auto; gap: 4px; padding: 0 8px; font-size: 10px; }
.canvas-floating-toolbar button:hover { color: #bfdbfe; background: rgba(37,99,235,.24); }
.workflow-canvas-empty, .workflow-canvas-loading { position: absolute; inset: 0; display: grid; place-content: center; justify-items: center; gap: 8px; color: var(--workflow-muted, rgba(226,232,240,.66)); pointer-events: none; }
.workflow-canvas-empty { margin: 54px; border: 1px dashed rgba(96,165,250,.34); border-radius: 12px; }
.workflow-canvas-empty strong { color: var(--workflow-text, #dbeafe); font-size: 13px; }
.workflow-canvas-empty span { color: var(--workflow-subtle, rgba(226,232,240,.46)); font-size: 11px; }
.workflow-canvas-empty-icon { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid rgba(96,165,250,.6); border-radius: 8px; color: #93c5fd; font-size: 20px; font-weight: 300; }
.workflow-canvas-loading { font-size: 12px; }
:deep(.vue-flow__background pattern circle) { fill: rgba(100,116,139,.34); }
:deep(.vue-flow__edge-path) { stroke: #64748b; stroke-width: 1.6; }
:deep(.vue-flow__edge.selected .vue-flow__edge-path) { stroke: #4f9cf9; stroke-width: 2; }
:deep(.vue-flow__edge-text) { fill: #fcd34d; font-size: 10px; }
:global(:root[data-theme="light"]) .workflow-canvas { background: #f8fafc; }
:global(:root[data-theme="light"]) .canvas-floating-toolbar { border-color: #cbd5e1; background: rgba(255,255,255,.94); box-shadow: 0 7px 18px rgba(15,23,42,.12); }
:global(:root[data-theme="light"]) .canvas-floating-toolbar button { color: #475569; }
:global(:root[data-theme="light"]) .canvas-floating-toolbar button:hover { color: #1d4ed8; background: #eaf2ff; }
:global(:root[data-theme="light"]) .workflow-canvas-empty, :global(:root[data-theme="light"]) .workflow-canvas-loading { color: #64748b; }
:global(:root[data-theme="light"]) .workflow-canvas-empty strong { color: #172033; }
:global(:root[data-theme="light"]) .workflow-canvas-empty span { color: #718096; }
:global(:root[data-theme="light"]) :deep(.vue-flow__edge-path) { stroke: #94a3b8; }
:global(:root[data-theme="light"]) :deep(.vue-flow__edge.selected .vue-flow__edge-path) { stroke: #2563eb; }
</style>
