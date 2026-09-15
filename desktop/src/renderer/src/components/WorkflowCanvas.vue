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

function validPosition(position: { x: number; y: number } | undefined, index: number): { x: number; y: number } {
  const x = Number(position?.x)
  const y = Number(position?.y)
  return {
    x: Number.isFinite(x) ? x : 80 + (index % 3) * 260,
    y: Number.isFinite(y) ? y : 70 + Math.floor(index / 3) * 160
  }
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

  return props.workflow.nodes.map((node, index) => {
    const hasIssue = props.issues?.some(issue => issue.node_id === node.id)

    return {
      id: node.id,
      type: 'custom',
      position: validPosition(node.position, index),
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
      :pan-on-drag="props.interactive !== false"
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
.workflow-canvas {
  width: 100%;
  height: 100%;
  min-height: 520px;
  min-width: 0;
  background: #0b1220;
  position: relative;
}

.vue-flow-wrapper {
  width: 100%;
  height: 100%;
  min-height: 520px;
  border: 0;
}

.canvas-floating-toolbar {
  position: absolute;
  top: 14px;
  right: 14px;
  z-index: 5;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  min-height: 34px;
  padding: 4px;
  border: 1px solid rgba(100, 116, 139, 0.5);
  border-radius: 8px;
  background: rgba(15, 23, 42, 0.88);
  box-shadow: 0 8px 24px rgba(2, 6, 23, 0.28);
  backdrop-filter: blur(10px);
}

.canvas-floating-toolbar button {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 0;
  border-radius: 5px;
  color: rgba(226, 232, 240, 0.7);
  background: transparent;
  cursor: pointer;
}

.canvas-floating-toolbar .canvas-fit-button {
  display: inline-flex;
  width: auto;
  padding: 0 8px;
  gap: 4px;
  font-size: 10px;
}

.canvas-floating-toolbar button:hover,
.canvas-floating-toolbar button.active {
  color: #dbeafe;
  background: rgba(59, 130, 246, 0.28);
}

.workflow-canvas-empty,
.workflow-canvas-loading {
  position: absolute;
  inset: 0;
  display: grid;
  place-content: center;
  justify-items: center;
  gap: 9px;
  color: rgba(226, 232, 240, 0.66);
  pointer-events: none;
}

.workflow-canvas-empty strong { color: #dbeafe; font-size: 14px; }
.workflow-canvas-empty span { color: rgba(226, 232, 240, 0.46); font-size: 11px; }
.workflow-canvas-empty-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border: 1px dashed rgba(96, 165, 250, 0.65);
  border-radius: 50%;
  color: #93c5fd;
  font-size: 24px;
  font-weight: 300;
}
.workflow-canvas-loading { font-size: 12px; }

/* Vue Flow 样式覆盖 */
:deep(.vue-flow__edge-path) {
  stroke: #64748b;
  stroke-width: 2;
}

:deep(.vue-flow__edge.selected .vue-flow__edge-path) {
  stroke: #3b82f6;
}

:deep(.vue-flow__edge-text) {
  fill: #fcd34d;
}

</style>
