<script setup lang="ts">
import { ref, computed } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import WorkflowNode from './WorkflowNode.vue'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'

// 定义类型
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
}

interface WorkflowItem {
  id: string
  name: string
  nodes?: WorkflowNode[]
  edges?: WorkflowEdge[]
}

const props = defineProps<{
  workflow: WorkflowItem | null
}>()

const emit = defineEmits<{
  nodeSelect: [nodeId: string]
  nodeAdd: [position: { x: number; y: number }]
  connect: [connection: { source: string; target: string }]
  nodePositionChange: [nodeId: string, position: { x: number; y: number }]
}>()

// 转换数据格式：Workflow nodes -> Vue Flow nodes
const nodes = computed(() => {
  if (!props.workflow?.nodes) return []

  return props.workflow.nodes.map((node) => ({
    id: node.id,
    type: 'custom',  // 使用自定义节点类型
    position: node.position || { x: 100, y: 50 },
    data: {
      label: node.id,
      action_id: node.action_id,
      config: node.config,
      state: 'ready'  // 可以根据验证结果动态设置
    }
  }))
})

// 转换数据格式：Workflow edges -> Vue Flow edges
const edges = computed(() => {
  if (!props.workflow?.edges) return []

  return props.workflow.edges.map(edge => ({
    id: `${edge.source}-${edge.target}`,
    source: edge.source,
    target: edge.target,
    type: edge.condition ? 'smoothstep' : 'default',
    label: edge.condition === 'true' ? '✓ 是' : edge.condition === 'false' ? '✗ 否' : '',
    animated: false,
    style: {
      stroke: edge.condition ? '#fbbf24' : '#64748b',
      strokeWidth: 2
    },
    labelStyle: {
      fill: '#fcd34d',
      fontSize: '11px',
      fontWeight: 600
    }
  }))
})

// Vue Flow 实例和事件处理
const { onConnect, onNodeDragStop, onNodeClick } = useVueFlow()

// 连接节点
onConnect((params) => {
  console.log('Connect:', params)
  emit('connect', { source: params.source as string, target: params.target as string })
})

// 拖拽节点
onNodeDragStop((event) => {
  console.log('Node drag stop:', event.node.id, event.node.position)
  emit('nodePositionChange', event.node.id, event.node.position)
})

// 点击节点
onNodeClick((event) => {
  console.log('Node click:', event.node.id)
  emit('nodeSelect', event.node.id)
})

// 测试用：添加节点
function handleAddNode() {
  emit('nodeAdd', { x: 100, y: 100 })
}
</script>

<template>
  <div class="workflow-canvas-poc">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :default-zoom="1"
      :min-zoom="0.2"
      :max-zoom="4"
      fit-view-on-init
      class="vue-flow-canvas"
    >
      <!-- 注册自定义节点类型 -->
      <template #node-custom="customNodeProps">
        <WorkflowNode v-bind="customNodeProps" />
      </template>

      <!-- 背景网格 -->
      <Background
        pattern-color="#334155"
        :gap="16"
        :size="1"
      />

      <!-- 控制按钮（放大、缩小、适应视图） -->
      <Controls
        position="bottom-right"
        :show-zoom="true"
        :show-fit-view="true"
        :show-interactive="true"
      />

      <!-- 缩略图 -->
      <MiniMap
        position="bottom-left"
        :node-color="() => '#475569'"
        :mask-color="'rgba(0, 0, 0, 0.6)'"
      />
    </VueFlow>

    <!-- POC 测试信息 -->
    <div class="poc-info">
      <h3>✅ 自定义节点</h3>
      <p>节点数: {{ nodes.length }}</p>
      <p>边数: {{ edges.length }}</p>
      <div class="node-legend">
        <div class="legend-item">
          <span class="legend-color execution"></span>
          <span>执行节点</span>
        </div>
        <div class="legend-item">
          <span class="legend-color control"></span>
          <span>控制节点</span>
        </div>
        <div class="legend-item">
          <span class="legend-color coordination"></span>
          <span>协调节点</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.workflow-canvas-poc {
  width: 100%;
  height: 100%;
  position: relative;
  background: #0f172a;
}

.vue-flow-canvas {
  width: 100%;
  height: 100%;
}

/* 覆盖 Vue Flow 默认样式以适配暗色主题 */
:deep(.vue-flow__edge-path) {
  stroke: #64748b !important;
  stroke-width: 2 !important;
}

:deep(.vue-flow__edge.selected .vue-flow__edge-path) {
  stroke: #3b82f6 !important;
}

:deep(.vue-flow__edge-text) {
  fill: #fcd34d !important;
}

:deep(.vue-flow__controls) {
  background: #1e293b !important;
  border: 1px solid #475569 !important;
  border-radius: 8px !important;
}

:deep(.vue-flow__controls button) {
  background: #334155 !important;
  border: none !important;
  color: #e2e8f0 !important;
}

:deep(.vue-flow__controls button:hover) {
  background: #475569 !important;
}

:deep(.vue-flow__minimap) {
  background: #1e293b !important;
  border: 1px solid #475569 !important;
  border-radius: 8px !important;
}

/* POC 信息面板 */
.poc-info {
  position: absolute;
  top: 16px;
  left: 16px;
  padding: 16px;
  background: rgba(30, 41, 59, 0.95);
  border: 1px solid #475569;
  border-radius: 8px;
  z-index: 10;
  min-width: 200px;
}

.poc-info h3 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #3b82f6;
}

.poc-info p {
  margin: 6px 0;
  font-size: 12px;
  color: #cbd5e1;
}

.node-legend {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid #334155;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 6px 0;
  font-size: 11px;
  color: #94a3b8;
}

.legend-color {
  width: 12px;
  height: 12px;
  border-radius: 2px;
}

.legend-color.execution {
  background: rgba(59, 130, 246, 0.6);
}

.legend-color.control {
  background: rgba(168, 85, 247, 0.6);
}

.legend-color.coordination {
  background: rgba(251, 191, 36, 0.6);
}

.test-button {
  margin-top: 12px;
  padding: 6px 12px;
  background: #3b82f6;
  border: none;
  border-radius: 4px;
  color: white;
  font-size: 12px;
  cursor: pointer;
}

.test-button:hover {
  background: #2563eb;
}
</style>
