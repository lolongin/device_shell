import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import { desktopApi, type AgentApproval, type AgentEventRecord } from '../transport/api'
import type { TaskRecord } from '../types'

export function useApplicationAgent(open: Ref<boolean>) {
  const conversationId = crypto.randomUUID()
  const busy = ref(false)
  const serverBusy = ref(false)
  const error = ref('')
  const events = ref<AgentEventRecord[]>([])
  const approvals = ref<AgentApproval[]>([])
  const tasks = ref<Record<string, TaskRecord>>({})
  const pending = computed(() => approvals.value.filter(item => item.status === 'pending'))
  const working = computed(() => busy.value || serverBusy.value)
  let cursor = 0
  let pollPromise: Promise<void> | null = null
  let timer: ReturnType<typeof setInterval> | undefined

  function captureTasks(value: unknown): void {
    if (!value || typeof value !== 'object') return
    if (Array.isArray(value)) { value.forEach(captureTasks); return }
    const item = value as Record<string, unknown>
    if (typeof item.id === 'string' && typeof item.workflow_id === 'string' && typeof item.status === 'string' && 'progress_percent' in item) {
      tasks.value[item.id] = item as unknown as TaskRecord
      return
    }
    for (const key of ['data', 'output', 'task', 'tasks', 'observations', 'result', 'approval']) captureTasks(item[key])
  }

  async function refresh(fresh = false): Promise<void> {
    if (pollPromise) {
      await pollPromise
      if (!fresh) return
    }
    pollPromise = poll().finally(() => { pollPromise = null })
    await pollPromise
  }

  async function poll(): Promise<void> {
    try {
      const state = await desktopApi.aiAgentState(conversationId, cursor)
      cursor = state.cursor
      serverBusy.value = state.busy
      events.value = [...events.value, ...state.events].slice(-300)
      approvals.value = state.approvals
      state.events.forEach(event => captureTasks(event.data))
      state.approvals.forEach(captureTasks)
      const active = Object.values(tasks.value).filter(task => !['completed', 'failed', 'cancelled'].includes(task.status))
      await Promise.all(active.map(async task => {
        const response = await desktopApi.getTask(task.id)
        tasks.value[task.id] = response.task
      }))
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function send(message: string, target: { device_id?: string; session_id?: string } = {}): Promise<void> {
    if (working.value || !message.trim()) return
    busy.value = true
    error.value = ''
    try {
      await desktopApi.aiChat({ conversation_id: conversationId, message, ...target })
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      busy.value = false
      await refresh(true)
    }
  }

  async function resolve(approval: AgentApproval, decision: 'approve' | 'reject'): Promise<void> {
    if (working.value) return
    busy.value = true
    error.value = ''
    try {
      await desktopApi.aiAgentResolve(conversationId, approval.id, decision)
      await refresh(true)
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally { busy.value = false }
    if (!error.value && !pending.value.length) await send('请读取应用审批结果并继续观察任务；不要重复执行已提交的操作。')
  }

  async function control(task: TaskRecord, action: 'pause' | 'resume' | 'cancel'): Promise<void> {
    error.value = ''
    try {
      const response = await ({ pause: desktopApi.pauseTask, resume: desktopApi.resumeTask, cancel: desktopApi.cancelTask })[action](task.id)
      tasks.value[task.id] = response.task
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  watch(open, visible => {
    if (timer) clearInterval(timer)
    if (visible) { void refresh(); timer = setInterval(() => { void refresh() }, 1000) }
  }, { immediate: true })
  onUnmounted(() => { if (timer) clearInterval(timer) })
  return { busy: working, error, events, approvals, pending, tasks, send, resolve, control, refresh }
}
