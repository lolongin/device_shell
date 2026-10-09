<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { MoreHorizontal, Pencil, Plus, Star, Trash2, Workflow } from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import { announceContextMenuOpen, subscribeContextMenuOpen } from '../contextMenu'

type QuickAction = {
  id: string
  type: 'command' | 'workflow'
  name: string
  command?: string
  workflowId?: string
}

const STORAGE_KEY = 'odyterm.desktop-v2.quick-actions'
const MAX_VISIBLE = 9
const workspace = useWorkspaceStore()
const actions = ref<QuickAction[]>(loadActions())
const overflowOpen = ref(false)
const contextOpen = ref(false)
const contextId = ref('')
const draggedId = ref('')
const dragOverId = ref('')
const quickActionsRoot = ref<HTMLElement | null>(null)
const commandDialogOpen = ref(false)
const commandDraft = ref('')
const commandName = ref('')
let unsubscribeContextMenuOpen: (() => void) | null = null

const visibleActions = computed(() => actions.value.slice(0, MAX_VISIBLE))
const overflowActions = computed(() => actions.value.slice(MAX_VISIBLE))
const contextAction = computed(() => actions.value.find((item) => item.id === contextId.value) || null)

function loadActions(): QuickAction[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item) => item && (item.type === 'command' || item.type === 'workflow') && item.name && item.id)
  } catch {
    return []
  }
}

function persist(): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(actions.value))
}

function makeId(): string {
  return `quick-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

function addCommand(command: string, name = ''): void {
  const text = command.trim()
  if (!text) return
  const defaultName = text.split(/\r?\n/)[0].slice(0, 36)
  const label = (name || defaultName).trim()
  if (!label) return
  actions.value.push({ id: makeId(), type: 'command', name: label, command: text })
  persist()
  workspace.notice = `已添加快捷命令：${label}`
}

function createCommand(): void {
  commandDraft.value = ''
  commandName.value = ''
  commandDialogOpen.value = true
}

function submitCommand(): void {
  const command = commandDraft.value.trim()
  if (!command) return
  addCommand(command, commandName.value.trim())
  commandDialogOpen.value = false
}

function addWorkflow(workflowId: string, name: string): void {
  if (!workflowId || actions.value.some((item) => item.type === 'workflow' && item.workflowId === workflowId)) {
    workspace.notice = '该 Workflow 已在快捷栏中。'
    return
  }
  actions.value.push({ id: makeId(), type: 'workflow', name, workflowId })
  persist()
  workspace.notice = `已添加快捷 Workflow：${name}`
}

async function activate(action: QuickAction): Promise<void> {
  overflowOpen.value = false
  contextOpen.value = false
  if (action.type === 'workflow') {
    const session = workspace.activeSession
    emit('run-workflow', {
      workflowId: action.workflowId || '', autoRun: true,
      deviceId: session?.device_id || workspace.selectedDeviceId,
      sessionId: session?.id || ''
    })
    return
  }
  if (!workspace.activeSession) {
    workspace.notice = '请先连接一个终端，再发送快捷命令。'
    return
  }
  await workspace.dispatchCommand(action.command || '')
  if (!workspace.error) workspace.notice = `已发送快捷命令：${action.name}`
}

function openContext(event: MouseEvent, id: string): void {
  event.preventDefault()
  announceContextMenuOpen()
  contextId.value = id
  contextOpen.value = true
}

function closeMenus(): void {
  overflowOpen.value = false
  contextOpen.value = false
  contextId.value = ''
}

function renameAction(): void {
  const action = contextAction.value
  if (!action) return
  const name = window.prompt('快捷项名称', action.name)?.trim()
  if (!name) return
  action.name = name
  persist()
  closeMenus()
}

function startDrag(event: DragEvent, id: string): void {
  draggedId.value = id
  dragOverId.value = ''
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', id)
  }
}

function dragOver(event: DragEvent, id: string): void {
  if (!draggedId.value || draggedId.value === id) return
  event.preventDefault()
  dragOverId.value = id
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
}

function dropAction(event: DragEvent, targetId: string): void {
  event.preventDefault()
  const sourceId = draggedId.value || event.dataTransfer?.getData('text/plain') || ''
  const sourceIndex = actions.value.findIndex((item) => item.id === sourceId)
  const targetIndex = actions.value.findIndex((item) => item.id === targetId)
  if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) {
    draggedId.value = ''
    dragOverId.value = ''
    return
  }
  const [item] = actions.value.splice(sourceIndex, 1)
  actions.value.splice(targetIndex, 0, item)
  persist()
  draggedId.value = ''
  dragOverId.value = ''
}

function finishDrag(): void {
  draggedId.value = ''
  dragOverId.value = ''
}

function handleGlobalClick(event: MouseEvent): void {
  if (quickActionsRoot.value?.contains(event.target as Node)) return
  closeMenus()
}

function handleGlobalContextMenu(event: MouseEvent): void {
  if (quickActionsRoot.value?.contains(event.target as Node)) return
  closeMenus()
}

onMounted(() => {
  unsubscribeContextMenuOpen = subscribeContextMenuOpen(closeMenus)
  window.addEventListener('click', handleGlobalClick, true)
  window.addEventListener('contextmenu', handleGlobalContextMenu, true)
})

onBeforeUnmount(() => {
  unsubscribeContextMenuOpen?.()
  window.removeEventListener('click', handleGlobalClick, true)
  window.removeEventListener('contextmenu', handleGlobalContextMenu, true)
})

function removeAction(): void {
  const action = contextAction.value
  if (!action || !window.confirm(`移除快捷项“${action.name}”？`)) return
  actions.value = actions.value.filter((item) => item.id !== action.id)
  persist()
  closeMenus()
}

const emit = defineEmits<{ 'run-workflow': [payload: { workflowId: string; autoRun: boolean; deviceId: string; sessionId: string }] }>()
defineExpose({ addCommand, addWorkflow })
</script>

<template>
  <div ref="quickActionsRoot" class="quick-actions-bar" aria-label="快捷发送" @click.stop>
    <span class="quick-actions-label"><Star :size="13" />快捷发送</span>
    <button type="button" class="quick-action-add" title="添加快捷命令" @click="createCommand"><Plus :size="13" />添加</button>
    <button
      v-for="action in visibleActions"
      :key="action.id"
      type="button"
      class="quick-action-button"
      :class="{ dragging: draggedId === action.id, 'drag-over': dragOverId === action.id }"
      draggable="true"
      :title="action.type === 'command' ? action.command : '运行最新已发布 Workflow'"
      @click="activate(action)"
      @contextmenu="openContext($event, action.id)"
      @dragstart="startDrag($event, action.id)"
      @dragover="dragOver($event, action.id)"
      @drop="dropAction($event, action.id)"
      @dragend="finishDrag"
    ><Workflow v-if="action.type === 'workflow'" :size="12" /><span>{{ action.name }}</span></button>
    <details v-if="overflowActions.length" class="quick-actions-more" :open="overflowOpen" @toggle="overflowOpen = ($event.target as HTMLDetailsElement).open">
      <summary title="更多快捷项"><MoreHorizontal :size="15" /></summary>
      <div class="quick-actions-overflow">
        <button v-for="action in overflowActions" :key="action.id" type="button" draggable="true" :class="{ dragging: draggedId === action.id, 'drag-over': dragOverId === action.id }" @click="activate(action)" @contextmenu="openContext($event, action.id)" @dragstart="startDrag($event, action.id)" @dragover="dragOver($event, action.id)" @drop="dropAction($event, action.id)" @dragend="finishDrag">{{ action.name }}</button>
      </div>
    </details>
    <span v-if="!actions.length" class="quick-actions-empty">从命令编辑器或 Workflow 添加</span>
    <div v-if="contextOpen && contextAction" class="quick-actions-context" role="menu">
      <strong>{{ contextAction.name }}</strong>
      <button type="button" role="menuitem" @click="renameAction"><Pencil :size="12" />重命名</button>
      <button type="button" role="menuitem" class="danger" @click="removeAction"><Trash2 :size="12" />移除</button>
    </div>
  </div>
  <div v-if="commandDialogOpen" class="quick-command-dialog-backdrop" @mousedown.self="commandDialogOpen = false">
    <form class="quick-command-dialog" role="dialog" aria-modal="true" aria-labelledby="quick-command-dialog-title" @submit.prevent="submitCommand">
      <h3 id="quick-command-dialog-title">添加快捷命令</h3>
      <input v-model="commandName" placeholder="名称（可选）" maxlength="80" data-dialog-initial-focus />
      <textarea v-model="commandDraft" placeholder="输入快捷命令，支持多行" rows="5" required></textarea>
      <footer><button type="button" @click="commandDialogOpen = false">取消</button><button type="submit" :disabled="!commandDraft.trim()">添加</button></footer>
    </form>
  </div>
</template>

<style scoped>
.quick-actions-bar { position: relative; display: flex; align-items: center; gap: 5px; min-width: 0; min-height: 30px; padding: 3px 10px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); background: var(--surface-raised); }
.quick-actions-label { display: inline-flex; align-items: center; gap: 4px; color: var(--muted); font-size: 11px; white-space: nowrap; }
.quick-action-add { display: inline-flex; align-items: center; gap: 3px; padding: 4px 7px; border: 1px dashed var(--line); border-radius: 5px; color: var(--muted); background: transparent; font-size: 11px; cursor: pointer; }
.quick-action-add:hover { border-color: var(--blue); color: var(--text); }
.quick-action-button, .quick-actions-more summary { display: inline-flex; align-items: center; gap: 4px; max-width: 150px; padding: 4px 7px; overflow: hidden; border: 1px solid var(--line); border-radius: 5px; color: var(--text); background: var(--surface); font-size: 11px; cursor: pointer; white-space: nowrap; }
.quick-action-button span { overflow: hidden; text-overflow: ellipsis; }
.quick-action-button.dragging, .quick-actions-overflow button.dragging { opacity: .45; }
.quick-action-button.drag-over, .quick-actions-overflow button.drag-over { border-color: var(--blue); box-shadow: inset 0 0 0 1px var(--blue); }
.quick-action-button:hover, .quick-actions-more summary:hover { border-color: var(--blue); }
.quick-actions-more { position: relative; }
.quick-actions-more summary { list-style: none; padding: 4px 6px; }
.quick-actions-more summary::-webkit-details-marker { display: none; }
.quick-actions-overflow { position: absolute; z-index: 50; top: calc(100% + 6px); right: 0; display: grid; gap: 3px; min-width: 160px; padding: 6px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-raised); box-shadow: 0 10px 26px rgba(0,0,0,.24); }
.quick-actions-overflow button { padding: 7px 8px; border: 0; border-radius: 4px; color: var(--text); background: transparent; text-align: left; cursor: pointer; }
.quick-actions-overflow button:hover { background: var(--surface-hover); }
.quick-actions-empty { color: var(--muted); font-size: 10px; white-space: nowrap; }
.quick-actions-context { position: absolute; z-index: 60; top: calc(100% + 5px); left: 50px; display: grid; gap: 2px; min-width: 150px; padding: 6px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface-raised); box-shadow: 0 12px 28px rgba(0,0,0,.25); }
.quick-actions-context strong { padding: 4px 6px; overflow: hidden; color: var(--muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.quick-actions-context button { display: flex; align-items: center; gap: 6px; padding: 6px; border: 0; border-radius: 4px; color: var(--text); background: transparent; font-size: 11px; text-align: left; cursor: pointer; }
.quick-actions-context button:hover { background: var(--surface-hover); }
.quick-actions-context .danger { color: #fca5a5; }
.quick-command-dialog-backdrop { position: fixed; z-index: 100; inset: 0; display: grid; place-items: center; background: rgba(2, 8, 23, .55); }
.quick-command-dialog { display: grid; gap: 10px; width: min(420px, calc(100vw - 32px)); padding: 16px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-raised); box-shadow: 0 18px 48px rgba(0,0,0,.35); }
.quick-command-dialog h3 { margin: 0; color: var(--text); font-size: 14px; }
.quick-command-dialog input, .quick-command-dialog textarea { width: 100%; box-sizing: border-box; padding: 8px; border: 1px solid var(--line); border-radius: 5px; color: var(--text); background: var(--surface); font: inherit; }
.quick-command-dialog footer { display: flex; justify-content: flex-end; gap: 7px; }
.quick-command-dialog footer button { padding: 6px 12px; border: 1px solid var(--line); border-radius: 5px; color: var(--text); background: var(--surface); cursor: pointer; }
.quick-command-dialog footer button[type="submit"] { border-color: var(--blue); background: var(--blue); }
.quick-command-dialog footer button:disabled { opacity: .5; cursor: not-allowed; }
@media (max-width: 1100px) { .quick-actions-label, .quick-actions-empty { display: none; } .quick-action-button { max-width: 100px; } }
</style>
