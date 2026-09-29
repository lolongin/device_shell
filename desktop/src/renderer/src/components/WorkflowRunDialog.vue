<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { CircleAlert, FileUp, ListChecks, LoaderCircle, Play, Search, ShieldAlert, X } from 'lucide-vue-next'
import { useDialogFocus } from '../composables/useDialogFocus'
import { desktopApi } from '../transport/api'
import { useWorkspaceStore } from '../stores/workspace'
import type { PublishedWorkflowDefinition, WorkflowRuntimeInput } from '../types'
import { createWorkflowPlatformAdapter } from '../composables/useWorkflowPlatform'

const props = defineProps<{ initialDeviceId?: string; initialWorkflowId?: string; initialVersion?: string | number; autoRun?: boolean }>()
const emit = defineEmits<{ close: []; openStudio: [] }>()
const workspace = useWorkspaceStore()
const platform = createWorkflowPlatformAdapter(() => workspace.devices)
const dialog = ref<HTMLElement | null>(null)
const { handleDialogKeydown } = useDialogFocus(dialog, { initialFocus: '[data-dialog-initial-focus]' })
const workflows = ref<PublishedWorkflowDefinition[]>([])
const loading = ref(true)
const running = ref(false)
const error = ref('')
const query = ref('')
const selectedId = ref('')
const selectedDeviceId = ref(props.initialDeviceId || workspace.selectedDeviceId)
const selectedTargetDeviceIds = ref<string[]>(props.initialDeviceId ? [props.initialDeviceId] : (workspace.selectedDeviceId ? [workspace.selectedDeviceId] : []))
const values = reactive<Record<string, any>>({})
const fileDirectories = reactive<Record<string, string>>({})
const fileNames = reactive<Record<string, string>>({})
const confirmedRisks = ref(false)
const requestedVersionMissing = ref(false)
const dialogVisible = ref(!props.autoRun)

const filteredWorkflows = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return workflows.value
  return workflows.value.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(needle))
})
const selectedWorkflow = computed(() => workflows.value.find((item) => item.id === selectedId.value) || null)
const workflowInputs = computed(() => selectedWorkflow.value?.input_contract || selectedWorkflow.value?.inputs || [])
const usesDeviceListTarget = computed(() => workflowInputs.value.some(isDeviceListInput))
const selectedDevice = computed(() => workspace.devices.find((item) => item.id === selectedDeviceId.value || item.row_id === selectedDeviceId.value) || null)
function isDeviceListInput(input: WorkflowRuntimeInput): boolean {
  return input.semanticType === 'device_list' || input.type === 'devices' || input.multiple === true || input.control?.id === 'device-list-picker'
}
const canRun = computed(() => Boolean(selectedWorkflow.value && (usesDeviceListTarget.value ? selectedTargetDeviceIds.value.length : selectedDevice.value) && !running.value && (!selectedWorkflow.value.requires_confirmation || confirmedRisks.value) && !invalidInput.value))
const invalidInput = computed(() => Boolean(workflowInputs.value.some((input) => {
  const value = values[input.name]
  if (input.required && (value === undefined || value === null || (typeof value === 'string' && !value.trim()))) return true
  const primitiveType = input.primitiveType || input.type
  if (isDeviceListInput(input)) return false
  if ((primitiveType === 'integer' || primitiveType === 'number') && value !== undefined && value !== '') {
    const parsed = Number(value)
    if (!Number.isFinite(parsed) || (primitiveType === 'integer' && !Number.isInteger(parsed))) return true
  }
  if ((primitiveType === 'array' || primitiveType === 'object') && value !== undefined && value !== '') {
    try {
      const parsed = JSON.parse(String(value))
      if (primitiveType === 'array' ? !Array.isArray(parsed) : !parsed || Array.isArray(parsed) || typeof parsed !== 'object') return true
    } catch { return true }
  }
  return false
})))

function inputLabel(input: WorkflowRuntimeInput): string { return input.name.replaceAll('_', ' ') }
function initialInputValue(input: WorkflowRuntimeInput): unknown {
  const primitiveType = input.primitiveType || input.type
  if (input.default === undefined || input.default === null) return primitiveType === 'boolean' ? false : isDeviceListInput(input) || primitiveType === 'array' ? [] : ''
  if (primitiveType === 'array' || primitiveType === 'object') return JSON.stringify(input.default, null, 2)
  return input.default
}
function resetInputs(workflow: PublishedWorkflowDefinition | null): void {
  for (const key of Object.keys(values)) delete values[key]
  for (const key of Object.keys(fileDirectories)) delete fileDirectories[key]
  for (const key of Object.keys(fileNames)) delete fileNames[key]
  for (const input of (workflow?.input_contract || workflow?.inputs || [])) {
    values[input.name] = initialInputValue(input)
    if (input.semanticType === 'file' || input.type === 'file' || input.name === 'package_path') {
      const raw = String(values[input.name] || '').replace(/\\/g, '/')
      const separator = raw.lastIndexOf('/')
      fileDirectories[input.name] = separator >= 0 ? raw.slice(0, separator) : ''
      fileNames[input.name] = separator >= 0 ? raw.slice(separator + 1) : raw
    }
  }
  confirmedRisks.value = false
}
function selectWorkflow(workflow: PublishedWorkflowDefinition): void {
  selectedId.value = workflow.id
  resetInputs(workflow)
}
function toggleTargetDevice(deviceId: string, checked: boolean): void {
  const selected = new Set(selectedTargetDeviceIds.value)
  if (checked) selected.add(deviceId)
  else selected.delete(deviceId)
  selectedTargetDeviceIds.value = Array.from(selected)
}
function inputType(input: WorkflowRuntimeInput): string {
  const primitiveType = input.primitiveType || input.type
  if (primitiveType === 'integer' || primitiveType === 'number') return 'number'
  return 'text'
}
function parseValue(input: WorkflowRuntimeInput): unknown {
  const value = values[input.name]
  const primitiveType = input.primitiveType || input.type
  if (isDeviceListInput(input)) return Array.isArray(value) ? value : (value ? [value] : [])
  if (primitiveType === 'integer') return value === '' ? undefined : Number(value)
  if (primitiveType === 'number') return value === '' ? undefined : Number(value)
  if (primitiveType === 'boolean') return Boolean(value)
  if (primitiveType === 'array' || primitiveType === 'object') {
    if (value === '' || value === undefined) return undefined
    return JSON.parse(String(value))
  }
  return value
}
function selectedDeviceIds(input: WorkflowRuntimeInput): string[] {
  const value = values[input.name]
  return Array.isArray(value) ? value.map(String) : value ? [String(value)] : []
}
function toggleDeviceId(input: WorkflowRuntimeInput, deviceId: string, checked: boolean): void {
  const selected = new Set(selectedDeviceIds(input))
  if (checked) selected.add(deviceId)
  else selected.delete(deviceId)
  values[input.name] = Array.from(selected)
}
async function chooseFile(input: WorkflowRuntimeInput): Promise<void> {
  const selected = await platform.pickFile(input)
  if (selected) values[input.name] = selected
}
async function chooseDirectory(input: WorkflowRuntimeInput): Promise<void> {
  const selected = await platform.pickDirectory(input, fileDirectories[input.name])
  if (!selected) return
  fileDirectories[input.name] = selected.replace(/\\/g, '/')
  updateRuntimeFileValue(input)
}
function updateRuntimeFileValue(input: WorkflowRuntimeInput): void {
  const directory = String(fileDirectories[input.name] || '').replace(/[\\/]$/, '')
  const name = String(fileNames[input.name] || '').trim()
  values[input.name] = directory && name ? `${directory}/${name}` : directory || name
}
function updateRuntimeFilePart(input: WorkflowRuntimeInput, part: 'directory' | 'name', event: Event): void {
  const value = (event.target as HTMLInputElement).value
  if (part === 'directory') fileDirectories[input.name] = value
  else fileNames[input.name] = value
  updateRuntimeFileValue(input)
}
async function loadCatalog(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    workflows.value = (await desktopApi.publishedWorkflowDefinitions()).workflows
    if (props.initialWorkflowId) {
      if (props.initialVersion !== undefined) {
        const versions = (await desktopApi.workflowVersions(props.initialWorkflowId)).versions
        const target = versions.find((item) => String(item.version) === String(props.initialVersion))
        if (target) {
          workflows.value = [target, ...workflows.value.filter((item) => item.id !== target.id)]
          selectWorkflow(target)
        } else {
          requestedVersionMissing.value = true
          error.value = `发布版本 v${props.initialVersion} 不存在或已被删除，请重新选择版本。`
          return
        }
      } else {
        const catalogItem = workflows.value.find((item) => item.id === props.initialWorkflowId)
        if (catalogItem) selectWorkflow(catalogItem)
      }
    }
    if (!selectedId.value && !requestedVersionMissing.value && workflows.value[0]) selectWorkflow(workflows.value[0])
    else if (selectedWorkflow.value) resetInputs(selectedWorkflow.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { loading.value = false }
}
async function runWorkflow(): Promise<void> {
  const workflow = selectedWorkflow.value
  const device = selectedDevice.value
  if (!workflow || (!usesDeviceListTarget.value && !device) || (usesDeviceListTarget.value && !selectedTargetDeviceIds.value.length) || !canRun.value) return
  running.value = true
  error.value = ''
  try {
    const inputs: Record<string, unknown> = {}
    for (const input of (workflow.input_contract || workflow.inputs)) {
      const value = usesDeviceListTarget.value && isDeviceListInput(input)
        ? selectedTargetDeviceIds.value
        : parseValue(input)
      if (value !== undefined && value !== '') inputs[input.name] = value
    }
    const targetIds = usesDeviceListTarget.value ? selectedTargetDeviceIds.value : [device!.id]
    const session = workspace.sessions.find((item) => item.device_id === targetIds[0] && item.status === 'connected')
    const result = await desktopApi.runWorkflowDefinition(workflow.id, {
      ...(usesDeviceListTarget.value ? { device_ids: targetIds } : { device_id: targetIds[0] }),
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
      if (device) workspace.selectDevice(device.row_id)
      workspace.upgradePanelOpen = true
    }
    emit('close')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally { running.value = false }
}
watch(() => props.initialDeviceId, (value) => { if (value) selectedDeviceId.value = value })
onMounted(async () => {
  await loadCatalog()
  const workflow = selectedWorkflow.value
  if (props.autoRun && workflow && !(workflow.input_contract || workflow.inputs).length && !workflow.requires_confirmation && selectedDevice.value) {
    await runWorkflow()
    return
  }
  dialogVisible.value = true
})
</script>

<template>
  <Teleport to="body">
  <div v-show="dialogVisible" class="dialog-backdrop workflow-run-backdrop" @mousedown.self="emit('close')">
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
            <label v-if="!usesDeviceListTarget" class="workflow-run-field"><span>目标设备</span><select v-model="selectedDeviceId"><option value="" disabled>选择设备</option><option v-for="device in workspace.devices" :key="device.row_id" :value="device.id">{{ device.name }} · {{ device.id }}</option></select></label>
            <div v-else class="workflow-run-field"><span>目标设备（可多选）</span><div class="workflow-device-list" role="group" aria-label="目标设备选择"><label v-for="target in workspace.devices" :key="target.row_id" class="workflow-device-option"><input type="checkbox" :checked="selectedTargetDeviceIds.includes(target.id)" @change="toggleTargetDevice(target.id, ($event.target as HTMLInputElement).checked)" /><span>{{ target.name }} · {{ target.id }}</span></label></div><small class="workflow-device-selection-count">已选择 {{ selectedTargetDeviceIds.length }} 台设备</small></div>
            <div v-if="workflowInputs.length" class="workflow-run-inputs">
              <template v-for="input in workflowInputs" :key="input.name">
              <label v-if="!(usesDeviceListTarget && isDeviceListInput(input))" class="workflow-run-field">
                <span>{{ inputLabel(input) }}<em v-if="input.required">必填</em></span>
                <small v-if="input.description">{{ input.description }}</small>
                <template v-if="input.control?.id === 'device-picker' || input.semanticType === 'device'">
                  <select v-model="values[input.name]"><option value="" disabled>选择设备</option><option v-for="device in workspace.devices" :key="device.row_id" :value="device.id">{{ device.name }} · {{ device.id }}</option></select>
                </template>
                <template v-else-if="isDeviceListInput(input)">
                  <div class="workflow-device-list" role="group" :aria-label="`${inputLabel(input)}设备选择`">
                    <label v-for="device in workspace.devices" :key="device.row_id" class="workflow-device-option">
                      <input type="checkbox" :checked="selectedDeviceIds(input).includes(device.id)" @change="toggleDeviceId(input, device.id, ($event.target as HTMLInputElement).checked)" />
                      <span>{{ device.name }} · {{ device.id }}</span>
                    </label>
                    <small v-if="!workspace.devices.length" class="workflow-device-list-empty">暂无可选设备</small>
                  </div>
                  <small class="workflow-device-selection-count">已选择 {{ selectedDeviceIds(input).length }} 台设备</small>
                </template>
                <template v-else-if="input.control?.id === 'file-picker' || input.semanticType === 'file' || input.type === 'file' || input.name === 'package_path'">
                  <div v-if="input.name === 'package_path'" class="workflow-run-file-parts">
                    <div class="workflow-run-file-row"><input :value="fileDirectories[input.name]" placeholder="本机文件夹路径" @input="updateRuntimeFilePart(input, 'directory', $event)" /><button class="workflow-run-file" type="button" @click="chooseDirectory(input)"><FileUp :size="14" />选择文件夹</button></div>
                    <input :value="fileNames[input.name]" placeholder="文件名，例如 image.cc" @input="updateRuntimeFilePart(input, 'name', $event)" />
                  </div>
                  <div v-else class="workflow-run-file-row"><input v-model="values[input.name]" :placeholder="String(input.uiHints?.placeholder || '选择本机文件')" readonly /><button class="workflow-run-file" type="button" @click="chooseFile(input)"><FileUp :size="14" />选择文件</button></div>
                </template>
                <textarea v-else-if="(input.primitiveType || input.type) === 'array' || (input.primitiveType || input.type) === 'object'" v-model="values[input.name]" rows="3" :placeholder="(input.primitiveType || input.type) === 'array' ? '[...]' : '{...}'" />
                <input v-else-if="(input.primitiveType || input.type) === 'boolean'" v-model="values[input.name]" type="checkbox" />
                <input v-else v-model="values[input.name]" :type="inputType(input)" :step="input.type === 'number' ? 'any' : (input.primitiveType || input.type) === 'number' ? 'any' : (input.primitiveType || input.type) === 'integer' ? '1' : undefined" />
              </label>
              </template>
            </div>
            <label v-if="selectedWorkflow.requires_confirmation" class="workflow-run-risk"><input v-model="confirmedRisks" type="checkbox" /><ShieldAlert :size="16" /><span>此 Workflow 包含高风险动作，确认后执行</span></label>
            <p v-if="error" class="workflow-run-error" role="alert"><CircleAlert :size="15" />{{ error }}</p>
            <footer class="workflow-run-footer"><span v-if="usesDeviceListTarget">将为选中的设备分别创建执行任务</span><span v-else-if="selectedDevice">将使用 {{ selectedDevice.name }} 的现有连接（如可用）</span><button class="secondary-button" type="button" @click="emit('close')">取消</button><button class="primary-button" type="submit" :disabled="!canRun"><LoaderCircle v-if="running" :size="14" class="spin" /><Play v-else :size="14" />{{ running ? '正在提交' : '开始执行' }}</button></footer>
          </template>
          <div v-else class="workflow-run-state workflow-run-form-empty"><CircleAlert v-if="requestedVersionMissing" :size="22" /><ListChecks v-else :size="22" />{{ requestedVersionMissing ? error : '从左侧选择一个已发布 Workflow' }}</div>
        </form>
      </div>
    </section>
  </div>
  </Teleport>
</template>
