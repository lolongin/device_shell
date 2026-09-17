<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { CircleAlert, FileUp, ListChecks, LoaderCircle, Play, Search, ShieldAlert, X } from 'lucide-vue-next'
import { useDialogFocus } from '../composables/useDialogFocus'
import { desktopApi } from '../transport/api'
import { useWorkspaceStore } from '../stores/workspace'
import type { PublishedWorkflowDefinition, WorkflowRuntimeInput } from '../types'

const props = defineProps<{ initialDeviceId?: string; initialWorkflowId?: string; initialVersion?: string | number }>()
const emit = defineEmits<{ close: []; openStudio: [] }>()
const workspace = useWorkspaceStore()
const dialog = ref<HTMLElement | null>(null)
const { handleDialogKeydown } = useDialogFocus(dialog, { initialFocus: '[data-dialog-initial-focus]' })
const workflows = ref<PublishedWorkflowDefinition[]>([])
const loading = ref(true)
const running = ref(false)
const error = ref('')
const query = ref('')
const selectedId = ref('')
const selectedDeviceId = ref(props.initialDeviceId || workspace.selectedDeviceId)
const values = reactive<Record<string, any>>({})
const confirmedRisks = ref(false)

const filteredWorkflows = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return workflows.value
  return workflows.value.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(needle))
})
const selectedWorkflow = computed(() => workflows.value.find((item) => item.id === selectedId.value) || null)
const selectedDevice = computed(() => workspace.devices.find((item) => item.id === selectedDeviceId.value || item.row_id === selectedDeviceId.value) || null)
const canRun = computed(() => Boolean(selectedWorkflow.value && selectedDevice.value && !running.value && (!selectedWorkflow.value.requires_confirmation || confirmedRisks.value) && !invalidInput.value))
const invalidInput = computed(() => Boolean(selectedWorkflow.value?.inputs.some((input) => {
  const value = values[input.name]
  if (input.required && (value === undefined || value === null || (typeof value === 'string' && !value.trim()))) return true
  if ((input.type === 'integer' || input.type === 'number') && value !== undefined && value !== '') {
    const parsed = Number(value)
    if (!Number.isFinite(parsed) || (input.type === 'integer' && !Number.isInteger(parsed))) return true
  }
  if ((input.type === 'array' || input.type === 'object') && value !== undefined && value !== '') {
    try {
      const parsed = JSON.parse(String(value))
      if (input.type === 'array' ? !Array.isArray(parsed) : !parsed || Array.isArray(parsed) || typeof parsed !== 'object') return true
    } catch { return true }
  }
  return false
})))

function inputLabel(input: WorkflowRuntimeInput): string { return input.name.replaceAll('_', ' ') }
function initialInputValue(input: WorkflowRuntimeInput): unknown {
  if (input.default === undefined || input.default === null) return input.type === 'boolean' ? false : ''
  if (input.type === 'array' || input.type === 'object') return JSON.stringify(input.default, null, 2)
  return input.default
}
function resetInputs(workflow: PublishedWorkflowDefinition | null): void {
  for (const key of Object.keys(values)) delete values[key]
  for (const input of workflow?.inputs || []) {
    values[input.name] = initialInputValue(input)
  }
  confirmedRisks.value = false
}
function selectWorkflow(workflow: PublishedWorkflowDefinition): void {
  selectedId.value = workflow.id
  resetInputs(workflow)
}
function inputType(input: WorkflowRuntimeInput): string {
  if (input.type === 'integer' || input.type === 'number') return 'number'
  return 'text'
}
function parseValue(input: WorkflowRuntimeInput): unknown {
  const value = values[input.name]
  if (input.type === 'integer') return value === '' ? undefined : Number(value)
  if (input.type === 'number') return value === '' ? undefined : Number(value)
  if (input.type === 'boolean') return Boolean(value)
  if (input.type === 'array' || input.type === 'object') {
    if (value === '' || value === undefined) return undefined
    return JSON.parse(String(value))
  }
  return value
}
async function chooseFile(input: WorkflowRuntimeInput): Promise<void> {
  const selected = await window.desktopApi.chooseWorkflowFile({ label: `选择${inputLabel(input)}`, extensions: ['*'] })
  if (selected) values[input.name] = selected
}
async function loadCatalog(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    workflows.value = (await desktopApi.publishedWorkflowDefinitions()).workflows
    if (props.initialWorkflowId) {
      const catalogItem = workflows.value.find((item) => item.id === props.initialWorkflowId)
      if (props.initialVersion !== undefined) {
        const versions = (await desktopApi.workflowVersions(props.initialWorkflowId)).versions
        const target = versions.find((item) => String(item.version) === String(props.initialVersion))
        if (target) {
          workflows.value = [target, ...workflows.value.filter((item) => item.id !== target.id)]
          selectWorkflow(target)
        }
      } else if (catalogItem) selectWorkflow(catalogItem)
    }
    if (!selectedId.value && workflows.value[0]) selectWorkflow(workflows.value[0])
    else if (selectedWorkflow.value) resetInputs(selectedWorkflow.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { loading.value = false }
}
async function runWorkflow(): Promise<void> {
  const workflow = selectedWorkflow.value
  const device = selectedDevice.value
  if (!workflow || !device || !canRun.value) return
  running.value = true
  error.value = ''
  try {
    const inputs: Record<string, unknown> = {}
    for (const input of workflow.inputs) {
      const value = parseValue(input)
      if (value !== undefined && value !== '') inputs[input.name] = value
    }
    const session = workspace.sessions.find((item) => item.device_id === device.id && item.status === 'connected')
    const result = await desktopApi.runWorkflowDefinition(workflow.id, {
      device_id: device.id,
      version: workflow.version,
      protocol: 'auto',
      inputs,
      ...(session ? { session_id: session.id } : {}),
      ...(workflow.requires_confirmation ? { confirmed_risks: true } : {})
    })
    const tasks = result.tasks?.length ? result.tasks : result.task ? [result.task] : []
    if (tasks.length) {
      workspace.tasks = [...tasks, ...workspace.tasks.filter((task) => !tasks.some((item) => item.id === task.id))]
      workspace.activeTaskId = tasks[0].id
      workspace.selectDevice(device.row_id)
      workspace.upgradePanelOpen = true
    }
    emit('close')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { running.value = false }
}
watch(() => props.initialDeviceId, (value) => { if (value) selectedDeviceId.value = value })
onMounted(() => { void loadCatalog() })
</script>

<template>
  <div class="dialog-backdrop" @mousedown.self="emit('close')">
    <section ref="dialog" class="workflow-run-dialog" role="dialog" aria-modal="true" aria-labelledby="workflow-run-title" @keydown="handleDialogKeydown">
      <header class="workflow-run-header">
        <div class="workflow-run-heading"><span class="task-ui-icon"><ListChecks :size="18" /></span><div><p class="eyebrow">PUBLISHED WORKFLOWS</p><h2 id="workflow-run-title">运行 Workflow</h2></div></div>
        <button class="icon-button" type="button" aria-label="关闭" title="关闭" @click="emit('close')"><X :size="16" /></button>
      </header>
      <div class="workflow-run-body">
        <aside class="workflow-run-catalog" aria-label="已发布 Workflow">
          <label class="workflow-run-search"><Search :size="14" /><input v-model="query" data-dialog-initial-focus placeholder="搜索已发布 Workflow" /></label>
          <div v-if="loading" class="workflow-run-state"><LoaderCircle :size="17" class="spin" />正在加载目录</div>
          <div v-else-if="error && !workflows.length" class="workflow-run-state workflow-run-error"><CircleAlert :size="16" />{{ error }}</div>
          <div v-else-if="!filteredWorkflows.length" class="workflow-run-state"><ListChecks :size="18" /><span>暂无已发布 Workflow</span><button class="secondary-button" type="button" @click="emit('openStudio')">打开 Workflow Studio</button></div>
          <div v-else class="workflow-run-list">
            <button v-for="workflow in filteredWorkflows" :key="workflow.id" type="button" :class="{ active: workflow.id === selectedId }" @click="selectWorkflow(workflow)">
              <span><strong>{{ workflow.name }}</strong><small>{{ workflow.description || '无描述' }}</small></span><b>v{{ workflow.version }}</b>
            </button>
          </div>
        </aside>
        <form class="workflow-run-form" @submit.prevent="runWorkflow">
          <template v-if="selectedWorkflow">
            <div class="workflow-run-summary"><div><strong>{{ selectedWorkflow.name }}</strong><small>{{ selectedWorkflow.description || '已发布版本，可直接执行' }}</small></div><span>v{{ selectedWorkflow.version }} · {{ selectedWorkflow.step_count }} 步</span></div>
            <label class="workflow-run-field"><span>目标设备</span><select v-model="selectedDeviceId"><option value="" disabled>选择设备</option><option v-for="device in workspace.devices" :key="device.row_id" :value="device.id">{{ device.name }} · {{ device.id }}</option></select></label>
            <div v-if="selectedWorkflow.inputs.length" class="workflow-run-inputs">
              <label v-for="input in selectedWorkflow.inputs" :key="input.name" class="workflow-run-field"><span>{{ inputLabel(input) }}<em v-if="input.required">必填</em></span><small v-if="input.description">{{ input.description }}</small><button v-if="input.type === 'file' || input.name === 'package_path'" class="workflow-run-file" type="button" @click="chooseFile(input)"><FileUp :size="14" />{{ values[input.name] ? String(values[input.name]) : '选择文件' }}</button><textarea v-else-if="input.type === 'array' || input.type === 'object'" v-model="values[input.name]" rows="3" :placeholder="input.type === 'array' ? '[...]' : '{...}'" /><input v-else-if="input.type === 'boolean'" v-model="values[input.name]" type="checkbox" /><input v-else v-model="values[input.name]" :type="inputType(input)" :step="input.type === 'number' ? 'any' : input.type === 'integer' ? '1' : undefined" /></label>
            </div>
            <label v-if="selectedWorkflow.requires_confirmation" class="workflow-run-risk"><input v-model="confirmedRisks" type="checkbox" /><ShieldAlert :size="16" /><span>此 Workflow 包含高风险动作，确认后执行</span></label>
            <p v-if="error" class="workflow-run-error" role="alert"><CircleAlert :size="15" />{{ error }}</p>
            <footer class="workflow-run-footer"><span v-if="selectedDevice">将使用 {{ selectedDevice.name }} 的现有连接（如可用）</span><button class="secondary-button" type="button" @click="emit('close')">取消</button><button class="primary-button" type="submit" :disabled="!canRun"><LoaderCircle v-if="running" :size="14" class="spin" /><Play v-else :size="14" />{{ running ? '正在提交' : '开始执行' }}</button></footer>
          </template>
          <div v-else class="workflow-run-state workflow-run-form-empty"><ListChecks :size="22" />从左侧选择一个已发布 Workflow</div>
        </form>
      </div>
    </section>
  </div>
</template>
