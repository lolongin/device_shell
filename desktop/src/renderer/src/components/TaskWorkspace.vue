<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Check, CircleAlert, CirclePause, CirclePlay, CircleStop, Copy, FileArchive, RotateCcw, ShieldAlert, Trash2, Workflow, X } from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import { desktopApi } from '../transport/api'
import type { TaskDecisionActionPayload, TaskRecord, TaskStepState, WorkflowParameterDescriptor } from '../types'

const workspace = useWorkspaceStore()
const taskMode = ref<'upgrade' | 'plan'>('upgrade')
const workflowId = ref('')
const workflowParameters = ref<Record<string, unknown>>({})
const planObjective = ref('')
const planCommand = ref('')
const localError = ref('')
const copyNotice = ref('')
const reportBusy = ref(false)
const decisionInputReason = ref('')
const selectedTaskIds = ref<Set<string>>(new Set())
let initializedWorkflowId = ''
let refreshTimer: ReturnType<typeof setInterval> | null = null
let copyNoticeTimer: ReturnType<typeof setTimeout> | null = null

const workflowOptions = computed(() => workspace.workflows)
const selectedWorkflow = computed(() => workflowOptions.value.find((item) => item.id === workflowId.value) || workflowOptions.value[0] || null)
const workflowParametersVisible = computed(() => selectedWorkflow.value?.parameters.filter((item) => !item.advanced) || [])
const selectedTask = computed(() => workspace.tasks.find((task) => task.id === workspace.activeTaskId) || null)
const workflowActionLabels: Record<string, string> = {
  'terminal.command': '执行命令',
  'terminal.batch': '批量执行命令',
  'terminal.wait': '等待终端输出',
  'device.info': '获取设备信息',
  'device.select': '选择设备',
  'device.wait_online': '等待设备上线',
  'device.reboot': '重启设备',
  'device.verify_version': '校验设备版本',
  'utility.wait': '等待',
  'utility.confirm': '人工确认',
  'file.transfer': '文件传输',
}
const terminalTasks = computed(() => workspace.tasks.filter((task) => isTerminalStatus(task.status)))
const taskSummary = computed(() => ({
  total: workspace.tasks.length,
  completed: workspace.tasks.filter((task) => task.status === 'completed' || task.status === 'succeeded').length,
  failed: workspace.tasks.filter((task) => task.status === 'failed').length,
  waiting: workspace.tasks.filter((task) => ['waiting_for_decision', 'waiting_for_user', 'paused', 'waiting_child', 'waiting_reconcile'].includes(task.status)).length,
}))
const selectedTerminalTaskCount = computed(() => terminalTasks.value.filter((task) => selectedTaskIds.value.has(task.id)).length)
const allTerminalTasksSelected = computed(() => terminalTasks.value.length > 0 && selectedTerminalTaskCount.value === terminalTasks.value.length)
const someTerminalTasksSelected = computed(() => selectedTerminalTaskCount.value > 0 && !allTerminalTasksSelected.value)
const taskSteps = computed<TaskStepState[]>(() => {
  const task = selectedTask.value
  if (!task) return []
  if (task.checkpoint?.step_states?.length) return task.checkpoint.step_states
  const resultSteps = (task.result?.steps || []).map((step) => ({
    step_id: step.step_id,
    status: step.status,
    attempt: 1,
    result: {
      status: step.status,
      output: step.output || '',
      facts: step.data || {},
      data: step.data || {},
      operation_id: step.operation_id || '',
      execution_id: step.execution_id || '',
      evidence: step.evidence || []
    },
    error: step.error_code
      ? { code: step.error_code, message: step.message || step.error_code }
      : null
  }))
  if (resultSteps.length) return resultSteps

  // Generic TaskPlan projections expose their declared states without a
  // legacy checkpoint. Keep the workflow visible and infer lightweight state
  // from the current task boundary until child details are available.
  const states = task.workflow_view?.states || []
  if (!states.length) return []
  const currentIndex = states.findIndex((state) => state.id === task.current_step_id)
  const terminal = ['completed', 'failed', 'cancelled'].includes(task.status)
  return states.map((state, index) => {
    const status = terminal && task.status === 'completed'
      ? 'completed'
      : task.status === 'failed' && state.id === task.current_step_id
        ? 'failed'
        : currentIndex >= 0 && index < currentIndex
          ? 'completed'
          : state.id === task.current_step_id
            ? 'running'
            : 'pending'
    return { step_id: state.id, status, attempt: 1, result: null, error: null }
  })
})
const decisionActions = computed(() => workspace.taskDecision?.available_actions || [])
const workflowStateById = computed(() => new Map(
  (selectedTask.value?.workflow_view?.states || []).map((state) => [state.id, state])
))
const isFrameworkTask = computed(() => Boolean(selectedTask.value?.workflow_view?.states?.length))
const isTerminal = computed(() => Boolean(selectedTask.value && ['completed', 'failed', 'cancelled'].includes(selectedTask.value.status)))
const failedStepId = computed(() => {
  const task = selectedTask.value
  if (!task) return ''
  return task.current_step_id || task.checkpoint?.failed_step_id || taskSteps.value.find((step) => step.status === 'failed')?.step_id || ''
})
const previousStepId = computed(() => {
  const index = taskSteps.value.findIndex((step) => step.step_id === failedStepId.value)
  return index > 0 ? taskSteps.value[index - 1]?.step_id || '' : ''
})

function stepLabel(stepId: string): string {
  const state = workflowStateById.value.get(stepId)
  return workflowActionLabels[state?.action_id || state?.operation || ''] || state?.label || stepId
}
function taskCurrentStepLabel(task: TaskRecord | null): string {
  if (!task) return ''
  if (task.status === 'completed' || task.status === 'success') return '全部步骤已完成'
  return task.current_step_id ? stepLabel(task.current_step_id) : '准备执行'
}
function taskWorkflowLabel(task: TaskRecord): string {
  return workspace.workflows.find((workflow) => workflow.id === task.workflow_id)?.name
    || task.workflow_view?.id
    || task.workflow_id
    || '未命名 Workflow'
}
function stepDescription(stepId: string): string {
  return workflowStateById.value.get(stepId)?.description || ''
}
function stepIcon(state: TaskStepState): string {
  if (state.status === 'completed' || state.status === 'success') return '✓'
  if (state.status === 'failed') return '✕'
  if (state.status === 'running') return '…'
  if (state.status === 'skipped') return '–'
  if (state.status === 'waiting' || state.status === 'waiting_for_user' || state.status === 'waiting_for_decision') return '◷'
  return '·'
}
function stepStatusLabel(status: string): string {
  if (status === 'completed' || status === 'success') return '已完成'
  if (status === 'failed') return '执行失败'
  if (status === 'running') return '执行中'
  if (status === 'skipped') return '已跳过'
  if (status === 'waiting' || status === 'waiting_for_user' || status === 'waiting_for_decision') return '等待确认'
  if (status === 'pending') return '排队中'
  return '等待执行'
}
function stepOutput(state: TaskStepState): string {
  const direct = state.result?.output
  if (typeof direct === 'string' && direct.trim()) return direct
  const data = state.result?.data
  if (data && Array.isArray(data.steps)) {
    const nested = data.steps
      .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
      .map((item) => String(item.output || ''))
      .filter(Boolean)
      .join('\n')
    if (nested.trim()) return nested
  }
  const raw = selectedTask.value?.checkpoint?.outputs?.[state.step_id]
  if (typeof raw === 'string' && raw.trim()) return raw
  if (raw && typeof raw === 'object') {
    const output = (raw as Record<string, unknown>).output
    if (typeof output === 'string' && output.trim()) return output
    const facts = (raw as Record<string, unknown>).facts
    if (facts && typeof facts === 'object') {
      const factOutput = (facts as Record<string, unknown>).output
      if (typeof factOutput === 'string' && factOutput.trim()) return factOutput
    }
  }
  return ''
}
function stepEvidence(state: TaskStepState): Array<Record<string, unknown>> {
  const evidence = state.result?.evidence
  return Array.isArray(evidence)
    ? evidence.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    : []
}
function evidenceTitle(item: Record<string, unknown>): string {
  const kind = String(item.kind || 'evidence')
  const id = String(item.execution_id || item.operation_id || '')
  return id ? `${kind} · ${id}` : kind
}
function decisionReason(decision: Record<string, unknown>): string {
  const reason = decision.reason
  return typeof reason === 'string' ? reason : ''
}
function decisionActionName(decision: Record<string, unknown>): string {
  const action = decision.action
  if (!action || typeof action !== 'object') return ''
  const name = (action as Record<string, unknown>).name
  return typeof name === 'string' ? name : ''
}
function decisionActorType(decision: Record<string, unknown>): string {
  const actor = decision.actor
  if (!actor || typeof actor !== 'object') return 'operator'
  const type = (actor as Record<string, unknown>).type
  return typeof type === 'string' ? type : 'operator'
}
function errorMessage(task: TaskRecord | null): string {
  if (!task) return ''
  const code = task.error_code || task.checkpoint?.error_code || ''
  const failedState = task.checkpoint?.step_states.find((state) => state.status === 'failed')
  const detail = failedState?.error?.message || task.checkpoint?.error_message || ''
  if (code === 'unresolved_task_input' || code === 'task_input_dependency_missing') {
    return '流程输入引用无效，请检查节点依赖和输出字段配置。'
  }
  if (detail) {
    const normalized = detail.toLowerCase()
    if (normalized.includes('timeout') || normalized.includes('timed out')) return '设备响应超时，请检查连接后重试。'
    if (normalized.includes('connection') || normalized.includes('connect')) return '设备连接失败，请确认设备在线。'
    if (normalized.includes('permission') || normalized.includes('denied')) return '设备拒绝了操作，请检查账号权限。'
    if (code === 'version_mismatch' || code.includes('verify') || detail.toLowerCase().includes('unknown command')) return detail
    return detail
  }
  if (code === 'version_mismatch' || code.includes('verify')) return '软件包校验失败'
  return task.message || task.checkpoint?.error_message || code
}
function taskErrorDetails(task: TaskRecord): string {
  const failedState = task.checkpoint?.step_states?.find((state) => state.status === 'failed')
  const resultFailedStep = task.result?.steps?.find((step) => step.status === 'failed')
  const rawMessage = task.message || task.checkpoint?.error_message || task.result?.message || ''
  const details = {
    task_id: task.id,
    workflow: taskWorkflowLabel(task),
    workflow_id: task.workflow_id,
    device_id: task.device_id,
    status: task.status,
    current_step_id: task.current_step_id || task.checkpoint?.current_step || '',
    failed_step_id: task.checkpoint?.failed_step_id || failedState?.step_id || resultFailedStep?.step_id || '',
    error_code: task.error_code || task.checkpoint?.error_code || task.result?.error_code || '',
    message: rawMessage,
    display_message: errorMessage(task),
    failed_step: failedState
      ? {
          step_id: failedState.step_id,
          status: failedState.status,
          attempt: failedState.attempt,
          error: failedState.error,
        }
      : resultFailedStep
        ? {
            step_id: resultFailedStep.step_id,
            status: resultFailedStep.status,
            error_code: resultFailedStep.error_code || '',
            message: resultFailedStep.message || '',
          }
        : null,
    result: task.result
      ? {
          status: task.result.status || '',
          error_code: task.result.error_code || '',
          message: task.result.message || '',
        }
      : null,
    checkpoint: task.checkpoint
      ? {
          revision: task.checkpoint.revision,
          current_step: task.checkpoint.current_step,
          failed_step_id: task.checkpoint.failed_step_id,
          error_code: task.checkpoint.error_code,
          error_message: task.checkpoint.error_message,
        }
      : null,
    updated_at: task.updated_at,
  }
  return JSON.stringify(details, null, 2)
}
const selectedTaskErrorDetails = computed(() => selectedTask.value ? taskErrorDetails(selectedTask.value) : '')
function showCopyNotice(message: string): void {
  copyNotice.value = message
  if (copyNoticeTimer) clearTimeout(copyNoticeTimer)
  copyNoticeTimer = setTimeout(() => { copyNotice.value = '' }, 2600)
}
async function copyText(text: string, successMessage: string): Promise<void> {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    showCopyNotice(successMessage)
  } catch {
    showCopyNotice('复制失败，请检查系统剪贴板权限')
  }
}
async function copySelectedTaskError(): Promise<void> {
  await copyText(selectedTaskErrorDetails.value, '错误详情已复制')
}
async function copyTaskApiError(): Promise<void> {
  await copyText(`Task API 暂不可用：${workspace.taskError}`, 'Task API 错误已复制')
}
function taskStatusLabel(task: TaskRecord | null): string {
  if (!task) return ''
  if (task.status === 'waiting_for_user' || task.status === 'waiting_for_decision') return '等待人工确认'
  if (task.status === 'running' || task.status === 'resumed') return '工作流执行中'
  if (task.status === 'paused') return '任务已暂停'
  if (task.status === 'cancelled') return '任务已取消'
  if (task.status === 'completed' || task.status === 'success') return '工作流已完成'
  if (task.status === 'failed') return errorMessage(task) || '工作流失败'
  if (task.status === 'waiting_child' || task.status === 'waiting_reconcile') return '等待系统处理'
  if (task.status === 'unknown') return '状态待确认'
  return task.message || '任务处理中'
}
function taskStatusMessage(task: TaskRecord | null): string {
  if (!task || task.status === 'completed' || task.status === 'success') return ''
  if (task.status === 'waiting_for_user' || task.status === 'waiting_for_decision') return '等待人工确认后继续工作流。'
  if (task.status === 'waiting_child' || task.status === 'waiting_reconcile') return '系统正在整理执行结果，请稍候。'
  if (task.status === 'unknown') return '暂时无法确认任务状态，请刷新后再试。'
  if (task.status === 'failed') return errorMessage(task) || '工作流失败'
  return ''
}
function actionLabel(action: TaskDecisionActionPayload & { metadata?: Record<string, unknown> }): string {
  return String(action.metadata?.label || action.name)
}
function actionDescription(action: TaskDecisionActionPayload & { metadata?: Record<string, unknown> }): string {
  return String(action.metadata?.description || '')
}
function actionRequiresReason(action: TaskDecisionActionPayload & { metadata?: Record<string, unknown> }): boolean {
  return Boolean(action.metadata?.requires_reason)
}
function actionTarget(action: TaskDecisionActionPayload): string {
  return action.target_step || String(action.parameters?.step_id || '')
}
function onDeviceChange(event: Event): void {
  workspace.selectDevice((event.target as HTMLSelectElement).value)
}

function packageName(value: string): string {
  return value.split(/[\\/]/).pop() || value
}

function isLocalPackage(value: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(value) || value.startsWith('/') || value.startsWith('\\\\')
}

function parameterValue(parameter: WorkflowParameterDescriptor): unknown {
  return workflowParameters.value[parameter.name]
}

function parameterLabel(parameter: WorkflowParameterDescriptor): string {
  return parameter.label || parameter.name
}

function setParameter(name: string, value: unknown): void {
  workflowParameters.value = { ...workflowParameters.value, [name]: value }
}

function initializeWorkflowParameters(workflow = selectedWorkflow.value): void {
  if (!workflow) return
  const current = initializedWorkflowId === workflow.id ? workflowParameters.value : {}
  const next: Record<string, unknown> = {}
  for (const parameter of workflow.parameters) {
    const hasCurrent = Object.prototype.hasOwnProperty.call(current, parameter.name)
    const currentValue = current[parameter.name]
    if (hasCurrent && !(parameter.control === 'file' && !String(currentValue || '').trim())) {
      next[parameter.name] = currentValue
    } else if (parameter.control === 'file') {
      next[parameter.name] = workflowFiles(parameter)[0]?.relative_path || ''
    } else if (parameter.default !== undefined) {
      next[parameter.name] = parameter.default
    }
  }
  workflowParameters.value = next
  initializedWorkflowId = workflow.id
}

function workflowParameterOptions(parameter: WorkflowParameterDescriptor): Array<{ value: string; label: string }> {
  return (parameter.enum || []).map((value) => ({
    value: String(value),
    label: parameter.enum_labels?.[String(value)] || String(value),
  }))
}

function usesDevicePackage(): boolean {
  return String(workflowParameters.value.package_source || 'local') === 'device'
}

function workflowFiles(parameter: WorkflowParameterDescriptor) {
  const extensions = (parameter.file_extensions || []).map((item) => item.toLowerCase())
  if (!extensions.length) return workspace.transferFiles
  return workspace.transferFiles.filter((file) => extensions.some((extension) => file.name.toLowerCase().endsWith(extension)))
}

function onParameterInput(parameter: WorkflowParameterDescriptor, event: Event): void {
  const input = event.target as HTMLInputElement | HTMLSelectElement
  if (parameter.type === 'boolean') {
    setParameter(parameter.name, (input as HTMLInputElement).checked)
  } else if (parameter.type === 'integer') {
    setParameter(parameter.name, Number(input.value))
  } else {
    setParameter(parameter.name, input.value)
  }
}

async function chooseWorkflowFile(parameter: WorkflowParameterDescriptor): Promise<void> {
  localError.value = ''
  try {
    const selected = await window.desktopApi.chooseWorkflowFile({
      defaultPath: workspace.transferSettings?.root || '',
      label: parameterLabel(parameter),
      // Workflow descriptors are reactive objects. Convert the extension
      // list to plain data before crossing Electron's structured-clone IPC.
      extensions: Array.isArray(parameter.file_extensions)
        ? parameter.file_extensions.map((extension) => String(extension))
        : [],
    })
    if (selected) {
      setParameter(parameter.name, selected)
    }
  } catch (cause) {
    localError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function createTask(): Promise<void> {
  localError.value = ''
  if (taskMode.value === 'plan') {
    if (!planObjective.value.trim() || !planCommand.value.trim()) {
      localError.value = '请输入任务目标和第一步命令。'
      return
    }
    await workspace.createWorkflowPlanTask(planObjective.value, planCommand.value)
    return
  }
  if (!workspace.selectedDeviceId) {
    localError.value = '请选择设备。'
    return
  }
  if (!selectedWorkflow.value) {
    localError.value = 'Workflow 目录尚未加载。'
    return
  }
  const missing = selectedWorkflow.value.parameters.find((parameter) => {
    if (!parameter.required) return false
    const value = workflowParameters.value[parameter.name]
    return value === undefined || value === null || String(value).trim() === ''
  })
  if (missing) {
    localError.value = `请填写${parameterLabel(missing)}。`
    return
  }
  if (selectedWorkflow.value.parameters.some((item) => item.name === 'expected_version')) {
    workflowParameters.value = {
      ...workflowParameters.value,
      expected_version: workflowParameters.value.expected_version || workspace.selectedDevice?.version || '',
    }
  }
  await workspace.createNamedWorkflowTask(selectedWorkflow.value.id, workflowParameters.value)
}
async function applyAction(action: TaskDecisionActionPayload): Promise<void> {
  const option = action as TaskDecisionActionPayload & { metadata?: Record<string, unknown> }
  if (actionRequiresReason(option) && !decisionInputReason.value.trim()) {
    localError.value = '此决策需要填写原因。'
    return
  }
  await workspace.applyTaskDecision({ name: option.name, target_step: actionTarget(option), parameters: option.parameters }, decisionInputReason.value.trim())
  decisionInputReason.value = ''
}
async function retryFailedStep(): Promise<void> {
  if (failedStepId.value) await workspace.resumeTask(workspace.activeTaskId, failedStepId.value)
}
async function downloadReport(): Promise<void> {
  if (!selectedTask.value) return
  reportBusy.value = true
  localError.value = ''
  try {
    const report = await desktopApi.taskReport(selectedTask.value.id)
    const cell = (value: unknown): string => {
      const text = String(value ?? '')
      const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text
      return `"${safe.replaceAll('"', '""')}"`
    }
    const rows = report.rows.length ? report.rows : [{ 流程: report.summary.workflow_id, 设备: report.summary.device_id, 总体状态: report.summary.status }]
    const csv = [report.columns, ...rows.map(row => report.columns.map(column => (row as Record<string, unknown>)[column]))].map(row => row.map(cell).join(',')).join('\r\n')
    const url = URL.createObjectURL(new Blob(['\ufeff', csv], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url
    link.download = report.filename
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) {
    localError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    reportBusy.value = false
  }
}
async function resumeFromPreviousStep(): Promise<void> {
  if (previousStepId.value) await workspace.resumeTask(workspace.activeTaskId, previousStepId.value)
}
async function chooseTask(task: TaskRecord): Promise<void> {
  workspace.activeTaskId = task.id
  // Selecting a record is a read-only action. Do not steal the terminal
  // focus from a device/session the operator is currently inspecting.
  await workspace.getTask(task.id, false)
}
async function deleteTask(task: TaskRecord): Promise<void> {
  if (!isTerminalStatus(task.status)) return
  if (!window.confirm(`确定删除 Task ${task.id.slice(0, 8)} 的记录吗？`)) return
  await workspace.deleteTask(task.id)
}
function toggleTaskSelection(task: TaskRecord): void {
  if (!isTerminalStatus(task.status)) return
  const next = new Set(selectedTaskIds.value)
  if (next.has(task.id)) next.delete(task.id)
  else next.add(task.id)
  selectedTaskIds.value = next
}
function toggleAllTerminalTasks(): void {
  selectedTaskIds.value = allTerminalTasksSelected.value
    ? new Set()
    : new Set(terminalTasks.value.map((task) => task.id))
}
async function deleteSelectedTasks(): Promise<void> {
  const ids = terminalTasks.value.filter((task) => selectedTaskIds.value.has(task.id)).map((task) => task.id)
  if (!ids.length) return
  if (!window.confirm(`确定删除选中的 ${ids.length} 条 Task 记录吗？`)) return
  if (await workspace.deleteTasks(ids)) selectedTaskIds.value = new Set()
}
function isTerminalStatus(status: string): boolean {
  return ['completed', 'failed', 'cancelled'].includes(status)
}
function openLatestTask(): void {
  const latest = workspace.tasks[0]
  // Restoring task details must not replace the device or terminal currently
  // open in the main workspace.
  if (latest) void chooseTask(latest)
}

onMounted(async () => {
  await workspace.refreshTasks()
  await workspace.refreshWorkflows()
  initializeWorkflowParameters()
  refreshTimer = setInterval(() => { void workspace.refreshTasks() }, 1000)
  openLatestTask()
})
onBeforeUnmount(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  if (copyNoticeTimer) clearTimeout(copyNoticeTimer)
})

watch(selectedWorkflow, (workflow) => {
  if (workflow && workflowId.value !== workflow.id) workflowId.value = workflow.id
  initializeWorkflowParameters(workflow)
}, { immediate: true })
watch(() => workspace.transferFiles, () => initializeWorkflowParameters(), { deep: true })
watch(() => workspace.tasks.map((task) => ({ id: task.id, status: task.status })), (items) => {
  const available = new Set(items.filter((item) => isTerminalStatus(item.status)).map((item) => item.id))
  selectedTaskIds.value = new Set([...selectedTaskIds.value].filter((id) => available.has(id)))
})
</script>

<template>
  <section class="task-ui" aria-labelledby="task-ui-title">
    <header class="task-ui-header">
      <div class="task-ui-title"><span class="task-ui-icon"><Workflow :size="18" /></span><div><p class="eyebrow">BACKEND TASK</p><h3 id="task-ui-title">任务工作区</h3></div></div>
      <button class="icon-button" type="button" aria-label="关闭任务面板" @click="workspace.upgradePanelOpen = false"><X :size="15" /></button>
    </header>

    <div class="task-ui-create">
      <div class="task-mode-tabs" role="tablist" aria-label="任务类型">
        <button type="button" :class="{ active: taskMode === 'upgrade' }" @click="taskMode = 'upgrade'"><RotateCcw :size="13" />Workflow</button>
        <button type="button" :class="{ active: taskMode === 'plan' }" @click="taskMode = 'plan'"><Workflow :size="13" />制定任务</button>
      </div>
      <label><span>设备</span><select :value="workspace.selectedDeviceRowId" @change="onDeviceChange"><option value="" disabled>选择设备</option><option v-for="device in workspace.devices" :key="device.row_id" :value="device.row_id">{{ device.name }} · {{ device.id }}</option></select></label>
      <template v-if="taskMode === 'upgrade'">
        <label><span>Workflow</span><select v-model="workflowId"><option v-for="workflow in workflowOptions" :key="workflow.id" :value="workflow.id">{{ workflow.name }}</option></select></label>
        <p v-if="selectedWorkflow?.description" class="task-workflow-description">{{ selectedWorkflow.description }}</p>
        <div class="task-upgrade-options task-workflow-parameters">
          <label v-for="parameter in workflowParametersVisible" :key="parameter.name">
            <span>{{ parameterLabel(parameter) }}</span>
            <div v-if="parameter.control === 'file' && parameter.name === 'package_path' && usesDevicePackage()" class="task-device-package-input">
              <input type="text" :value="String(parameterValue(parameter) ?? '')" placeholder="例如 flash:/S5735-V200R023C00.cc" @input="onParameterInput(parameter, $event)" />
            </div>
            <div v-else-if="parameter.control === 'file'" class="task-package-picker">
              <select :value="String(parameterValue(parameter) || '')" @change="onParameterInput(parameter, $event)">
                <option value="" disabled>选择{{ parameterLabel(parameter) }}</option>
                <option v-if="parameterValue(parameter) && !workflowFiles(parameter).some((file) => file.relative_path === parameterValue(parameter))" :value="String(parameterValue(parameter))">{{ packageName(String(parameterValue(parameter))) }}</option>
                <option v-for="file in workflowFiles(parameter)" :key="file.relative_path" :value="file.relative_path">{{ file.name }}</option>
              </select>
              <button class="secondary-button" type="button" :title="`从本机选择${parameterLabel(parameter)}`" @click="chooseWorkflowFile(parameter)"><FileArchive :size="13" />选择文件</button>
            </div>
            <select v-else-if="parameter.control === 'select'" :value="String(parameterValue(parameter) ?? '')" @change="onParameterInput(parameter, $event)">
              <option v-for="option in workflowParameterOptions(parameter)" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <div v-else-if="parameter.type === 'boolean'" class="task-toggle" :class="{ 'is-on': Boolean(parameterValue(parameter)) }">
              <input type="checkbox" :checked="Boolean(parameterValue(parameter))" @change="onParameterInput(parameter, $event)" />
              <span class="task-toggle-track" aria-hidden="true"><i></i></span>
              <b>{{ Boolean(parameterValue(parameter)) ? '已开启' : '已关闭' }}</b>
            </div>
            <input v-else :type="parameter.type === 'integer' ? 'number' : 'text'" :value="String(parameterValue(parameter) ?? '')" @input="onParameterInput(parameter, $event)" />
            <small v-if="parameter.control === 'file' && parameter.name === 'package_path' && usesDevicePackage()" class="task-package-hint">使用设备已有包，不启动本地 FTP 传输</small>
            <small v-else-if="parameter.control === 'file' && parameterValue(parameter) && isLocalPackage(String(parameterValue(parameter)))" class="task-package-hint">本地文件将在创建 Task 时放入文件服务目录</small>
          </label>
        </div>
        <button class="primary-button" type="button" :disabled="workspace.taskBusy || !selectedWorkflow || !workspace.selectedDeviceId" @click="createTask"><RotateCcw :size="14" />创建 Workflow Task</button>
      </template>
      <template v-else>
        <label><span>任务目标</span><input v-model="planObjective" placeholder="例如：检查设备版本" /></label>
        <label><span>第一步命令</span><input v-model="planCommand" placeholder="例如：display version" /></label>
        <button class="primary-button" type="button" :disabled="workspace.taskBusy || !planObjective.trim() || !planCommand.trim() || !workspace.selectedDeviceId" @click="createTask"><Workflow :size="14" />校验并创建 Task</button>
      </template>
      <p v-if="localError" class="task-error" role="alert">{{ localError }}</p>
      <div v-if="workspace.taskError" class="task-error task-error-with-action" role="alert"><span>Task API 暂不可用：{{ workspace.taskError }}</span><button class="icon-button" type="button" title="复制 Task API 错误" aria-label="复制 Task API 错误" @click="copyTaskApiError"><Copy :size="13" /></button></div>
      <p v-if="copyNotice" class="task-copy-notice" role="status" aria-live="polite">{{ copyNotice }}</p>
    </div>

    <div class="task-ui-list" aria-label="Task 列表">
      <div class="task-ui-list-heading"><strong>Task 记录</strong><div class="task-ui-list-actions"><small>{{ workspace.tasks.length }} 条 · ✓{{ taskSummary.completed }}　✕{{ taskSummary.failed }}　⏸{{ taskSummary.waiting }}</small><label v-if="terminalTasks.length" class="task-select-all" title="选择全部已结束任务"><input type="checkbox" :checked="allTerminalTasksSelected" :indeterminate="someTerminalTasksSelected" :disabled="workspace.taskBusy" @change="toggleAllTerminalTasks" /><span>已结束</span></label><button v-if="selectedTerminalTaskCount" class="task-bulk-delete" type="button" :disabled="workspace.taskBusy" title="删除选中的任务记录" @click="deleteSelectedTasks"><Trash2 :size="13" />删除选中 ({{ selectedTerminalTaskCount }})</button></div></div>
      <div v-for="task in workspace.tasks" :key="task.id" class="task-row" :data-active="task.id === workspace.activeTaskId" role="button" tabindex="0" @click="chooseTask(task)" @keydown.enter="chooseTask(task)">
        <input v-if="isTerminalStatus(task.status)" class="task-row-select" type="checkbox" :checked="selectedTaskIds.has(task.id)" :disabled="workspace.taskBusy" :aria-label="`选择 Task ${task.id.slice(0, 8)}`" @click.stop @change="toggleTaskSelection(task)" /><span v-else class="task-row-select-placeholder" aria-hidden="true"></span><span class="task-row-status" :data-status="task.status"></span><span><strong>{{ taskWorkflowLabel(task) }}</strong><small>{{ task.workflow_id }} · {{ task.device_id }} · {{ task.updated_at }}</small></span><b>{{ taskStatusLabel(task) }}</b><button v-if="isTerminalStatus(task.status)" class="task-row-delete" type="button" title="删除任务记录" aria-label="删除任务记录" :disabled="workspace.taskBusy" @click.stop="deleteTask(task)"><Trash2 :size="14" /></button>
      </div>
      <p v-if="!workspace.tasks.length" class="task-empty">还没有任务，选择 Workflow 或“制定任务”开始。</p>
    </div>

    <article v-if="selectedTask" class="task-detail">
      <header><div><strong>{{ taskWorkflowLabel(selectedTask) }}</strong><small>Task {{ selectedTask.id.slice(0, 8) }} · {{ taskStatusLabel(selectedTask) }}</small></div><div class="task-controls">
        <button class="secondary-button" type="button" :disabled="reportBusy" @click="downloadReport"><FileArchive :size="13" />{{ reportBusy ? '正在导出…' : '导出报告' }}</button>
        <button v-if="selectedTask.status === 'running'" class="secondary-button" type="button" @click="workspace.pauseTask()"><CirclePause :size="13" />暂停</button>
        <button v-if="selectedTask.status === 'paused'" class="secondary-button" type="button" @click="workspace.resumeTask()"><CirclePlay :size="13" />恢复</button>
        <button v-if="selectedTask.status === 'failed' && failedStepId" class="secondary-button" type="button" :disabled="workspace.taskBusy" @click="retryFailedStep"><RotateCcw :size="13" />重新执行此步骤</button>
        <button v-if="selectedTask.status === 'failed' && previousStepId" class="secondary-button" type="button" :disabled="workspace.taskBusy" @click="resumeFromPreviousStep"><CirclePlay :size="13" />从上一步继续</button>
        <button v-if="!isTerminal" class="danger-button task-cancel-button" type="button" @click="workspace.cancelTask()"><CircleStop :size="14" />取消任务</button>
      </div></header>
      <div class="task-progress"><i :style="{ width: `${selectedTask.progress_percent}%` }"></i></div>
      <div class="task-detail-summary"><span><small>整体进度</small><strong>{{ selectedTask.progress_percent }}%</strong></span><span><small>步骤</small><strong>{{ taskSteps.filter((step) => step.status === 'completed' || step.status === 'success').length }}/{{ taskSteps.length }}</strong></span><span><small>当前步骤</small><strong>{{ taskCurrentStepLabel(selectedTask) }}</strong></span></div>
      <ol class="task-timeline">
        <li v-for="state in taskSteps" :key="state.step_id" :data-status="state.status"><span>{{ stepIcon(state) }}</span><div><strong>{{ stepLabel(state.step_id) }}</strong><small>{{ stepStatusLabel(state.status) }}<span v-if="state.attempt > 1"> · 第 {{ state.attempt }} 次尝试</span></small><small v-if="state.result?.execution_id || state.result?.operation_id" class="task-resource-id">{{ state.result?.execution_id ? `Execution ${state.result.execution_id}` : `Operation ${state.result.operation_id}` }}</small><p v-if="state.error">{{ state.error.message || state.error.code }}</p><p v-else-if="stepDescription(state.step_id)">{{ stepDescription(state.step_id) }}</p><details v-if="stepOutput(state)" class="task-step-output"><summary>查看过程输出</summary><pre>{{ stepOutput(state) }}</pre></details><details v-if="stepEvidence(state).length" class="task-step-output task-step-evidence"><summary>查看执行证据（{{ stepEvidence(state).length }}）</summary><div v-for="(item, index) in stepEvidence(state)" :key="`${state.step_id}-evidence-${index}`"><small>{{ evidenceTitle(item) }}</small><pre>{{ JSON.stringify(item, null, 2) }}</pre></div></details></div></li>
      </ol>
      <div v-if="taskStatusMessage(selectedTask)" class="task-status-banner" :data-status="selectedTask.status"><CircleAlert :size="16" /><span>{{ taskStatusMessage(selectedTask) }}</span></div>
      <details v-if="selectedTask.status === 'failed'" class="task-error-details" open>
        <summary><span>错误详情</span><button class="secondary-button" type="button" title="复制完整错误详情" @click.stop="copySelectedTaskError"><Copy :size="13" />复制错误详情</button></summary>
        <pre>{{ selectedTaskErrorDetails }}</pre>
      </details>
      <div v-if="workspace.taskDecision" class="task-decision" role="dialog" aria-labelledby="task-decision-title">
        <div class="task-decision-heading"><ShieldAlert :size="16" /><div><strong id="task-decision-title">需要人工决策</strong><small>{{ stepLabel(workspace.taskDecision.current_step) }} · revision {{ workspace.taskDecision.checkpoint_revision }}</small></div></div>
        <p v-if="workspace.taskDecision.error?.message">{{ workspace.taskDecision.error.message }}</p>
        <input v-if="decisionActions.some(action => actionRequiresReason(action))" v-model="decisionInputReason" type="text" placeholder="填写决策原因" />
        <div class="task-decision-actions"><div v-for="action in decisionActions" :key="`${action.name}-${action.target_step}`"><button class="secondary-button" type="button" :disabled="workspace.taskBusy" :title="actionDescription(action)" @click="applyAction(action)">{{ actionLabel(action) }}</button><small v-if="actionDescription(action)">{{ actionDescription(action) }}</small></div></div>
      </div>
      <div v-if="selectedTask.checkpoint?.decisions?.length" class="task-activity">
        <strong>Agent / Decision 记录</strong>
        <div v-for="decision in selectedTask.checkpoint.decisions" :key="String(decision.decision_id || decision.timestamp || decision.reason)">
          <small>{{ decisionActionName(decision) || 'decision' }} · {{ decisionActorType(decision) }}</small>
          <p v-if="decisionReason(decision)">{{ decisionReason(decision) }}</p>
        </div>
      </div>
      <div v-if="selectedTask.status === 'completed'" class="task-success"><Check :size="15" />Workflow Task 已完成</div>
      <div v-else-if="selectedTask.status === 'failed'" class="task-failure"><CircleAlert :size="15" />Workflow Task 失败</div>
    </article>
  </section>
</template>
