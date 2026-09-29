<script setup lang="ts">
import type { ActionItem, DeviceSummary, NodeItem, ResultSource } from './types'

type WorkflowReference = { id?: string; nodes?: NodeItem[] }
type PublishedWorkflow = { id: string; name: string; version?: string | number; step_count?: number; inputs?: Array<{ name: string; required?: boolean }>; outputs?: Array<{ name: string }> }
type ConditionRule = { field: string; operator: string; value: string }
type ConditionTargets = { trueTarget: string; falseTarget: string }

const props = defineProps<{
  node: NodeItem
  availableDevices?: DeviceSummary[]
  workflowInputs?: Array<{ name: string; type?: string }>
  workflow: WorkflowReference | null
  publishedWorkflows: PublishedWorkflow[]
  subworkflowVersions: PublishedWorkflow[]
  selectedSubworkflow: PublishedWorkflow | null
  resultSources: ResultSource[]
  actions: ActionItem[]
  loopChildActions: ActionItem[]
  loopItemsMode: 'manual' | 'reference'
  loopItemsSourceId: string
  loopItemsField: string
  loopUntilStopMode: string
  loopUntilPattern: string
  conditionRules: ConditionRule[]
  conditionLogicalOperator: string
  conditionTargets: ConditionTargets
  variableValueSourceId: string
  variableValueField: string
  variableExtractEnabled: boolean
  configString: (key: string) => string
  variableExtractString: (key: string) => string
  variableExtractConfig: () => Record<string, unknown>
  onSelectSubworkflow: (id: string) => void | Promise<void>
  onSelectSubworkflowVersion: (version: string) => void
  onUpdateSubworkflowInput: (name: string, value: string) => void
  onUpdateConfigString: (key: string, event: Event) => void
  onUpdateConfigJson: (key: string, event: Event) => void
  onSetLoopItemsSource: (id: string) => void
  onSetLoopItemsField: (field: string) => void
  onSetVariableValueReference: (reference: string) => void
  onToggleVariableExtract: (enabled: boolean) => void
  onUpdateVariableExtractString: (key: string, event: Event) => void
  onUpdateVariableExtractMode: (event: Event) => void
  onUpdateVariableExtractNumber: (key: string, event: Event) => void
  onUpdateVariableExtractBoolean: (key: string, event: Event) => void
  onSetConditionTarget: (branch: 'true' | 'false', event: Event) => void
  onAddCondition: () => void
  onResultFieldChange: (event: Event) => void
}>()

const emit = defineEmits<{
  update: [node: NodeItem]
  'loop-items-mode': [value: string]
  'loop-until-stop-mode': [value: string]
  'update:loop-until-pattern': [value: string]
  'update-condition-operator': [value: string]
}>()

function updateConfig(key: string, event: Event): void {
  try { props.node.config[key] = JSON.parse((event.target as HTMLTextAreaElement).value) } catch { /* keep last valid config */ }
}
function updateConfigValue(key: string, event: Event): void {
  const target = event.target as HTMLInputElement | HTMLSelectElement
  props.node.config[key] = target.type === 'number' ? Number(target.value) : target.value
  emit('update', props.node)
}
function selectedDeviceIds(): string[] {
  return Array.isArray(props.node.config.devices) ? props.node.config.devices.map(String) : []
}
function toggleDevice(deviceId: string, checked: boolean): void {
  const next = new Set(selectedDeviceIds())
  if (checked) next.add(deviceId)
  else next.delete(deviceId)
  props.node.config.devices = [...next]
  emit('update', props.node)
}
function updateDeviceIds(event: Event): void {
  const value = (event.target as HTMLInputElement).value
  if (/^\$\{inputs?\.[^}]+\}$/.test(value.trim())) {
    props.node.config.devices = value.trim().replace('${input.', '${inputs.')
    emit('update', props.node)
    return
  }
  props.node.config.devices = value.split(/[,\n]/).map((item) => item.trim()).filter(Boolean)
  emit('update', props.node)
}
const executableActions = props.actions.filter((action) => !['device.for_each', 'loop.for_each', 'loop.until', 'utility.condition', 'utility.confirm', 'workflow.call'].includes(action.id))

function actionLabel(actionId: string): string {
  return props.actions.find((action) => action.id === actionId)?.label || actionId
}

function fieldLabel(name: string): string {
  return ({
    address: '地址', device_id: '设备', exitCode: '退出码', name: '名称', output: '输出',
    software_version: '软件版本', status: '状态', stderr: '错误输出', stdout: '标准输出',
    duration: '执行耗时', value: '值',
  } as Record<string, string>)[name] || name
}
</script>

<template>
  <div class="workflow-advanced-node-config">
    <template v-if="node.action_id === 'workflow.call'">
      <label>已发布流程
        <select :value="String(node.config.workflow_id || '')" @change="onSelectSubworkflow(($event.target as HTMLSelectElement).value)">
          <option value="">选择流程</option>
          <option v-for="item in publishedWorkflows.filter((item) => item.id !== workflow?.id)" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select>
      </label>
      <label>固定版本
        <select :value="String(node.config.version || '')" @change="onSelectSubworkflowVersion(($event.target as HTMLSelectElement).value)">
          <option value="">选择版本</option>
          <option v-for="item in subworkflowVersions" :key="`${item.id}-${item.version}`" :value="String(item.version)">v{{ item.version }} · {{ item.step_count || 0 }} 步</option>
        </select>
      </label>
      <div v-if="selectedSubworkflow?.inputs?.length" class="workflow-subflow-contract">
        <strong>输入映射</strong>
        <label v-for="input in selectedSubworkflow.inputs" :key="input.name">
          {{ input.name }}
          <input :value="String((node.config.inputs as Record<string, unknown> | undefined)?.[input.name] ?? '')" :placeholder="input.required ? '必填值或 ${inputs.name}' : '可选'" @input="onUpdateSubworkflowInput(input.name, ($event.target as HTMLInputElement).value)" />
        </label>
      </div>
      <div v-if="selectedSubworkflow?.outputs?.length" class="workflow-command-result-contract"><span>输出</span><code v-for="output in selectedSubworkflow.outputs" :key="output.name">{{ output.name }}</code></div>
      <small class="field-hint">运行时展开固定发布版本；下游可使用 <code>{{ '${' + node.id + '.输出名}' }}</code>。</small>
    </template>

    <template v-if="node.action_id === 'variable.set'">
      <label>变量名<input :value="configString('name')" @input="onUpdateConfigString('name', $event)" /></label>
      <label>变量值
        <input :value="configString('value')" placeholder="固定值或支持 ${node.field}" @input="onUpdateConfigString('value', $event)" />
        <details class="workflow-variable-reference"><summary>插入上游引用</summary>
          <select :value="variableValueSourceId && variableValueField ? `${variableValueSourceId}.${variableValueField}` : variableValueSourceId" aria-label="选择上游输出" @change="onSetVariableValueReference(($event.target as HTMLSelectElement).value)">
            <option value="">选择步骤或字段</option>
            <template v-for="source in resultSources" :key="`${source.id}-fields`">
              <option :value="source.id">{{ source.label }} · 完整结果</option>
              <option v-for="field in source.fields" :key="`${source.id}-${field.name}`" :value="`${source.id}.${field.name}`">{{ source.label }} · {{ fieldLabel(field.name) }}</option>
            </template>
          </select>
        </details>
      </label>
      <label class="workflow-inline-toggle"><input :checked="variableExtractEnabled" type="checkbox" @change="onToggleVariableExtract(($event.target as HTMLInputElement).checked)" /><span>提取匹配</span></label>
      <div v-if="variableExtractEnabled" class="workflow-variable-extract">
        <label>匹配规则<textarea :value="variableExtractString('pattern')" rows="2" @input="onUpdateVariableExtractString('pattern', $event)" /></label>
        <label>保存方式<select :value="variableExtractString('mode') || 'match'" @change="onUpdateVariableExtractMode"><option value="match">匹配内容</option><option value="line">匹配所在整行</option></select></label>
        <label>捕获组<input :value="variableExtractString('group') || '0'" type="number" min="0" step="1" @input="onUpdateVariableExtractNumber('group', $event)" /></label>
        <label>转换为<select :value="variableExtractString('convert') || 'string'" @change="onUpdateVariableExtractString('convert', $event)"><option value="string">文本</option><option value="integer">整数</option><option value="number">数字</option><option value="boolean">布尔值</option><option value="json">JSON</option></select></label>
        <label class="workflow-inline-toggle"><input :checked="Boolean(variableExtractConfig().trim)" type="checkbox" @change="onUpdateVariableExtractBoolean('trim', $event)" /><span>去除首尾空白</span></label>
      </div>
    </template>

    <template v-if="node.action_id === 'expression.evaluate'"><label>表达式<textarea :value="configString('expression')" rows="2" @input="onUpdateConfigString('expression', $event)" /></label><label>表达式上下文 JSON<textarea :value="JSON.stringify(node.config.values || {})" rows="2" @change="onUpdateConfigJson('values', $event)" /></label></template>

    <template v-if="node.action_id === 'device.for_each'">
      <label>设备列表</label>
      <label>设备 ID 或参数引用（多个用逗号分隔）<input :value="typeof node.config.devices === 'string' ? node.config.devices : selectedDeviceIds().join(', ')" placeholder="例如：router-1, router-2 或 ${input.devices}" @change="updateDeviceIds" /></label>
      <label>选择流程参数<select aria-label="选择设备列表参数" :value="typeof node.config.devices === 'string' && node.config.devices.startsWith('${inputs.') ? node.config.devices : ''" @change="updateDeviceIds"><option value="">手动设备列表</option><option v-for="input in workflowInputs || []" :key="input.name" :value="`\${inputs.${input.name}}`">{{ input.name }} · {{ input.type || 'string' }}</option></select></label>
      <p class="field-hint">选择参数后会插入 <code>${input.xxx}</code> 引用；参数值应为设备 ID 数组。</p>
      <div class="device-for-each-picker">
        <label v-for="device in availableDevices || []" :key="device.id" class="device-for-each-option">
          <input type="checkbox" :checked="selectedDeviceIds().includes(device.id)" @change="toggleDevice(device.id, ($event.target as HTMLInputElement).checked)" />
          <span><strong>{{ device.name || device.id }}</strong><small>{{ device.id }}</small></span>
        </label>
        <p v-if="!(availableDevices || []).length" class="field-hint">暂无设备，请先添加或导入设备。</p>
      </div>
      <div class="workflow-loop-child-hint">
        <strong>循环体由下游节点执行</strong>
        <span>遍历节点会把当前设备传给后面的第一个执行节点；请将“执行命令”等动作连接在此节点之后。</span>
      </div>
      <label v-if="node.config.action_id">兼容动作映射<select :value="node.config.action_id" @change="updateConfigValue('action_id', $event)"><option v-for="action in executableActions" :key="action.id" :value="action.id">{{ action.label }}</option></select></label>
      <label>并发数<input type="number" min="1" max="32" :value="node.config.concurrency || 1" @change="updateConfigValue('concurrency', $event)" /></label>
      <label>单台失败<select :value="node.config.failure_strategy || 'continue'" @change="updateConfigValue('failure_strategy', $event)"><option value="continue">继续其他设备</option><option value="stop">停止遍历</option></select></label>
    </template>
    <template v-else-if="node.action_id === 'loop.for_each'">
      <label>列表来源<select :value="loopItemsMode" @change="$emit('loop-items-mode', ($event.target as HTMLSelectElement).value)"><option value="manual">手动输入列表</option><option value="reference">引用前置步骤输出</option></select></label>
      <label v-if="loopItemsMode === 'manual'">遍历列表 JSON<textarea :value="JSON.stringify(node.config.items || [])" rows="2" @change="onUpdateConfigJson('items', $event)" /></label>
      <template v-else>
        <label>列表来源步骤<select :value="loopItemsSourceId" @change="onSetLoopItemsSource(($event.target as HTMLSelectElement).value)"><option value="">选择步骤</option><option v-for="source in resultSources" :key="source.id" :value="source.id">{{ source.label }}</option></select></label>
        <label>输出字段<select :value="loopItemsField" @change="onSetLoopItemsField(($event.target as HTMLSelectElement).value)"><option value="">完整输出</option><option v-for="field in resultSources.find((source) => source.id === loopItemsSourceId)?.fields || []" :key="`${loopItemsSourceId}-${field.name}`" :value="field.name">{{ fieldLabel(field.name) }}</option></select></label>
      </template>
      <label>循环动作<select :value="String(node.config.action_id || '')" @change="updateConfigValue('action_id', $event)"><option v-for="action in loopChildActions" :key="action.id" :value="action.id">{{ action.label }}</option></select></label>
      <label>动作参数 JSON<textarea :value="JSON.stringify(node.config.action_inputs || {})" rows="2" @change="onUpdateConfigJson('action_inputs', $event)" /></label>
    </template>

    <template v-if="node.action_id === 'loop.until'">
      <label>循环执行什么？<select :value="String(node.config.action_id || '')" @change="updateConfigValue('action_id', $event)"><option v-for="action in loopChildActions" :key="action.id" :value="action.id">{{ action.label }}</option></select></label>
      <label>何时停止？<select :value="loopUntilStopMode" @change="$emit('loop-until-stop-mode', ($event.target as HTMLSelectElement).value)"><option value="output_contains">输出包含文本</option><option value="output_regex">输出匹配正则</option><option value="success">命令成功</option><option value="failure">命令失败</option><option value="max_iterations">达到最大次数</option></select></label>
      <label v-if="loopUntilStopMode === 'output_contains' || loopUntilStopMode === 'output_regex'">{{ loopUntilStopMode === 'output_contains' ? '目标文本' : '正则表达式' }}<input :value="loopUntilPattern" @input="$emit('update:loop-until-pattern', ($event.target as HTMLInputElement).value)" /></label>
      <label>最多执行<input v-model.number="node.config.max_iterations" type="number" min="1" max="100" /> 次</label>
      <label>每次间隔<input v-model.number="node.config.interval_seconds" type="number" min="0" max="86400" step="0.1" /> 秒</label>
    </template>

    <template v-if="node.action_id === 'utility.confirm'"><label>确认提示<textarea :value="configString('prompt')" rows="3" @input="onUpdateConfigString('prompt', $event)" /></label><label>同意按钮文字<input :value="configString('approve_label')" @input="onUpdateConfigString('approve_label', $event)" /></label><label>拒绝按钮文字<input :value="configString('reject_label')" @input="onUpdateConfigString('reject_label', $event)" /></label></template>

    <div v-if="node.action_id === 'utility.condition'" class="condition-builder">
      <strong>如果</strong>
      <label>多个条件<select :value="conditionLogicalOperator" @change="$emit('update-condition-operator', ($event.target as HTMLSelectElement).value)"><option value="AND">全部满足（AND）</option><option value="OR">任一满足（OR）</option></select></label>
      <div v-for="(rule, index) in conditionRules" :key="index" class="condition-row"><select v-model="rule.field"><option value="software_version">软件版本</option><option value="status">状态</option><option value="name">名称</option><option value="stdout">标准输出</option><option value="stderr">错误输出</option><option value="exitCode">退出码</option><option value="duration">执行耗时</option></select><select v-model="rule.operator"><option>等于</option><option>不等于</option><option>包含</option><option>不包含</option><option>正则匹配</option><option>大于</option><option>小于</option><option>是否为空</option></select><input v-model="rule.value" placeholder="比较值或正则表达式" /></div>
      <button type="button" class="connect-button" @click="onAddCondition">+ 添加条件</button>
      <label>满足条件时<select :value="conditionTargets.trueTarget" @change="onSetConditionTarget('true', $event)"><option value="">选择真分支步骤</option><option v-for="item in (workflow?.nodes || []).filter((candidate) => candidate.id !== node.id)" :key="item.id" :value="item.id">{{ actionLabel(item.action_id) }}</option></select></label>
      <label>不满足时<select :value="conditionTargets.falseTarget" @change="onSetConditionTarget('false', $event)"><option value="">选择假分支步骤</option><option v-for="item in (workflow?.nodes || []).filter((candidate) => candidate.id !== node.id)" :key="item.id" :value="item.id">{{ actionLabel(item.action_id) }}</option></select></label>
    </div>

    <label v-if="node.action_id === 'result.save'">结果名称<input v-model="node.config.key" placeholder="例如：版本检查结果" /><select :value="String(node.config.value || '')" @change="onResultFieldChange"><option value="">上一步完整结果</option><template v-for="source in resultSources" :key="`${source.id}-result-fields`"><option :value="source.id">{{ source.label }} · 完整结果</option><option v-for="field in source.fields" :key="`${source.id}-${field.name}`" :value="`${source.id}.${field.name}`">{{ source.label }} · {{ fieldLabel(field.name) }}</option></template></select></label>
  </div>
</template>

<style scoped>
.device-for-each-picker { display: grid; gap: 6px; max-height: 190px; overflow: auto; padding: 6px; border: 1px solid var(--workflow-border); border-radius: 6px; background: var(--workflow-surface-input); }
.device-for-each-option { display: flex; align-items: center; gap: 8px; min-height: 30px; padding: 4px 6px; border-radius: 4px; cursor: pointer; }
.device-for-each-option:hover { background: rgba(59, 130, 246, .1); }
.device-for-each-option span { display: grid; min-width: 0; gap: 1px; }
.device-for-each-option strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.device-for-each-option small { color: var(--workflow-muted); font-size: 10px; }
.workflow-advanced-node-config { display: grid; gap: 10px; }
.workflow-advanced-node-config label { display: grid; gap: 5px; color: var(--workflow-text); font-size: 11px; }
.workflow-advanced-node-config input, .workflow-advanced-node-config select, .workflow-advanced-node-config textarea { box-sizing: border-box; width: 100%; padding: 7px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; color: inherit; background: var(--workflow-surface-input); font: inherit; }
.condition-builder, .workflow-variable-extract, .workflow-subflow-contract { display: grid; gap: 8px; }
.condition-row { display: grid; grid-template-columns: 1fr 1fr 1.2fr; gap: 6px; }
.workflow-inline-toggle { display: flex !important; align-items: center; gap: 7px; }
.workflow-inline-toggle input { width: auto !important; }
.field-hint { color: var(--workflow-muted); font-size: 10px; }
</style>
