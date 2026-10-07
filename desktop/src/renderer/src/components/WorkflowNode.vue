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
  AlertCircle,
  Code2,
  LogIn,
  LogOut
} from 'lucide-vue-next'

const props = defineProps<{
  id: string
  selected?: boolean
  data: {
    label: string
    action_id: string
    config: Record<string, unknown>
    loopStructured?: boolean
    virtual?: boolean
    contractKind?: 'input' | 'result'
    virtualLabel?: string
    virtualSummary?: string
    state?: 'ready' | 'attention'
  }
}>()

// 节点类别和元数据
interface NodeMeta {
  label: string
  category: 'flow-control' | 'device' | 'transfer' | 'data' | 'workflow' | 'script'
  tone: 'blue' | 'purple' | 'amber' | 'teal'
  icon: any
}

const ACTION_META: Record<string, NodeMeta> = {
  'device.select': { label: '选择设备', category: 'device', tone: 'blue', icon: CheckCircle2 },
  'device.ssh': { label: 'SSH 连接', category: 'device', tone: 'blue', icon: Terminal },
  'device.telnet': { label: 'Telnet 连接', category: 'device', tone: 'blue', icon: Terminal },
  'device.info': { label: '获取设备信息', category: 'device', tone: 'blue', icon: CheckCircle2 },
  'device.command': { label: '执行命令', category: 'device', tone: 'blue', icon: Terminal },
  'script.run': { label: '执行脚本', category: 'script', tone: 'teal', icon: Code2 },
  'device.reboot': { label: '重启设备', category: 'device', tone: 'blue', icon: RotateCw },
  'device.connect': { label: '连接设备', category: 'device', tone: 'blue', icon: CheckCircle2 },
  'file.upload': { label: '上传文件', category: 'transfer', tone: 'blue', icon: Upload },
  'file.download': { label: '下载文件', category: 'transfer', tone: 'blue', icon: Upload },
  'utility.condition': { label: '如果 / 否则', category: 'flow-control', tone: 'purple', icon: GitBranch },
  'loop.for_each': { label: '循环 FOR', category: 'flow-control', tone: 'purple', icon: Repeat },
  'device.for_each': { label: '遍历设备', category: 'device', tone: 'blue', icon: Repeat },
  'loop.until': { label: '循环直到满足', category: 'flow-control', tone: 'purple', icon: Repeat },
  'utility.wait': { label: '等待', category: 'flow-control', tone: 'amber', icon: Clock },
  'terminal.wait': { label: '等待终端输出', category: 'flow-control', tone: 'amber', icon: Terminal },
  'utility.confirm': { label: '人工确认', category: 'flow-control', tone: 'amber', icon: AlertCircle },
  'result.save': { label: '保存结果', category: 'data', tone: 'blue', icon: CheckCircle2 },
  'variable.set': { label: '设置变量', category: 'data', tone: 'blue', icon: CheckCircle2 },
  'expression.evaluate': { label: '计算表达式', category: 'data', tone: 'purple', icon: GitBranch },
  'workflow.call': { label: '调用子流程', category: 'workflow', tone: 'blue', icon: GitBranch },
  '__workflow_input__': { label: '流程输入', category: 'workflow', tone: 'teal', icon: LogIn },
  '__workflow_result__': { label: '流程结果', category: 'workflow', tone: 'teal', icon: LogOut },
}

const nodeMeta = computed<NodeMeta>(() => {
  return ACTION_META[props.data.action_id] || {
    label: props.data.virtualLabel || props.data.action_id,
    category: 'device',
    tone: 'blue',
    icon: Terminal
  }
})
const isCondition = computed(() => props.data.action_id === 'utility.condition')
const isLoop = computed(() => ['device.for_each', 'loop.for_each', 'loop.until'].includes(props.data.action_id))
const isStructuredLoop = computed(() => isLoop.value && props.data.loopStructured)

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
  if (props.data.virtualSummary) return props.data.virtualSummary
  const config = props.data.config
  const actionId = props.data.action_id

  if (actionId === 'device.command') {
    const cmd = config.command as string
    return cmd ? (cmd.length > 30 ? cmd.substring(0, 30) + '...' : cmd) : '(未配置)'
  }

  if (actionId === 'script.run') {
    const language = String(config.language || 'python')
    const script = String(config.script || '').trim()
    return script ? `${language} · ${script.split(/\r?\n/)[0].slice(0, 24)}` : '(未配置)'
  }

  if (actionId === 'utility.wait') {
    const seconds = config.seconds as number
    return seconds ? `${seconds}秒` : '(未配置)'
  }

  if (actionId === 'device.for_each') {
    const devices = Array.isArray(config.devices)
      ? `${config.devices.length} 台设备`
      : String(config.devices || '设备列表')
    return `${devices} · 循环框内执行`
  }

  if (actionId === 'loop.for_each') {
    const items = Array.isArray(config.items) ? `${config.items.length} 个项目` : String(config.items || '列表')
    return `${items} · 循环框内执行`
  }

  if (actionId === 'loop.until') {
    const maxIterations = Number(config.max_iterations || 10)
    return `最多 ${maxIterations} 次 · 循环框内执行`
  }

  if (actionId === 'file.upload' || actionId === 'file.download') {
    const path = String(config.source || config.source_path || '')
    return path ? path.split(/[/\\]/).pop() || path : '(未配置)'
  }

  return ''
})
</script>

<template>
  <div :class="[nodeClass, { selected: props.selected }]">
    <!-- 输入连接点 -->
    <Handle
      v-if="!data.virtual && data.contractKind !== 'input'"
      type="target"
      :id="data.contractKind === 'result' ? 'contract-input' : undefined"
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
      <div v-if="props.selected" class="node-id">{{ data.label }}</div>
      <div v-if="configSummary" class="node-config">{{ configSummary }}</div>
    </div>

    <!-- 输出连接点 -->
    <template v-if="!data.virtual && data.contractKind === 'input'">
      <Handle type="source" id="contract-output" :position="Position.Bottom" class="node-handle node-handle-source" />
    </template>
    <template v-else-if="!data.virtual && data.contractKind === 'result'">
      <!-- Result is an end boundary and has no outgoing connection handle. -->
    </template>
    <template v-else-if="!data.virtual && isStructuredLoop">
      <Handle type="source" id="loop-body" :position="Position.Bottom" class="node-handle node-handle-loop-body" />
    </template>
    <template v-else-if="!data.virtual">
      <Handle
        v-if="isLoop || !isCondition"
        type="source"
        :position="Position.Bottom"
        class="node-handle node-handle-source"
      />
      <template v-else>
        <Handle type="source" id="true" :position="Position.Right" class="node-handle node-handle-true" />
        <Handle type="source" id="false" :position="Position.Right" class="node-handle node-handle-false" />
        <span class="branch-label branch-label-true">满足</span>
        <span class="branch-label branch-label-false">不满足</span>
      </template>
    </template>
  </div>
</template>


<style scoped>
.workflow-node {
  position: relative;
  box-sizing: border-box;
  width: 232px;
  min-width: 232px;
  max-width: 232px;
  min-height: 96px;
  padding: 10px 12px 9px 14px;
  border: 1px solid rgba(100,116,139,.46);
  border-radius: 8px;
  color: var(--workflow-text, #e2e8f0);
  background: color-mix(in srgb, var(--workflow-surface, #0f172a) 94%, #07111f);
  cursor: pointer;
  transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
  box-shadow: 0 5px 14px rgba(2,6,23,.2);
}
.workflow-node::before { content: ''; position: absolute; inset: 7px auto 7px 0; width: 4px; border-radius: 0 3px 3px 0; background: #4f9cf9; }
.workflow-node:hover { border-color: rgba(96,165,250,.72); box-shadow: 0 8px 18px rgba(2,6,23,.3); }
.workflow-node:active { cursor: grabbing; }
.workflow-node.category-flow-control::before { background: #a78bfa; }
.workflow-node.category-data::before { background: #f0b44d; }
.workflow-node.category-transfer::before { background: #38bdf8; }
.workflow-node.category-workflow::before { background: #2dd4a3; }
.workflow-node.category-script::before { background: #2dd4bf; }
.workflow-node.state-attention { border-color: rgba(240,180,77,.86) !important; background: rgba(161,98,7,.12); }
.workflow-node.state-attention::before { background: #f0b44d; }
.node-header { display: flex; align-items: center; gap: 7px; min-height: 22px; margin-bottom: 5px; padding: 0 12px 6px 0; border-bottom: 1px solid rgba(100,116,139,.2); }
.node-icon { flex: 0 0 auto; color: #60a5fa; }
.tone-purple .node-icon { color: #a78bfa; }
.tone-amber .node-icon { color: #f0b44d; }
.tone-teal .node-icon { color: #2dd4bf; }
.node-label { min-width: 0; flex: 1; overflow: hidden; color: var(--workflow-text, #e2e8f0); font-size: 12px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.state-icon { flex: 0 0 auto; }
.state-ready { color: #2dd4a3; }
.state-attention { color: #f0b44d; }
.node-body { min-width: 0; margin-bottom: 3px; }
.node-id { overflow: hidden; color: var(--workflow-subtle, rgba(226,232,240,.6)); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.node-config { min-width: 0; margin-top: 4px; padding: 0; overflow: hidden; color: var(--workflow-muted, rgba(226,232,240,.8)); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.node-handle { width: 10px; height: 10px; border: 2px solid #64748b; background: #0f172a; transition: border-color .16s ease, background .16s ease; }
.node-handle:hover { width: 10px; height: 10px; border-color: #60a5fa; background: #60a5fa; }
.node-handle-target { top: -5px; }
.node-handle-source { bottom: -5px; }
.node-handle-loop-body { bottom: -5px; }
.node-handle-loop-body { left: 50%; transform: translateX(-50%); }
.node-handle-true, .node-handle-false { right: -5px; }
.node-handle-true { top: 38%; }
.node-handle-false { top: 68%; }
.branch-label { position: absolute; right: -40px; color: #fcd34d; font-size: 9px; pointer-events: none; }
.branch-label-true { top: 30%; }
.branch-label-false { top: 60%; }
.category-device .node-handle { border-color: #4f9cf9; }
.category-flow-control .node-handle { border-color: #a78bfa; }
.category-data .node-handle { border-color: #f0b44d; }
.category-transfer .node-handle { border-color: #38bdf8; }
.category-workflow .node-handle { border-color: #2dd4a3; }
.category-script .node-handle { border-color: #2dd4bf; }
.workflow-node.selected { outline: 2px solid rgba(79,156,249,.82); outline-offset: 3px; box-shadow: 0 0 0 5px rgba(79,156,249,.12), 0 8px 18px rgba(2,6,23,.3); }
.category-flow-control.workflow-node.selected { outline-color: rgba(167,139,250,.9); box-shadow: 0 0 0 5px rgba(167,139,250,.12), 0 8px 18px rgba(2,6,23,.3); }
.category-data.workflow-node.selected { outline-color: rgba(240,180,77,.9); box-shadow: 0 0 0 5px rgba(240,180,77,.12), 0 8px 18px rgba(2,6,23,.3); }
:global(:root[data-theme="light"]) .workflow-node { color: #172033; background: #ffffff; border-color: #cbd5e1; box-shadow: 0 5px 14px rgba(15,23,42,.1); }
:global(:root[data-theme="light"]) .node-label { color: #172033; }
:global(:root[data-theme="light"]) .node-id { color: #64748b; }
:global(:root[data-theme="light"]) .node-config { color: #475569; }
:global(:root[data-theme="light"]) .node-handle { background: #ffffff; }
</style>
