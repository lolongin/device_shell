import { computed, type Ref } from 'vue'
import { desktopApi } from '../../transport/api'
import type { SessionSummary, TaskRecord } from '../../types'
import { buildWorkflowRunRequest, buildWorkflowTargets, mergeTasks, taskFailureMessage } from './run-request'

type WorkflowLike = { id: string; version?: string | number; nodes?: unknown[]; name: string }

export function useWorkflowRunActions(options: {
  selected: Ref<WorkflowLike | null>
  selectedDeviceId: Ref<string>
  selectedDeviceIds: Ref<string[]>
  sessions: Ref<SessionSummary[]>
  inputs: Ref<Record<string, unknown>>
  running: Ref<boolean>
  runMessage: Ref<string>
  flowTestRunning: Ref<boolean>
  flowTestTask: Ref<TaskRecord | null>
  flowTestError: Ref<string>
  flowTestRequestId: { value: number }
  updateTasks: (tasks: TaskRecord[]) => void
  persist: () => Promise<boolean>
  validate: () => Promise<boolean>
  hasIssues: Ref<boolean>
  issueMessage: () => string
  showValidationProblem: () => void
  emitClose: () => void
  openTaskPanel: () => void
}) {
  const targets = () => buildWorkflowTargets(options.selectedDeviceIds.value, options.sessions.value, options.selectedDeviceId.value)
  const canTarget = computed(() => targets().length > 0)

  async function run(draft = false): Promise<void> {
    const workflow = options.selected.value
    if (!workflow || !canTarget.value) return
    options.runMessage.value = ''
    await options.validate()
    if (options.hasIssues.value) { options.showValidationProblem(); return }
    if (!await options.persist()) return
    options.running.value = true
    try {
      const result = await desktopApi.runWorkflowDefinition(workflow.id, buildWorkflowRunRequest(targets(), options.inputs.value, {
        protocol: 'auto',
        draft,
        ...(draft || workflow.version === 'draft' ? {} : { version: workflow.version }),
      }))
      const tasks = result.tasks?.length ? result.tasks : result.task ? [result.task] : []
      if (!tasks.length) {
        options.runMessage.value = draft ? '草稿测试运行未返回任务记录。' : '模拟运行完成：流程结构和参数均可执行。'
        return
      }
      options.updateTasks(tasks)
      options.runMessage.value = draft
        ? `草稿任务 ${tasks[0].id.slice(0, 8)} 已创建，正在打开任务监控。`
        : tasks.length > 1 ? `已为 ${tasks.length} 台设备创建任务，正在打开任务监控。` : `任务 ${tasks[0].id.slice(0, 8)} 已创建，正在打开任务监控。`
      options.emitClose()
      options.openTaskPanel()
    } catch (cause) {
      options.runMessage.value = cause instanceof Error ? cause.message : String(cause)
    } finally { options.running.value = false }
  }

  async function test(): Promise<void> {
    const workflow = options.selected.value
    if (!workflow || !canTarget.value || options.flowTestRunning.value) return
    options.flowTestError.value = ''
    options.flowTestTask.value = null
    await options.validate()
    if (options.hasIssues.value) { options.flowTestError.value = options.issueMessage(); options.showValidationProblem(); return }
    if (!await options.persist()) { options.flowTestError.value = options.runMessage.value || '流程保存失败，无法测试'; return }
    options.flowTestRunning.value = true
    const requestId = ++options.flowTestRequestId.value
    try {
      const result = await desktopApi.runWorkflowDefinition(workflow.id, buildWorkflowRunRequest(targets(), options.inputs.value, { protocol: 'simulated', draft: true, confirmed_risks: true }))
      const task = result.tasks?.[0] || result.task
      if (!task) throw new Error('测试运行未返回任务记录')
      options.flowTestTask.value = task
      options.updateTasks([task])
      await monitor(task.id, requestId)
    } catch (cause) {
      options.flowTestError.value = cause instanceof Error ? cause.message : String(cause)
    } finally { options.flowTestRunning.value = false }
  }

  async function monitor(taskId: string, requestId: number): Promise<void> {
    while (requestId === options.flowTestRequestId.value && !terminal.value) {
      await new Promise((resolve) => window.setTimeout(resolve, 500))
      if (requestId !== options.flowTestRequestId.value) return
      try {
        const latest = (await desktopApi.getTask(taskId)).task
        options.flowTestTask.value = latest
        options.flowTestError.value = ['failed', 'cancelled'].includes(String(latest.status)) ? taskFailureMessage(latest) : ''
        options.updateTasks([latest])
      } catch (cause) {
        options.flowTestError.value = `读取任务进度失败：${cause instanceof Error ? cause.message : String(cause)}`
        return
      }
    }
  }

  const terminal = computed(() => ['completed', 'success', 'succeeded', 'failed', 'cancelled'].includes(String(options.flowTestTask.value?.status || '')))
  async function resume(): Promise<void> {
    const task = options.flowTestTask.value
    if (!task || options.flowTestRunning.value || terminal.value) return
    options.flowTestRunning.value = true
    const requestId = ++options.flowTestRequestId.value
    try { await monitor(task.id, requestId) } finally { options.flowTestRunning.value = false }
  }

  return { canTarget, run, test, monitor, resume, terminal }
}
