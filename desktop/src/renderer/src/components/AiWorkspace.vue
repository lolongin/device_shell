<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { Activity, Bot, Check, ChevronRight, CircleAlert, Clock3, ListTodo, Maximize2, MessageSquare, Minimize2, Pause, Play, Send, ShieldCheck, Square, TerminalSquare, X } from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import { useApplicationAgent } from '../composables/useApplicationAgent'
import type { TaskRecord } from '../types'

const workspace = useWorkspaceStore()
const agent = useApplicationAgent(toRef(workspace, 'aiPanelOpen'))
const draft = ref('')
const linkError = ref('')
const view = ref<'conversation' | 'tasks'>('conversation')
const scrollArea = ref<HTMLElement | null>(null)
const expanded = ref(false)
const viewportWidth = ref(window.innerWidth)
const maxPanelWidth = computed(() => Math.max(560, viewportWidth.value - 52))
const savedWidth = Number(localStorage.getItem('odyterm.agent-panel-width'))
const panelWidth = ref(Number.isFinite(savedWidth) && savedWidth >= 560 ? savedWidth : 760)
const panelStyle = computed(() => ({
  width: expanded.value ? 'calc(100vw - 52px)' : `min(${panelWidth.value}px, calc(100vw - 52px))`
}))
const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true })
markdown.disable('image')
markdown.validateLink = value => {
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password
  } catch { return false }
}
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return self.renderToken(tokens, index, options)
}
const markdownCache = new Map<string, string>()
let resizing = false

function renderMarkdown(value: unknown): string {
  const source = String(value ?? '')
  const cached = markdownCache.get(source)
  if (cached !== undefined) return cached
  const html = markdown.render(source)
  if (markdownCache.size >= 300) markdownCache.delete(markdownCache.keys().next().value || '')
  markdownCache.set(source, html)
  return html
}

async function openMarkdownLink(event: MouseEvent): Promise<void> {
  const anchor = (event.target as Element | null)?.closest('a')
  if (!anchor) return
  event.preventDefault()
  const url = anchor.getAttribute('href')
  if (!url) return
  linkError.value = ''
  try { await window.desktopApi.openExternalLink(url) }
  catch (cause) { linkError.value = cause instanceof Error ? cause.message : String(cause) }
}

function resizePanel(event: PointerEvent): void {
  if (!resizing) return
  const maxWidth = Math.max(360, window.innerWidth - 52)
  panelWidth.value = Math.min(maxWidth, Math.max(Math.min(560, maxWidth), window.innerWidth - event.clientX))
}

function syncViewportWidth(): void {
  viewportWidth.value = window.innerWidth
}

function resizeBy(delta: number): void {
  const maxWidth = Math.max(360, window.innerWidth - 52)
  panelWidth.value = Math.min(maxWidth, Math.max(Math.min(560, maxWidth), panelWidth.value + delta))
  localStorage.setItem('odyterm.agent-panel-width', String(panelWidth.value))
}

function stopResize(): void {
  if (!resizing) return
  resizing = false
  localStorage.setItem('odyterm.agent-panel-width', String(panelWidth.value))
  window.removeEventListener('pointermove', resizePanel)
  window.removeEventListener('pointerup', stopResize)
  window.removeEventListener('pointercancel', stopResize)
}

function startResize(event: PointerEvent): void {
  if (expanded.value || event.button !== 0) return
  event.preventDefault()
  resizing = true
  window.addEventListener('pointermove', resizePanel)
  window.addEventListener('pointerup', stopResize)
  window.addEventListener('pointercancel', stopResize)
}

onMounted(() => window.addEventListener('resize', syncViewportWidth))
onBeforeUnmount(() => {
  stopResize()
  window.removeEventListener('resize', syncViewportWidth)
})

const timeline = computed(() => agent.events.value.filter(event =>
  ['agent.started', 'agent.message', 'agent.tool.output', 'agent.error'].includes(event.type)
))
const tasks = computed(() => Object.values(agent.tasks.value))
const pendingApprovals = computed(() => agent.approvals.value.filter(item => item.status === 'pending'))
const resolvedApprovals = computed(() => agent.approvals.value.filter(item => item.status !== 'pending').slice(-5).reverse())
const target = computed(() => workspace.activeSession?.device_id || workspace.selectedDeviceId || '全部设备')
const statusLabel = computed(() => agent.busy.value ? '正在处理' : pendingApprovals.value.length ? '等待审批' : '就绪')

const approvalStatus: Record<string, string> = {
  completed: '已执行', failed: '执行失败', rejected: '已拒绝', expired: '已过期', stale: '内容已变更'
}
const taskStatus: Record<string, string> = {
  pending: '待执行', running: '运行中', resumed: '运行中', paused: '已暂停',
  waiting_for_decision: '等待决策', waiting_for_user: '等待处理',
  completed: '已完成', success: '已完成', failed: '失败', cancelled: '已取消'
}

function format(value: unknown): string {
  return JSON.stringify(value, null, 2) || ''
}

function toolName(value: unknown): string {
  return String(value || '操作').replaceAll('_', '.')
}

function toolResult(value: unknown): string {
  if (!value || typeof value !== 'object') return '已返回结果'
  const result = value as Record<string, unknown>
  if (result.status === 'needs_approval') return '等待审批'
  return result.ok === false ? '未完成' : '已完成'
}

function canControl(task: TaskRecord): boolean {
  return !['completed', 'success', 'failed', 'cancelled'].includes(task.status)
}

async function send(): Promise<void> {
  const message = draft.value.trim()
  if (!message || agent.busy.value || pendingApprovals.value.length) return
  linkError.value = ''
  draft.value = ''
  view.value = 'conversation'
  await agent.send(message, {
    device_id: workspace.activeSession?.device_id || workspace.selectedDeviceId || undefined,
    session_id: workspace.activeSessionId || undefined
  })
  if (agent.error.value) draft.value = message
}

function handleComposerKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  void send()
}

watch(() => timeline.value.length, async () => {
  const element = scrollArea.value
  if (!element || view.value !== 'conversation') return
  const nearBottom = element.scrollHeight - element.scrollTop - element.clientHeight < 120
  await nextTick()
  if (nearBottom) element.scrollTop = element.scrollHeight
})

watch(() => pendingApprovals.value.length, async (count, previous) => {
  if (count <= previous) return
  view.value = 'conversation'
  await nextTick()
  if (scrollArea.value) scrollArea.value.scrollTop = 0
})
</script>

<template>
  <aside v-if="workspace.aiPanelOpen" class="agent-shell" :style="panelStyle" aria-label="AI 操作助手" @keydown.esc="workspace.aiPanelOpen = false">
    <div v-if="!expanded" class="agent-resize-handle" role="separator" tabindex="0" aria-orientation="vertical" aria-label="调整助手宽度" :aria-valuenow="panelWidth" aria-valuemin="560" :aria-valuemax="maxPanelWidth" @pointerdown="startResize" @keydown.left.prevent="resizeBy(40)" @keydown.right.prevent="resizeBy(-40)"></div>
    <header class="agent-header">
      <div class="agent-identity">
        <span class="agent-mark"><Bot :size="18" /></span>
        <div><h2>AI 操作助手</h2><span>OdyTerm Agent</span></div>
      </div>
      <div class="agent-header-actions">
        <button class="agent-icon-button" type="button" :title="expanded ? '还原宽度' : '展开助手'" :aria-label="expanded ? '还原宽度' : '展开助手'" :aria-pressed="expanded" @click="expanded = !expanded"><Minimize2 v-if="expanded" :size="17" /><Maximize2 v-else :size="17" /></button>
        <button class="agent-icon-button" type="button" title="关闭助手" aria-label="关闭助手" @click="workspace.aiPanelOpen = false"><X :size="17" /></button>
      </div>
    </header>

    <div class="agent-context">
      <span class="agent-state"><span class="agent-state-dot" :class="{ busy: agent.busy.value, attention: pendingApprovals.length }"></span>{{ statusLabel }}</span>
      <span class="agent-target" :title="target"><Activity :size="13" />{{ target }}</span>
    </div>

    <nav class="agent-tabs" aria-label="助手视图">
      <button type="button" :class="{ active: view === 'conversation' }" :aria-current="view === 'conversation' ? 'page' : undefined" @click="view = 'conversation'"><MessageSquare :size="15" />对话<span v-if="pendingApprovals.length" class="agent-tab-count">{{ pendingApprovals.length }}</span></button>
      <button type="button" :class="{ active: view === 'tasks' }" :aria-current="view === 'tasks' ? 'page' : undefined" @click="view = 'tasks'"><ListTodo :size="15" />任务<span v-if="tasks.length" class="agent-tab-count">{{ tasks.length }}</span></button>
    </nav>

    <div ref="scrollArea" class="agent-scroll">
      <template v-if="view === 'conversation'">
        <section v-if="pendingApprovals.length" class="agent-approvals" aria-label="待审批操作">
          <div class="agent-section-heading"><ShieldCheck :size="15" /><strong>待确认操作</strong><span>{{ pendingApprovals.length }}</span></div>
          <article v-for="approval in pendingApprovals" :key="approval.id" class="agent-approval">
            <div class="agent-approval-heading"><strong>{{ toolName(approval.tool) }}</strong><span>执行前确认</span></div>
            <dl class="agent-parameters"><div v-for="[key, value] in Object.entries(approval.arguments)" :key="key"><dt>{{ key }}</dt><dd>{{ typeof value === 'string' ? value : format(value) }}</dd></div></dl>
            <details v-if="Object.keys(approval.preview).length" class="agent-details"><summary>校验与预览 <ChevronRight :size="13" /></summary><pre>{{ format(approval.preview) }}</pre></details>
            <div class="agent-approval-actions">
              <button class="agent-primary" type="button" :disabled="agent.busy.value" @click="agent.resolve(approval, 'approve')"><Check :size="14" />批准执行</button>
              <button class="agent-secondary" type="button" :disabled="agent.busy.value" @click="agent.resolve(approval, 'reject')"><X :size="14" />拒绝</button>
            </div>
          </article>
        </section>

        <div v-if="!timeline.length && !pendingApprovals.length" class="agent-empty">
          <span class="agent-empty-icon"><Bot :size="23" /></span>
          <h3>开始一项工作</h3>
          <p>选择当前设备，或从全部设备中指定目标。</p>
          <div class="agent-prompts">
            <button type="button" @click="draft = '列出可用设备和当前任务'">查看设备与任务 <ChevronRight :size="14" /></button>
            <button type="button" @click="draft = '创建检查设备版本的 Workflow，先校验并预览'">编排版本检查 <ChevronRight :size="14" /></button>
          </div>
        </div>

        <ol v-else class="agent-timeline" aria-label="对话记录">
          <li v-for="event in timeline" :key="event.sequence" :class="['agent-entry', event.type === 'agent.started' ? 'from-user' : '', event.type === 'agent.tool.output' ? 'from-tool' : '', event.type === 'agent.error' ? 'is-error' : '']">
            <template v-if="event.type === 'agent.tool.output'">
              <div class="agent-tool-line"><TerminalSquare :size="15" /><strong>{{ toolName(event.data.tool) }}</strong><span>{{ toolResult(event.data.output) }}</span></div>
              <details class="agent-details"><summary>查看结果 <ChevronRight :size="13" /></summary><pre>{{ format(event.data.output) }}</pre></details>
            </template>
            <template v-else>
              <div class="agent-entry-meta"><span>{{ event.type === 'agent.started' ? '你' : event.type === 'agent.error' ? '错误' : '助手' }}</span><time>{{ new Date(event.created_at * 1000).toLocaleTimeString() }}</time></div>
              <div v-if="event.type === 'agent.message'" class="agent-markdown" v-html="renderMarkdown(event.data.message || event.data.content)" @click="openMarkdownLink"></div>
              <p v-else>{{ event.data.message || event.data.content || event.data.error }}</p>
            </template>
          </li>
        </ol>

        <details v-if="resolvedApprovals.length" class="agent-history"><summary>已处理审批 ({{ resolvedApprovals.length }}) <ChevronRight :size="13" /></summary><div v-for="approval in resolvedApprovals" :key="approval.id"><span>{{ toolName(approval.tool) }}</span><strong>{{ approvalStatus[approval.status] || approval.status }}</strong></div></details>
      </template>

      <section v-else class="agent-tasks" aria-label="关联任务">
        <div class="agent-section-heading"><ListTodo :size="15" /><strong>关联任务</strong><span>{{ tasks.length }}</span></div>
        <div v-if="!tasks.length" class="agent-empty agent-task-empty"><Clock3 :size="24" /><h3>暂无任务</h3></div>
        <article v-for="task in tasks" :key="task.id" class="agent-task">
          <div class="agent-task-heading"><strong>{{ task.workflow_id || '任务' }}</strong><span :class="{ failed: task.status === 'failed' }">{{ taskStatus[task.status] || task.status }}</span></div>
          <p>{{ task.message || task.current_step_id || task.id }}</p>
          <div class="agent-task-meta"><span>{{ task.device_id }}</span><span>{{ task.progress_percent }}%</span></div>
          <progress :value="task.progress_percent" max="100" aria-label="任务进度"></progress>
          <div v-if="canControl(task)" class="agent-task-actions">
            <button v-if="['running', 'pending', 'resumed'].includes(task.status)" type="button" title="暂停任务" @click="agent.control(task, 'pause')"><Pause :size="14" />暂停</button>
            <button v-if="task.status === 'paused'" type="button" title="恢复任务" @click="agent.control(task, 'resume')"><Play :size="14" />恢复</button>
            <button type="button" title="取消任务" @click="agent.control(task, 'cancel')"><Square :size="13" />取消</button>
          </div>
        </article>
      </section>
    </div>

    <form class="agent-composer" @submit.prevent="send">
      <p v-if="agent.error.value || linkError" class="agent-error" role="alert"><CircleAlert :size="15" />{{ agent.error.value || linkError }}</p>
      <label for="agent-message">操作目标 · 回车发送，Shift+回车换行</label>
      <textarea id="agent-message" v-model="draft" rows="3" placeholder="描述要完成的工作…" :disabled="agent.busy.value || !!pendingApprovals.length" @keydown="handleComposerKeydown"></textarea>
      <div class="agent-composer-footer"><span>{{ pendingApprovals.length ? '请先处理待确认操作' : target }}</span><button class="agent-send" type="submit" :disabled="agent.busy.value || !!pendingApprovals.length || !draft.trim()"><Send :size="15" />发送</button></div>
    </form>
  </aside>
</template>

<style scoped>
.agent-shell { position: fixed; z-index: 30; top: 32px; right: 0; bottom: 24px; width: min(760px, calc(100vw - 52px)); min-width: 0; display: flex; flex-direction: column; background: var(--surface); border-left: 1px solid var(--line-strong); box-shadow: -16px 0 42px rgba(0, 0, 0, .28); color: var(--text); }
.agent-resize-handle { position: absolute; z-index: 1; inset: 0 auto 0 -5px; width: 10px; cursor: ew-resize; touch-action: none; }
.agent-resize-handle::after { content: ''; position: absolute; top: 42%; bottom: 42%; left: 4px; width: 2px; border-radius: 2px; background: var(--line-strong); }
.agent-resize-handle:hover::after, .agent-resize-handle:focus-visible::after { background: var(--blue); }
.agent-resize-handle:focus-visible { outline: 2px solid var(--blue); outline-offset: 1px; }
.agent-header { flex: none; height: 62px; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 0 20px; border-bottom: 1px solid var(--line); background: var(--surface-raised); }
.agent-header-actions { display: flex; align-items: center; gap: 4px; }
.agent-identity { min-width: 0; display: flex; align-items: center; gap: 11px; }
.agent-mark { width: 34px; height: 34px; display: grid; place-items: center; flex: none; border: 1px solid color-mix(in srgb, var(--accent) 36%, var(--line)); border-radius: 7px; color: var(--accent); background: color-mix(in srgb, var(--accent) 9%, var(--surface)); }
.agent-identity h2 { margin: 0; font-size: 14px; line-height: 1.3; font-weight: 650; }
.agent-identity div > span { display: block; margin-top: 2px; color: var(--soft); font-size: 11px; }
.agent-icon-button { width: 30px; height: 30px; display: grid; place-items: center; flex: none; border: 0; border-radius: 5px; color: var(--muted); background: transparent; cursor: pointer; }
.agent-icon-button:hover { color: var(--text); background: var(--surface-hover); }
.agent-context { flex: none; min-height: 39px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 0 20px; border-bottom: 1px solid var(--line); color: var(--muted); font-size: 11px; }
.agent-state, .agent-target { min-width: 0; display: inline-flex; align-items: center; gap: 7px; }
.agent-target { max-width: 58%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-target svg { flex: none; }
.agent-state-dot { width: 6px; height: 6px; flex: none; border-radius: 50%; background: var(--accent); }
.agent-state-dot.busy { background: var(--blue); }
.agent-state-dot.attention { background: var(--warning); }
.agent-tabs { flex: none; display: flex; gap: 22px; padding: 0 20px; border-bottom: 1px solid var(--line); background: var(--surface-raised); }
.agent-tabs button { position: relative; height: 42px; display: inline-flex; align-items: center; gap: 7px; padding: 0 2px; border: 0; color: var(--muted); background: transparent; cursor: pointer; font-size: 12px; }
.agent-tabs button.active { color: var(--text); font-weight: 650; }
.agent-tabs button.active::after { content: ''; position: absolute; right: 0; bottom: -1px; left: 0; height: 2px; background: var(--accent); }
.agent-tab-count { min-width: 17px; height: 17px; padding: 1px 4px; border-radius: 4px; color: var(--muted); background: var(--surface-hover); font-size: 10px; line-height: 15px; text-align: center; }
.agent-scroll { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 18px 20px 24px; }
.agent-section-heading { display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 11px; }
.agent-section-heading strong { color: var(--text); font-size: 12px; }
.agent-section-heading > span { margin-left: auto; }
.agent-approvals { margin-bottom: 24px; }
.agent-approval { margin-top: 10px; padding: 14px; border: 1px solid color-mix(in srgb, var(--warning) 44%, var(--line)); border-radius: 6px; background: color-mix(in srgb, var(--warning) 5%, var(--surface-raised)); }
.agent-approval-heading, .agent-task-heading, .agent-entry-meta, .agent-task-meta { min-width: 0; display: flex; align-items: baseline; justify-content: space-between; gap: 10px; }
.agent-approval-heading strong { overflow-wrap: anywhere; font-size: 12px; }
.agent-approval-heading span { flex: none; color: var(--warning); font-size: 11px; }
.agent-parameters { display: grid; gap: 7px; max-height: 150px; overflow-y: auto; margin: 12px 0; padding: 10px 0; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.agent-parameters > div { display: grid; grid-template-columns: minmax(90px, 32%) minmax(0, 1fr); gap: 8px; }
.agent-parameters dt { color: var(--muted); font-size: 11px; overflow-wrap: anywhere; }
.agent-parameters dd { min-width: 0; margin: 0; color: var(--text); font-family: Consolas, 'Cascadia Code', monospace; font-size: 11px; overflow-wrap: anywhere; white-space: pre-wrap; }
.agent-details { margin-top: 8px; }
.agent-details summary, .agent-history summary { display: flex; align-items: center; gap: 5px; width: fit-content; color: var(--muted); cursor: pointer; font-size: 11px; list-style: none; }
.agent-details summary::-webkit-details-marker, .agent-history summary::-webkit-details-marker { display: none; }
.agent-details[open] summary svg, .agent-history[open] summary svg { transform: rotate(90deg); }
.agent-details pre { max-height: 230px; overflow: auto; margin: 10px 0 0; padding: 10px; border: 1px solid var(--line); border-radius: 4px; background: var(--surface); color: var(--muted); font-family: Consolas, 'Cascadia Code', monospace; font-size: 11px; white-space: pre-wrap; overflow-wrap: anywhere; }
.agent-approval-actions { display: flex; gap: 8px; margin-top: 14px; }
.agent-approval-actions button, .agent-task-actions button, .agent-send { min-height: 30px; display: inline-flex; align-items: center; justify-content: center; gap: 6px; border-radius: 5px; padding: 5px 10px; cursor: pointer; font-size: 11px; font-weight: 600; }
.agent-primary, .agent-send { border: 1px solid var(--accent-hover); background: var(--accent-hover); color: white; }
.agent-primary:hover:not(:disabled), .agent-send:hover:not(:disabled) { background: var(--accent); }
.agent-secondary, .agent-task-actions button { border: 1px solid var(--line-strong); background: var(--surface-raised); color: var(--text); }
.agent-secondary:hover:not(:disabled), .agent-task-actions button:hover:not(:disabled) { background: var(--surface-hover); }
.agent-timeline { display: grid; gap: 4px; margin: 0; padding: 0; list-style: none; }
.agent-entry { min-width: 0; padding: 14px 0; border-bottom: 1px solid var(--line); }
.agent-entry:first-child { padding-top: 0; }
.agent-entry-meta { color: var(--muted); font-size: 11px; }
.agent-entry-meta span { font-weight: 650; color: var(--text); }
.agent-entry.from-user { padding-left: 12px; border-left: 2px solid var(--blue); background: color-mix(in srgb, var(--blue) 4%, transparent); }
.agent-entry.from-user .agent-entry-meta { padding-right: 12px; }
.agent-entry p { margin: 8px 0 0; color: var(--text); font-size: 13px; line-height: 1.65; white-space: pre-wrap; overflow-wrap: anywhere; }
.agent-entry.from-user p { padding-right: 12px; }
.agent-entry.is-error p { color: var(--danger); }
.agent-markdown { min-width: 0; margin-top: 9px; color: var(--text); font-size: 13.5px; line-height: 1.7; overflow-wrap: anywhere; }
.agent-markdown :deep(p) { margin: 0 0 11px; font-size: inherit; line-height: inherit; white-space: normal; }
.agent-markdown :deep(p:last-child), .agent-markdown :deep(ul:last-child), .agent-markdown :deep(ol:last-child), .agent-markdown :deep(pre:last-child), .agent-markdown :deep(table:last-child) { margin-bottom: 0; }
.agent-markdown :deep(h1), .agent-markdown :deep(h2), .agent-markdown :deep(h3), .agent-markdown :deep(h4) { margin: 20px 0 8px; color: var(--text); line-height: 1.35; font-weight: 700; }
.agent-markdown :deep(h1:first-child), .agent-markdown :deep(h2:first-child), .agent-markdown :deep(h3:first-child), .agent-markdown :deep(h4:first-child) { margin-top: 0; }
.agent-markdown :deep(h1) { font-size: 19px; }
.agent-markdown :deep(h2) { font-size: 16px; }
.agent-markdown :deep(h3), .agent-markdown :deep(h4) { font-size: 14px; }
.agent-markdown :deep(ul), .agent-markdown :deep(ol) { margin: 4px 0 12px; padding-left: 22px; }
.agent-markdown :deep(li) { padding-left: 2px; margin: 3px 0; }
.agent-markdown :deep(li > p) { margin: 0 0 5px; }
.agent-markdown :deep(blockquote) { margin: 12px 0; padding: 2px 0 2px 13px; border-left: 3px solid var(--blue); color: var(--muted); }
.agent-markdown :deep(blockquote p) { color: inherit; }
.agent-markdown :deep(a) { color: var(--blue); text-decoration: underline; text-underline-offset: 2px; }
.agent-markdown :deep(code) { padding: 2px 4px; border: 1px solid var(--line); border-radius: 4px; background: var(--surface-raised); font-family: Consolas, 'Cascadia Code', monospace; font-size: .92em; }
.agent-markdown :deep(pre) { max-width: 100%; margin: 11px 0 14px; padding: 12px 14px; overflow-x: auto; border: 1px solid var(--line-strong); border-radius: 6px; background: var(--bg); line-height: 1.55; }
.agent-markdown :deep(pre code) { padding: 0; border: 0; background: transparent; font-size: 12.5px; white-space: pre; overflow-wrap: normal; }
.agent-markdown :deep(table) { display: block; max-width: 100%; margin: 11px 0 14px; overflow-x: auto; border-collapse: collapse; font-size: 12.5px; }
.agent-markdown :deep(th), .agent-markdown :deep(td) { min-width: 90px; padding: 7px 10px; border: 1px solid var(--line-strong); text-align: left; vertical-align: top; }
.agent-markdown :deep(th) { background: var(--surface-raised); font-weight: 650; }
.agent-markdown :deep(hr) { height: 1px; margin: 17px 0; border: 0; background: var(--line-strong); }
.agent-entry.from-tool { padding: 10px 0; }
.agent-tool-line { display: flex; align-items: center; gap: 7px; min-width: 0; color: var(--muted); font-size: 11px; }
.agent-tool-line strong { min-width: 0; flex: 1; color: var(--text); overflow-wrap: anywhere; font-weight: 550; }
.agent-tool-line span { flex: none; }
.agent-entry.from-tool .agent-details { margin-left: 22px; }
.agent-history { margin-top: 20px; padding-top: 14px; border-top: 1px solid var(--line); }
.agent-history > div { display: flex; justify-content: space-between; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--line); font-size: 11px; }
.agent-history > div span { overflow-wrap: anywhere; }
.agent-history > div strong { flex: none; color: var(--muted); }
.agent-empty { padding: clamp(34px, 12vh, 110px) 0 24px; text-align: center; }
.agent-empty-icon { width: 48px; height: 48px; display: grid; place-items: center; margin: 0 auto 15px; border: 1px solid var(--line-strong); border-radius: 8px; color: var(--accent); background: var(--surface-raised); }
.agent-empty h3 { margin: 0; font-size: 15px; }
.agent-empty p { margin: 7px 0 0; color: var(--muted); font-size: 11px; }
.agent-prompts { display: grid; gap: 7px; margin: 24px auto 0; max-width: 300px; }
.agent-prompts button { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 36px; padding: 8px 11px; border: 1px solid var(--line); border-radius: 5px; color: var(--text); background: var(--surface-raised); text-align: left; cursor: pointer; font-size: 11px; }
.agent-prompts button:hover { border-color: var(--line-strong); background: var(--surface-hover); }
.agent-tasks { display: grid; gap: 10px; }
.agent-task-empty { padding-top: 80px; color: var(--muted); }
.agent-task { padding: 14px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-raised); }
.agent-task-heading strong { min-width: 0; overflow-wrap: anywhere; font-size: 12px; }
.agent-task-heading span { flex: none; color: var(--muted); font-size: 11px; }
.agent-task-heading span.failed { color: var(--danger); }
.agent-task p { min-height: 18px; margin: 8px 0 12px; color: var(--muted); font-size: 11px; overflow-wrap: anywhere; }
.agent-task-meta { margin-bottom: 6px; color: var(--muted); font-size: 10px; }
.agent-task-meta span:first-child { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-task progress { display: block; width: 100%; height: 5px; accent-color: var(--accent); }
.agent-task-actions { display: flex; gap: 7px; margin-top: 12px; }
.agent-composer { flex: none; display: grid; gap: 8px; padding: 12px 20px 15px; border-top: 1px solid var(--line); background: var(--surface-raised); }
.agent-composer label { color: var(--muted); font-size: 11px; font-weight: 600; }
.agent-composer textarea { width: 100%; min-height: 72px; max-height: 180px; resize: vertical; padding: 10px 11px; border: 1px solid var(--line-strong); border-radius: 6px; outline: none; color: var(--text); background: var(--surface); font: inherit; font-size: 12px; line-height: 1.5; }
.agent-composer textarea:focus { border-color: var(--blue); box-shadow: 0 0 0 2px var(--focus); }
.agent-composer textarea:disabled { opacity: .6; }
.agent-composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.agent-composer-footer > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font-size: 10px; }
.agent-send { min-width: 76px; flex: none; }
.agent-error { display: flex; align-items: flex-start; gap: 7px; margin: 0; color: var(--danger); font-size: 11px; overflow-wrap: anywhere; }
.agent-error svg { flex: none; }
button:disabled { cursor: default; opacity: .5; }
@media (max-width: 620px) { .agent-shell { width: calc(100vw - 52px) !important; } .agent-resize-handle { display: none; } .agent-header, .agent-context, .agent-tabs, .agent-composer { padding-left: 14px; padding-right: 14px; } .agent-scroll { padding-left: 14px; padding-right: 14px; } }
@media (max-height: 760px) { .agent-empty { padding-top: 28px; } .agent-prompts { margin-top: 16px; } }
</style>
