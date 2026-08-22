<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  BookOpenText,
  Check,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  RadioTower,
  Replace,
  Search,
  Send,
  Target,
  X
} from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import TerminalQuickToolbar from './TerminalQuickToolbar.vue'
import {
  announceContextMenuOpen,
  clampContextMenuElement,
  clampContextMenuPoint,
  contextMenuTrigger,
  focusFirstContextMenuItem,
  handleContextMenuKeydown,
  restoreContextMenuFocus,
  subscribeContextMenuOpen
} from '../contextMenu'

const workspace = useWorkspaceStore()
const commandWorkspace = ref<HTMLElement | null>(null)
const editor = ref<HTMLTextAreaElement | null>(null)
const lineNumberGutter = ref<HTMLElement | null>(null)
const findInput = ref<HTMLInputElement | null>(null)
const content = ref('')
const renameValue = ref('')
const renameInput = ref<HTMLInputElement | null>(null)
const renameGroupId = ref('')
const renaming = ref(false)
const findOpen = ref(false)
const findValue = ref('')
const replaceValue = ref('')
const findStatus = ref('')
const selectionStart = ref(0)
const selectionEnd = ref(0)
const saveState = ref<'saved' | 'dirty' | 'saving' | 'error'>('saved')
const dispatchFeedback = ref('')
const commandGroupContextMenu = ref<{ groupId: string; name: string; x: number; y: number } | null>(null)
const commandGroupContextMenuElement = ref<HTMLElement | null>(null)
const commandGroupContextMenuReturnFocus = ref<HTMLElement | null>(null)
const draggedGroupId = ref('')
const dragOverGroupId = ref('')
const dragOverPosition = ref<'before' | 'after'>('before')
const commandGroupDragBusy = ref(false)
const commandGroupScrollTops = new Map<string, number>()
const editorContextMenu = ref<{ x: number; y: number; hasSelection: boolean; hasCommand: boolean } | null>(null)
const editorContextMenuElement = ref<HTMLElement | null>(null)
const editorContextMenuReturnFocus = ref<HTMLElement | null>(null)
const COMMAND_PANEL_HEIGHT_KEY = 'device-tui.desktop-v2.command-panel-height'
const COMMAND_PANEL_MIN_HEIGHT = 180
const COMMAND_PANEL_DEFAULT_HEIGHT = 300
const commandPanelMaxHeight = ref(680)
const preferredCommandPanelHeight = ref(storedCommandPanelHeight())
const commandPanelHeight = ref(preferredCommandPanelHeight.value)
let saveTimer: ReturnType<typeof setTimeout> | null = null
let dispatchFeedbackTimer: ReturnType<typeof setTimeout> | null = null
let resizeStartY = 0
let resizeStartHeight = 0
let panelResizing = false
let editorGroupId = ''
let unsubscribeContextMenuOpen: (() => void) | null = null

const currentGroup = computed(() => workspace.currentCommandGroup)
const matchCount = computed(() => {
  if (!findValue.value) return 0
  return content.value.toLocaleLowerCase().split(findValue.value.toLocaleLowerCase()).length - 1
})
const currentMatchIndex = computed(() => {
  if (!findValue.value || selectionStart.value === selectionEnd.value) return 0
  const selected = content.value.slice(selectionStart.value, selectionEnd.value)
  if (selected.toLocaleLowerCase() !== findValue.value.toLocaleLowerCase()) return 0
  return content.value
    .slice(0, selectionStart.value)
    .toLocaleLowerCase()
    .split(findValue.value.toLocaleLowerCase()).length
})
const matchLabel = computed(() =>
  currentMatchIndex.value ? `${currentMatchIndex.value}/${matchCount.value}` : `${matchCount.value} 处`
)
const dispatchScopeLabel = computed(() => {
  if (selectionStart.value === selectionEnd.value) return '当前行'
  const selected = content.value.slice(selectionStart.value, selectionEnd.value)
  const lineCount = selected.split(/\r?\n/).length
  return `${lineCount} 行已选中`
})
const dispatchTargetLabel = computed(() =>
  workspace.activeSession?.title || '未选择终端'
)
const totalLineCount = computed(() => Math.max(1, content.value.split(/\r?\n/).length))
const lineNumberText = computed(() =>
  Array.from({ length: totalLineCount.value }, (_, index) => String(index + 1)).join('\n')
)
const currentLineNumber = computed(() =>
  Math.max(1, content.value.slice(0, selectionStart.value).split(/\r?\n/).length)
)
const hasDispatchCommand = computed(() => {
  content.value
  selectionStart.value
  selectionEnd.value
  return Boolean(selectedCommand())
})
const saveStateLabel = computed(() => ({
  saved: '已保存',
  dirty: '待保存',
  saving: '保存中',
  error: '保存失败'
})[saveState.value])

function storedCommandPanelHeight(): number {
  const value = Number(localStorage.getItem(COMMAND_PANEL_HEIGHT_KEY) || COMMAND_PANEL_DEFAULT_HEIGHT)
  return Number.isFinite(value) ? Math.max(COMMAND_PANEL_MIN_HEIGHT, Math.round(value)) : COMMAND_PANEL_DEFAULT_HEIGHT
}

function availableCommandPanelHeight(): number {
  const stageHeight = commandWorkspace.value?.parentElement?.clientHeight || window.innerHeight
  return Math.max(COMMAND_PANEL_MIN_HEIGHT, Math.min(680, stageHeight - 180))
}

function setCommandPanelHeight(value: number, persist = true): void {
  commandPanelMaxHeight.value = availableCommandPanelHeight()
  commandPanelHeight.value = Math.max(
    COMMAND_PANEL_MIN_HEIGHT,
    Math.min(commandPanelMaxHeight.value, Math.round(value))
  )
  if (persist) {
    preferredCommandPanelHeight.value = commandPanelHeight.value
    localStorage.setItem(COMMAND_PANEL_HEIGHT_KEY, String(commandPanelHeight.value))
  }
}

function clampCommandPanelHeight(): void {
  setCommandPanelHeight(preferredCommandPanelHeight.value, false)
}

function stopCommandPanelResize(): void {
  if (!panelResizing) return
  panelResizing = false
  document.removeEventListener('pointermove', resizeCommandPanel)
  document.removeEventListener('pointerup', stopCommandPanelResize)
  document.removeEventListener('pointercancel', stopCommandPanelResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

function resizeCommandPanel(event: PointerEvent): void {
  if (!panelResizing) return
  setCommandPanelHeight(resizeStartHeight + resizeStartY - event.clientY)
}

function startCommandPanelResize(event: PointerEvent): void {
  if (event.button !== 0) return
  event.preventDefault()
  if (!workspace.commandPanelOpen) {
    workspace.commandPanelOpen = true
    commandPanelHeight.value = COMMAND_PANEL_MIN_HEIGHT
  }
  panelResizing = true
  resizeStartY = event.clientY
  resizeStartHeight = commandPanelHeight.value
  document.body.style.cursor = 'ns-resize'
  document.body.style.userSelect = 'none'
  document.addEventListener('pointermove', resizeCommandPanel)
  document.addEventListener('pointerup', stopCommandPanelResize)
  document.addEventListener('pointercancel', stopCommandPanelResize)
}

function handleCommandPanelResizeKeydown(event: KeyboardEvent): void {
  const step = event.shiftKey ? 40 : 10
  if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return
  workspace.commandPanelOpen = true
  if (event.key === 'ArrowUp') setCommandPanelHeight(commandPanelHeight.value + step)
  else if (event.key === 'ArrowDown') setCommandPanelHeight(commandPanelHeight.value - step)
  else if (event.key === 'Home') setCommandPanelHeight(COMMAND_PANEL_MIN_HEIGHT)
  else setCommandPanelHeight(commandPanelMaxHeight.value)
  event.preventDefault()
}

function resetCommandPanelHeight(): void {
  workspace.commandPanelOpen = true
  setCommandPanelHeight(COMMAND_PANEL_DEFAULT_HEIGHT)
}

watch(
  () => [currentGroup.value?.id, currentGroup.value?.content] as const,
  async ([nextGroupId, nextContent]) => {
    const groupChanged = editorGroupId !== (nextGroupId || '')
    if (groupChanged && editorGroupId && editor.value) {
      commandGroupScrollTops.set(editorGroupId, editor.value.scrollTop)
    }
    editorGroupId = nextGroupId || ''
    content.value = nextContent || ''
    saveState.value = 'saved'
    if (groupChanged) {
      await nextTick()
      const scrollTop = commandGroupScrollTops.get(editorGroupId) || 0
      if (editor.value) editor.value.scrollTop = scrollTop
      if (lineNumberGutter.value) lineNumberGutter.value.scrollTop = scrollTop
    }
  },
  { immediate: true }
)

watch(content, () => {
  if (!currentGroup.value || content.value === currentGroup.value.content) {
    if (saveState.value !== 'saving') saveState.value = 'saved'
    return
  }
  saveState.value = 'dirty'
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => void saveContent(), 650)
})

async function saveContent(): Promise<void> {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = null
  const group = currentGroup.value
  if (!group || content.value === group.content) {
    saveState.value = 'saved'
    return
  }
  saveState.value = 'saving'
  const saved = await workspace.updateCommandGroup(group.id, { content: content.value })
  saveState.value = saved ? 'saved' : 'error'
}

async function selectGroup(groupId: string): Promise<void> {
  await saveContent()
  await workspace.selectCommandGroup(groupId)
  await nextTick()
  editor.value?.focus()
}

async function beginRename(group = currentGroup.value): Promise<void> {
  if (!group) return
  renameGroupId.value = group.id
  renameValue.value = group.name
  renaming.value = true
  closeCommandGroupContextMenu()
  await nextTick()
  renameInput.value?.focus()
  renameInput.value?.select()
}

async function commitRename(): Promise<void> {
  const groupId = renameGroupId.value || currentGroup.value?.id || ''
  const name = renameValue.value.trim()
  if (!groupId || !name) return
  if (await workspace.updateCommandGroup(groupId, { name })) renaming.value = false
}

async function removeGroup(groupId: string, name: string): Promise<void> {
  closeCommandGroupContextMenu()
  if (!window.confirm(`确定删除命令页签“${name}”吗？`)) return
  await workspace.deleteCommandGroup(groupId)
}

function startCommandGroupDrag(event: DragEvent, groupId: string): void {
  if (workspace.commandGroups.length < 2 || commandGroupDragBusy.value) {
    event.preventDefault()
    return
  }
  draggedGroupId.value = groupId
  dragOverGroupId.value = ''
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', groupId)
  }
}

function handleCommandGroupDragOver(event: DragEvent, groupId: string): void {
  if (!draggedGroupId.value || draggedGroupId.value === groupId) return
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
  dragOverGroupId.value = groupId
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  dragOverPosition.value = event.clientX >= rect.left + rect.width / 2 ? 'after' : 'before'
}

function resetCommandGroupDrag(): void {
  draggedGroupId.value = ''
  dragOverGroupId.value = ''
  dragOverPosition.value = 'before'
}

async function dropCommandGroup(event: DragEvent, targetGroupId: string): Promise<void> {
  event.preventDefault()
  const sourceGroupId = draggedGroupId.value || event.dataTransfer?.getData('text/plain') || ''
  if (!sourceGroupId || sourceGroupId === targetGroupId || commandGroupDragBusy.value) {
    resetCommandGroupDrag()
    return
  }
  const nextIds = workspace.commandGroups.map((group) => group.id)
  const sourceIndex = nextIds.indexOf(sourceGroupId)
  const targetIndex = nextIds.indexOf(targetGroupId)
  if (sourceIndex < 0 || targetIndex < 0) {
    resetCommandGroupDrag()
    return
  }
  let insertIndex = targetIndex + (dragOverPosition.value === 'after' ? 1 : 0)
  nextIds.splice(sourceIndex, 1)
  if (sourceIndex < insertIndex) insertIndex -= 1
  nextIds.splice(insertIndex, 0, sourceGroupId)
  commandGroupDragBusy.value = true
  resetCommandGroupDrag()
  try {
    await workspace.reorderCommandGroups(nextIds)
  } finally {
    commandGroupDragBusy.value = false
  }
}

function closeCommandGroupContextMenu(): void {
  commandGroupContextMenu.value = null
}

function closeEditorContextMenu(): void {
  editorContextMenu.value = null
}

function closeCommandGroupContextMenuAndRestoreFocus(): void {
  closeCommandGroupContextMenu()
  restoreContextMenuFocus(commandGroupContextMenuReturnFocus.value)
}

function closeEditorContextMenuAndRestoreFocus(): void {
  closeEditorContextMenu()
  restoreContextMenuFocus(editorContextMenuReturnFocus.value)
}

function openCommandGroupContextMenu(event: MouseEvent, groupId: string, name: string): void {
  announceContextMenuOpen()
  commandGroupContextMenuReturnFocus.value = contextMenuTrigger(event)
  commandGroupContextMenu.value = {
    groupId,
    name,
    ...clampContextMenuPoint(event.clientX, event.clientY)
  }
}

function handleCommandGroupKeydown(event: KeyboardEvent, groupId: string, name: string): void {
  if (event.key === 'Escape') {
    closeCommandGroupContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    event.preventDefault()
    announceContextMenuOpen()
    const rect = (event.currentTarget as HTMLElement | null)?.getBoundingClientRect()
    commandGroupContextMenuReturnFocus.value = event.currentTarget as HTMLElement | null
    commandGroupContextMenu.value = {
      groupId,
      name,
      x: rect ? rect.left + 20 : 180,
      y: rect ? rect.bottom + 4 : 180
    }
  }
}

function selectedCommand(): string {
  const element = editor.value
  if (!element) return ''
  if (element.selectionStart !== element.selectionEnd) {
    return content.value.slice(element.selectionStart, element.selectionEnd).trim()
  }
  const before = content.value.lastIndexOf('\n', Math.max(0, element.selectionStart - 1)) + 1
  const nextBreak = content.value.indexOf('\n', element.selectionStart)
  const after = nextBreak < 0 ? content.value.length : nextBreak
  return content.value.slice(before, after).trim()
}

function updateSelectionState(): void {
  const element = editor.value
  if (!element) return
  selectionStart.value = element.selectionStart
  selectionEnd.value = element.selectionEnd
}

function selectCurrentCommandLine(): void {
  const element = editor.value
  if (!element) return
  const before = content.value.lastIndexOf('\n', Math.max(0, element.selectionStart - 1)) + 1
  const nextBreak = content.value.indexOf('\n', element.selectionStart)
  const after = nextBreak < 0 ? content.value.length : nextBreak
  element.focus()
  element.setSelectionRange(before, after)
  updateSelectionState()
  closeEditorContextMenu()
}

async function copySelectedCommand(): Promise<void> {
  const command = selectedCommand()
  if (command) await window.desktopApi.writeClipboardText(command)
  closeEditorContextMenu()
}

async function pasteCommandText(): Promise<void> {
  const element = editor.value
  if (!element) return
  const text = await window.desktopApi.readClipboardText()
  if (!text) return
  const start = element.selectionStart
  const end = element.selectionEnd
  content.value = `${content.value.slice(0, start)}${text}${content.value.slice(end)}`
  await nextTick()
  element.focus()
  element.setSelectionRange(start + text.length, start + text.length)
  updateSelectionState()
  void saveContent()
  closeEditorContextMenu()
}

async function clearCurrentCommandGroup(): Promise<void> {
  if (!content.value) return
  if (!window.confirm(`清空命令页签“${currentGroup.value?.name || '当前页签'}”中的全部内容吗？`)) {
    closeEditorContextMenu()
    return
  }
  content.value = ''
  await nextTick()
  editor.value?.focus()
  updateSelectionState()
  void saveContent()
  closeEditorContextMenu()
}

async function openFindReplace(): Promise<void> {
  workspace.commandPanelOpen = true
  findOpen.value = true
  findStatus.value = ''
  await nextTick()
  findInput.value?.focus()
  findInput.value?.select()
}

function closeFindReplace(): void {
  findOpen.value = false
  findStatus.value = ''
  void nextTick(() => editor.value?.focus())
}

function handleWorkspaceShortcut(event: KeyboardEvent): void {
  if (!(event.ctrlKey || event.metaKey) || event.key.toLocaleLowerCase() !== 'f') return
  event.preventDefault()
  event.stopPropagation()
  void openFindReplace()
}

function openEditorContextMenu(event: MouseEvent): void {
  announceContextMenuOpen()
  updateSelectionState()
  editorContextMenuReturnFocus.value = contextMenuTrigger(event)
  editorContextMenu.value = {
    ...clampContextMenuPoint(event.clientX, event.clientY),
    hasSelection: selectionStart.value !== selectionEnd.value,
    hasCommand: Boolean(selectedCommand())
  }
}

watch(commandGroupContextMenu, async (menu) => {
  if (!menu) return
  await nextTick()
  if (commandGroupContextMenu.value !== menu) return
  const point = clampContextMenuElement(commandGroupContextMenuElement.value, menu.x, menu.y)
  if (point.x !== menu.x || point.y !== menu.y) commandGroupContextMenu.value = { ...menu, ...point }
  focusFirstContextMenuItem(commandGroupContextMenuElement.value)
})

watch(editorContextMenu, async (menu) => {
  if (!menu) return
  await nextTick()
  if (editorContextMenu.value !== menu) return
  const point = clampContextMenuElement(editorContextMenuElement.value, menu.x, menu.y)
  if (point.x !== menu.x || point.y !== menu.y) editorContextMenu.value = { ...menu, ...point }
  focusFirstContextMenuItem(editorContextMenuElement.value)
})

async function dispatch(broadcast = false): Promise<void> {
  if (workspace.commandBusy) return
  const command = selectedCommand()
  if (!command) return
  await saveContent()
  const targetLabel = dispatchTargetLabel.value
  const targetCount = workspace.connectedSessions.length
  const sent = await workspace.dispatchCommand(command, broadcast)
  if (sent) {
    dispatchFeedback.value = broadcast
      ? `已广播到 ${targetCount} 个终端`
      : `已发送到 ${targetLabel}`
    if (dispatchFeedbackTimer) clearTimeout(dispatchFeedbackTimer)
    dispatchFeedbackTimer = setTimeout(() => {
      dispatchFeedback.value = ''
    }, 2_400)
  }
  editor.value?.focus()
}

function handleEditorKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    closeEditorContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    event.preventDefault()
    announceContextMenuOpen()
    const rect = editor.value?.getBoundingClientRect()
    updateSelectionState()
    editorContextMenuReturnFocus.value = editor.value
    editorContextMenu.value = {
      x: rect ? rect.left + 36 : 220,
      y: rect ? rect.top + 36 : 220,
      hasSelection: selectionStart.value !== selectionEnd.value,
      hasCommand: Boolean(selectedCommand())
    }
    return
  }
  if (event.key !== 'Enter' || event.shiftKey || event.altKey || event.metaKey) return
  const shouldSend = workspace.commandEnterSends ? !event.ctrlKey : event.ctrlKey
  event.preventDefault()
  if (shouldSend) {
    void dispatch(false)
    return
  }
  const element = editor.value
  if (!element) return
  const start = element.selectionStart
  const cursor = start + 1
  content.value = `${content.value.slice(0, start)}\n${content.value.slice(element.selectionEnd)}`
  void nextTick(() => {
    element.focus()
    element.setSelectionRange(cursor, cursor)
    updateSelectionState()
  })
}

function handleEditorActivity(): void {
  updateSelectionState()
}

function syncEditorScroll(): void {
  if (!editor.value || !lineNumberGutter.value) return
  lineNumberGutter.value.scrollTop = editor.value.scrollTop
  if (editorGroupId) commandGroupScrollTops.set(editorGroupId, editor.value.scrollTop)
}

function findNext(): void {
  const element = editor.value
  const query = findValue.value
  if (!element || !query) {
    findStatus.value = '请输入要查找的命令文本。'
    return
  }
  const lower = content.value.toLocaleLowerCase()
  const needle = query.toLocaleLowerCase()
  let index = lower.indexOf(needle, element.selectionEnd)
  if (index < 0) index = lower.indexOf(needle)
  if (index >= 0) {
    element.focus()
    element.setSelectionRange(index, index + query.length)
    updateSelectionState()
    findStatus.value = ''
  } else {
    findStatus.value = `未找到: ${query}`
  }
}

function replaceCurrent(): void {
  const element = editor.value
  if (!element || !findValue.value) {
    findStatus.value = '请输入要替换的命令文本。'
    return
  }
  const selected = content.value.slice(element.selectionStart, element.selectionEnd)
  if (selected.toLocaleLowerCase() !== findValue.value.toLocaleLowerCase()) {
    findNext()
    return
  }
  const start = element.selectionStart
  content.value = `${content.value.slice(0, start)}${replaceValue.value}${content.value.slice(element.selectionEnd)}`
  findStatus.value = '已替换当前匹配。'
  void nextTick(() => {
    element.setSelectionRange(start, start + replaceValue.value.length)
    updateSelectionState()
    void saveContent()
  })
}

function replaceAll(): void {
  if (!findValue.value) {
    findStatus.value = '请输入要替换的命令文本。'
    return
  }
  const expression = new RegExp(findValue.value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi')
  let count = 0
  content.value = content.value.replace(expression, () => {
    count += 1
    return replaceValue.value
  })
  findStatus.value = count ? `已替换 ${count} 处命令文本。` : `未找到: ${findValue.value}`
  void nextTick(() => {
    updateSelectionState()
    void saveContent()
  })
}

onMounted(() => {
  unsubscribeContextMenuOpen = subscribeContextMenuOpen(() => {
    closeCommandGroupContextMenu()
    closeEditorContextMenu()
  })
  clampCommandPanelHeight()
  window.addEventListener('resize', clampCommandPanelHeight)
})

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  if (dispatchFeedbackTimer) clearTimeout(dispatchFeedbackTimer)
  stopCommandPanelResize()
  unsubscribeContextMenuOpen?.()
  window.removeEventListener('resize', clampCommandPanelHeight)
  void saveContent()
})
</script>

<template>
  <section
    ref="commandWorkspace"
    class="command-workspace"
    :class="{ open: workspace.commandPanelOpen }"
    :style="workspace.commandPanelOpen ? { height: `${commandPanelHeight}px` } : undefined"
    :data-panel-height="workspace.commandPanelOpen ? commandPanelHeight : undefined"
    aria-label="常用命令工作台"
    @click="closeCommandGroupContextMenu(); closeEditorContextMenu()"
    @keydown.capture="handleWorkspaceShortcut"
  >
    <div
      class="command-resize-handle"
      data-testid="command-resize-handle"
      role="separator"
      aria-label="调整常用命令面板高度"
      aria-orientation="horizontal"
      :aria-valuemin="COMMAND_PANEL_MIN_HEIGHT"
      :aria-valuemax="commandPanelMaxHeight"
      :aria-valuenow="workspace.commandPanelOpen ? commandPanelHeight : 0"
      tabindex="0"
      title="向上拖动展开并调整快捷发送与命令面板；双击恢复默认高度"
      @pointerdown="startCommandPanelResize"
      @keydown="handleCommandPanelResizeKeydown"
      @dblclick="resetCommandPanelHeight"
    ><span aria-hidden="true"></span></div>
    <div v-if="!workspace.commandPanelOpen" class="command-quick-send-row"><TerminalQuickToolbar /></div>
    <div v-if="!workspace.commandPanelOpen" class="command-collapsed-bar">
      <button class="command-collapsed-trigger" type="button" title="展开常用命令" @click="workspace.commandPanelOpen = true">
        <span><BookOpenText :size="14" />常用命令 <strong>{{ currentGroup?.name || '终端' }}</strong></span>
        <span>{{ dispatchTargetLabel }} <ChevronUp :size="14" /></span>
      </button>
    </div>
    <template v-else>
      <div class="command-quick-send-row"><TerminalQuickToolbar /></div>
      <header class="command-header" @click="closeCommandGroupContextMenu">
        <div class="command-tabs" role="tablist">
          <div
            v-for="group in workspace.commandGroups"
            :key="group.id"
            class="command-tab"
            :class="{
              active: group.id === workspace.currentCommandGroupId,
              dragging: group.id === draggedGroupId,
              'drag-over-before': group.id === dragOverGroupId && dragOverPosition === 'before',
              'drag-over-after': group.id === dragOverGroupId && dragOverPosition === 'after'
            }"
            :draggable="workspace.commandGroups.length > 1 && !commandGroupDragBusy"
            :aria-label="`${group.name}，可拖动排序`"
            @dragstart="startCommandGroupDrag($event, group.id)"
            @dragover="handleCommandGroupDragOver($event, group.id)"
            @drop="dropCommandGroup($event, group.id)"
            @dragend="resetCommandGroupDrag"
          >
            <button
              type="button"
              role="tab"
              :title="group.name"
              :aria-selected="group.id === workspace.currentCommandGroupId"
              @click="selectGroup(group.id)"
              @contextmenu.prevent="openCommandGroupContextMenu($event, group.id, group.name)"
              @keydown="handleCommandGroupKeydown($event, group.id, group.name)"
            >{{ group.name }}</button>
            <button
              v-if="workspace.commandGroups.length > 1"
              class="command-tab-close"
              type="button"
              :aria-label="`删除 ${group.name}`"
              @click="removeGroup(group.id, group.name)"
            ><X :size="11" /></button>
          </div>
          <button class="icon-button" type="button" title="新增命令页签" @click="workspace.createCommandGroup">
            <Plus :size="14" />
          </button>
        </div>
        <div
          v-if="commandGroupContextMenu"
          ref="commandGroupContextMenuElement"
          class="command-context-menu"
          role="menu"
          :style="{ left: `${commandGroupContextMenu.x}px`, top: `${commandGroupContextMenu.y}px` }"
          @click.stop
          @keydown="handleContextMenuKeydown($event, commandGroupContextMenuElement, closeCommandGroupContextMenuAndRestoreFocus)"
        >
          <p>{{ commandGroupContextMenu.name }}<small>命令页签</small></p>
          <button
            type="button"
            role="menuitem"
            @click="beginRename(workspace.commandGroups.find((group) => group.id === commandGroupContextMenu?.groupId) || currentGroup)"
          >重命名</button>
          <button type="button" role="menuitem" @click="workspace.createCommandGroup(); closeCommandGroupContextMenu()">新增命令页签</button>
          <button
            v-if="workspace.commandGroups.length > 1"
            type="button"
            role="menuitem"
            class="danger-menu-item"
            @click="removeGroup(commandGroupContextMenu.groupId, commandGroupContextMenu.name)"
          >删除页签</button>
        </div>
        <div class="command-header-actions">
          <span class="command-save-state" :data-state="saveState" aria-live="polite">
            <Check v-if="saveState === 'saved'" :size="12" />
            <span v-else aria-hidden="true"></span>
            {{ saveStateLabel }}
          </span>
          <button class="icon-button" type="button" title="重命名页签" @click="beginRename()"><Pencil :size="14" /></button>
          <button class="icon-button" type="button" title="查找和替换 (Ctrl+F)" :aria-pressed="findOpen" @click="findOpen ? closeFindReplace() : openFindReplace()"><Search :size="14" /></button>
          <button
            class="command-mode-button"
            type="button"
            :aria-pressed="workspace.commandEnterSends"
            :title="workspace.commandEnterSends ? '按 Enter 发送；Ctrl+Enter 换行' : '按 Ctrl+Enter 发送；Enter 换行'"
            @click="workspace.setCommandEnterSends(!workspace.commandEnterSends)"
          >{{ workspace.commandEnterSends ? 'Enter 发送' : 'Ctrl+Enter 发送' }}</button>
          <button class="icon-button" type="button" title="收起常用命令" @click="workspace.commandPanelOpen = false"><ChevronDown :size="15" /></button>
        </div>
      </header>

      <form v-if="renaming" class="command-inline-form" @submit.prevent="commitRename">
        <input ref="renameInput" v-model="renameValue" maxlength="160" aria-label="页签名称" @keydown.esc.prevent="renaming = false" />
        <button class="secondary-button" type="button" @click="renaming = false">取消</button>
        <button class="primary-button" type="submit">保存名称</button>
      </form>

      <form v-if="findOpen" class="command-find-row" @submit.prevent="findNext" @keydown.esc.prevent.stop="closeFindReplace">
        <Search :size="13" />
        <input ref="findInput" v-model="findValue" placeholder="查找" aria-label="查找命令" />
        <Replace :size="13" />
        <input v-model="replaceValue" placeholder="替换为" aria-label="替换命令" />
        <span :title="findStatus || `找到 ${matchCount} 处匹配`">{{ findStatus || matchLabel }}</span>
        <button class="secondary-button" type="submit">下一个</button>
        <button class="secondary-button" type="button" @click="replaceCurrent">替换</button>
        <button class="secondary-button" type="button" @click="replaceAll">全部</button>
      </form>

      <div class="command-editor-row">
        <div class="command-editor-meta">
          <div>
            <span class="command-editor-title"><BookOpenText :size="13" />命令编辑</span>
            <span>第 {{ currentLineNumber }} / {{ totalLineCount }} 行</span>
            <span>{{ dispatchScopeLabel }}</span>
          </div>
          <div class="command-dispatch-actions command-editor-controls">
            <div class="command-dispatch-context" aria-live="polite">
              <span :class="{ success: dispatchFeedback }">{{ dispatchFeedback || (hasDispatchCommand ? '可发送' : '选择命令') }}</span>
            </div>
            <span
              class="command-target-badge"
              :data-state="workspace.activeSession ? 'ready' : 'empty'"
              :title="dispatchTargetLabel"
            ><Target :size="12" />{{ dispatchTargetLabel }}</span>
            <div class="command-dispatch-buttons" :class="{ 'is-busy': workspace.commandBusy }">
              <button
                class="secondary-button"
                type="button"
                :disabled="!hasDispatchCommand || !workspace.connectedSessions.length || workspace.commandBusy"
                :title="`广播到 ${workspace.connectedSessions.length} 个终端`"
                @click="dispatch(true)"
              ><RadioTower :size="13" />广播 {{ workspace.connectedSessions.length }}</button>
              <button
                class="primary-button command-primary-send"
                type="button"
                :disabled="!hasDispatchCommand || !workspace.activeSession || workspace.commandBusy"
                :title="`发送到 ${dispatchTargetLabel}`"
                @click="dispatch(false)"
              ><Send :size="13" />发送</button>
            </div>
          </div>
        </div>
        <div class="command-editor-surface">
          <div
            ref="lineNumberGutter"
            class="command-line-numbers"
            aria-hidden="true"
          >{{ lineNumberText }}</div>
          <textarea
            ref="editor"
            v-model="content"
            aria-label="常用命令"
            spellcheck="false"
            wrap="off"
            placeholder="每行一条命令；选择多行可批量发送"
            @click="handleEditorActivity"
            @keyup="handleEditorActivity"
            @select="updateSelectionState"
            @mouseup="updateSelectionState"
            @scroll="syncEditorScroll"
            @keydown="handleEditorKeydown"
            @contextmenu.prevent="openEditorContextMenu"
          ></textarea>
        </div>
        <div
          v-if="editorContextMenu"
          ref="editorContextMenuElement"
          class="command-context-menu"
          role="menu"
          :style="{ left: `${editorContextMenu.x}px`, top: `${editorContextMenu.y}px` }"
          @click.stop
          @keydown="handleContextMenuKeydown($event, editorContextMenuElement, closeEditorContextMenuAndRestoreFocus)"
        >
          <p>{{ currentGroup?.name || '常用命令' }}<small>命令编辑器</small></p>
          <button
            type="button"
            role="menuitem"
            :disabled="!editorContextMenu.hasCommand"
            @click="copySelectedCommand"
          >复制选中内容或当前行</button>
          <button type="button" role="menuitem" @click="pasteCommandText">粘贴</button>
          <button
            type="button"
            role="menuitem"
            :disabled="!content"
            @click="selectCurrentCommandLine"
          >选择当前行</button>
          <hr />
          <button
            type="button"
            role="menuitem"
            :disabled="!editorContextMenu.hasCommand || !workspace.activeSession || workspace.commandBusy"
            @click="dispatch(false); closeEditorContextMenu()"
          >发送到当前终端</button>
          <button
            type="button"
            role="menuitem"
            :disabled="!editorContextMenu.hasCommand || !workspace.connectedSessions.length || workspace.commandBusy"
            @click="dispatch(true); closeEditorContextMenu()"
          >发送到全部已连接终端</button>
          <hr />
          <button type="button" role="menuitem" @click="openFindReplace(); closeEditorContextMenu()">查找和替换</button>
          <button
            v-if="content"
            type="button"
            role="menuitem"
            class="danger-menu-item"
            @click="clearCurrentCommandGroup"
          >清空当前页签…</button>
        </div>
      </div>
    </template>
  </section>
</template>
