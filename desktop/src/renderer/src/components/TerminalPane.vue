<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { SearchAddon } from '@xterm/addon-search'
import {
  Clipboard,
  ExternalLink,
  FilePlus2,
  FileText,
  FolderOpen,
  Minus,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Unplug,
  Workflow,
  X
} from 'lucide-vue-next'
import { desktopApi, terminalSocketUrl } from '../transport/api'
import type { SessionSummary, TerminalEvent } from '../types'

const props = defineProps<{ session: SessionSummary }>()
const emit = defineEmits<{
  status: [sessionId: string, status: string, sequence: number]
  automation: [sessionId: string]
}>()

const pane = ref<HTMLElement | null>(null)
const container = ref<HTMLElement | null>(null)
const connectionStatus = ref(props.session.status || 'connecting')
const logOpen = ref(false)
const logLoading = ref(false)
const logContent = ref('')
const logTruncated = ref(false)
const logNotice = ref('')
const searchOpen = ref(false)
const searchQuery = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const fontSize = ref(readFontSize())
const reconnecting = ref(false)
const disconnecting = ref(false)
const contextMenu = ref<{ x: number; y: number; hasSelection: boolean } | null>(null)
let terminal: Terminal | null = null
let fitAddon: FitAddon | null = null
let searchAddon: SearchAddon | null = null
let socket: WebSocket | null = null
let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null
let lastSequence = 0
let pendingCommand = ''
let outputTail = ''

const canReconnect = computed(() =>
  !reconnecting.value && ['disconnected', 'detached', 'error', 'failed'].includes(connectionStatus.value)
)
const canDisconnect = computed(() =>
  !disconnecting.value && !['disconnected', 'detached', 'closed'].includes(connectionStatus.value)
)
const canPaste = computed(() => socket?.readyState === WebSocket.OPEN)
const connectionStatusLabel = computed(() => ({
  connecting: '正在连接',
  connected: '已连接',
  disconnected: '已断开',
  detached: '通道已分离',
  error: '连接错误',
  failed: '连接失败',
  closed: '已关闭'
})[connectionStatus.value] || connectionStatus.value)

function readFontSize(): number {
  const value = Number(localStorage.getItem('device-tui.desktop-v2.terminal-font-size') || 13)
  return Math.max(9, Math.min(28, Number.isFinite(value) ? value : 13))
}

async function connect(): Promise<void> {
  try {
    socket?.close()
    const url = await terminalSocketUrl(props.session.id, lastSequence)
    socket = new WebSocket(url)
    socket.addEventListener('open', sendResize)
    socket.addEventListener('message', (message) => {
      const event = JSON.parse(String(message.data)) as TerminalEvent
      lastSequence = Math.max(lastSequence, event.sequence)
      if (event.type === 'terminal.output' && event.data) {
        terminal?.write(event.data)
        outputTail = `${outputTail}${event.data}`.slice(-512)
      }
      if (event.type === 'terminal.error') {
        terminal?.writeln(`\r\n\x1b[31m[${event.code || 'terminal_error'}] ${event.data || ''}\x1b[0m`)
      }
      if (event.type === 'terminal.gap') {
        terminal?.writeln(
          `\r\n\x1b[33m[输出缺失：${event.fromSequence || '?'}-${event.toSequence || '?'}]\x1b[0m`
        )
      }
      if (event.type === 'terminal.status' && event.status) {
        connectionStatus.value = event.status
        emit('status', props.session.id, event.status, event.sequence)
      }
    })
    socket.addEventListener('close', () => {
      if (!['disconnected', 'error', 'failed', 'closed'].includes(connectionStatus.value)) {
        connectionStatus.value = 'detached'
      }
    })
    socket.addEventListener('error', () => {
      connectionStatus.value = 'error'
      terminal?.writeln('\r\n\x1b[31m[终端通道错误] 请重新连接。\x1b[0m')
    })
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause)
    connectionStatus.value = 'error'
    emit('status', props.session.id, 'error', lastSequence)
    terminal?.writeln(`\r\n\x1b[31m[终端连接失败] ${message}\x1b[0m`)
  }
}

function sendResize(): void {
  if (!terminal || socket?.readyState !== WebSocket.OPEN) return
  socket.send(
    JSON.stringify({
      type: 'terminal.resize',
      cols: terminal.cols,
      rows: terminal.rows
    })
  )
}

async function reconnect(): Promise<void> {
  if (reconnecting.value) return
  reconnecting.value = true
  terminal?.writeln('\r\n\x1b[36m[正在重新连接]\x1b[0m')
  try {
    const session = await desktopApi.reconnectSession(props.session.id)
    connectionStatus.value = session.status
    emit('status', props.session.id, session.status, session.sequence)
    if (socket?.readyState !== WebSocket.OPEN) await connect()
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause)
    connectionStatus.value = 'error'
    terminal?.writeln(`\r\n\x1b[31m[重连失败] ${message}\x1b[0m`)
  } finally {
    reconnecting.value = false
  }
}

async function disconnect(): Promise<void> {
  if (!canDisconnect.value) return
  disconnecting.value = true
  try {
    const session = await desktopApi.disconnectSession(props.session.id)
    connectionStatus.value = session.status
    emit('status', props.session.id, session.status, session.sequence)
    terminal?.writeln('\r\n\x1b[33m[会话已断开，按 Enter 可重连]\x1b[0m')
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause)
    connectionStatus.value = 'error'
    terminal?.writeln(`\r\n\x1b[31m[断开失败] ${message}\x1b[0m`)
  } finally {
    disconnecting.value = false
  }
}

async function loadLog(): Promise<void> {
  logOpen.value = true
  logLoading.value = true
  logNotice.value = ''
  try {
    const response = await desktopApi.sessionLog(props.session.id)
    logContent.value = response.content
    logTruncated.value = response.truncated
  } catch (cause) {
    logContent.value = ''
    logNotice.value = `读取日志失败: ${cause instanceof Error ? cause.message : String(cause)}`
  } finally {
    logLoading.value = false
  }
}

async function copyLog(): Promise<void> {
  if (!logContent.value) {
    logNotice.value = '暂无日志可复制'
    return
  }
  await navigator.clipboard.writeText(logContent.value)
  logNotice.value = logTruncated.value ? '已复制日志尾部内容' : '已复制全部日志'
}

async function openLogDirectory(): Promise<void> {
  contextMenu.value = null
  logNotice.value = ''
  try {
    const opened = await window.desktopApi.openSessionLogDirectory()
    logNotice.value = opened ? '已打开日志目录' : '未打开日志目录'
  } catch (cause) {
    logNotice.value = `打开日志目录失败: ${cause instanceof Error ? cause.message : String(cause)}`
  }
}

async function openCurrentLog(): Promise<void> {
  contextMenu.value = null
  logNotice.value = ''
  try {
    const opened = await window.desktopApi.openCurrentSessionLog(props.session.id)
    logNotice.value = opened ? '已打开当前会话日志' : '未打开当前会话日志'
  } catch (cause) {
    logNotice.value = `打开当前会话日志失败: ${cause instanceof Error ? cause.message : String(cause)}`
  }
}

async function createNewLog(): Promise<void> {
  contextMenu.value = null
  logNotice.value = ''
  try {
    await desktopApi.createSessionLog(props.session.id)
    await loadLog()
    logNotice.value = '已新建当前会话日志，原日志已归档'
  } catch (cause) {
    logNotice.value = `新建会话日志失败: ${cause instanceof Error ? cause.message : String(cause)}`
  }
}

async function saveLogCopy(): Promise<void> {
  contextMenu.value = null
  if (!logContent.value) {
    logNotice.value = '暂无日志可保存'
    return
  }
  try {
    const saved = await window.desktopApi.saveSessionLog({
      suggestedName: `${props.session.device_id}-${props.session.id}.log`,
      content: logContent.value
    })
    logNotice.value = saved ? '日志副本已保存' : '已取消保存日志'
  } catch (cause) {
    logNotice.value = `保存日志失败: ${cause instanceof Error ? cause.message : String(cause)}`
  }
}

function terminalBufferText(): string {
  if (!terminal) return ''
  const lines: string[] = []
  for (let index = 0; index < terminal.buffer.active.length; index += 1) {
    lines.push(terminal.buffer.active.getLine(index)?.translateToString(true) || '')
  }
  return lines.join('\n').replace(/\s+$/u, '')
}

async function copySelection(): Promise<void> {
  const selected = terminal?.getSelection() || ''
  if (selected) await navigator.clipboard.writeText(selected)
  contextMenu.value = null
}

async function copyAll(): Promise<void> {
  const text = terminalBufferText()
  if (text) await navigator.clipboard.writeText(text)
  contextMenu.value = null
}

function clearTerminal(): void {
  terminal?.clear()
  contextMenu.value = null
}

async function pasteFromClipboard(): Promise<void> {
  if (!canPaste.value) return
  const text = await navigator.clipboard.readText()
  if (!text) return
  recordTerminalInput(text)
  socket?.send(JSON.stringify({ type: 'terminal.input', data: text }))
  contextMenu.value = null
}

function openContextMenu(event: MouseEvent): void {
  contextMenu.value = {
    x: event.clientX,
    y: event.clientY,
    hasSelection: Boolean(terminal?.hasSelection())
  }
}

function closeContextMenu(): void {
  contextMenu.value = null
}

function handleTerminalContextKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    closeContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    event.preventDefault()
    const rect = container.value?.getBoundingClientRect()
    contextMenu.value = {
      x: rect ? rect.left + 36 : 160,
      y: rect ? rect.top + 36 : 160,
      hasSelection: Boolean(terminal?.hasSelection())
    }
  }
}

function reconnectFromContext(): void {
  void reconnect()
  closeContextMenu()
}

function disconnectFromContext(): void {
  void disconnect()
  closeContextMenu()
}

function loadLogFromContext(): void {
  void loadLog()
  closeContextMenu()
}

function openAutomation(): void {
  emit('automation', props.session.id)
  closeContextMenu()
}

async function openSearch(): Promise<void> {
  searchOpen.value = true
  await nextTick()
  searchInput.value?.focus()
  searchInput.value?.select()
}

function findNext(): void {
  if (searchQuery.value) searchAddon?.findNext(searchQuery.value, { incremental: true })
}

function findPrevious(): void {
  if (searchQuery.value) searchAddon?.findPrevious(searchQuery.value)
}

function changeFontSize(delta: number): void {
  const nextSize = Math.max(9, Math.min(28, fontSize.value + delta))
  localStorage.setItem('device-tui.desktop-v2.terminal-font-size', String(nextSize))
  window.dispatchEvent(new CustomEvent('device-tui:terminal-font-size', { detail: nextSize }))
}

function handleSharedFontSize(event: Event): void {
  const requested = Number((event as CustomEvent<number>).detail)
  if (!Number.isFinite(requested)) return
  fontSize.value = Math.max(9, Math.min(28, requested))
  if (terminal) terminal.options.fontSize = fontSize.value
  fitAddon?.fit()
  sendResize()
}

function readThemeMode(): 'dark' | 'light' {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

function terminalThemeFor(mode: 'dark' | 'light') {
  if (mode === 'light') {
    return {
      background: '#f8fafc',
      foreground: '#111827',
      cursor: '#15803d',
      selectionBackground: '#bfdbfe',
      black: '#0f172a',
      red: '#dc2626',
      green: '#15803d',
      yellow: '#b45309',
      blue: '#2563eb',
      magenta: '#7c3aed',
      cyan: '#0891b2',
      white: '#f8fafc'
    }
  }
  return {
    background: '#020617',
    foreground: '#f8fafc',
    cursor: '#22c55e',
    selectionBackground: '#315f9f',
    black: '#020617',
    red: '#f87171',
    green: '#22c55e',
    yellow: '#fbbf24',
    blue: '#60a5fa',
    magenta: '#c4b5fd',
    cyan: '#91d7e3',
    white: '#f8fafc'
  }
}

function applyTerminalTheme(): void {
  if (terminal) terminal.options.theme = terminalThemeFor(readThemeMode())
}

function recordTerminalInput(data: string): void {
  if (data.includes('\x1b')) return
  for (const character of data) {
    if (character === '\r' || character === '\n') {
      const command = pendingCommand.trim()
      const sensitivePrompt = /(?:password|passwd|secret|token|密码|口令)\s*[:：]?\s*$/i.test(
        outputTail.replace(/\x1b\[[0-9;?]*[ -/]*[@-~]/g, '')
      )
      if (command && !sensitivePrompt) {
        void desktopApi.recordCommand(props.session.id, command).catch(() => undefined)
      }
      pendingCommand = ''
      outputTail = ''
    } else if (character === '\x7f' || character === '\b') {
      pendingCommand = pendingCommand.slice(0, -1)
    } else if (character === '\x03' || character === '\x15') {
      pendingCommand = ''
    } else if (character >= ' ') {
      pendingCommand += character
    }
  }
}

function handleShortcut(event: KeyboardEvent): void {
  const target = event.target instanceof Node ? event.target : null
  if (!pane.value || (!pane.value.contains(target) && !pane.value.contains(document.activeElement))) return
  if (!(event.ctrlKey || event.metaKey)) return
  if (event.key.toLocaleLowerCase() === 'f') {
    event.preventDefault()
    void openSearch()
  } else if (event.key === '=' || event.key === '+') {
    event.preventDefault()
    changeFontSize(1)
  } else if (event.key === '-') {
    event.preventDefault()
    changeFontSize(-1)
  } else if (event.shiftKey && event.key.toLocaleLowerCase() === 'r') {
    event.preventDefault()
    void reconnect()
  } else if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    handleTerminalContextKeydown(event)
  }
}

watch(() => props.session.status, (status) => {
  if (status) connectionStatus.value = status
})

onMounted(async () => {
  await nextTick()
  if (!container.value) return
  fitAddon = new FitAddon()
  searchAddon = new SearchAddon()
  terminal = new Terminal({
    convertEol: true,
    cursorBlink: true,
    cursorStyle: 'bar',
    fontFamily: '"Cascadia Mono", "JetBrains Mono", Consolas, monospace',
    fontSize: fontSize.value,
    lineHeight: 1.25,
    scrollback: 10_000,
    theme: terminalThemeFor(readThemeMode())
  })
  terminal.loadAddon(fitAddon)
  terminal.loadAddon(searchAddon)
  terminal.open(container.value)
  fitAddon.fit()
  terminal.onData((data) => {
    if ((data === '\r' || data === '\n') && canReconnect.value) {
      void reconnect()
      return
    }
    recordTerminalInput(data)
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'terminal.input', data }))
    }
  })
  resizeObserver = new ResizeObserver(() => {
    fitAddon?.fit()
    sendResize()
  })
  resizeObserver.observe(container.value)
  themeObserver = new MutationObserver(applyTerminalTheme)
  themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  window.addEventListener('keydown', handleShortcut, true)
  window.addEventListener('device-tui:terminal-font-size', handleSharedFontSize)
  await connect()
  terminal.focus()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  window.removeEventListener('keydown', handleShortcut, true)
  window.removeEventListener('device-tui:terminal-font-size', handleSharedFontSize)
  socket?.close()
  terminal?.dispose()
})
</script>

<template>
  <section ref="pane" class="terminal-pane" aria-label="终端会话" @click="closeContextMenu">
    <header class="terminal-toolbar">
      <div>
        <strong>{{ session.title }}</strong>
        <span class="terminal-endpoint">{{ session.device_id }} · {{ session.kind }}</span>
      </div>
      <div class="terminal-actions">
        <span class="connection-state" :data-state="connectionStatus" :title="connectionStatus">
          <i aria-hidden="true"></i>{{ connectionStatusLabel }}
        </span>
        <button class="icon-button" type="button" title="查看会话日志" @click="loadLog">
          <FileText :size="15" aria-hidden="true" />
          <span class="sr-only">查看会话日志</span>
        </button>
        <button class="icon-button" type="button" title="打开当前会话自动响应" @click="openAutomation">
          <Workflow :size="15" aria-hidden="true" />
          <span class="sr-only">打开当前会话自动响应</span>
        </button>
        <button class="icon-button" type="button" title="搜索终端 (Ctrl+F)" @click="openSearch">
          <Search :size="15" aria-hidden="true" />
          <span class="sr-only">搜索终端</span>
        </button>
        <button class="icon-button" type="button" title="缩小字体 (Ctrl+-)" @click="changeFontSize(-1)">
          <Minus :size="15" aria-hidden="true" />
          <span class="sr-only">缩小终端字体</span>
        </button>
        <button class="icon-button" type="button" title="放大字体 (Ctrl++)" @click="changeFontSize(1)">
          <Plus :size="15" aria-hidden="true" />
          <span class="sr-only">放大终端字体</span>
        </button>
        <button
          class="icon-button"
          type="button"
          :title="canDisconnect ? '断开连接' : '当前会话已断开'"
          :disabled="!canDisconnect"
          @click="disconnect"
        >
          <Unplug :size="15" aria-hidden="true" />
          <span class="sr-only">断开连接</span>
        </button>
        <button
          class="icon-button"
          type="button"
          :title="canReconnect ? '重新连接 (Ctrl+Shift+R)' : '当前会话未处于断开状态'"
          :disabled="!canReconnect"
          @click="reconnect"
        >
          <RotateCcw :size="15" aria-hidden="true" />
          <span class="sr-only">重新连接</span>
        </button>
      </div>
    </header>
    <div
      ref="container"
      class="terminal-host"
      tabindex="0"
      @contextmenu.prevent="openContextMenu"
      @keydown="handleTerminalContextKeydown"
    ></div>
    <div
      v-if="contextMenu"
      class="terminal-context-menu"
      role="menu"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
      @click.stop
      @keydown.esc.prevent="closeContextMenu"
    >
      <p>{{ session.title }}</p>
      <button
        type="button"
        role="menuitem"
        :disabled="!contextMenu.hasSelection"
        @click="copySelection"
      >复制选中文本</button>
      <button type="button" role="menuitem" @click="copyAll">复制全部</button>
      <button
        type="button"
        role="menuitem"
        :disabled="!canPaste"
        @click="pasteFromClipboard"
      >粘贴</button>
      <button type="button" role="menuitem" @click="clearTerminal">清屏</button>
      <hr />
      <button type="button" role="menuitem" @click="openSearch">搜索终端</button>
      <button type="button" role="menuitem" @click="openAutomation">自动响应</button>
      <button type="button" role="menuitem" @click="createNewLog">新建日志</button>
      <button type="button" role="menuitem" @click="openCurrentLog">打开当前会话日志</button>
      <button type="button" role="menuitem" @click="loadLogFromContext">查看会话日志</button>
      <button type="button" role="menuitem" @click="openLogDirectory">打开日志目录</button>
      <button type="button" role="menuitem" :disabled="!logContent" @click="saveLogCopy">保存日志副本</button>
      <hr />
      <button
        type="button"
        role="menuitem"
        :disabled="!canDisconnect"
        @click="disconnectFromContext"
      >断开连接</button>
      <button
        type="button"
        role="menuitem"
        :disabled="!canReconnect"
        @click="reconnectFromContext"
      >重新连接</button>
    </div>
    <form v-if="searchOpen" class="terminal-search" @submit.prevent="findNext">
      <Search :size="14" aria-hidden="true" />
      <input
        ref="searchInput"
        v-model="searchQuery"
        type="search"
        placeholder="搜索终端输出"
        aria-label="搜索终端输出"
        @input="findNext"
        @keydown.shift.enter.prevent="findPrevious"
        @keydown.esc.prevent="searchOpen = false"
      />
      <button class="search-nav" type="button" title="上一个" @click="findPrevious">↑</button>
      <button class="search-nav" type="submit" title="下一个">↓</button>
      <button class="icon-button" type="button" title="关闭搜索" @click="searchOpen = false">
        <X :size="14" />
      </button>
    </form>
    <aside v-if="logOpen" class="terminal-log-panel" aria-label="会话日志">
      <header>
        <div>
          <strong>会话日志</strong>
          <span v-if="logTruncated">仅显示尾部内容</span>
          <span v-if="logNotice">{{ logNotice }}</span>
        </div>
        <div>
          <button class="icon-button" type="button" title="新建日志" @click="createNewLog">
            <FilePlus2 :size="14" />
          </button>
          <button class="icon-button" type="button" title="打开当前会话日志" @click="openCurrentLog">
            <ExternalLink :size="14" />
          </button>
          <button class="icon-button" type="button" title="保存日志副本" :disabled="!logContent" @click="saveLogCopy">
            <Save :size="14" />
          </button>
          <button class="icon-button" type="button" title="打开日志目录" @click="openLogDirectory">
            <FolderOpen :size="14" />
          </button>
          <button class="icon-button" type="button" title="复制日志" :disabled="!logContent" @click="copyLog">
            <Clipboard :size="14" />
          </button>
          <button class="icon-button" type="button" title="刷新日志" @click="loadLog">
            <RefreshCw :size="14" />
          </button>
          <button class="icon-button" type="button" title="关闭日志" @click="logOpen = false">
            <X :size="14" />
          </button>
        </div>
      </header>
      <pre>{{ logLoading ? '正在读取日志…' : logContent || '暂无日志记录。' }}</pre>
    </aside>
  </section>
</template>
