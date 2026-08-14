<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  MonitorDot,
  Search,
  X
} from 'lucide-vue-next'
import type { DeviceSummary, SessionSummary } from '../types'
import {
  aggregateSessionHealth,
  sessionHealthLabel,
  sessionHealthShortLabel,
  sessionStatusLabel
} from '../sessionStatus'

interface SessionDeviceGroup {
  id: string
  label: string
  device: DeviceSummary | null
  sessions: SessionSummary[]
  health: ReturnType<typeof aggregateSessionHealth>
}

const props = defineProps<{
  devices: DeviceSummary[]
  sessions: SessionSummary[]
  activeSessionId: string
  collapsed: boolean
}>()

const emit = defineEmits<{
  activate: [sessionId: string]
  close: [sessionId: string]
  sessionContext: [event: MouseEvent, session: SessionSummary]
  deviceContext: [event: MouseEvent, deviceId: string]
  locateDevice: [deviceId: string]
  updateCollapsed: [collapsed: boolean]
}>()

const WIDTH_KEY = 'device-tui.desktop-v2.session-manager-width'
const COLLAPSED_GROUPS_KEY = 'device-tui.desktop-v2.session-manager-collapsed-groups'
const SESSION_DRAG_TYPE = 'application/x-device-tui-session'
const manager = ref<HTMLElement | null>(null)
const query = ref('')
const managerWidth = ref(readManagerWidth())
const collapsedGroups = ref<Set<string>>(readCollapsedGroups())

const groups = computed<SessionDeviceGroup[]>(() => {
  const byDevice = new Map<string, SessionSummary[]>()
  for (const session of props.sessions) {
    const current = byDevice.get(session.device_id) || []
    current.push(session)
    byDevice.set(session.device_id, current)
  }
  return [...byDevice.entries()].map(([deviceId, sessions]) => {
    const device = props.devices.find((candidate) => candidate.id === deviceId) || null
    return {
      id: deviceId,
      label: device?.name || sessions[0]?.title.split(' · ')[0] || deviceId,
      device,
      sessions,
      health: aggregateSessionHealth(sessions)
    }
  })
})

const visibleGroups = computed<SessionDeviceGroup[]>(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  if (!needle) return groups.value
  return groups.value.flatMap((group) => {
    const deviceText = [
      group.id,
      group.label,
      group.device?.domain,
      group.device?.site,
      group.device?.rack,
      group.device?.device_type
    ].filter(Boolean).join(' ').toLocaleLowerCase()
    if (deviceText.includes(needle)) return [group]
    const sessions = group.sessions.filter((session) => [
      session.id,
      session.title,
      session.kind,
      session.status
    ].join(' ').toLocaleLowerCase().includes(needle))
    return sessions.length ? [{ ...group, sessions, health: aggregateSessionHealth(sessions) }] : []
  })
})

const allGroupsExpanded = computed(() =>
  visibleGroups.value.length > 0
    && visibleGroups.value.every((group) => !collapsedGroups.value.has(group.id))
)
const sessionDisplayLabels = computed<Record<string, string>>(() => {
  const totals = new Map<string, number>()
  const seen = new Map<string, number>()
  for (const session of props.sessions) {
    totals.set(session.title, (totals.get(session.title) || 0) + 1)
  }
  return Object.fromEntries(props.sessions.map((session) => {
    const index = (seen.get(session.title) || 0) + 1
    seen.set(session.title, index)
    return [session.id, (totals.get(session.title) || 0) > 1
      ? `${session.title} #${index}`
      : session.title]
  }))
})

function readManagerWidth(): number {
  const value = Number(localStorage.getItem(WIDTH_KEY) || 260)
  return clampWidth(Number.isFinite(value) ? value : 260)
}

function readCollapsedGroups(): Set<string> {
  try {
    const parsed = JSON.parse(localStorage.getItem(COLLAPSED_GROUPS_KEY) || '[]')
    return new Set(Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : [])
  } catch {
    return new Set()
  }
}

function clampWidth(value: number): number {
  return Math.max(200, Math.min(480, Math.round(value)))
}

function persistCollapsedGroups(groupsToSave: Set<string>): void {
  collapsedGroups.value = groupsToSave
  localStorage.setItem(COLLAPSED_GROUPS_KEY, JSON.stringify([...groupsToSave].sort()))
}

function groupExpanded(groupId: string): boolean {
  return Boolean(query.value.trim()) || !collapsedGroups.value.has(groupId)
}

function toggleGroup(groupId: string): void {
  const next = new Set(collapsedGroups.value)
  if (next.has(groupId)) next.delete(groupId)
  else next.add(groupId)
  persistCollapsedGroups(next)
}

function toggleAllGroups(): void {
  const next = new Set(collapsedGroups.value)
  if (allGroupsExpanded.value) {
    for (const group of visibleGroups.value) next.add(group.id)
  } else {
    for (const group of visibleGroups.value) next.delete(group.id)
  }
  persistCollapsedGroups(next)
}

function activateGroup(group: SessionDeviceGroup): void {
  const active = group.sessions.find((session) => session.id === props.activeSessionId)
    || group.sessions[0]
  if (active) emit('activate', active.id)
  if (group.device) emit('locateDevice', group.id)
}

function startSessionDrag(event: DragEvent, session: SessionSummary): void {
  if (!event.dataTransfer) return
  emit('activate', session.id)
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData(SESSION_DRAG_TYPE, session.id)
  event.dataTransfer.setData('text/plain', session.id)
}

function handleSessionKeydown(event: KeyboardEvent, session: SessionSummary): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    emit('activate', session.id)
    return
  }
  if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
  event.preventDefault()
  const rect = (event.currentTarget as HTMLElement | null)?.getBoundingClientRect()
  emit('sessionContext', new MouseEvent('contextmenu', {
    clientX: rect ? rect.left + 24 : 160,
    clientY: rect ? rect.bottom + 4 : 160
  }), session)
}

function handleDeviceKeydown(event: KeyboardEvent, group: SessionDeviceGroup): void {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    activateGroup(group)
    return
  }
  if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
  event.preventDefault()
  const rect = (event.currentTarget as HTMLElement | null)?.getBoundingClientRect()
  emit('deviceContext', new MouseEvent('contextmenu', {
    clientX: rect ? rect.left + 28 : 150,
    clientY: rect ? rect.bottom + 4 : 150
  }), group.id)
}

function setManagerWidth(value: number): void {
  managerWidth.value = clampWidth(value)
  localStorage.setItem(WIDTH_KEY, String(managerWidth.value))
}

function resizeManager(event: PointerEvent): void {
  const rect = manager.value?.getBoundingClientRect()
  if (!rect) return
  setManagerWidth(rect.right - event.clientX)
}

function stopResize(): void {
  window.removeEventListener('pointermove', resizeManager)
  window.removeEventListener('pointerup', stopResize)
}

function startResize(event: PointerEvent): void {
  event.preventDefault()
  resizeManager(event)
  window.addEventListener('pointermove', resizeManager)
  window.addEventListener('pointerup', stopResize, { once: true })
}

function handleResizeKeydown(event: KeyboardEvent): void {
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  setManagerWidth(managerWidth.value + (event.key === 'ArrowLeft' ? 10 : -10))
}

function kindLabel(kind: string): string {
  return kind === 'ssh' ? 'SSH'
    : kind === 'telnet' ? 'Telnet'
      : kind === 'serial' ? '串口'
        : kind === 'simulated' ? '模拟'
          : kind
}

function sessionAccessibleLabel(session: SessionSummary): string {
  return `${sessionDisplayLabels.value[session.id]}，${kindLabel(session.kind)}，${sessionStatusLabel(session.status)}`
}

function groupAccessibleLabel(group: SessionDeviceGroup): string {
  return `${group.label}，${group.sessions.length} 个终端，${sessionHealthLabel(group.health)}`
}

onBeforeUnmount(stopResize)
</script>

<template>
  <aside
    ref="manager"
    class="session-tabs session-manager"
    :class="{ collapsed }"
    :style="{ width: collapsed ? '42px' : managerWidth + 'px' }"
    :data-manager-width="managerWidth"
    :data-manager-collapsed="collapsed ? 'true' : 'false'"
    aria-label="会话管理器"
  >
    <button
      class="session-rail-toggle"
      type="button"
      :title="collapsed ? '展开右侧会话栏' : '折叠右侧会话栏'"
      :aria-label="collapsed ? '展开右侧会话栏' : '折叠右侧会话栏'"
      :aria-expanded="!collapsed"
      @click="emit('updateCollapsed', !collapsed)"
    >
      <ChevronLeft v-if="collapsed" :size="15" />
      <ChevronRight v-else :size="15" />
    </button>

    <template v-if="collapsed">
      <div class="session-manager-strip" role="tablist" aria-label="收起的终端会话">
        <div
          v-for="session in sessions"
          :key="session.id"
          class="session-tab session-manager-strip-tab"
          :class="{ active: session.id === activeSessionId }"
          :data-session-tab-id="session.id"
          :title="sessionAccessibleLabel(session)"
          draggable="true"
          @dragstart="startSessionDrag($event, session)"
          @contextmenu.prevent="emit('sessionContext', $event, session)"
        >
          <button
            class="session-tab-select"
            type="button"
            role="tab"
            :aria-label="sessionAccessibleLabel(session)"
            :aria-selected="session.id === activeSessionId"
            @click="emit('activate', session.id)"
            @keydown="handleSessionKeydown($event, session)"
          ><i :data-state="session.status" aria-hidden="true"></i></button>
        </div>
      </div>
    </template>

    <template v-else>
      <header class="session-manager-header">
        <span><MonitorDot :size="14" />会话管理器</span>
        <b>共 {{ sessions.length }}</b>
      </header>
      <div class="session-manager-search-row">
        <label>
          <Search :size="13" aria-hidden="true" />
          <input v-model="query" type="search" placeholder="搜索设备、会话" aria-label="搜索设备、会话" />
        </label>
        <button
          class="session-manager-expand-all"
          type="button"
          :title="allGroupsExpanded ? '全部收起' : '全部展开'"
          :aria-label="allGroupsExpanded ? '全部收起' : '全部展开'"
          @click="toggleAllGroups"
        ><ChevronsUpDown :size="14" /></button>
      </div>
      <div class="session-manager-tree" role="tree" aria-label="按设备分组的会话">
        <section v-for="group in visibleGroups" :key="group.id" class="session-device-group">
          <div
            class="session-device-group-header"
            role="treeitem"
            :aria-expanded="groupExpanded(group.id)"
            :aria-label="groupAccessibleLabel(group)"
            :title="groupAccessibleLabel(group)"
            :data-device-group-id="group.id"
            tabindex="0"
            @contextmenu.prevent="emit('deviceContext', $event, group.id)"
            @keydown="handleDeviceKeydown($event, group)"
          >
            <button
              class="session-device-disclosure"
              type="button"
              :aria-label="groupExpanded(group.id) ? `收起 ${group.label}` : `展开 ${group.label}`"
              @click.stop="toggleGroup(group.id)"
            >
              <ChevronDown v-if="groupExpanded(group.id)" :size="13" />
              <ChevronRight v-else :size="13" />
            </button>
            <button class="session-device-select" type="button" @click="activateGroup(group)">
              <span class="device-session-health" :data-state="group.health" aria-hidden="true">
                <MonitorDot :size="13" />
                <i></i>
              </span>
              <span>{{ group.label }}</span>
              <small>{{ group.id }}</small>
            </button>
            <span class="session-device-group-summary">
              <em class="device-session-health-label" :data-state="group.health">{{ sessionHealthShortLabel(group.health) }}</em>
              <b>{{ group.sessions.length }}</b>
            </span>
          </div>
          <div v-if="groupExpanded(group.id)" class="session-device-children" role="group">
            <div
              v-for="session in group.sessions"
              :key="session.id"
              class="session-tab session-manager-session"
              :class="{ active: session.id === activeSessionId }"
              :data-session-tab-id="session.id"
              :title="sessionAccessibleLabel(session)"
              role="treeitem"
              draggable="true"
              @dragstart="startSessionDrag($event, session)"
              @contextmenu.prevent="emit('sessionContext', $event, session)"
            >
              <button
                class="session-tab-select"
                type="button"
                role="tab"
                :aria-label="sessionAccessibleLabel(session)"
                :aria-selected="session.id === activeSessionId"
                @click="emit('activate', session.id)"
                @keydown="handleSessionKeydown($event, session)"
              >
                <i :data-state="session.status" aria-hidden="true"></i>
                <span>
                  <strong>{{ sessionDisplayLabels[session.id] }}</strong>
                  <small>{{ kindLabel(session.kind) }} · {{ sessionStatusLabel(session.status) }}</small>
                </span>
              </button>
              <button class="tab-close" type="button" aria-label="关闭会话" @click="emit('close', session.id)">
                <X :size="12" />
              </button>
            </div>
          </div>
        </section>
        <div v-if="!visibleGroups.length" class="session-manager-empty">
          <Search :size="17" />
          <strong>没有匹配结果</strong>
          <span>尝试设备名称、会话类型或设备 ID</span>
        </div>
      </div>
      <div
        class="session-manager-resize-handle"
        role="separator"
        aria-label="调整会话管理器宽度"
        aria-orientation="vertical"
        :aria-valuenow="managerWidth"
        aria-valuemin="200"
        aria-valuemax="480"
        tabindex="0"
        @pointerdown="startResize"
        @keydown="handleResizeKeydown"
      ></div>
    </template>
  </aside>
</template>
