<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import {
  CheckCircle2,
  AlertTriangle,
  Terminal,
  Upload,
  RotateCw,
  Clock,
  GitBranch,
  Repeat,
  AlertCircle
} from 'lucide-vue-next'

const props = defineProps<{
  id: string
  selected?: boolean
  data: {
    label: string
    action_id: string
    config: Record<string, unknown>
    state?: 'ready' | 'attention'
  }
}>()

// 节点类别和元数据
interface NodeMeta {
  label: string
  category: 'execution' | 'control' | 'coordination'
  tone: 'blue' | 'purple' | 'amber'
  icon: any
}

const ACTION_META: Record<string, NodeMeta> = {
  'device.select': { label: '选择设备', category: 'execution', tone: 'blue', icon: CheckCircle2 },
  'device.ssh': { label: 'SSH 连接', category: 'execution', tone: 'blue', icon: Terminal },
  'device.telnet': { label: 'Telnet 连接', category: 'execution', tone: 'blue', icon: Terminal },
  'device.info': { label: '获取设备信息', category: 'execution', tone: 'blue', icon: CheckCircle2 },
  'device.command': { label: '执行命令', category: 'execution', tone: 'blue', icon: Terminal },
  'device.reboot': { label: '重启设备', category: 'execution', tone: 'blue', icon: RotateCw },
  'device.connect': { label: '连接设备', category: 'execution', tone: 'blue', icon: CheckCircle2 },
  'file.upload': { label: '上传文件', category: 'execution', tone: 'blue', icon: Upload },
  'file.download': { label: '下载文件', category: 'execution', tone: 'blue', icon: Upload },
  'utility.condition': { label: '如果 / 否则', category: 'control', tone: 'purple', icon: GitBranch },
  'loop.for_each': { label: '循环 FOR', category: 'control', tone: 'purple', icon: Repeat },
  'loop.until': { label: '循环直到满足', category: 'control', tone: 'purple', icon: Repeat },
  'utility.wait': { label: '等待', category: 'coordination', tone: 'amber', icon: Clock },
  'terminal.wait': { label: '等待终端输出', category: 'coordination', tone: 'amber', icon: Terminal },
  'utility.confirm': { label: '人工确认', category: 'coordination', tone: 'amber', icon: AlertCircle },
  'result.save': { label: '保存结果', category: 'coordination', tone: 'blue', icon: CheckCircle2 },
  'variable.set': { label: '设置变量', category: 'coordination', tone: 'blue', icon: CheckCircle2 },
  'expression.evaluate': { label: '计算表达式', category: 'control', tone: 'purple', icon: GitBranch },
}

const nodeMeta = computed<NodeMeta>(() => {
  return ACTION_META[props.data.action_id] || {
    label: props.data.action_id,
    category: 'execution',
    tone: 'blue',
    icon: Terminal
  }
})
const isCondition = computed(() => props.data.action_id === 'utility.condition')

const nodeClass = computed(() => {
  return [
    'workflow-node',
    `category-${nodeMeta.value.category}`,
    `tone-${nodeMeta.value.tone}`,
    `state-${props.data.state || 'ready'}`
  ]
})

const IconComponent = computed(() => nodeMeta.value.icon)

// 获取配置摘要（显示在节点上）
const configSummary = computed(() => {
  const config = props.data.config
  const actionId = props.data.action_id

  if (actionId === 'device.command') {
    const cmd = config.command as string
    return cmd ? (cmd.length > 30 ? cmd.substring(0, 30) + '...' : cmd) : '(未配置)'
  }

  if (actionId === 'utility.wait') {
    const seconds = config.seconds as number
    return seconds ? `${seconds}秒` : '(未配置)'
  }

  if (actionId === 'file.upload' || actionId === 'file.download') {
    const path = (config.local_path || config.remote_path) as string
    return path ? path.split(/[/\\]/).pop() || path : '(未配置)'
  }

  return ''
})
</script>

<template>
  <div :class="[nodeClass, { selected: props.selected }]">
    <!-- 输入连接点 -->
    <Handle
      type="target"
      :position="Position.Top"
      class="node-handle node-handle-target"
    />

    <!-- 节点内容 -->
    <div class="node-header">
      <component :is="IconComponent" :size="16" class="node-icon" />
      <span class="node-label">{{ nodeMeta.label }}</span>
      <CheckCircle2
        v-if="data.state === 'ready'"
        :size="14"
        class="state-icon state-ready"
      />
      <AlertTriangle
        v-else-if="data.state === 'attention'"
        :size="14"
        class="state-icon state-attention"
      />
    </div>

    <div class="node-body">
      <div class="node-id">{{ data.label }}</div>
      <div v-if="configSummary" class="node-config">{{ configSummary }}</div>
    </div>

    <!-- 分类标签 -->
    <div class="node-category-badge">
      {{ nodeMeta.category === 'execution' ? '执行' :
         nodeMeta.category === 'control' ? '控制' : '协调' }}
    </div>

    <!-- 输出连接点 -->
    <Handle
      type="source"
      :position="Position.Bottom"
      v-if="!isCondition"
      class="node-handle node-handle-source"
    />
    <template v-else>
      <Handle type="source" id="true" :position="Position.Right" class="node-handle node-handle-true" />
      <Handle type="source" id="false" :position="Position.Right" class="node-handle node-handle-false" />
      <span class="branch-label branch-label-true">满足</span>
      <span class="branch-label branch-label-false">不满足</span>
    </template>
  </div>
</template>

<style scoped>
.workflow-node {
  padding: 14px 16px;
  border-radius: 10px;
  background: rgba(17, 27, 45, 0.96);
  border: 2px solid rgba(100, 116, 139, 0.4);
  min-width: 200px;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
  backdrop-filter: blur(8px);
  box-shadow: 0 8px 22px rgba(2, 6, 23, 0.24);
}

.workflow-node::before {
  content: '';
  position: absolute;
  inset: 9px auto 9px 0;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: #60a5fa;
  opacity: 0.9;
}

.workflow-node:hover {
  border-color: rgba(59, 130, 246, 0.6);
  box-shadow: 0 10px 26px rgba(2, 6, 23, 0.36), 0 0 0 1px rgba(96, 165, 250, 0.16);
  transform: translateY(-2px);
}

.workflow-node:active { cursor: grabbing; }

/* 节点分类颜色 */
.workflow-node.category-execution {
  border-color: rgba(59, 130, 246, 0.5);
}

.workflow-node.category-control {
  border-color: rgba(168, 85, 247, 0.5);
}

.category-control.workflow-node::before { background: #c084fc; }

.workflow-node.category-coordination {
  border-color: rgba(251, 191, 36, 0.5);
}

.category-coordination.workflow-node::before { background: #fbbf24; }

/* 状态样式 */
.workflow-node.state-attention {
  border-color: rgba(251, 191, 36, 0.7) !important;
  background: rgba(180, 83, 9, 0.1);
}

.state-attention.workflow-node::before { background: #fbbf24; }

/* 节点头部 */
.node-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid rgba(100, 116, 139, 0.2);
}

.node-icon {
  color: #94a3b8;
  flex-shrink: 0;
}

.tone-blue .node-icon {
  color: #60a5fa;
}

.tone-purple .node-icon {
  color: #c084fc;
}

.tone-amber .node-icon {
  color: #fbbf24;
}

.node-label {
  flex: 1;
  font-weight: 600;
  font-size: 13px;
  color: #e2e8f0;
}

.state-icon {
  flex-shrink: 0;
}

.state-ready {
  color: #22c55e;
}

.state-attention {
  color: #fbbf24;
}

/* 节点主体 */
.node-body {
  margin-bottom: 8px;
}

.node-id {
  font-size: 11px;
  color: rgba(226, 232, 240, 0.6);
  margin-bottom: 4px;
  font-family: monospace;
}

.node-config {
  font-size: 11px;
  color: rgba(226, 232, 240, 0.8);
  padding: 4px 8px;
  background: rgba(15, 23, 42, 0.5);
  border-radius: 4px;
  font-family: monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 分类标签 */
.node-category-badge {
  position: absolute;
  top: -8px;
  right: -8px;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  pointer-events: none;
}

.category-execution .node-category-badge {
  background: rgba(59, 130, 246, 0.9);
  color: white;
}

.category-control .node-category-badge {
  background: rgba(168, 85, 247, 0.9);
  color: white;
}

.category-coordination .node-category-badge {
  background: rgba(251, 191, 36, 0.9);
  color: #0f172a;
}

/* 连接点样式 */
.node-handle {
  width: 12px;
  height: 12px;
  border: 2px solid #64748b;
  background: #1e293b;
  transition: all 0.2s;
}

.node-handle:hover {
  width: 16px;
  height: 16px;
  border-color: #3b82f6;
  background: #3b82f6;
}

.node-handle-target {
  top: -6px;
}

.node-handle-source {
  bottom: -6px;
}

.node-handle-true,
.node-handle-false { right: -6px; }
.node-handle-true { top: 38%; }
.node-handle-false { top: 68%; }
.branch-label { position: absolute; right: -43px; font-size: 9px; color: #fcd34d; pointer-events: none; }
.branch-label-true { top: 30%; }
.branch-label-false { top: 60%; }

.category-execution .node-handle {
  border-color: #3b82f6;
}

.category-control .node-handle {
  border-color: #a855f7;
}

.category-coordination .node-handle {
  border-color: #fbbf24;
}

/* 选中状态 */
.workflow-node.selected {
  border-width: 2px;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.2), 0 12px 30px rgba(2, 6, 23, 0.34);
}

.category-execution.selected {
  border-color: #3b82f6 !important;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.2) !important;
}

.category-control.selected {
  border-color: #a855f7 !important;
  box-shadow: 0 0 0 4px rgba(168, 85, 247, 0.2) !important;
}

.category-coordination.selected {
  border-color: #fbbf24 !important;
  box-shadow: 0 0 0 4px rgba(251, 191, 36, 0.2) !important;
}
</style>
