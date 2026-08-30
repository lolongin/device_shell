<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Columns2, Rows2, X } from 'lucide-vue-next'
import TerminalPane from './TerminalPane.vue'
import type { SessionSummary } from '../types'

type PaneId = 'primary' | 'secondary'
type SplitDirection = 'left' | 'right' | 'top' | 'bottom'
type DeviceProtocolKind = 'ssh' | 'telnet' | 'serial'

interface DeviceProtocolAction {
  kind: DeviceProtocolKind
  label: string
  opened: boolean
}

interface StoredSplitLayout {
  direction: SplitDirection | null
  assignments: Record<string, PaneId>
  primaryActiveId: string
  secondaryActiveId: string
  ratio: number
}

const props = defineProps<{
  active: boolean
  deviceId: string
  sessions: SessionSummary[]
  activeSessionId: string
  protocolActions: DeviceProtocolAction[]
}>()
const emit = defineEmits<{
  activate: [sessionId: string]
  status: [sessionId: string, status: string, sequence: number]
  automation: [sessionId: string]
  transfer: [sessionId: string]
  upgrade: [sessionId: string]
  openProtocol: [kind: DeviceProtocolKind]
  splitChange: [active: boolean]
}>()

const STORAGE_KEY = 'odyterm.desktop-v2.terminal-split-layout'
const SESSION_DRAG_TYPE = 'application/x-odyterm-session'
const MAX_WARM_TERMINAL_PANES = 6
const restored = readStoredLayout()
const splitDirection = ref<SplitDirection | null>(restored.direction)
const assignments = ref<Record<string, PaneId>>(restored.assignments)
const primaryActiveId = ref(restored.primaryActiveId)
const secondaryActiveId = ref(restored.secondaryActiveId)
const splitRatio = ref(restored.ratio)
const splitContainer = ref<HTMLElement | null>(null)
const focusedPane = ref<PaneId>('primary')
const dropDirection = ref<SplitDirection | null>(null)
const dropPane = ref<PaneId>('secondary')
const warmSessionIds = ref<string[]>([])

function splitStorageKey(): string {
  return `${STORAGE_KEY}.${props.deviceId}`
}

const primarySessions = computed(() => sessionsForPane('primary'))
const secondarySessions = computed(() => sessionsForPane('secondary'))
const orderedPanes = computed<PaneId[]>(() =>
  splitDirection.value === 'left' || splitDirection.value === 'top'
    ? ['secondary', 'primary']
    : ['primary', 'secondary']
)
const visiblePanes = computed<PaneId[]>(() =>
  splitDirection.value ? orderedPanes.value : ['primary']
)
const splitGridStyle = computed(() => {
  if (!splitDirection.value) return undefined
  const leading = `${splitRatio.value}fr`
  const trailing = `${100 - splitRatio.value}fr`
  return splitDirection.value === 'left' || splitDirection.value === 'right'
    ? { gridTemplateColumns: `${leading} ${trailing}` }
    : { gridTemplateRows: `${leading} ${trailing}` }
})
const splitResizeStyle = computed(() => {
  if (!splitDirection.value) return undefined
  return splitDirection.value === 'left' || splitDirection.value === 'right'
    ? { left: `calc(${splitRatio.value}% - 4px)` }
    : { top: `calc(${splitRatio.value}% - 4px)` }
})

function readStoredLayout(): StoredSplitLayout {
  try {
    const parsed = JSON.parse(localStorage.getItem(splitStorageKey()) || '{}') as Partial<StoredSplitLayout>
    const direction = ['left', 'right', 'top', 'bottom'].includes(String(parsed.direction))
      ? parsed.direction as SplitDirection
      : null
    return {
      direction,
      assignments: parsed.assignments && typeof parsed.assignments === 'object'
        ? parsed.assignments
        : {},
      primaryActiveId: String(parsed.primaryActiveId || ''),
      secondaryActiveId: String(parsed.secondaryActiveId || ''),
      ratio: Math.max(20, Math.min(80, Number(parsed.ratio) || 50))
    }
  } catch {
    return { direction: null, assignments: {}, primaryActiveId: '', secondaryActiveId: '', ratio: 50 }
  }
}

function sessionsForPane(pane: PaneId): SessionSummary[] {
  return props.sessions.filter((session) => (assignments.value[session.id] || 'primary') === pane)
}

function touchWarmSession(sessionId: string): void {
  if (!sessionId) return
  const currentIds = new Set(props.sessions.map((session) => session.id))
  warmSessionIds.value = [
    sessionId,
    ...warmSessionIds.value.filter((id) => id !== sessionId && currentIds.has(id))
  ].slice(0, MAX_WARM_TERMINAL_PANES)
}

function warmSessionsForPane(pane: PaneId): SessionSummary[] {
  return sessionsForPane(pane).filter((session) => mountedSessionIds.value.has(session.id))
}

function activeSessionFor(pane: PaneId): SessionSummary | null {
  const sessions = pane === 'primary' ? primarySessions.value : secondarySessions.value
  const activeId = pane === 'primary' ? primaryActiveId.value : secondaryActiveId.value
  return sessions.find((session) => session.id === activeId) || sessions[0] || null
}

const mountedSessionIds = computed(() => {
  const activeIds = visiblePanes.value
    .map((pane) => activeSessionFor(pane)?.id || '')
    .filter(Boolean)
  return new Set([
    ...activeIds,
    ...warmSessionIds.value.filter((id) => !activeIds.includes(id))
  ].slice(0, MAX_WARM_TERMINAL_PANES))
})

function activateSession(sessionId: string, pane: PaneId): void {
  if (pane === 'primary') primaryActiveId.value = sessionId
  else secondaryActiveId.value = sessionId
  focusedPane.value = pane
  touchWarmSession(sessionId)
  emit('activate', sessionId)
}

function activatePane(pane: PaneId): void {
  const active = activeSessionFor(pane)
  if (active) activateSession(active.id, pane)
}

function splitSession(
  sessionId: string,
  direction: SplitDirection,
  targetPane: PaneId = 'secondary'
): void {
  if (!props.sessions.some((session) => session.id === sessionId)) return
  const nextAssignments: Record<string, PaneId> = {}
  for (const session of props.sessions) {
    nextAssignments[session.id] = assignments.value[session.id] || 'primary'
  }
  nextAssignments[sessionId] = targetPane
  assignments.value = nextAssignments
  splitDirection.value = direction
  touchWarmSession(sessionId)
  if (targetPane === 'primary') primaryActiveId.value = sessionId
  else secondaryActiveId.value = sessionId
  activateSession(sessionId, targetPane)
}

function resetSplit(): void {
  assignments.value = Object.fromEntries(props.sessions.map((session) => [session.id, 'primary']))
  primaryActiveId.value = props.activeSessionId || props.sessions[0]?.id || ''
  secondaryActiveId.value = ''
  splitDirection.value = null
  focusedPane.value = 'primary'
  dropDirection.value = null
}

function updateSplitRatio(event: PointerEvent): void {
  const container = splitContainer.value
  if (!container || !splitDirection.value) return
  const rect = container.getBoundingClientRect()
  const horizontal = splitDirection.value === 'left' || splitDirection.value === 'right'
  const position = horizontal ? event.clientX - rect.left : event.clientY - rect.top
  const size = horizontal ? rect.width : rect.height
  if (size <= 0) return
  splitRatio.value = Math.max(20, Math.min(80, Math.round((position / size) * 100)))
}

function stopSplitResize(): void {
  window.removeEventListener('pointermove', updateSplitRatio)
  window.removeEventListener('pointerup', stopSplitResize)
}

function startSplitResize(event: PointerEvent): void {
  event.preventDefault()
  updateSplitRatio(event)
  window.addEventListener('pointermove', updateSplitRatio)
  window.addEventListener('pointerup', stopSplitResize, { once: true })
}

function handleSplitResizeKeydown(event: KeyboardEvent): void {
  const horizontal = splitDirection.value === 'left' || splitDirection.value === 'right'
  const decrease = horizontal ? event.key === 'ArrowLeft' : event.key === 'ArrowUp'
  const increase = horizontal ? event.key === 'ArrowRight' : event.key === 'ArrowDown'
  if (!decrease && !increase) return
  event.preventDefault()
  splitRatio.value = Math.max(20, Math.min(80, splitRatio.value + (increase ? 5 : -5)))
}

function directionForEvent(event: DragEvent): SplitDirection {
  const target = event.currentTarget as HTMLElement
  const rect = target.getBoundingClientRect()
  const distances: Record<SplitDirection, number> = {
    left: Math.max(0, event.clientX - rect.left),
    right: Math.max(0, rect.right - event.clientX),
    top: Math.max(0, event.clientY - rect.top),
    bottom: Math.max(0, rect.bottom - event.clientY)
  }
  return (Object.entries(distances) as [SplitDirection, number][])
    .sort((left, right) => left[1] - right[1])[0][0]
}

function handleDragOver(event: DragEvent, pane: PaneId): void {
  if (!event.dataTransfer?.types.includes(SESSION_DRAG_TYPE)) return
  event.preventDefault()
  event.dataTransfer.dropEffect = 'move'
  dropDirection.value = directionForEvent(event)
  dropPane.value = splitDirection.value ? pane : 'secondary'
}

function handleDragLeave(event: DragEvent): void {
  const target = event.currentTarget as HTMLElement
  const related = event.relatedTarget as Node | null
  if (related && target.contains(related)) return
  dropDirection.value = null
}

function handleDrop(event: DragEvent, pane: PaneId): void {
  const sessionId = event.dataTransfer?.getData(SESSION_DRAG_TYPE)
    || event.dataTransfer?.getData('text/plain')
    || ''
  if (!sessionId) return
  event.preventDefault()
  const direction = dropDirection.value || directionForEvent(event)
  splitSession(sessionId, direction, splitDirection.value ? pane : 'secondary')
  dropDirection.value = null
}

function reconcileSessions(): void {
  const ids = new Set(props.sessions.map((session) => session.id))
  const nextAssignments: Record<string, PaneId> = {}
  warmSessionIds.value = warmSessionIds.value.filter((id) => ids.has(id))
  for (const session of props.sessions) {
    const storedPane = assignments.value[session.id]
    nextAssignments[session.id] = splitDirection.value && storedPane === 'secondary'
      ? 'secondary'
      : 'primary'
  }
  assignments.value = nextAssignments
  if (!ids.has(primaryActiveId.value)) primaryActiveId.value = primarySessions.value[0]?.id || ''
  if (!ids.has(secondaryActiveId.value)) secondaryActiveId.value = secondarySessions.value[0]?.id || ''
  if (splitDirection.value && !secondarySessions.value.length) {
    splitDirection.value = null
    assignments.value = Object.fromEntries(props.sessions.map((session) => [session.id, 'primary']))
  }
}

watch(
  () => props.sessions.map((session) => session.id).join('|'),
  reconcileSessions,
  { immediate: true }
)

watch(
  () => props.activeSessionId,
  (sessionId) => {
    if (!sessionId) return
    touchWarmSession(sessionId)
    const pane = assignments.value[sessionId] || 'primary'
    if (pane === 'primary') primaryActiveId.value = sessionId
    else secondaryActiveId.value = sessionId
    focusedPane.value = pane
  },
  { immediate: true }
)

watch(
  [splitDirection, assignments, primaryActiveId, secondaryActiveId, splitRatio],
  () => {
    localStorage.setItem(splitStorageKey(), JSON.stringify({
      direction: splitDirection.value,
      assignments: assignments.value,
      primaryActiveId: primaryActiveId.value,
      secondaryActiveId: secondaryActiveId.value,
      ratio: splitRatio.value
    }))
    emit('splitChange', Boolean(splitDirection.value))
  },
  { deep: true }
)

onBeforeUnmount(stopSplitResize)

defineExpose({ splitSession, resetSplit })
</script>

<template>
  <div class="terminal-workspace-stack" :class="{ split: Boolean(splitDirection), active }">
    <div
      ref="splitContainer"
      class="terminal-split-layout"
      :class="{ split: Boolean(splitDirection) }"
      :data-split-direction="splitDirection || 'none'"
      :style="splitGridStyle"
    >
    <section
      v-for="pane in visiblePanes"
      :key="pane"
      class="terminal-split-pane"
      :class="{ focused: focusedPane === pane }"
      :data-pane-id="pane"
      :aria-label="pane === 'primary' ? '主终端窗格' : '分屏终端窗格'"
      @mousedown="activatePane(pane)"
      @dragover="handleDragOver($event, pane)"
      @dragleave="handleDragLeave"
      @drop="handleDrop($event, pane)"
    >
      <header v-if="splitDirection" class="split-pane-tabs">
        <span :title="pane === 'primary' ? '主窗格' : '分屏窗格'">
          <Columns2 v-if="splitDirection === 'left' || splitDirection === 'right'" :size="13" />
          <Rows2 v-else :size="13" />
          {{ pane === 'primary' ? '主窗格' : '分屏' }}
        </span>
        <strong
          v-if="activeSessionFor(pane)"
          class="split-pane-session-title"
          :data-session-id="activeSessionFor(pane)!.id"
          :title="activeSessionFor(pane)!.title"
        >{{ activeSessionFor(pane)!.title }}</strong>
        <button
          v-if="pane === 'secondary'"
          class="split-close-button"
          type="button"
          title="退出终端分屏"
          aria-label="退出终端分屏"
          @click="resetSplit"
        ><X :size="13" /></button>
      </header>

      <TerminalPane
        v-for="session in warmSessionsForPane(pane)"
        v-show="activeSessionFor(pane)?.id === session.id"
        :key="session.id"
        :session="session"
        :active="active && focusedPane === pane && activeSessionFor(pane)?.id === session.id"
        :protocol-actions="protocolActions"
        @status="(sessionId, status, sequence) => emit('status', sessionId, status, sequence)"
        @automation="emit('automation', $event)"
        @transfer="emit('transfer', $event)"
        @upgrade="emit('upgrade', $event)"
        @open-protocol="emit('openProtocol', $event)"
      ></TerminalPane>
      <div v-if="!sessionsForPane(pane).length" class="split-empty-pane">
        <Columns2 :size="24" />
        <strong>空窗格</strong>
        <span>将另一个会话页签拖到这里，或通过页签菜单选择分屏方向。</span>
      </div>

      <div
        v-if="dropDirection && dropPane === pane"
        class="terminal-drop-indicator"
        :data-direction="dropDirection"
        aria-hidden="true"
      >放到{{ { left: '左侧', right: '右侧', top: '上方', bottom: '下方' }[dropDirection] }}</div>
    </section>
      <div
      v-if="splitDirection"
      class="split-resize-handle"
      :data-orientation="splitDirection === 'left' || splitDirection === 'right' ? 'vertical' : 'horizontal'"
      :style="splitResizeStyle"
      role="separator"
      :aria-orientation="splitDirection === 'left' || splitDirection === 'right' ? 'vertical' : 'horizontal'"
      :aria-valuenow="splitRatio"
      aria-valuemin="20"
      aria-valuemax="80"
      tabindex="0"
      title="拖动调整终端分屏大小"
      @pointerdown="startSplitResize"
      @keydown="handleSplitResizeKeydown"
      ></div>
    </div>
  </div>
</template>
