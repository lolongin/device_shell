<script setup lang="ts">
import { computed } from 'vue'
import BaseNodeConfig from './BaseNodeConfig.vue'
import CommandNodeConfig from './CommandNodeConfig.vue'
import GenericNodeConfig from './GenericNodeConfig.vue'
import ScriptNodeConfig from './ScriptNodeConfig.vue'
import { fieldLabels, inputFieldLabels } from './actionCatalog'
import type { DeviceSummary, CommandReference, ResultSource, WorkflowScript } from './types'
import type { ActionItem, NodeItem } from './types'

const props = defineProps<{
  node: NodeItem | null
  availableDevices?: DeviceSummary[]
  workflowInputs?: Array<{ name: string; type?: string; description?: string }>
  commandReferences?: CommandReference[]
  resultSources?: ResultSource[]
  scripts?: WorkflowScript[]
  actions?: ActionItem[]
  nodeOptions: Array<{ id: string; label: string }>
  predecessorId?: string
  successorId?: string
  scriptSaving?: boolean
}>()

const emit = defineEmits<{
  rename: [event: Event]
  'update:predecessorId': [value: string]
  'update:successorId': [value: string]
  update: [node: NodeItem]
  remove: []
  test: []
  'save-as-action': []
  'open-script-studio': [scriptId: string]
  'save-script': []
  'choose-upload-source': []
}>()

const selectedAction = computed(() => {
  if (!props.node) return undefined
  return props.actions?.find(a => a.id === props.node?.action_id)
})

const inputFields = computed(() => {
  const schema = selectedAction.value?.inputSchema
  const properties = schema?.properties
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return []
  const required = new Set(Array.isArray(schema.required) ? schema.required : [])
  return Object.keys(properties).map((name) => ({
    name,
    required: required.has(name),
    label: inputLabel(name),
  }))
})

function inputLabel(name: string): string {
  if (props.node?.action_id === 'file.upload') {
    if (name === 'source') return '本机文件路径'
    if (name === 'destination') return '设备目标路径'
  }
  if (props.node?.action_id === 'file.download') {
    if (name === 'source') return '设备源路径'
    if (name === 'destination') return '本机保存路径'
  }
  return inputFieldLabels[name] || name
}

function updateConfig(key: string, value: unknown): void {
  if (!props.node) return
  props.node.config[key] = value
  emit('update', props.node)
}

</script>

<template>
  <section v-if="node" class="workflow-properties" aria-label="步骤设置">
    <!-- 基础配置：步骤名称、上下游连接 -->
    <BaseNodeConfig
      :node="node"
      :node-options="nodeOptions"
      :predecessor-id="predecessorId"
      :successor-id="successorId"
      :selected-action="selectedAction"
      @rename="emit('rename', $event)"
      @update:predecessor-id="emit('update:predecessorId', $event)"
      @update:successor-id="emit('update:successorId', $event)"
    />

    <details v-if="selectedAction" class="workflow-io-contract" :open="node.action_id === 'file.upload' || node.action_id === 'file.download'">
      <summary>输入与输出 <span>必填 {{ inputFields.filter(field => field.required).length }} · 输出 {{ selectedAction.outputFields.length }}</span></summary>
      <div class="workflow-io-row">
        <strong>必填输入</strong>
        <span>{{ inputFields.filter(field => field.required).map(field => field.label).join('、') || '无' }}</span>
      </div>
      <div class="workflow-io-row">
        <strong>可选输入</strong>
        <span>{{ inputFields.filter(field => !field.required).map(field => field.label).join('、') || '无' }}</span>
      </div>
      <div class="workflow-io-row">
        <strong>可用输出</strong>
        <span>{{ selectedAction.outputFields.map(field => fieldLabels[field.name] || field.label).join('、') || '未声明' }}</span>
      </div>
    </details>

    <template v-if="['variable.set', 'expression.evaluate', 'loop.for_each', 'device.for_each', 'loop.until', 'utility.condition', 'utility.confirm', 'result.save', 'workflow.call'].includes(node.action_id)">
      <slot />
    </template>
    <ScriptNodeConfig
      v-else-if="node.action_id === 'script.run'"
      :node="node"
      :scripts="scripts"
      :command-references="commandReferences"
      :script-saving="scriptSaving"
      :actions="actions"
      @update="emit('update', $event)"
      @remove="emit('remove')"
      @test="emit('test')"
      @save-as-action="emit('save-as-action')"
      @open-script-studio="emit('open-script-studio', $event)"
      @save-script="emit('save-script')"
    />
    <CommandNodeConfig
      v-else-if="node.action_id === 'device.command'"
      :node="node"
      :command-references="commandReferences"
      :actions="actions"
      @update="emit('update', $event)"
      @remove="emit('remove')"
      @test="emit('test')"
      @save-as-action="emit('save-as-action')"
    />
    <GenericNodeConfig
      v-else
      :node="node"
      :available-devices="availableDevices"
      :workflow-inputs="workflowInputs"
      :command-references="commandReferences"
      :result-sources="resultSources"
      :scripts="scripts"
      :actions="actions"
      @update="emit('update', $event)"
      @remove="emit('remove')"
      @test="emit('test')"
      @save-as-action="emit('save-as-action')"
      @choose-upload-source="emit('choose-upload-source')"
    />

    <div v-if="!['variable.set', 'utility.condition', 'utility.wait', 'utility.confirm'].includes(node.action_id)" class="workflow-common-node-options">
      <label>失败重试次数<input :value="node.config.retry_attempts ?? 1" type="number" min="1" max="5" @input="updateConfig('retry_attempts', Number(($event.target as HTMLInputElement).value))" /></label>
      <label>失败重试间隔（秒）<input :value="node.config.retry_backoff_seconds ?? 0" type="number" min="0" max="60" step="0.1" @input="updateConfig('retry_backoff_seconds', Number(($event.target as HTMLInputElement).value))" /></label>
      <label v-if="node.action_id === 'device.command'">失败后的处理<select :value="String(node.config.failure_strategy || 'stop')" @change="updateConfig('failure_strategy', ($event.target as HTMLSelectElement).value)"><option value="stop">停止流程</option><option value="continue">继续后续节点</option></select></label>
      <label v-if="!['utility.condition', 'utility.confirm'].includes(node.action_id)">并行组（可选）<input :value="String(node.config.parallel_group || '')" @input="updateConfig('parallel_group', ($event.target as HTMLInputElement).value)" /></label>
      <label v-if="!['utility.condition', 'utility.confirm'].includes(node.action_id)">重复执行次数<input :value="node.config.repeat_count ?? 1" type="number" min="1" max="20" @input="updateConfig('repeat_count', Number(($event.target as HTMLInputElement).value))" /></label>
    </div>
  </section>
  <section v-else class="workflow-properties workflow-empty">
    选择一个步骤编辑参数
  </section>
</template>

<style scoped>
.workflow-properties {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
  box-sizing: border-box;
  padding: 10px;
  border: 1px solid var(--workflow-border);
  border-radius: 6px;
  align-self: stretch;
}

.workflow-empty {
  display: grid;
  place-items: center;
  min-height: 200px;
  color: var(--workflow-muted);
  font-size: 12px;
}

.workflow-io-contract {
  padding: 8px 10px;
  border: 1px solid var(--workflow-border);
  border-radius: 6px;
  color: var(--workflow-text);
  font-size: 11px;
}

.workflow-io-contract summary {
  cursor: pointer;
  font-weight: 600;
}

.workflow-io-contract summary span {
  float: right;
  color: var(--workflow-muted);
  font-weight: 400;
}

.workflow-io-row {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  gap: 8px;
  padding-top: 8px;
  line-height: 1.5;
}

.workflow-io-row strong { color: var(--workflow-muted); }
</style>
