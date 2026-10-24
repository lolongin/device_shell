import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import { desktopApi, type AgentApproval, type AgentEventRecord } from '../transport/api'
import type { TaskRecord } from '../types'

export function useApplicationAgent(open: Ref<boolean>, options: { initialConversationId?: string; storageKey?: string } = {}) {
  const storageKey = options.storageKey || 'odyterm.agent.sidebar-conversation'
  const savedId = options.initialConversationId || localStorage.getItem(storageKey)
  const conversationId = ref(savedId && /^[a-zA-Z0-9_-]{1,160}$/.test(savedId) ? savedId : crypto.randomUUID())
  watch(conversationId, id => localStorage.setItem(storageKey, id), { immediate: true })
  const conversations = ref<Array<{ conversation_id: string; title: string; last_message: string; message_count: number; updated_at: number }>>([])
  const requests = ref(new Set<string>())
  const loading = ref(true)
  const serverBusy = ref(false)
  const error = ref('')
  const events = ref<AgentEventRecord[]>([])
  const approvals = ref<AgentApproval[]>([])
  const tasks = ref<Record<string, TaskRecord>>({})
  const pending = computed(() => approvals.value.filter(item => item.status === 'pending'))
  const working = computed(() => requests.value.has(conversationId.value) || serverBusy.value || loading.value)
  let cursor = 0
  let generation = 0
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
    const current = poll()
    pollPromise = current
    try { await current }
    finally { if (pollPromise === current) pollPromise = null }
  }

  async function poll(): Promise<void> {
    const id = conversationId.value
    const version = generation
    try {
      const firstPage = cursor === 0
      const state = await desktopApi.aiAgentState(id, cursor)
      if (version !== generation) return
      serverBusy.value = state.busy
      loading.value = false
      if (firstPage) {
        const persistedEvents: AgentEventRecord[] = []
        for (const [index, message] of state.history.entries()) {
          const role = message.role
          if (role === 'system' || (role === 'assistant' && message.tool_calls) || (role === 'user' && String(message.content || '').startsWith('Backend restarted:'))) continue
          const content = message.content
          if (role === 'user') persistedEvents.push({ sequence: -(index + 1), type: 'agent.started', data: { message: String(content || '') }, created_at: 0 })
          else if (role === 'assistant') persistedEvents.push({ sequence: -(index + 1), type: 'agent.message', data: { content: String(content || '') }, created_at: 0 })
          else if (role === 'tool') {
            let output: unknown = content
            try { output = JSON.parse(String(content || 'null')) } catch { /* preserve plain text result */ }
            persistedEvents.push({ sequence: -(index + 1), type: 'agent.tool.output', data: { tool: message.name, output }, created_at: 0 })
          }
        }
        events.value = state.events.length ? state.events : persistedEvents
      } else {
        events.value = [...events.value, ...state.events].slice(-300)
      }
      cursor = state.cursor
      approvals.value = state.approvals
      events.value.forEach(event => captureTasks(event.data))
      state.approvals.forEach(captureTasks)
      const active = Object.values(tasks.value).filter(task => !['completed', 'failed', 'cancelled'].includes(task.status))
      await Promise.all(active.map(async task => {
        const response = await desktopApi.getTask(task.id)
        if (version === generation) tasks.value[task.id] = response.task
      }))
    } catch (cause) {
      if (version === generation) {
        loading.value = false
        error.value = cause instanceof Error ? cause.message : String(cause)
      }
    }
  }

  async function send(message: string, target: { device_id?: string; session_id?: string } = {}): Promise<void> {
    if (working.value || !message.trim()) return
    const id = conversationId.value
    requests.value.add(id)
    error.value = ''
    try {
      await desktopApi.aiChat({ conversation_id: id, message, ...target })
    } catch (cause) {
      if (id === conversationId.value) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      requests.value.delete(id)
      if (id === conversationId.value) await refresh(true)
      await loadConversations()
    }
  }

  async function resolve(approval: AgentApproval, decision: 'approve' | 'reject'): Promise<void> {
    if (working.value) return
    const id = conversationId.value
    requests.value.add(id)
    error.value = ''
    try {
      await desktopApi.aiAgentResolve(id, approval.id, decision)
      if (id === conversationId.value) await refresh(true)
    } catch (cause) {
      if (id === conversationId.value) error.value = cause instanceof Error ? cause.message : String(cause)
    } finally { requests.value.delete(id) }
    if (id === conversationId.value && !error.value && !pending.value.length) await send('请读取应用审批结果并继续观察任务；不要重复执行已提交的操作。')
  }

  async function control(task: TaskRecord, action: 'pause' | 'resume' | 'cancel'): Promise<void> {
    const version = generation
    error.value = ''
    try {
      const response = await ({ pause: desktopApi.pauseTask, resume: desktopApi.resumeTask, cancel: desktopApi.cancelTask })[action](task.id)
      if (version === generation) tasks.value[task.id] = response.task
    } catch (cause) {
      if (version === generation) error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function loadConversations(): Promise<void> {
    try { conversations.value = (await desktopApi.aiAgentConversations()).conversations }
    catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  }

  async function newConversation(): Promise<void> {
    await switchConversation(crypto.randomUUID())
    await loadConversations()
  }

  async function switchConversation(id: string): Promise<void> {
    if (!/^[a-zA-Z0-9_-]{1,160}$/.test(id) || id === conversationId.value) return
    generation += 1
    pollPromise = null
    conversationId.value = id
    loading.value = true
    serverBusy.value = false
    cursor = 0
    events.value = []
    approvals.value = []
    tasks.value = {}
    error.value = ''
    await refresh(true)
  }

  async function renameConversation(id: string, title: string): Promise<void> {
    const result = await desktopApi.renameAiAgentConversation(id, title)
    const conversation = conversations.value.find(item => item.conversation_id === id)
    if (conversation) conversation.title = result.conversation.title
  }

  async function deleteConversation(id: string): Promise<void> {
    await desktopApi.deleteAiAgentConversation(id)
    conversations.value = conversations.value.filter(item => item.conversation_id !== id)
    if (id === conversationId.value) await newConversation()
  }

  watch(open, visible => {
    if (timer) clearInterval(timer)
    if (visible) {
      void refresh(); void loadConversations()
      let ticks = 0
      timer = setInterval(() => { void refresh(); if (++ticks % 5 === 0) void loadConversations() }, 1000)
    }
  }, { immediate: true })
  onUnmounted(() => { if (timer) clearInterval(timer) })
  return { conversationId, conversations, busy: working, error, events, approvals, pending, tasks, send, resolve, control, refresh, loadConversations, newConversation, switchConversation, renameConversation, deleteConversation }
}
