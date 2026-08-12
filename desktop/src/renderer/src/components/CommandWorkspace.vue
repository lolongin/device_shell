<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  BookOpenText,
  ChevronDown,
  ChevronUp,
  Pencil,
  Plus,
  RadioTower,
  Replace,
  Search,
  Send,
  X
} from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const commandWorkspace = ref<HTMLElement | null>(null)
const editor = ref<HTMLTextAreaElement | null>(null)
const findInput = ref<HTMLInputElement | null>(null)
const content = ref('')
const renameValue = ref('')
const renameGroupId = ref('')
const renaming = ref(false)
const findOpen = ref(false)
const findValue = ref('')
const replaceValue = ref('')
const findStatus = ref('')
const selectionStart = ref(0)
const selectionEnd = ref(0)
const commandGroupContextMenu = ref<{ groupId: string; name: string; x: number; y: number } | null>(null)
const editorContextMenu = ref<{ x: number; y: number; hasSelection: boolean; hasCommand: boolean } | null>(null)
const COMMAND_PANEL_HEIGHT_KEY = 'device-tui.desktop-v2.command-panel-height'
const COMMAND_PANEL_MIN_HEIGHT = 180
const COMMAND_PANEL_DEFAULT_HEIGHT = 300
const commandPanelMaxHeight = ref(680)
const preferredCommandPanelHeight = ref(storedCommandPanelHeight())
const commandPanelHeight = ref(preferredCommandPanelHeight.value)
let saveTimer: ReturnType<typeof setTimeout> | null = null
let suggestionTimer: ReturnType<typeof setTimeout> | null = null
let resizeStartY = 0
let resizeStartHeight = 0
let panelResizing = false

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
  if (event.key === 'ArrowUp') setCommandPanelHeight(commandPanelHeight.value + step)
  else if (event.key === 'ArrowDown') setCommandPanelHeight(commandPanelHeight.value - step)
  else if (event.key === 'Home') setCommandPanelHeight(COMMAND_PANEL_MIN_HEIGHT)
  else if (event.key === 'End') setCommandPanelHeight(commandPanelMaxHeight.value)
  else return
  event.preventDefault()
}

function resetCommandPanelHeight(): void {
  setCommandPanelHeight(COMMAND_PANEL_DEFAULT_HEIGHT)
}

watch(
  () => [currentGroup.value?.id, currentGroup.value?.content] as const,
  ([, nextContent]) => {
    content.value = nextContent || ''
  },
  { immediate: true }
)

watch(content, () => {
  if (!currentGroup.value || content.value === currentGroup.value.content) return
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => void saveContent(), 650)
  scheduleSuggestions()
})

async function saveContent(): Promise<void> {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = null
  const group = currentGroup.value
  if (!group || content.value === group.content) return
  await workspace.updateCommandGroup(group.id, { content: content.value })
}

async function selectGroup(groupId: string): Promise<void> {
  await saveContent()
  await workspace.selectCommandGroup(groupId)
  await nextTick()
  editor.value?.focus()
}

function beginRename(group = currentGroup.value): void {
  if (!group) return
  renameGroupId.value = group.id
  renameValue.value = group.name
  renaming.value = true
  closeCommandGroupContextMenu()
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

function closeCommandGroupContextMenu(): void {
  commandGroupContextMenu.value = null
}

function closeEditorContextMenu(): void {
  editorContextMenu.value = null
}

function openCommandGroupContextMenu(event: MouseEvent, groupId: string, name: string): void {
  commandGroupContextMenu.value = { groupId, name, x: event.clientX, y: event.clientY }
}

function handleCommandGroupKeydown(event: KeyboardEvent, groupId: string, name: string): void {
  if (event.key === 'Escape') {
    closeCommandGroupContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    event.preventDefault()
    const rect = (event.currentTarget as HTMLElement | null)?.getBoundingClientRect()
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
  if (command) await navigator.clipboard.writeText(command)
  closeEditorContextMenu()
}

async function pasteCommandText(): Promise<void> {
  const element = editor.value
  if (!element) return
  const text = await navigator.clipboard.readText()
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
  updateSelectionState()
  editorContextMenu.value = {
    x: event.clientX,
    y: event.clientY,
    hasSelection: selectionStart.value !== selectionEnd.value,
    hasCommand: Boolean(selectedCommand())
  }
}

async function dispatch(broadcast = false): Promise<void> {
  const command = selectedCommand()
  if (!command) return
  await saveContent()
  await workspace.dispatchCommand(command, broadcast)
  editor.value?.focus()
}

function handleEditorKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    closeEditorContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    event.preventDefault()
    const rect = editor.value?.getBoundingClientRect()
    updateSelectionState()
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
  if (!shouldSend) return
  event.preventDefault()
  void dispatch(false)
}

function currentLineQuery(): string {
  const element = editor.value
  if (!element) return ''
  const before = content.value.lastIndexOf('\n', Math.max(0, element.selectionStart - 1)) + 1
  return content.value.slice(before, element.selectionStart).trim()
}

function scheduleSuggestions(): void {
  if (suggestionTimer) clearTimeout(suggestionTimer)
  suggestionTimer = setTimeout(() => {
    void workspace.fetchCommandSuggestions(currentLineQuery())
  }, 180)
}

function applySuggestion(command: string): void {
  const element = editor.value
  if (!element) return
  const start = content.value.lastIndexOf('\n', Math.max(0, element.selectionStart - 1)) + 1
  const nextBreak = content.value.indexOf('\n', element.selectionStart)
  const end = nextBreak < 0 ? content.value.length : nextBreak
  content.value = `${content.value.slice(0, start)}${command}${content.value.slice(end)}`
  void nextTick(() => {
    element.setSelectionRange(start + command.length, start + command.length)
    element.focus()
  })
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
  clampCommandPanelHeight()
  window.addEventListener('resize', clampCommandPanelHeight)
})

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer)
  if (suggestionTimer) clearTimeout(suggestionTimer)
  stopCommandPanelResize()
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
    <button
      v-if="!workspace.commandPanelOpen"
      class="command-collapsed-bar"
      type="button"
      title="展开常用命令"
      @click="workspace.commandPanelOpen = true"
    >
      <span><BookOpenText :size="14" />常用命令</span>
      <span>{{ currentGroup?.name || '终端' }} · {{ workspace.commandHistory.length }} 条历史 <ChevronUp :size="14" /></span>
    </button>
    <template v-else>
      <div
        class="command-resize-handle"
        data-testid="command-resize-handle"
        role="separator"
        aria-label="调整常用命令面板高度"
        aria-orientation="horizontal"
        :aria-valuemin="COMMAND_PANEL_MIN_HEIGHT"
        :aria-valuemax="commandPanelMaxHeight"
        :aria-valuenow="commandPanelHeight"
        tabindex="0"
        title="拖动调整高度；双击恢复默认"
        @pointerdown="startCommandPanelResize"
        @keydown="handleCommandPanelResizeKeydown"
        @dblclick="resetCommandPanelHeight"
      ><span aria-hidden="true"></span></div>
      <header class="command-header" @click="closeCommandGroupContextMenu">
        <div class="command-tabs" role="tablist">
          <div
            v-for="group in workspace.commandGroups"
            :key="group.id"
            class="command-tab"
            :class="{ active: group.id === workspace.currentCommandGroupId }"
          >
            <button
              type="button"
              role="tab"
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
          class="command-context-menu"
          role="menu"
          :style="{ left: `${commandGroupContextMenu.x}px`, top: `${commandGroupContextMenu.y}px` }"
          @click.stop
          @keydown.esc.prevent="closeCommandGroupContextMenu"
        >
          <p>{{ commandGroupContextMenu.name }}</p>
          <button
            type="button"
            role="menuitem"
            @click="beginRename(workspace.commandGroups.find((group) => group.id === commandGroupContextMenu?.groupId) || currentGroup)"
          >重命名</button>
          <button type="button" role="menuitem" @click="workspace.createCommandGroup(); closeCommandGroupContextMenu()">新增命令页签</button>
          <button
            type="button"
            role="menuitem"
            class="danger-menu-item"
            :disabled="workspace.commandGroups.length <= 1"
            @click="removeGroup(commandGroupContextMenu.groupId, commandGroupContextMenu.name)"
          >删除页签</button>
        </div>
        <div class="command-header-actions">
          <button class="icon-button" type="button" title="重命名页签" @click="beginRename()"><Pencil :size="14" /></button>
          <button class="icon-button" type="button" title="查找和替换 (Ctrl+F)" :aria-pressed="findOpen" @click="findOpen ? closeFindReplace() : openFindReplace()"><Search :size="14" /></button>
          <button
            class="command-mode-button"
            type="button"
            :aria-pressed="workspace.commandEnterSends"
            @click="workspace.setCommandEnterSends(!workspace.commandEnterSends)"
          >{{ workspace.commandEnterSends ? 'Enter 发送' : 'Ctrl+Enter 发送' }}</button>
          <button class="icon-button" type="button" title="收起常用命令" @click="workspace.commandPanelOpen = false"><ChevronDown :size="15" /></button>
        </div>
      </header>

      <form v-if="renaming" class="command-inline-form" @submit.prevent="commitRename">
        <input v-model="renameValue" maxlength="160" aria-label="页签名称" autofocus @keydown.esc.prevent="renaming = false" />
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
        <textarea
          ref="editor"
          v-model="content"
          aria-label="常用命令"
          spellcheck="false"
          placeholder="每行一条命令；选择多行可批量发送"
          @click="scheduleSuggestions"
          @keyup="scheduleSuggestions"
          @select="updateSelectionState"
          @mouseup="updateSelectionState"
          @keyup.left="updateSelectionState"
          @keyup.right="updateSelectionState"
          @keyup.up="updateSelectionState"
          @keyup.down="updateSelectionState"
          @keydown="handleEditorKeydown"
          @contextmenu.prevent="openEditorContextMenu"
        ></textarea>
        <div
          v-if="editorContextMenu"
          class="command-context-menu"
          role="menu"
          :style="{ left: `${editorContextMenu.x}px`, top: `${editorContextMenu.y}px` }"
          @click.stop
          @keydown.esc.prevent="closeEditorContextMenu"
        >
          <p>{{ currentGroup?.name || '常用命令' }}</p>
          <button
            type="button"
            role="menuitem"
            :disabled="!editorContextMenu.hasCommand"
            @click="copySelectedCommand"
          >复制选中/当前命令</button>
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
          >发送到终端</button>
          <button
            type="button"
            role="menuitem"
            :disabled="!editorContextMenu.hasCommand || !workspace.connectedSessions.length || workspace.commandBusy"
            @click="dispatch(true); closeEditorContextMenu()"
          >广播发送</button>
          <hr />
          <button type="button" role="menuitem" @click="openFindReplace(); closeEditorContextMenu()">查找和替换</button>
          <button
            type="button"
            role="menuitem"
            class="danger-menu-item"
            :disabled="!content"
            @click="clearCurrentCommandGroup"
          >清空当前页签</button>
        </div>
        <div class="command-dispatch-actions">
          <button
            class="primary-button"
            type="button"
            :disabled="!workspace.activeSession || workspace.commandBusy"
            @click="dispatch(false)"
          ><Send :size="14" />发送</button>
          <button
            class="secondary-button"
            type="button"
            :disabled="!workspace.connectedSessions.length || workspace.commandBusy"
            @click="dispatch(true)"
          ><RadioTower :size="14" />广播 {{ workspace.connectedSessions.length }}</button>
          <small>发送选中内容；未选择时发送当前行。</small>
        </div>
      </div>

      <div v-if="workspace.commandSuggestions.length" class="command-suggestions" aria-label="命令建议">
        <button
          v-for="suggestion in workspace.commandSuggestions"
          :key="suggestion"
          type="button"
          @click="applySuggestion(suggestion)"
        >{{ suggestion }}</button>
      </div>
    </template>
  </section>
</template>
