<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { Check, CircleAlert, CirclePause, CirclePlay, CircleStop, FileArchive, RotateCcw, ShieldAlert, Workflow, X } from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import type { TaskDecisionActionPayload, TaskRecord, TaskStepState, WorkflowParameterDescriptor } from '../types'

const workspace = useWorkspaceStore()
const taskMode = ref<'upgrade' | 'plan'>('upgrade')
const workflowId = ref('')
const workflowParameters = ref<Record<string, unknown>>({})
const planObjective = ref('')
const planCommand = ref('')
const localError = ref('')
let refreshTimer: ReturnType<typeof setInterval> | null = null

const workflowOptions = computed(() => workspace.workflows)
const selectedWorkflow = computed(() => workflowOptions.value.find((item) => item.id === workflowId.value) || workflowOptions.value[0] || null)
const workflowParametersVisible = computed(() => selectedWorkflow.value?.parameters.filter((item) => !item.advanced) || [])
const selectedTask = computed(() => workspace.tasks.find((task) => task.id === workspace.activeTaskId) || null)
const taskSteps = computed<TaskStepState[]>(() => {
  const task = selectedTask.value
  if (!task) return []
  if (task.checkpoint?.step_states?.length) return task.checkpoint.step_states
  return (task.result?.steps || []).map((step) => ({
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
})
const decisionActions = computed(() => workspace.taskDecision?.available_actions || [])
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

const labels: Record<string, string> = {
  precheck: '预检', backup: '备份', upload: '上传', verify: '校验', activate: '激活',
  reboot: '重启', wait_online: '等待上线', verify_version: '版本确认', validation: '最终验证',
  prepare_upgrade: '准备系统包并设置启动项', package_upgrade: '换包流程',
}

const upgradeStageLabels: Record<string, string> = {
  queued: '排队',
  prechecking: '预检启动项与存储',
  cleanup: '清理未使用旧包',
  downloading: '上传目标系统包',
  verifying: '校验主控系统包',
  synchronizing: '同步并校验备控系统包',
  setting_startup: '设置下次启动项',
  staged: '已暂存，等待重启激活',
  reboot_approval: '等待重启确认',
  rebooting: '重启设备并等待上线',
  completed: '换包完成',
  failed: '换包失败',
  cancelled: '已取消',
}

function stepLabel(stepId: string): string {
  const leaf = stepId.split('.').pop() || stepId
  return labels[leaf] || stepId
}
function stepIcon(state: TaskStepState): string {
  if (state.status === 'completed' || state.status === 'success') return '✓'
  if (state.status === 'failed') return '✕'
  if (state.status === 'running') return '…'
  return '·'
}
function stageHistory(state: TaskStepState): Array<Record<string, unknown>> {
  const data = state.result?.data
  if (!data || typeof data !== 'object') return []
  const operation = data.operation
  const operationData = operation && typeof operation === 'object'
    ? (operation as Record<string, unknown>).data
    : null
  const history = operationData && typeof operationData === 'object'
    ? (operationData as Record<string, unknown>).stage_history
    : data.stage_history
  if (!Array.isArray(history)) return []
  return history.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
}
function stageLabel(stage: unknown): string {
  const value = String(stage || '')
  return upgradeStageLabels[value] || value
}
function stageStatus(item: Record<string, unknown>, index: number, history: Array<Record<string, unknown>>): string {
  const status = String(item.status || '')
  if (status === 'waiting_approval') return 'waiting_for_decision'
  if (status === 'staged') return 'completed'
  if (status === 'failed' || status === 'cancelled') return status
  if (index < history.length - 1) return 'completed'
  return status === 'completed' ? 'completed' : 'running'
}
function stageMessage(item: Record<string, unknown>): string {
  return String(item.message || '')
}
function stageActions(item: Record<string, unknown>): string[] {
  const actions = item.actions
  if (!Array.isArray(actions)) return []
  return actions.map((action) => String(action || '').trim()).filter(Boolean)
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
  if (detail) {
    if (code === 'version_mismatch' || code.includes('verify') || detail.toLowerCase().includes('unknown command')) return detail
    return detail
  }
  if (code === 'version_mismatch' || code.includes('verify')) return '软件包校验失败'
  return task.message || task.checkpoint?.error_message || code
}
function taskStatusLabel(task: TaskRecord | null): string {
  if (!task) return ''
  if (task.status === 'waiting_for_user' || task.status === 'waiting_for_decision') return '等待人工确认'
  if (task.status === 'running' || task.status === 'resumed') return '工作流执行中'
  if (task.status === 'paused') return '任务已暂停'
  if (task.status === 'cancelled') return '任务已取消'
  if (task.status === 'completed' || task.status === 'success') return '工作流已完成'
  if (task.status === 'failed') return errorMessage(task) || '工作流失败'
  return task.message || task.status
}
function taskStatusMessage(task: TaskRecord | null): string {
  if (!task || task.status === 'completed' || task.status === 'success') return ''
  if (task.status === 'waiting_for_user' || task.status === 'waiting_for_decision') return '等待人工确认后继续工作流。'
  if (task.status === 'failed') return errorMessage(task) || '工作流失败'
  return ''
}
function actionLabel(action: string, targetStep = ''): string {
  if (action === 'retry' && targetStep === 'verify') return '重新校验'
  if (action === 'resume_from' && targetStep === 'upload') return '重新上传'
  return ({ retry: '重新执行', retry_step: '重新执行', continue: '确认继续', accept: '确认继续', accept_failure: '确认继续', resume_from: '从此步骤恢复', approve: '确认执行', cancel: '终止任务', pause: '暂停任务', resume: '继续任务' } as Record<string, string>)[action] || action
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
  const next: Record<string, unknown> = {}
  for (const parameter of workflow.parameters) {
    if (parameter.control === 'file') {
      const current = workflowParameters.value[parameter.name]
      next[parameter.name] = current || workflowFiles(parameter)[0]?.relative_path || ''
    } else if (parameter.default !== undefined) {
      next[parameter.name] = parameter.default
    }
  }
  workflowParameters.value = next
}

function workflowParameterOptions(parameter: WorkflowParameterDescriptor): Array<{ value: string; label: string }> {
  return (parameter.enum || []).map((value) => ({
    value: String(value),
    label: parameter.enum_labels?.[String(value)] || String(value),
  }))
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
      extensions: parameter.file_extensions || [],
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
  await workspace.applyTaskDecision({ name: action.name, target_step: actionTarget(action), parameters: action.parameters }, actionLabel(action.name, actionTarget(action)))
}
async function retryFailedStep(): Promise<void> {
  if (failedStepId.value) await workspace.resumeTask(workspace.activeTaskId, failedStepId.value)
}
async function resumeFromPreviousStep(): Promise<void> {
  if (previousStepId.value) await workspace.resumeTask(workspace.activeTaskId, previousStepId.value)
}
async function chooseTask(task: TaskRecord): Promise<void> {
  workspace.activeTaskId = task.id
  await workspace.getTask(task.id)
}
function openLatestTask(): void {
  const latest = workspace.tasks[0]
  if (latest) void chooseTask(latest)
}

onMounted(async () => {
  await workspace.refreshTasks()
  await workspace.refreshWorkflows()
  initializeWorkflowParameters()
  refreshTimer = setInterval(() => { void workspace.refreshTasks() }, 1000)
  openLatestTask()
})
onBeforeUnmount(() => { if (refreshTimer) clearInterval(refreshTimer) })

watch(selectedWorkflow, (workflow) => {
  if (workflow && workflowId.value !== workflow.id) workflowId.value = workflow.id
  initializeWorkflowParameters(workflow)
}, { immediate: true })
watch(() => workspace.transferFiles, () => initializeWorkflowParameters(), { deep: true })
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
      <label><span>设备</span><select :value="workspace.selectedDeviceId" @change="onDeviceChange"><option value="" disabled>选择设备</option><option v-for="device in workspace.devices" :key="device.id" :value="device.id">{{ device.name }} · {{ device.id }}</option></select></label>
      <template v-if="taskMode === 'upgrade'">
        <label><span>Workflow</span><select v-model="workflowId"><option v-for="workflow in workflowOptions" :key="workflow.id" :value="workflow.id">{{ workflow.name }}</option></select></label>
        <p v-if="selectedWorkflow?.description" class="task-workflow-description">{{ selectedWorkflow.description }}</p>
        <div class="task-upgrade-options task-workflow-parameters">
          <label v-for="parameter in workflowParametersVisible" :key="parameter.name">
            <span>{{ parameterLabel(parameter) }}</span>
            <div v-if="parameter.control === 'file'" class="task-package-picker">
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
            <input v-else-if="parameter.type === 'boolean'" type="checkbox" :checked="Boolean(parameterValue(parameter))" @change="onParameterInput(parameter, $event)" />
            <input v-else :type="parameter.type === 'integer' ? 'number' : 'text'" :value="String(parameterValue(parameter) ?? '')" @input="onParameterInput(parameter, $event)" />
            <small v-if="parameter.control === 'file' && parameterValue(parameter) && isLocalPackage(String(parameterValue(parameter)))" class="task-package-hint">本地文件将在创建 Task 时放入文件服务目录</small>
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
      <p v-if="workspace.taskError" class="task-error" role="alert">Task API 暂不可用：{{ workspace.taskError }}</p>
    </div>

    <div class="task-ui-list" aria-label="Task 列表">
      <div class="task-ui-list-heading"><strong>Task 记录</strong><small>{{ workspace.tasks.length }} 条</small></div>
      <button v-for="task in workspace.tasks" :key="task.id" type="button" class="task-row" :data-active="task.id === workspace.activeTaskId" @click="chooseTask(task)">
        <span class="task-row-status" :data-status="task.status"></span><span><strong>{{ task.workflow_id }}</strong><small>{{ task.device_id }} · {{ task.updated_at }}</small></span><b>{{ task.status }}</b>
      </button>
      <p v-if="!workspace.tasks.length" class="task-empty">还没有任务，选择 Workflow 或“制定任务”开始。</p>
    </div>

    <article v-if="selectedTask" class="task-detail">
      <header><div><strong>Task {{ selectedTask.id.slice(0, 8) }}</strong><small>{{ selectedTask.progress_percent }}% · {{ taskStatusLabel(selectedTask) }}</small></div><div class="task-controls">
        <button v-if="selectedTask.status === 'running'" class="secondary-button" type="button" @click="workspace.pauseTask()"><CirclePause :size="13" />暂停</button>
        <button v-if="selectedTask.status === 'paused'" class="secondary-button" type="button" @click="workspace.resumeTask()"><CirclePlay :size="13" />恢复</button>
        <button v-if="selectedTask.status === 'failed' && failedStepId" class="secondary-button" type="button" :disabled="workspace.taskBusy" @click="retryFailedStep"><RotateCcw :size="13" />重试断点</button>
        <button v-if="selectedTask.status === 'failed' && previousStepId" class="secondary-button" type="button" :disabled="workspace.taskBusy" @click="resumeFromPreviousStep"><CirclePlay :size="13" />从上一步恢复</button>
        <button v-if="!isTerminal" class="danger-button task-cancel-button" type="button" @click="workspace.cancelTask()"><CircleStop :size="14" />取消任务</button>
      </div></header>
      <div class="task-progress"><i :style="{ width: `${selectedTask.progress_percent}%` }"></i></div>
      <ol class="task-timeline">
        <li v-for="state in taskSteps" :key="state.step_id" :data-status="state.status"><span>{{ stepIcon(state) }}</span><div><strong>{{ stepLabel(state.step_id) }}</strong><small>{{ state.status }} · attempt {{ state.attempt }}</small><small v-if="state.result?.execution_id || state.result?.operation_id" class="task-resource-id">{{ state.result?.execution_id ? `Execution ${state.result.execution_id}` : `Operation ${state.result?.operation_id}` }}</small><p v-if="state.error">{{ state.error.message || state.error.code }}</p><details v-if="stepOutput(state)" class="task-step-output"><summary>查看过程输出</summary><pre>{{ stepOutput(state) }}</pre></details><details v-if="stepEvidence(state).length" class="task-step-output task-step-evidence"><summary>查看执行证据（{{ stepEvidence(state).length }}）</summary><div v-for="(item, index) in stepEvidence(state)" :key="`${state.step_id}-evidence-${index}`"><small>{{ evidenceTitle(item) }}</small><pre>{{ JSON.stringify(item, null, 2) }}</pre></div></details><ol v-if="stageHistory(state).length" class="task-substeps" aria-label="换包内部步骤"><li v-for="(item, index) in stageHistory(state)" :key="`${state.step_id}-${String(item.stage)}-${index}`" :data-status="stageStatus(item, index, stageHistory(state))"><span>{{ stageStatus(item, index, stageHistory(state)) === 'completed' ? '✓' : stageStatus(item, index, stageHistory(state)) === 'failed' ? '✕' : '…' }}</span><div><strong>{{ stageLabel(item.stage) }}</strong><small>{{ stageStatus(item, index, stageHistory(state)) }} · {{ String(item.progress_percent || 0) }}%</small><p v-if="stageMessage(item)">{{ stageMessage(item) }}</p><ul v-if="stageActions(item).length" class="task-stage-actions"><li v-for="action in stageActions(item)" :key="action">{{ action }}</li></ul></div></li></ol></div></li>
      </ol>
      <div v-if="taskStatusMessage(selectedTask)" class="task-status-banner" :data-status="selectedTask.status"><CircleAlert :size="16" /><span>{{ taskStatusMessage(selectedTask) }}</span></div>
      <div v-if="workspace.taskDecision" class="task-decision" role="dialog" aria-labelledby="task-decision-title">
        <div class="task-decision-heading"><ShieldAlert :size="16" /><div><strong id="task-decision-title">需要人工 Action</strong><small>{{ workspace.taskDecision.current_step }} · revision {{ workspace.taskDecision.checkpoint_revision }}</small></div></div>
        <p v-if="workspace.taskDecision.error?.message">{{ workspace.taskDecision.error.message }}</p>
        <div class="task-decision-actions"><button v-for="action in decisionActions" :key="`${action.name}-${action.target_step}`" class="secondary-button" type="button" :disabled="workspace.taskBusy" @click="applyAction(action)">{{ actionLabel(action.name, action.target_step || String(action.parameters?.step_id || '')) }}</button></div>
      </div>
      <div v-if="selectedTask.checkpoint?.decisions?.length" class="task-activity">
        <strong>Agent / Decision 记录</strong>
        <div v-for="decision in selectedTask.checkpoint.decisions" :key="String(decision.decision_id || decision.timestamp || decision.reason)">
          <small>{{ decisionActionName(decision) || 'decision' }} · {{ decisionActorType(decision) }}</small>
          <p v-if="decisionReason(decision)">{{ decisionReason(decision) }}</p>
        </div>
      </div>
      <div v-if="selectedTask.status === 'completed'" class="task-success"><Check :size="15" />换包 Task 已完成</div>
      <div v-else-if="selectedTask.status === 'failed'" class="task-failure"><CircleAlert :size="15" />换包 Task 失败</div>
    </article>
  </section>
</template>
