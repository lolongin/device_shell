<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  Box,
  Cable,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleCheck,
  CircleHelp,
  Database,
  FileUp,
  FileSpreadsheet,
  FileArchive,
  FolderPlus,
  Globe2,
  Plug,
  KeyRound,
  LogIn,
  LogOut,
  MonitorDot,
  PanelLeftClose,
  Pencil,
  Pin,
  Plus,
  RefreshCw,
  Search,
  SearchX,
  ServerCog,
  Settings,
  Moon,
  Sun,
  Trash2,
  UserRound,
  Workflow,
  X
} from 'lucide-vue-next'
import ConnectionProfileDialog from './components/ConnectionProfileDialog.vue'
import ConnectionGroupDialog from './components/ConnectionGroupDialog.vue'
import DeviceImportDialog from './components/DeviceImportDialog.vue'
import CommandWorkspace from './components/CommandWorkspace.vue'
import CompactSelect from './components/CompactSelect.vue'
import HelpPanel from './components/HelpPanel.vue'
import SettingsPanel from './components/SettingsPanel.vue'
import SessionManager from './components/SessionManager.vue'
import TerminalSplitWorkspace from './components/TerminalSplitWorkspace.vue'
import { useWorkspaceStore } from './stores/workspace'
import {
  aggregateSessionHealth,
  sessionHealthLabel,
  sessionHealthShortLabel,
  sessionStatusLabel
} from './sessionStatus'
import {
  announceContextMenuOpen,
  clampContextMenuElement,
  clampContextMenuPoint,
  contextMenuTrigger,
  focusFirstContextMenuItem,
  handleContextMenuKeydown,
  restoreContextMenuFocus,
  subscribeContextMenuOpen
} from './contextMenu'
import type {
  ConnectionProfilePayload,
  ConnectionProfileSecrets,
  ConnectionProfileSummary,
  DeviceSummary,
  ProfileType,
  SessionKind,
  SessionSummary,
  DeviceSourceId
} from './types'

const AutomationWorkspace = defineAsyncComponent(() => import('./components/AutomationWorkspace.vue'))
const TransferWorkspace = defineAsyncComponent(() => import('./components/TransferWorkspace.vue'))
const UpgradeWorkspace = defineAsyncComponent(() => import('./components/UpgradeWorkspace.vue'))
const PackageBuildWorkspace = defineAsyncComponent(() => import('./components/PackageBuildWorkspace.vue'))

const workspace = useWorkspaceStore()
const deviceDomainFilterOptions = computed(() => [
  { value: '', label: '全部领域' },
  ...workspace.deviceDomains.map((domain) => ({ value: domain, label: domain }))
])
const deviceStatusFilterOptions = computed(() => [
  { value: '', label: '全部状态' },
  ...workspace.deviceStatuses.map((status) => ({ value: status, label: status }))
])
const activeDeviceSource = computed(() =>
  workspace.deviceSourceStatus.sources.find(
    (source) => source.id === workspace.deviceSourceStatus.active_source
  ) || null
)
const defaultDeviceSource = computed(() =>
  workspace.deviceSourceStatus.sources.find(
    (source) => source.id === workspace.deviceSourceStatus.default_source
  ) || null
)
const importDeviceSource = computed(() =>
  workspace.deviceSourceStatus.sources.find((source) => source.supports_import) || null
)
const backendFailure = ref('')
const workspaceRecoveryBusy = ref(false)
const activeSection = ref<'devices' | 'temporary' | 'server'>('devices')
type ThemeMode = 'dark' | 'light'
type SessionTabLayout = 'top' | 'side'
type SplitDirection = 'left' | 'right' | 'top' | 'bottom'
type SessionContextSource = 'tab' | 'manager' | 'terminal'
type DeviceProtocolKind = 'ssh' | 'telnet' | 'serial'
type ApplicationMenuKey = 'file' | 'edit' | 'view' | 'window'
const THEME_KEY = 'odyterm.desktop-v2.theme'
const ALWAYS_ON_TOP_KEY = 'odyterm.desktop-v2.always-on-top'
const SESSION_TAB_LAYOUT_KEY = 'odyterm.desktop-v2.session-tab-layout'
const SESSION_TAB_RAIL_COLLAPSED_KEY = 'odyterm.desktop-v2.session-tab-rail-collapsed'
const NAVIGATOR_DETAIL_COLLAPSED_KEY = 'odyterm.desktop-v2.navigator-detail-collapsed'
const NAVIGATOR_VISIBLE_KEY = 'odyterm.desktop-v2.navigator-visible'
const NAVIGATOR_WIDTH_KEY = 'odyterm.desktop-v2.navigator-width'
const PROFILE_GROUP_COLLAPSE_KEY = 'odyterm.desktop-v2.profile-collapsed-groups'
const NAVIGATOR_MIN_WIDTH = 400
const NAVIGATOR_MAX_WIDTH = 760
const ACTIVITY_RAIL_WIDTH = 52
const MAX_WARM_DEVICE_WORKSPACES = 3
const DEVICE_ROW_HEIGHT = 46
const DEVICE_LIST_HEADER_HEIGHT = 30
const DEVICE_VIRTUALIZATION_THRESHOLD = 120
const DEVICE_VIRTUAL_OVERSCAN = 6
const windowWidth = ref(window.innerWidth)
const themeMode = ref<ThemeMode>(localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark')
const alwaysOnTop = ref(localStorage.getItem(ALWAYS_ON_TOP_KEY) === '1')
const sessionTabLayout = ref<SessionTabLayout>(
  localStorage.getItem(SESSION_TAB_LAYOUT_KEY) === 'side' ? 'side' : 'top'
)
const sessionTabRailCollapsed = ref(
  localStorage.getItem(SESSION_TAB_RAIL_COLLAPSED_KEY) === '1'
)
const navigatorDetailCollapsed = ref(
  localStorage.getItem(NAVIGATOR_DETAIL_COLLAPSED_KEY) === '1'
)
const navigatorVisible = ref(localStorage.getItem(NAVIGATOR_VISIBLE_KEY) !== '0')
const navigatorWidth = ref(readStoredNavigatorWidth())
const navigatorResizing = ref(false)
const operationPanelOpen = computed(() =>
  workspace.automationPanelOpen || workspace.transferPanelOpen || workspace.upgradePanelOpen || workspace.packageBuildPanelOpen
)
const showSessionSidebar = computed(() =>
  workspace.sessions.length > 0 && sessionTabLayout.value === 'side'
)
const settingsPanelOpen = ref(false)
const helpPanelOpen = ref(false)
const selectedProfileId = ref('')
const editingProfile = ref<ConnectionProfileSummary | null>(null)
const dialogType = ref<ProfileType | ''>('')
const savingProfile = ref(false)
const groupDialogOpen = ref(false)
const savingGroup = ref(false)
const settingsReturnFocus = ref<HTMLElement | null>(null)
const helpReturnFocus = ref<HTMLElement | null>(null)
const profileDialogReturnFocus = ref<HTMLElement | null>(null)
const groupDialogReturnFocus = ref<HTMLElement | null>(null)
const deviceImportReturnFocus = ref<HTMLElement | null>(null)
let noticeTimer: ReturnType<typeof setTimeout> | null = null
const collapsedProfileGroups = ref(new Set<string>(storedCollapsedProfileGroups()))
const deviceContextMenu = ref<{ device: DeviceSummary; x: number; y: number } | null>(null)
const deviceContextMenuElement = ref<HTMLElement | null>(null)
const deviceContextMenuReturnFocus = ref<HTMLElement | null>(null)
const sessionContextMenu = ref<{
  session: SessionSummary
  source: SessionContextSource
  x: number
  y: number
} | null>(null)
const sessionContextMenuElement = ref<HTMLElement | null>(null)
const sessionContextMenuReturnFocus = ref<HTMLElement | null>(null)
const sessionManagerDeviceContextMenu = ref<{ deviceId: string; x: number; y: number } | null>(null)
const sessionManagerDeviceContextMenuElement = ref<HTMLElement | null>(null)
const sessionManagerDeviceContextMenuReturnFocus = ref<HTMLElement | null>(null)
type TerminalSplitWorkspaceInstance = InstanceType<typeof TerminalSplitWorkspace>
const terminalSplitWorkspaces = new Map<string, TerminalSplitWorkspaceInstance>()
const terminalSplitStates = ref<Record<string, boolean>>({})
const terminalSplitActive = ref(false)
const profileContextMenu = ref<{ profile: ConnectionProfileSummary; x: number; y: number } | null>(null)
const profileContextMenuElement = ref<HTMLElement | null>(null)
const profileContextMenuReturnFocus = ref<HTMLElement | null>(null)
const lastActiveSessionByDevice = ref<Record<string, string>>({})
const warmDeviceWorkspaceIds = ref<string[]>([])
const deviceListElement = ref<HTMLElement | null>(null)
const deviceListScrollTop = ref(0)
const deviceListViewportHeight = ref(0)
let deviceListResizeObserver: ResizeObserver | null = null
let unsubscribeBackendExit: (() => void) | null = null
let unsubscribeBackendRecovered: (() => void) | null = null
let stopApplicationEvents: (() => void) | null = null
let unsubscribeContextMenuOpen: (() => void) | null = null

function defaultNavigatorWidth(width = window.innerWidth): number {
  if (width <= 1150) return 400
  if (width <= 1280) return 420
  if (width <= 1680) return 460
  return 500
}

function readStoredNavigatorWidth(): number {
  const stored = Number(localStorage.getItem(NAVIGATOR_WIDTH_KEY))
  return Number.isFinite(stored) && stored > 0 ? stored : defaultNavigatorWidth()
}

const navigatorMaxWidth = computed(() => {
  const centerMinimum = windowWidth.value <= 1150
    ? 420
    : windowWidth.value <= 1280
      ? 440
      : windowWidth.value <= 1680
        ? 460
        : 520
  const sideManagerReserve = showSessionSidebar.value
    ? (sessionTabRailCollapsed.value ? 42 : 260)
    : 0
  return Math.max(
    NAVIGATOR_MIN_WIDTH,
    Math.min(
      NAVIGATOR_MAX_WIDTH,
      windowWidth.value - ACTIVITY_RAIL_WIDTH - centerMinimum - sideManagerReserve
    )
  )
})

const effectiveNavigatorWidth = computed(() => Math.max(
  NAVIGATOR_MIN_WIDTH,
  Math.min(navigatorMaxWidth.value, navigatorWidth.value)
))

const recommendedDeviceSessionKind = computed(() => recommendedSessionKind(workspace.selectedDevice))
const availableDeviceProtocolLabels = computed(() => {
  const device = workspace.selectedDevice
  if (!device) return []
  if (device.is_simulated) return ['模拟终端']
  return [
    device.can_connect_ssh ? 'SSH' : '',
    device.can_connect_telnet ? 'Telnet' : '',
    device.can_connect_serial ? '串口' : ''
  ].filter(Boolean)
})
const emptyWorkspaceActionLabel = computed(() => {
  const device = workspace.selectedDevice
  const kind = recommendedDeviceSessionKind.value
  if (!device) return '请先选择设备'
  if (kind === 'simulated') return '打开模拟终端'
  if (!kind) return '暂无可用连接'
  return `打开 ${device.name} · ${kind === 'ssh' ? 'SSH' : kind === 'telnet' ? 'Telnet' : '串口'}`
})

const appShellStyle = computed<Record<string, string>>(() => ({
  '--navigator-width': `${effectiveNavigatorWidth.value}px`
}))

const noticeRequiresAttention = computed(() => /(?:失败|错误|没有|请先|未连接|不可用|已取消)/u.test(
  workspace.notice
))

function clearWorkspaceNotice(): void {
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = null
  workspace.notice = ''
}

async function retryWorkspaceRecovery(): Promise<void> {
  if (workspaceRecoveryBusy.value) return
  if (!window.desktopApi) {
    window.location.reload()
    return
  }
  workspaceRecoveryBusy.value = true
  stopApplicationEvents?.()
  stopApplicationEvents = null
  await workspace.initialize()
  if (!workspace.error) {
    backendFailure.value = ''
    workspace.notice = '工作区已恢复，设备与会话数据已重新载入。'
    stopApplicationEvents = workspace.startApplicationEvents()
  }
  workspaceRecoveryBusy.value = false
}

watch(() => workspace.notice, (notice) => {
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = null
  if (!notice || noticeRequiresAttention.value) return
  noticeTimer = setTimeout(() => {
    if (workspace.notice === notice) workspace.notice = ''
  }, 6000)
})

function setNavigatorWidth(value: number, persist = true): void {
  navigatorWidth.value = Math.round(Math.max(
    NAVIGATOR_MIN_WIDTH,
    Math.min(navigatorMaxWidth.value, value)
  ))
  if (persist) localStorage.setItem(NAVIGATOR_WIDTH_KEY, String(navigatorWidth.value))
}

function resizeNavigatorFromPointer(event: PointerEvent): void {
  setNavigatorWidth(event.clientX - ACTIVITY_RAIL_WIDTH)
}

function stopNavigatorResize(): void {
  if (!navigatorResizing.value) return
  navigatorResizing.value = false
  window.removeEventListener('pointermove', resizeNavigatorFromPointer)
  window.removeEventListener('pointerup', stopNavigatorResize)
  window.removeEventListener('pointercancel', stopNavigatorResize)
  document.body.style.cursor = ''
  document.body.style.userSelect = ''
}

function startNavigatorResize(event: PointerEvent): void {
  event.preventDefault()
  navigatorResizing.value = true
  resizeNavigatorFromPointer(event)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  window.addEventListener('pointermove', resizeNavigatorFromPointer)
  window.addEventListener('pointerup', stopNavigatorResize)
  window.addEventListener('pointercancel', stopNavigatorResize)
}

function handleNavigatorResizeKeydown(event: KeyboardEvent): void {
  if (event.key === 'Home') {
    event.preventDefault()
    setNavigatorWidth(defaultNavigatorWidth(windowWidth.value))
    return
  }
  if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
  event.preventDefault()
  const step = event.shiftKey ? 40 : 10
  setNavigatorWidth(effectiveNavigatorWidth.value + (event.key === 'ArrowRight' ? step : -step))
}

function resetNavigatorWidth(): void {
  setNavigatorWidth(defaultNavigatorWidth(windowWidth.value))
}

function setNavigatorVisible(visible: boolean): void {
  navigatorVisible.value = visible
  localStorage.setItem(NAVIGATOR_VISIBLE_KEY, visible ? '1' : '0')
  if (!visible) stopNavigatorResize()
}

function handleWindowResize(): void {
  windowWidth.value = window.innerWidth
  if (navigatorWidth.value > navigatorMaxWidth.value) setNavigatorWidth(navigatorMaxWidth.value)
  closeAppContextMenus()
}

const visibleProfiles = computed(() => {
  const needle = workspace.profileQuery.trim().toLocaleLowerCase()
  return workspace.profiles.filter((profile) => {
    if (profile.profile_type !== activeSection.value) return false
    return !needle || [
      profile.name,
      profile.group,
      profile.ssh.host,
      profile.telnet.host,
      profile.serial.host,
      profile.notes
    ].join(' ').toLocaleLowerCase().includes(needle)
  })
})
const groupedServerProfiles = computed(() => {
  const groups = new Map<string, ConnectionProfileSummary[]>()
  if (!workspace.profileQuery.trim()) {
    for (const group of workspace.profileGroups) groups.set(group, [])
  }
  for (const profile of visibleProfiles.value) {
    const group = profile.group || '未分组'
    groups.set(group, [...(groups.get(group) || []), profile])
  }
  return [...groups.entries()]
    .sort(([left], [right]) => left === '未分组' ? 1 : right === '未分组' ? -1 : left.localeCompare(right))
    .map(([name, profiles]) => ({ name, profiles }))
})
const visibleProfileCredentialCount = computed(() =>
  visibleProfiles.value.filter((profile) =>
    profile[profile.preferred_protocol].has_password
  ).length
)
const visibleProfileGroupCount = computed(() =>
  activeSection.value === 'server' ? groupedServerProfiles.value.length : 0
)
const selectedProfile = computed(
  () => workspace.profiles.find((profile) => profile.id === selectedProfileId.value) || null
)
const deviceById = computed(() => new Map(
  workspace.devices.map((device) => [device.id, device])
))
const sessionsByDevice = computed(() => {
  const groups = new Map<string, SessionSummary[]>()
  for (const session of workspace.sessions) {
    const sessions = groups.get(session.device_id)
    if (sessions) sessions.push(session)
    else groups.set(session.device_id, [session])
  }
  return groups
})
const liveWorkspaceTitle = computed(() => {
  const session = workspace.activeSession
  if (session) {
    return deviceById.value.get(session.device_id)?.name
      || session.title
      || session.device_id
  }
  return activeSection.value === 'devices'
    ? workspace.selectedDevice?.name || '选择一个设备'
    : selectedProfile.value?.name || '选择一个连接配置'
})
const sessionDeviceGroups = computed(() => {
  return [...sessionsByDevice.value.entries()].map(([deviceId, sessions]) => {
    const device = deviceById.value.get(deviceId) || null
    return {
      id: deviceId,
      label: device?.name || sessions[0]?.title.split(' · ').slice(1).join(' · ') || deviceId,
      health: aggregateSessionHealth(sessions),
      sessions
    }
  })
})
const activeSessionDeviceId = computed(() => workspace.activeSession?.device_id || '')
const warmSessionDeviceGroups = computed(() => {
  const warmIds = new Set([...warmDeviceWorkspaceIds.value, activeSessionDeviceId.value])
  return sessionDeviceGroups.value.filter((group) => warmIds.has(group.id))
})
const activeDeviceSessions = computed(() =>
  sessionsByDevice.value.get(activeSessionDeviceId.value) || []
)
function deviceProtocolActions(deviceId: string): Array<{
  kind: DeviceProtocolKind
  label: string
  opened: boolean
}> {
  const device = deviceById.value.get(deviceId)
  if (!device || device.is_simulated) return []
  const deviceSessions = sessionsByDevice.value.get(deviceId) || []
  return [
    { kind: 'ssh' as const, label: 'SSH', available: device.can_connect_ssh },
    { kind: 'telnet' as const, label: 'Telnet', available: device.can_connect_telnet },
    { kind: 'serial' as const, label: '串口', available: device.can_connect_serial }
  ].filter((action) => action.available).map((action) => ({
    ...action,
    opened: deviceSessions.some((session) => session.kind === action.kind)
  }))
}
const activeProtocolLabels = computed<Record<string, string>>(() => {
  const totals = new Map<string, number>()
  const seen = new Map<string, number>()
  for (const session of activeDeviceSessions.value) {
    const label = sessionKindLabel(session.kind)
    totals.set(label, (totals.get(label) || 0) + 1)
  }
  return Object.fromEntries(activeDeviceSessions.value.map((session) => {
    const label = sessionKindLabel(session.kind)
    const index = (seen.get(label) || 0) + 1
    seen.set(label, index)
    return [session.id, (totals.get(label) || 0) > 1 ? `${label} #${index}` : label]
  }))
})

function setTerminalSplitWorkspace(deviceId: string, instance: unknown): void {
  if (instance) {
    terminalSplitWorkspaces.set(deviceId, instance as TerminalSplitWorkspaceInstance)
  } else {
    terminalSplitWorkspaces.delete(deviceId)
    const nextStates = { ...terminalSplitStates.value }
    delete nextStates[deviceId]
    terminalSplitStates.value = nextStates
  }
}

function touchWarmDeviceWorkspace(deviceId: string): void {
  if (!deviceId) return
  const currentIds = new Set(sessionDeviceGroups.value.map((group) => group.id))
  warmDeviceWorkspaceIds.value = [
    deviceId,
    ...warmDeviceWorkspaceIds.value.filter((id) => id !== deviceId && currentIds.has(id))
  ].slice(0, MAX_WARM_DEVICE_WORKSPACES)
}

function activeSessionIdForDevice(deviceId: string, sessions: SessionSummary[]): string {
  if (deviceId === activeSessionDeviceId.value) return workspace.activeSessionId
  const remembered = lastActiveSessionByDevice.value[deviceId]
  return sessions.some((session) => session.id === remembered)
    ? remembered
    : sessions[0]?.id || ''
}

function updateTerminalSplitState(deviceId: string, active: boolean): void {
  terminalSplitStates.value = { ...terminalSplitStates.value, [deviceId]: active }
  if (deviceId === activeSessionDeviceId.value) terminalSplitActive.value = active
}

watch(
  activeSessionDeviceId,
  (deviceId) => {
    touchWarmDeviceWorkspace(deviceId)
    terminalSplitActive.value = Boolean(deviceId && terminalSplitStates.value[deviceId])
  },
  { immediate: true }
)

function sessionKindLabel(kind: string): string {
  return ({ ssh: 'SSH', telnet: 'Telnet', serial: '串口', simulated: '模拟终端' } as Record<string, string>)[kind]
    || kind.toLocaleUpperCase()
}

function activateSession(sessionId: string): void {
  if (!workspace.sessions.some((session) => session.id === sessionId)) return
  workspace.activeSessionId = sessionId
}

function activateSessionDevice(deviceId: string): void {
  const sessions = sessionsByDevice.value.get(deviceId) || []
  if (!sessions.length) return
  const remembered = lastActiveSessionByDevice.value[deviceId]
  activateSession(sessions.some((session) => session.id === remembered) ? remembered : sessions[0].id)
}

function closeSessionDevice(deviceId: string): void {
  void workspace.closeDeviceSessionGroups(deviceId, 'current')
}

watch(
  () => workspace.activeSession,
  (session) => {
    if (!session) return
    lastActiveSessionByDevice.value = {
      ...lastActiveSessionByDevice.value,
      [session.device_id]: session.id
    }
  },
  { immediate: true }
)

function storedCollapsedProfileGroups(): string[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(PROFILE_GROUP_COLLAPSE_KEY) || '[]')
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
      : []
  } catch {
    return []
  }
}

function profileGroupCollapsed(name: string): boolean {
  return !workspace.profileQuery.trim() && collapsedProfileGroups.value.has(name)
}

function saveCollapsedProfileGroups(next: Set<string>): void {
  collapsedProfileGroups.value = next
  localStorage.setItem(PROFILE_GROUP_COLLAPSE_KEY, JSON.stringify([...next].sort()))
}

function toggleProfileGroup(name: string): void {
  const next = new Set(collapsedProfileGroups.value)
  if (next.has(name)) next.delete(name)
  else next.add(name)
  saveCollapsedProfileGroups(next)
}

function expandProfileGroup(name: string): void {
  if (!name || !collapsedProfileGroups.value.has(name)) return
  const next = new Set(collapsedProfileGroups.value)
  next.delete(name)
  saveCollapsedProfileGroups(next)
}

function selectDevice(deviceRowId: string): void {
  workspace.selectedDeviceRowId = deviceRowId
  void nextTick(() => {
    const renderedRow = document.querySelector(`[data-device-row-id="${CSS.escape(deviceRowId)}"]`)
    if (renderedRow) {
      renderedRow.scrollIntoView({ block: 'nearest' })
      return
    }
    const index = workspace.filteredDevices.findIndex((device) => device.row_id === deviceRowId)
    scrollDeviceIndexIntoView(index)
  })
}

const virtualizedDeviceList = computed(() =>
  workspace.filteredDevices.length > DEVICE_VIRTUALIZATION_THRESHOLD
)
const virtualDeviceStart = computed(() => {
  if (!virtualizedDeviceList.value) return 0
  return Math.max(
    0,
    Math.floor(deviceListScrollTop.value / DEVICE_ROW_HEIGHT) - DEVICE_VIRTUAL_OVERSCAN
  )
})
const virtualDeviceEnd = computed(() => {
  if (!virtualizedDeviceList.value) return workspace.filteredDevices.length
  const visibleHeight = Math.max(
    DEVICE_ROW_HEIGHT,
    deviceListViewportHeight.value - DEVICE_LIST_HEADER_HEIGHT
  )
  return Math.min(
    workspace.filteredDevices.length,
    Math.ceil((deviceListScrollTop.value + visibleHeight) / DEVICE_ROW_HEIGHT)
      + DEVICE_VIRTUAL_OVERSCAN
  )
})
const renderedDevices = computed(() =>
  workspace.filteredDevices.slice(virtualDeviceStart.value, virtualDeviceEnd.value)
)
const virtualDeviceTopHeight = computed(() =>
  virtualizedDeviceList.value ? virtualDeviceStart.value * DEVICE_ROW_HEIGHT : 0
)
const virtualDeviceBottomHeight = computed(() =>
  virtualizedDeviceList.value
    ? Math.max(0, (workspace.filteredDevices.length - virtualDeviceEnd.value) * DEVICE_ROW_HEIGHT)
    : 0
)

function handleDeviceListScroll(event: Event): void {
  deviceListScrollTop.value = (event.currentTarget as HTMLElement).scrollTop
}

function scrollDeviceIndexIntoView(index: number): void {
  const list = deviceListElement.value
  if (!list || index < 0) return
  const rowTop = DEVICE_LIST_HEADER_HEIGHT + index * DEVICE_ROW_HEIGHT
  const rowBottom = rowTop + DEVICE_ROW_HEIGHT
  const visibleTop = list.scrollTop + DEVICE_LIST_HEADER_HEIGHT
  const visibleBottom = list.scrollTop + list.clientHeight
  if (rowTop < visibleTop) list.scrollTop = Math.max(0, rowTop - DEVICE_LIST_HEADER_HEIGHT)
  else if (rowBottom > visibleBottom) list.scrollTop = rowBottom - list.clientHeight
  deviceListScrollTop.value = list.scrollTop
}

watch(deviceListElement, (element) => {
  deviceListResizeObserver?.disconnect()
  deviceListResizeObserver = null
  if (!element) return
  const updateViewport = (): void => {
    deviceListViewportHeight.value = element.clientHeight
    deviceListScrollTop.value = element.scrollTop
  }
  updateViewport()
  deviceListResizeObserver = new ResizeObserver(updateViewport)
  deviceListResizeObserver.observe(element)
})

watch(
  () => workspace.filteredDevices,
  () => {
    const list = deviceListElement.value
    if (list) list.scrollTop = 0
    deviceListScrollTop.value = 0
  }
)

function selectDeviceByDeviceId(deviceId: string): boolean {
  const device = (workspace.selectedDevice?.id === deviceId ? workspace.selectedDevice : null)
    || workspace.filteredDevices.find((candidate) => candidate.id === deviceId)
    || deviceById.value.get(deviceId)
  if (!device) return false
  selectDevice(device.row_id)
  return true
}

function moveDeviceSelection(delta: number): void {
  const devices = workspace.filteredDevices
  if (!devices.length) return
  const currentIndex = devices.findIndex((device) => device.row_id === workspace.selectedDeviceRowId)
  const nextIndex = Math.min(
    devices.length - 1,
    Math.max(0, (currentIndex >= 0 ? currentIndex : 0) + delta)
  )
  selectDevice(devices[nextIndex].row_id)
}

function handleDeviceListKeydown(event: KeyboardEvent): void {
  if (activeSection.value !== 'devices') return
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    moveDeviceSelection(1)
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    moveDeviceSelection(-1)
  } else if (event.key === 'Home') {
    event.preventDefault()
    const first = workspace.filteredDevices[0]
    if (first) selectDevice(first.row_id)
  } else if (event.key === 'End') {
    event.preventDefault()
    const last = workspace.filteredDevices[workspace.filteredDevices.length - 1]
    if (last) selectDevice(last.row_id)
  } else if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    const device = workspace.selectedDevice
    if (!device) return
    openRecommendedDeviceSession(device)
  }
}

function recommendedSessionKind(device: DeviceSummary | null): SessionKind | '' {
  if (!device) return ''
  if (device.is_simulated) return 'simulated'
  if (device.can_connect_ssh) return 'ssh'
  if (device.can_connect_telnet) return 'telnet'
  if (device.can_connect_serial) return 'serial'
  return ''
}

function openRecommendedDeviceSession(device = workspace.selectedDevice): void {
  const kind = recommendedSessionKind(device)
  if (!device || !kind) return
  void workspace.openSessionForDevice(device, kind)
}

function deviceRowCopyText(device: DeviceSummary): string {
  return [
    device.board_id || device.id,
    device.name,
    device.board_type || device.device_type || '—',
    device.cpu || '—',
    device.slot || device.rack || '—',
    device.status_text || device.status || '—'
  ].join('\t')
}

function deviceConnectionCopyText(device: DeviceSummary): string {
  return [
    `设备: ${device.name}`,
    `Telnet: ${device.telnet_endpoint || '—'}`,
    `串口: ${device.serial_display || device.serial_endpoint || '—'}`,
    `SSH: ${device.ssh_endpoint || '—'}`
  ].join('\n')
}

function endpointHost(endpoint: string | null | undefined): string {
  if (!endpoint) return ''
  if (endpoint.startsWith('[')) {
    const end = endpoint.indexOf(']')
    return end > 0 ? endpoint.slice(1, end) : endpoint
  }
  const portSeparator = endpoint.lastIndexOf(':')
  return portSeparator > 0 ? endpoint.slice(0, portSeparator) : endpoint
}

function copyableSerialText(device: DeviceSummary): string {
  const endpoint = device.serial_endpoint || device.serial_display || ''
  return device.can_connect_serial
    ? endpointHost(endpoint)
    : ''
}

async function copyDeviceText(text: string, message: string): Promise<void> {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    workspace.notice = message
    workspace.error = ''
  } catch (cause) {
    workspace.error = cause instanceof Error ? cause.message : String(cause)
  } finally {
    closeDeviceContextMenu()
  }
}

function openDeviceContextMenu(event: MouseEvent, device: DeviceSummary): void {
  announceContextMenuOpen()
  selectDevice(device.row_id)
  deviceContextMenuReturnFocus.value = contextMenuTrigger(event)
  deviceContextMenu.value = { device, ...clampContextMenuPoint(event.clientX, event.clientY) }
}

function openDeviceInspectorContextMenu(event: MouseEvent, device: DeviceSummary): void {
  announceContextMenuOpen()
  selectDevice(device.row_id)
  deviceContextMenuReturnFocus.value = contextMenuTrigger(event)
  deviceContextMenu.value = { device, ...clampContextMenuPoint(event.clientX, event.clientY) }
}

function closeDeviceContextMenu(): void {
  deviceContextMenu.value = null
}

function closeSessionContextMenu(): void {
  sessionContextMenu.value = null
}

function closeSessionManagerDeviceContextMenu(): void {
  sessionManagerDeviceContextMenu.value = null
}

function closeProfileContextMenu(): void {
  profileContextMenu.value = null
}

function closeDeviceContextMenuAndRestoreFocus(): void {
  closeDeviceContextMenu()
  restoreContextMenuFocus(deviceContextMenuReturnFocus.value)
}

function closeSessionContextMenuAndRestoreFocus(): void {
  closeSessionContextMenu()
  restoreContextMenuFocus(sessionContextMenuReturnFocus.value)
}

function closeSessionManagerDeviceContextMenuAndRestoreFocus(): void {
  closeSessionManagerDeviceContextMenu()
  restoreContextMenuFocus(sessionManagerDeviceContextMenuReturnFocus.value)
}

function closeProfileContextMenuAndRestoreFocus(): void {
  closeProfileContextMenu()
  restoreContextMenuFocus(profileContextMenuReturnFocus.value)
}

function closeAppContextMenus(): void {
  closeDeviceContextMenu()
  closeSessionContextMenu()
  closeSessionManagerDeviceContextMenu()
  closeProfileContextMenu()
}

function showApplicationMenu(key: ApplicationMenuKey, event: MouseEvent): void {
  const button = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  if (!button) return
  const { left, bottom } = button.getBoundingClientRect()
  void window.desktopApi?.showApplicationMenu(key, Math.round(left), Math.round(bottom)).catch(() => {
    // The rest of the workspace stays usable if the native menu cannot be opened.
  })
}

watch(deviceContextMenu, async (menu) => {
  if (!menu) return
  await nextTick()
  if (deviceContextMenu.value !== menu) return
  const point = clampContextMenuElement(deviceContextMenuElement.value, menu.x, menu.y)
  if (point.x !== menu.x || point.y !== menu.y) deviceContextMenu.value = { ...menu, ...point }
  focusFirstContextMenuItem(deviceContextMenuElement.value)
})

watch(sessionContextMenu, async (menu) => {
  if (!menu) return
  await nextTick()
  if (sessionContextMenu.value !== menu) return
  const point = clampContextMenuElement(sessionContextMenuElement.value, menu.x, menu.y)
  if (point.x !== menu.x || point.y !== menu.y) sessionContextMenu.value = { ...menu, ...point }
  focusFirstContextMenuItem(sessionContextMenuElement.value)
})

watch(sessionManagerDeviceContextMenu, async (menu) => {
  if (!menu) return
  await nextTick()
  if (sessionManagerDeviceContextMenu.value !== menu) return
  const point = clampContextMenuElement(sessionManagerDeviceContextMenuElement.value, menu.x, menu.y)
  if (point.x !== menu.x || point.y !== menu.y) {
    sessionManagerDeviceContextMenu.value = { ...menu, ...point }
  }
  focusFirstContextMenuItem(sessionManagerDeviceContextMenuElement.value)
})

watch(profileContextMenu, async (menu) => {
  if (!menu) return
  await nextTick()
  if (profileContextMenu.value !== menu) return
  const point = clampContextMenuElement(profileContextMenuElement.value, menu.x, menu.y)
  if (point.x !== menu.x || point.y !== menu.y) profileContextMenu.value = { ...menu, ...point }
  focusFirstContextMenuItem(profileContextMenuElement.value)
})

function handleDeviceContextKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    closeAppContextMenus()
    return
  }
  if (
    activeSection.value === 'devices'
    && workspace.selectedDevice
    && (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10'))
  ) {
    event.preventDefault()
    announceContextMenuOpen()
    const target = event.currentTarget as HTMLElement | null
    const selectedRow = document.querySelector<HTMLElement>(
      `[data-device-row-id="${CSS.escape(workspace.selectedDevice.row_id)}"]`
    )
    const rect = (selectedRow || target)?.getBoundingClientRect()
    deviceContextMenuReturnFocus.value = selectedRow || target
    deviceContextMenu.value = {
      device: workspace.selectedDevice,
      x: rect ? rect.left + 28 : 96,
      y: rect ? rect.top + 28 : 96
    }
  }
}

function handleDeviceTableKeydown(event: KeyboardEvent): void {
  handleDeviceContextKeydown(event)
  if (!event.defaultPrevented) handleDeviceListKeydown(event)
}

function handleDeviceInspectorKeydown(event: KeyboardEvent, device: DeviceSummary): void {
  if (event.key === 'Escape') {
    closeDeviceContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    event.preventDefault()
    announceContextMenuOpen()
    const rect = (event.currentTarget as HTMLElement | null)?.getBoundingClientRect()
    deviceContextMenuReturnFocus.value = event.currentTarget as HTMLElement | null
    deviceContextMenu.value = {
      device,
      x: rect ? rect.left + 28 : 160,
      y: rect ? rect.top + 28 : 160
    }
  }
}

function visibleDeviceFieldValue(value: string | null | undefined, fallback = '—'): string {
  return value && value.trim() ? value : fallback
}

function dynamicDeviceFieldValue(device: DeviceSummary, key: string): string {
  const value = device.attributes?.[key] ?? device.extensions?.[key]
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function copyDeviceInspectorField(label: string, value: string): void {
  if (!value || value === '—') return
  void copyDeviceText(value, `已复制${label}: ${value}`)
}

function openDeviceContextRecommendedSession(): void {
  const device = deviceContextMenu.value?.device
  if (!device) return
  selectDevice(device.row_id)
  openRecommendedDeviceSession(device)
  closeAppContextMenus()
}

function openDeviceContextSession(kind: 'ssh' | 'telnet' | 'serial'): void {
  const device = deviceContextMenu.value?.device
  if (!device) return
  selectDevice(device.row_id)
  void workspace.openSessionForDevice(device, kind)
  closeAppContextMenus()
}

function openDeviceContextSimulatedSession(): void {
  void workspace.openSimulatedSession()
  closeAppContextMenus()
}

function confirmDevicePowerOff(device: DeviceSummary): boolean {
  return window.confirm(`确定让设备“${device.name}”掉电吗？当前终端和正在运行的任务会立即中断。`)
}

function runDeviceContextAction(action: 'claim' | 'release' | 'power_off'): void {
  const device = deviceContextMenu.value?.device
  if (!device) return
  selectDevice(device.row_id)
  if (action === 'power_off' && !confirmDevicePowerOff(device)) return
  void workspace.runDeviceAction(action)
  closeAppContextMenus()
}

function sessionDevice(session: SessionSummary | null): DeviceSummary | null {
  if (!session) return null
  return deviceById.value.get(session.device_id) || null
}

function openSessionContextMenu(
  event: MouseEvent,
  session: SessionSummary,
  source: SessionContextSource = 'tab'
): void {
  announceContextMenuOpen()
  workspace.activeSessionId = session.id
  sessionContextMenuReturnFocus.value = contextMenuTrigger(event)
  sessionContextMenu.value = {
    session,
    source,
    ...clampContextMenuPoint(event.clientX, event.clientY)
  }
}

function openSessionManagerSessionContextMenu(event: MouseEvent, session: SessionSummary): void {
  openSessionContextMenu(event, session, 'manager')
}

function openSessionManagerDeviceContextMenu(event: MouseEvent, deviceId: string): void {
  announceContextMenuOpen()
  sessionManagerDeviceContextMenuReturnFocus.value = contextMenuTrigger(event)
  sessionManagerDeviceContextMenu.value = {
    deviceId,
    ...clampContextMenuPoint(event.clientX, event.clientY)
  }
}

function openDeviceSessionTabContextMenu(event: MouseEvent, deviceId: string): void {
  activateSessionDevice(deviceId)
  openSessionManagerDeviceContextMenu(event, deviceId)
}

function handleDeviceSessionTabKeydown(event: KeyboardEvent, deviceId: string): void {
  if (event.key === 'Escape') {
    closeSessionManagerDeviceContextMenu()
    return
  }
  if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
  event.preventDefault()
  activateSessionDevice(deviceId)
  announceContextMenuOpen()
  const deviceTab = document.querySelector<HTMLElement>(
    `[data-device-tab-id="${CSS.escape(deviceId)}"] .device-session-tab-select`
  )
  const trigger = deviceTab || (event.currentTarget as HTMLElement | null)
  const rect = trigger?.getBoundingClientRect()
  sessionManagerDeviceContextMenuReturnFocus.value = trigger
  sessionManagerDeviceContextMenu.value = {
    deviceId,
    x: rect ? rect.left + 24 : 140,
    y: rect ? rect.bottom + 4 : 140
  }
}

function sessionManagerContextDevice(): DeviceSummary | null {
  const deviceId = sessionManagerDeviceContextMenu.value?.deviceId || ''
  return deviceById.value.get(deviceId) || null
}

function sessionManagerDeviceHasSession(kind: SessionKind): boolean {
  const deviceId = sessionManagerDeviceContextMenu.value?.deviceId || ''
  return workspace.sessions.some((session) => session.device_id === deviceId && session.kind === kind)
}

function sessionManagerDeviceIds(): string[] {
  return [...new Set(workspace.sessions.map((session) => session.device_id))]
}

function canCloseDeviceSessions(
  deviceId: string,
  mode: 'current' | 'left' | 'right' | 'others' | 'all'
): boolean {
  const deviceIds = sessionManagerDeviceIds()
  const index = deviceIds.indexOf(deviceId)
  if (mode === 'all') return deviceIds.length > 0
  if (index < 0) return false
  if (mode === 'current') return true
  if (mode === 'left') return index > 0
  if (mode === 'right') return index < deviceIds.length - 1
  return deviceIds.length > 1
}

function runSessionManagerDeviceClose(
  mode: 'current' | 'left' | 'right' | 'others' | 'all'
): void {
  const deviceId = sessionManagerDeviceContextMenu.value?.deviceId
  if (!deviceId) return
  const device = sessionManagerContextDevice()
  const count = mode === 'current'
    ? workspace.sessions.filter((session) => session.device_id === deviceId).length
    : mode === 'others'
      ? workspace.sessions.filter((session) => session.device_id !== deviceId).length
      : workspace.sessions.length
  if (count > 1 && !window.confirm(
    mode === 'current'
      ? `关闭“${device?.name || deviceId}”的 ${count} 个会话吗？`
      : mode === 'others'
        ? `关闭其他设备的 ${count} 个会话吗？`
        : `关闭全部 ${count} 个设备会话吗？`
  )) return
  void workspace.closeDeviceSessionGroups(deviceId, mode)
  closeSessionManagerDeviceContextMenu()
}

function locateSessionManagerDevice(deviceId = sessionManagerDeviceContextMenu.value?.deviceId || ''): void {
  if (!deviceId) return
  activeSection.value = 'devices'
  if (!workspace.filteredDevices.some((device) => device.id === deviceId)) {
    workspace.clearDeviceFilters()
  }
  if (selectDeviceByDeviceId(deviceId)) {
    workspace.notice = `已定位到设备: ${deviceById.value.get(deviceId)?.name || deviceId}`
  }
  closeSessionManagerDeviceContextMenu()
}

function openSessionManagerDeviceSession(kind: 'ssh' | 'telnet' | 'serial'): void {
  const device = sessionManagerContextDevice()
  if (!device) return
  openOrActivateDeviceSession(device, kind)
  closeSessionManagerDeviceContextMenu()
}

function openOrActivateDeviceSession(
  device: DeviceSummary,
  kind: 'ssh' | 'telnet' | 'serial'
): void {
  const existing = workspace.sessions.find((session) =>
    session.device_id === device.id && session.kind === kind
  )
  if (existing) {
    activateSession(existing.id)
    workspace.notice = `已切换至 ${device.name} 的 ${sessionKindLabel(kind)} 会话`
    return
  }
  void workspace.openSessionForDevice(device, kind)
}

function openOrActivateDeviceProtocol(deviceId: string, kind: DeviceProtocolKind): void {
  const device = deviceById.value.get(deviceId)
  if (device) openOrActivateDeviceSession(device, kind)
}

function startSessionTabDrag(event: DragEvent, session: SessionSummary): void {
  if (!event.dataTransfer) return
  workspace.activeSessionId = session.id
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-odyterm-session', session.id)
  event.dataTransfer.setData('text/plain', session.id)
}

function splitSessionFromContext(direction: SplitDirection): void {
  const session = sessionContextMenu.value?.session
  if (!session) return
  const splitWorkspace = terminalSplitWorkspaces.get(session.device_id)
  if (splitWorkspace) {
    splitWorkspace.splitSession(session.id, direction)
  } else {
    activateSession(session.id)
    void nextTick(() => {
      terminalSplitWorkspaces.get(session.device_id)?.splitSession(session.id, direction)
    })
  }
  closeSessionContextMenu()
}

function resetTerminalSplit(): void {
  const session = sessionContextMenu.value?.session || workspace.activeSession
  if (session) terminalSplitWorkspaces.get(session.device_id)?.resetSplit()
  closeSessionContextMenu()
}

function handleSessionTabKeydown(event: KeyboardEvent, session: SessionSummary): void {
  if (event.key === 'Escape') {
    closeSessionContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    event.preventDefault()
    announceContextMenuOpen()
    workspace.activeSessionId = session.id
    const selectedTab = document.querySelector<HTMLElement>(
      `[data-session-tab-id="${CSS.escape(session.id)}"]`
    )
    const rect = (selectedTab || (event.currentTarget as HTMLElement | null))?.getBoundingClientRect()
    sessionContextMenuReturnFocus.value = selectedTab || (event.currentTarget as HTMLElement | null)
    sessionContextMenu.value = {
      session,
      source: 'tab',
      x: rect ? rect.left + 24 : 140,
      y: rect ? rect.bottom + 4 : 140
    }
  }
}

function canCloseSessionRelative(session: SessionSummary, mode: 'current' | 'left' | 'right' | 'others' | 'all'): boolean {
  const deviceSessions = sessionsByDevice.value.get(session.device_id) || []
  const index = deviceSessions.findIndex((candidate) => candidate.id === session.id)
  if (mode === 'all') return deviceSessions.length > 0
  if (index < 0) return false
  if (mode === 'current') return true
  if (mode === 'left') return index > 0
  if (mode === 'right') return index < deviceSessions.length - 1
  return deviceSessions.length > 1
}

function runSessionContextClose(mode: 'current' | 'left' | 'right' | 'others' | 'all'): void {
  const session = sessionContextMenu.value?.session
  if (!session) return
  const count = sessionCloseCount(session, mode)
  if (count > 1 && !window.confirm(
    mode === 'others'
      ? `关闭此设备的其他 ${count} 个会话吗？`
      : mode === 'all'
        ? `关闭此设备的全部 ${count} 个会话吗？`
        : `关闭${mode === 'left' ? '左侧' : '右侧'} ${count} 个页签吗？`
  )) return
  void workspace.closeSessionsRelative(session.id, mode, session.device_id)
  closeSessionContextMenu()
}

function sessionCloseCount(
  session: SessionSummary,
  mode: 'current' | 'left' | 'right' | 'others' | 'all'
): number {
  const deviceSessions = sessionsByDevice.value.get(session.device_id) || []
  const index = deviceSessions.findIndex((candidate) => candidate.id === session.id)
  if (index < 0 && mode !== 'all') return 0
  if (mode === 'current') return 1
  if (mode === 'left') return index
  if (mode === 'right') return Math.max(0, deviceSessions.length - index - 1)
  if (mode === 'others') return Math.max(0, deviceSessions.length - 1)
  return deviceSessions.length
}

function canSplitSession(session: SessionSummary): boolean {
  return (sessionsByDevice.value.get(session.device_id) || []).length > 1
}

function canReconnectSession(session: SessionSummary): boolean {
  return ['disconnected', 'detached', 'error', 'failed'].includes(session.status)
}

function canDisconnectSession(session: SessionSummary): boolean {
  return ['connected', 'connecting'].includes(session.status)
}

function runSessionConnectionAction(action: 'reconnect' | 'disconnect'): void {
  const session = sessionContextMenu.value?.session
  if (!session) return
  if (action === 'reconnect') void workspace.reconnectSession(session.id)
  else void workspace.disconnectSession(session.id)
  closeSessionContextMenu()
}

async function copySessionInfoFromContext(): Promise<void> {
  const session = sessionContextMenu.value?.session
  if (!session) return
  const device = sessionDevice(session)
  await navigator.clipboard.writeText([
    `会话: ${session.title}`,
    `协议: ${sessionKindLabel(session.kind)}`,
    `状态: ${sessionStatusLabel(session.status)}`,
    `设备: ${device?.name || session.device_id}`,
    `设备 ID: ${session.device_id}`
  ].join('\n'))
  workspace.notice = `已复制会话信息: ${session.title}`
  closeSessionContextMenu()
}

function locateSessionDevice(session: SessionSummary): void {
  activeSection.value = 'devices'
  if (!workspace.filteredDevices.some((device) => device.id === session.device_id)) {
    workspace.clearDeviceFilters()
  }
  selectDeviceByDeviceId(session.device_id)
  workspace.notice = `已定位到设备: ${sessionDevice(session)?.name || session.device_id}`
  closeSessionContextMenu()
}

function profileEndpointText(profile: ConnectionProfileSummary, kind: 'ssh' | 'telnet' | 'serial'): string {
  const endpoint = profile[kind]
  return endpoint.host ? `${endpoint.host}:${endpoint.port}` : ''
}

function profileConnectionCopyText(profile: ConnectionProfileSummary): string {
  const lines = [
    `名称: ${profile.name}`,
    `类型: ${profile.profile_type === 'server' ? '服务器' : '临时连接'}`,
    `默认协议: ${profile.preferred_protocol.toUpperCase()}`
  ]
  if (profile.group) lines.push(`分组: ${profile.group}`)
  for (const kind of ['ssh', 'telnet', 'serial'] as const) {
    const endpoint = profileEndpointText(profile, kind)
    if (endpoint) lines.push(`${kind.toUpperCase()}: ${endpoint}`)
    if (endpoint && profile[kind].username) lines.push(`${kind.toUpperCase()} 用户: ${profile[kind].username}`)
  }
  if (profile.notes) lines.push(`备注: ${profile.notes}`)
  return lines.join('\n')
}

function profileDefaultOpenLabel(profile: ConnectionProfileSummary): string {
  return `使用默认协议打开（${sessionKindLabel(profile.preferred_protocol)}）`
}

function profilePayload(
  profile: ConnectionProfileSummary,
  overrides: Partial<ConnectionProfilePayload> = {}
): ConnectionProfilePayload {
  return {
    profile_type: profile.profile_type,
    name: profile.name,
    group: profile.profile_type === 'server' ? profile.group : '',
    notes: profile.notes,
    preferred_protocol: profile.preferred_protocol,
    telnet: {
      host: profile.profile_type === 'temporary' ? profile.telnet.host : '',
      port: profile.telnet.port,
      username: profile.telnet.username
    },
    ssh: {
      host: profile.ssh.host,
      port: profile.ssh.port,
      username: profile.ssh.username
    },
    serial: {
      host: profile.profile_type === 'temporary' ? profile.serial.host : '',
      port: profile.serial.port,
      username: profile.serial.username
    },
    ...overrides
  }
}

async function copyProfileText(text: string, message: string): Promise<void> {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    workspace.notice = message
    workspace.error = ''
  } catch (cause) {
    workspace.error = cause instanceof Error ? cause.message : String(cause)
  } finally {
    closeProfileContextMenu()
  }
}

function openProfileContextMenu(event: MouseEvent, profile: ConnectionProfileSummary): void {
  announceContextMenuOpen()
  selectedProfileId.value = profile.id
  profileContextMenuReturnFocus.value = contextMenuTrigger(event)
  profileContextMenu.value = { profile, ...clampContextMenuPoint(event.clientX, event.clientY) }
}

function handleProfileKeydown(event: KeyboardEvent, profile: ConnectionProfileSummary): void {
  if (event.key === 'Escape') {
    closeProfileContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    event.preventDefault()
    announceContextMenuOpen()
    selectedProfileId.value = profile.id
    const row = document.querySelector<HTMLElement>(
      `[data-profile-row-id="${CSS.escape(profile.id)}"]`
    )
    const rect = (row || (event.currentTarget as HTMLElement | null))?.getBoundingClientRect()
    profileContextMenuReturnFocus.value = row || (event.currentTarget as HTMLElement | null)
    profileContextMenu.value = {
      profile,
      x: rect ? rect.left + 28 : 128,
      y: rect ? rect.top + 28 : 128
    }
  }
}

function openProfileFromContext(kind: 'ssh' | 'telnet' | 'serial' = profileContextMenu.value?.profile.preferred_protocol || 'ssh'): void {
  const profile = profileContextMenu.value?.profile
  if (!profile) return
  void workspace.openProfileSession(profile, kind)
  closeProfileContextMenu()
}

function manageProfileCredentialFromContext(kind: 'ssh' | 'telnet' | 'serial'): void {
  const profile = profileContextMenu.value?.profile
  if (!profile) return
  void workspace.manageProfileCredential(profile, kind)
  closeProfileContextMenu()
}

function editProfileFromContext(): void {
  const profile = profileContextMenu.value?.profile
  if (!profile) return
  showProfileDialog(profile.profile_type, profile)
  closeProfileContextMenu()
}

async function deleteProfileFromContext(): Promise<void> {
  const profile = profileContextMenu.value?.profile
  if (!profile) return
  closeProfileContextMenu()
  if (!window.confirm(`确定删除“${profile.name}”吗？`)) return
  if (await workspace.deleteProfile(profile.id)) {
    selectedProfileId.value = visibleProfiles.value.find((candidate) => candidate.id !== profile.id)?.id || ''
  }
}

async function moveProfileToGroupFromContext(group: string): Promise<void> {
  const profile = profileContextMenu.value?.profile
  if (!profile || profile.profile_type !== 'server') return
  const saved = await workspace.saveProfile(
    profilePayload(profile, { group }),
    profile.id
  )
  if (saved) {
    selectedProfileId.value = saved.id
    if (group) expandProfileGroup(group)
    workspace.notice = group ? `已移动到分组: ${group}` : '已移动到未分组'
  }
  closeProfileContextMenu()
}

function connectionDisabledReason(device: DeviceSummary | null, kind: 'ssh' | 'telnet' | 'serial'): string {
  if (!device) return '请先选择设备'
  if (workspace.openingKind) return '正在创建终端会话'
  if (kind === 'ssh' && !device.can_connect_ssh) {
    return device.is_simulated ? '模拟终端不支持 SSH' : '设备 SSH 地址不可用'
  }
  if (kind === 'telnet' && !device.can_connect_telnet) {
    if (device.is_simulated) return '模拟终端不支持 Telnet'
    return device.is_saved_server ? '保存服务器请使用 SSH' : '设备 Telnet 地址不可用'
  }
  if (kind === 'serial' && !device.can_connect_serial) {
    if (device.is_simulated) return '模拟终端不支持串口'
    if (device.is_temporary) return '临时连接不进入设备串口通道'
    if (device.is_saved_server) return '保存服务器不支持设备串口'
    return device.serial_display || '请先占用设备后再连接串口'
  }
  return ''
}

function setSection(section: 'devices' | 'temporary' | 'server'): void {
  const hideCurrentSection = navigatorVisible.value
    && !operationPanelOpen.value
    && activeSection.value === section
  if (workspace.automationPanelOpen && !workspace.closeAutomationPanel()) return
  workspace.transferPanelOpen = false
  workspace.upgradePanelOpen = false
  workspace.packageBuildPanelOpen = false
  if (hideCurrentSection) {
    setNavigatorVisible(false)
    return
  }
  activeSection.value = section
  setNavigatorVisible(true)
  if (section !== 'devices') {
    selectedProfileId.value =
      workspace.profiles.find((profile) => profile.profile_type === section)?.id || ''
  }
}

function toggleAutomationPanel(): void {
  if (workspace.automationPanelOpen) {
    workspace.closeAutomationPanel()
  } else {
    workspace.automationPanelOpen = true
    workspace.transferPanelOpen = false
    workspace.upgradePanelOpen = false
    workspace.packageBuildPanelOpen = false
    workspace.aiPanelOpen = false
  }
}

function openSessionAutomation(sessionId: string): void {
  workspace.activeSessionId = sessionId
  workspace.automationPanelOpen = true
  workspace.transferPanelOpen = false
  workspace.upgradePanelOpen = false
  workspace.packageBuildPanelOpen = false
  workspace.aiPanelOpen = false
}

function openSessionTransfer(sessionId: string): void {
  if (workspace.automationPanelOpen && !workspace.closeAutomationPanel()) return
  workspace.activeSessionId = sessionId
  workspace.transferPanelOpen = true
  workspace.upgradePanelOpen = false
  workspace.packageBuildPanelOpen = false
  workspace.aiPanelOpen = false
}

function openSessionUpgrade(sessionId: string): void {
  if (workspace.automationPanelOpen && !workspace.closeAutomationPanel()) return
  workspace.activeSessionId = sessionId
  workspace.upgradePanelOpen = true
  workspace.transferPanelOpen = false
  workspace.packageBuildPanelOpen = false
  workspace.aiPanelOpen = false
}

function toggleTransferPanel(): void {
  const open = !workspace.transferPanelOpen
  if (open && workspace.automationPanelOpen && !workspace.closeAutomationPanel()) return
  workspace.transferPanelOpen = open
  if (open) {
    workspace.upgradePanelOpen = false
    workspace.packageBuildPanelOpen = false
  }
}

function toggleUpgradePanel(): void {
  const open = !workspace.upgradePanelOpen
  if (open && workspace.automationPanelOpen && !workspace.closeAutomationPanel()) return
  workspace.upgradePanelOpen = open
  if (open) {
    workspace.transferPanelOpen = false
    workspace.packageBuildPanelOpen = false
  }
}

function togglePackageBuildPanel(): void {
  const open = !workspace.packageBuildPanelOpen
  if (open && workspace.automationPanelOpen && !workspace.closeAutomationPanel()) return
  workspace.packageBuildPanelOpen = open
  if (open) {
    workspace.transferPanelOpen = false
    workspace.upgradePanelOpen = false
  }
}

function applyRendererTheme(mode: ThemeMode): void {
  themeMode.value = mode
  document.documentElement.dataset.theme = mode
  document.documentElement.style.colorScheme = mode
  localStorage.setItem(THEME_KEY, mode)
  void window.desktopApi?.setNativeTheme(mode).catch(() => {
    // The renderer theme remains usable if the preload bridge is unavailable.
  })
}

async function setAlwaysOnTop(enabled: boolean, announce = true): Promise<void> {
  try {
    alwaysOnTop.value = await window.desktopApi.setAlwaysOnTop(enabled)
    localStorage.setItem(ALWAYS_ON_TOP_KEY, alwaysOnTop.value ? '1' : '0')
    if (announce) workspace.notice = alwaysOnTop.value ? '窗口已置顶' : '窗口已取消置顶'
    workspace.error = ''
  } catch (cause) {
    workspace.error = cause instanceof Error ? cause.message : String(cause)
  }
}

function toggleAlwaysOnTop(): void {
  void setAlwaysOnTop(!alwaysOnTop.value)
}

function toggleTheme(): void {
  applyRendererTheme(themeMode.value === 'dark' ? 'light' : 'dark')
}

function setSessionTabLayout(layout: SessionTabLayout): void {
  sessionTabLayout.value = layout
  localStorage.setItem(SESSION_TAB_LAYOUT_KEY, layout)
}

function setSessionTabRailCollapsed(collapsed: boolean): void {
  sessionTabRailCollapsed.value = collapsed
  localStorage.setItem(SESSION_TAB_RAIL_COLLAPSED_KEY, collapsed ? '1' : '0')
}

function toggleNavigatorDetail(): void {
  navigatorDetailCollapsed.value = !navigatorDetailCollapsed.value
  localStorage.setItem(
    NAVIGATOR_DETAIL_COLLAPSED_KEY,
    navigatorDetailCollapsed.value ? '1' : '0'
  )
}

function eventTrigger(event?: Event): HTMLElement | null {
  return event?.currentTarget instanceof HTMLElement ? event.currentTarget : null
}

function showSettingsPanel(event?: Event): void {
  settingsReturnFocus.value = eventTrigger(event)
  helpPanelOpen.value = false
  settingsPanelOpen.value = true
}

function showHelpPanel(event?: Event): void {
  helpReturnFocus.value = eventTrigger(event)
  settingsPanelOpen.value = false
  helpPanelOpen.value = true
}

function showInternalLogin(): void {
  if (workspace.internalAuthBusy) return
  if (!workspace.internalAuthStatus.available) {
    workspace.notice = '当前设备源未提供网站登录能力，请检查对应插件的登录配置。'
  } else if (!workspace.internalAuthStatus.configured) {
    workspace.notice = `${activeDeviceSource.value?.label || '设备网站'}登录未配置，请检查对应插件。`
  }
  void workspace.loginInternalService()
}

function logoutInternalService(): void {
  if (workspace.internalAuthBusy || !workspace.internalAuthStatus.authenticated) return
  void workspace.logoutInternalService()
}

async function switchDeviceSource(event: Event): Promise<void> {
  const select = event.target as HTMLSelectElement
  const source = select.value as DeviceSourceId
  const switched = await workspace.switchDeviceSource(source)
  if (!switched) select.value = workspace.deviceSourceStatus.active_source
}

async function chooseDeviceImport(event?: Event): Promise<void> {
  deviceImportReturnFocus.value = eventTrigger(event)
  await workspace.chooseDeviceImport()
}

function restoreDefaultDeviceSource(): void {
  void workspace.switchDeviceSource(workspace.deviceSourceStatus.default_source)
}

function showProfileDialog(
  profileType: ProfileType,
  profile: ConnectionProfileSummary | null = null,
  event?: Event
): void {
  profileDialogReturnFocus.value = eventTrigger(event) || document.querySelector<HTMLElement>(
    profile ? `[data-profile-row-id="${CSS.escape(profile.id)}"]` : '.navigator-actions button[title="新增连接"]'
  )
  dialogType.value = profileType
  editingProfile.value = profile
}

function showGroupDialog(event?: Event): void {
  groupDialogReturnFocus.value = eventTrigger(event)
  groupDialogOpen.value = true
}

async function saveProfile(
  payload: ConnectionProfilePayload,
  connectAfterSave = false,
  secrets: ConnectionProfileSecrets = {}
): Promise<void> {
  savingProfile.value = true
  let saved = await workspace.saveProfile(payload, editingProfile.value?.id, secrets)
  if (
    !saved
    && workspace.errorCode === 'conflict'
    && window.confirm('已存在相同地址和端口的连接配置，仍要继续保存吗？')
  ) {
    saved = await workspace.saveProfile(
      { ...payload, allow_duplicate: true },
      editingProfile.value?.id,
      secrets
    )
  }
  savingProfile.value = false
  if (saved) {
    selectedProfileId.value = saved.id
    if (saved.profile_type === 'server' && saved.group) expandProfileGroup(saved.group)
    dialogType.value = ''
    editingProfile.value = null
    if (connectAfterSave) await workspace.openProfileSession(saved)
  }
}

async function createGroup(name: string): Promise<void> {
  savingGroup.value = true
  const created = await workspace.createProfileGroup(name)
  savingGroup.value = false
  if (created) {
    expandProfileGroup(name)
    groupDialogOpen.value = false
  }
}

function profileCanConnect(
  profile: ConnectionProfileSummary,
  kind: 'ssh' | 'telnet' | 'serial' = profile.preferred_protocol
): boolean {
  return Boolean(profile[kind].host)
}

function openProfileIfReady(profile: ConnectionProfileSummary): void {
  if (profileCanConnect(profile)) void workspace.openProfileSession(profile)
}

async function deleteSelectedProfile(): Promise<void> {
  const profile = selectedProfile.value
  if (!profile || !window.confirm(`确定删除“${profile.name}”吗？`)) return
  if (await workspace.deleteProfile(profile.id)) {
    selectedProfileId.value = visibleProfiles.value.find((candidate) => candidate.id !== profile.id)?.id || ''
  }
}

const statusCounts = computed(() => {
  const counts = { total: workspace.filteredDevices.length, idle: 0, occupied: 0, pipeline: 0, other: 0 }
  for (const device of workspace.filteredDevices) {
    counts[statusKind(device.status)] += 1
  }
  return counts
})

type DeviceStatusKind = 'idle' | 'occupied' | 'pipeline' | 'other'

function statusKind(status: string): DeviceStatusKind {
  const value = status.toLocaleLowerCase()
  if (value.includes('空闲') || value.includes('idle')) return 'idle'
  if (value.includes('流水') || value.includes('pipeline')) return 'pipeline'
  if (value.includes('占用') || value.includes('occupied')) return 'occupied'
  return 'other'
}

onMounted(async () => {
  unsubscribeContextMenuOpen = subscribeContextMenuOpen(closeAppContextMenus)
  window.addEventListener('resize', handleWindowResize)
  setNavigatorWidth(navigatorWidth.value, false)
  applyRendererTheme(themeMode.value)
  if (!window.desktopApi) {
    backendFailure.value = 'Electron preload bridge unavailable'
    return
  }
  unsubscribeBackendExit = window.desktopApi.onBackendExit((details) => {
    stopApplicationEvents?.()
    stopApplicationEvents = null
    backendFailure.value = details
  })
  unsubscribeBackendRecovered = window.desktopApi.onBackendRecovered((details) => {
    void (async () => {
      await workspace.initialize()
      if (workspace.error) {
        backendFailure.value = `${details}; 重新载入工作区失败: ${workspace.error}`
        return
      }
      backendFailure.value = ''
      workspace.notice = 'Python 后端已自动恢复，工作区已重新载入。'
      stopApplicationEvents = workspace.startApplicationEvents()
    })()
  })
  await setAlwaysOnTop(alwaysOnTop.value, false)
  await workspace.initialize()
  stopApplicationEvents = workspace.startApplicationEvents()
})

onBeforeUnmount(() => {
  if (noticeTimer) clearTimeout(noticeTimer)
  stopNavigatorResize()
  deviceListResizeObserver?.disconnect()
  unsubscribeContextMenuOpen?.()
  window.removeEventListener('resize', handleWindowResize)
  unsubscribeBackendExit?.()
  unsubscribeBackendRecovered?.()
  stopApplicationEvents?.()
})
</script>

<template>
  <div class="app-frame">
    <header class="app-titlebar" aria-label="应用菜单">
      <div class="app-titlebar-identity"><span>OdyTerm</span></div>
      <div class="app-titlebar-menus" role="menubar" aria-label="应用菜单">
        <button type="button" role="menuitem" @click.stop="showApplicationMenu('file', $event)">文件</button>
        <button type="button" role="menuitem" @click.stop="showApplicationMenu('edit', $event)">编辑</button>
        <button type="button" role="menuitem" @click.stop="showApplicationMenu('view', $event)">视图</button>
        <button type="button" role="menuitem" @click.stop="showApplicationMenu('window', $event)">窗口</button>
      </div>
    </header>
  <div
    class="app-shell"
    :class="{
      'has-session-sidebar': showSessionSidebar,
      'session-sidebar-collapsed': showSessionSidebar && sessionTabRailCollapsed,
      'navigator-hidden': !operationPanelOpen && !navigatorVisible,
      'navigator-resizing': navigatorResizing
    }"
    :style="appShellStyle"
    @click="closeAppContextMenus"
  >
    <nav class="activity-rail" aria-label="主功能">
      <button class="rail-button" :class="{ active: navigatorVisible && !operationPanelOpen && activeSection === 'devices' }" type="button" :title="navigatorVisible && !operationPanelOpen && activeSection === 'devices' ? '隐藏设备列表' : '显示设备列表'" :aria-pressed="navigatorVisible && !operationPanelOpen && activeSection === 'devices'" @click="setSection('devices')">
        <MonitorDot :size="19" /><span class="sr-only">设备与终端</span>
      </button>
      <button class="rail-button" :class="{ active: navigatorVisible && !operationPanelOpen && activeSection === 'temporary' }" type="button" :title="navigatorVisible && !operationPanelOpen && activeSection === 'temporary' ? '隐藏临时连接' : '显示临时连接'" :aria-pressed="navigatorVisible && !operationPanelOpen && activeSection === 'temporary'" @click="setSection('temporary')">
        <Cable :size="19" /><span class="sr-only">临时连接</span>
      </button>
      <button class="rail-button" :class="{ active: navigatorVisible && !operationPanelOpen && activeSection === 'server' }" type="button" :title="navigatorVisible && !operationPanelOpen && activeSection === 'server' ? '隐藏服务器列表' : '显示服务器列表'" :aria-pressed="navigatorVisible && !operationPanelOpen && activeSection === 'server'" @click="setSection('server')">
        <ServerCog :size="19" /><span class="sr-only">服务器</span>
      </button>
      <button
        class="rail-button"
        :class="{ active: workspace.automationPanelOpen }"
        type="button"
        title="终端自动化"
        :aria-pressed="workspace.automationPanelOpen"
        @click="toggleAutomationPanel"
      >
        <Workflow :size="19" /><span class="sr-only">终端自动化</span>
      </button>
      <button
        class="rail-button"
        :class="{ active: workspace.transferPanelOpen }"
        type="button"
        title="文件传输"
        :aria-pressed="workspace.transferPanelOpen"
        @click="toggleTransferPanel"
      >
        <FileUp :size="19" /><span class="sr-only">文件传输</span>
      </button>
      <button
        class="rail-button"
        :class="{ active: workspace.upgradePanelOpen }"
        type="button"
        title="升级任务"
        :aria-pressed="workspace.upgradePanelOpen"
        @click="toggleUpgradePanel"
      >
        <Box :size="19" /><span class="sr-only">升级任务</span>
      </button>
      <button
        class="rail-button"
        :class="{ active: workspace.packageBuildPanelOpen }"
        type="button"
        title="VRP 编包"
        :aria-pressed="workspace.packageBuildPanelOpen"
        @click="togglePackageBuildPanel"
      >
        <FileArchive :size="19" /><span class="sr-only">VRP 编包</span>
      </button>
      <div class="rail-spacer"></div>
      <button
        v-if="activeDeviceSource?.requires_login"
        class="rail-button internal-auth-rail"
        :class="{ active: workspace.internalAuthStatus.authenticated }"
        type="button"
        :disabled="workspace.internalAuthBusy"
        :title="workspace.internalAuthStatus.authenticated ? `${activeDeviceSource?.label}：${workspace.internalAuthStatus.username} · CID ${workspace.internalAuthStatus.cid}；点击切换账号` : workspace.internalAuthStatus.configured ? `登录${activeDeviceSource?.label}` : `${activeDeviceSource?.label}登录未配置`"
        :aria-label="workspace.internalAuthStatus.authenticated ? `切换${activeDeviceSource?.label}账号` : `登录${activeDeviceSource?.label}`"
        @click="showInternalLogin"
      >
        <UserRound :size="18" />
        <i :data-authenticated="workspace.internalAuthStatus.authenticated" aria-hidden="true"></i>
      </button>
      <button
        class="rail-button"
        :class="{ active: helpPanelOpen }"
        type="button"
        title="帮助"
        :aria-pressed="helpPanelOpen"
        @click="showHelpPanel($event)"
      >
        <CircleHelp :size="19" /><span class="sr-only">帮助</span>
      </button>
      <button
        class="rail-button"
        :class="{ active: settingsPanelOpen }"
        type="button"
        title="设置"
        :aria-pressed="settingsPanelOpen"
        @click="showSettingsPanel($event)"
      >
        <Settings :size="19" /><span class="sr-only">设置</span>
      </button>
      <button
        class="rail-button always-on-top-toggle"
        :class="{ active: alwaysOnTop }"
        type="button"
        :title="alwaysOnTop ? '取消窗口置顶' : '窗口置顶'"
        :aria-label="alwaysOnTop ? '取消窗口置顶' : '窗口置顶'"
        :aria-pressed="alwaysOnTop"
        @click="toggleAlwaysOnTop"
      >
        <Pin :size="18" />
        <span class="sr-only">{{ alwaysOnTop ? '取消窗口置顶' : '窗口置顶' }}</span>
      </button>
      <button
        class="rail-button theme-toggle"
        type="button"
        :title="themeMode === 'dark' ? '切换浅色主题' : '切换深色主题'"
        :aria-label="themeMode === 'dark' ? '切换浅色主题' : '切换深色主题'"
        :aria-pressed="themeMode === 'light'"
        @click="toggleTheme"
      >
        <Sun v-if="themeMode === 'dark'" :size="18" />
        <Moon v-else :size="18" />
        <span class="sr-only">{{ themeMode === 'dark' ? '切换浅色主题' : '切换深色主题' }}</span>
      </button>
    </nav>

    <aside v-show="navigatorVisible && !operationPanelOpen" class="navigator">
      <header class="navigator-header">
        <div>
          <p v-if="activeSection !== 'devices'" class="eyebrow">DEVICE OPERATIONS</p>
          <h1>{{ activeSection === 'devices' ? '设备' : activeSection === 'temporary' ? '临时连接' : '服务器' }}</h1>
        </div>
        <div class="navigator-actions">
          <button v-if="activeSection === 'devices'" class="icon-button" type="button" title="刷新" @click="workspace.initialize">
            <RefreshCw :size="15" /><span class="sr-only">刷新设备</span>
          </button>
          <template v-else>
            <button v-if="activeSection === 'server'" class="icon-button" type="button" title="新建分组" @click="showGroupDialog($event)">
              <FolderPlus :size="16" /><span class="sr-only">新建服务器分组</span>
            </button>
            <button class="icon-button" type="button" title="新增连接" @click="showProfileDialog(activeSection, null, $event)">
              <Plus :size="16" /><span class="sr-only">新增连接</span>
            </button>
          </template>
          <button class="icon-button" type="button" title="隐藏设备工作台" aria-label="隐藏设备工作台" @click="setNavigatorVisible(false)">
            <PanelLeftClose :size="16" aria-hidden="true" />
          </button>
        </div>
      </header>

      <section
        v-if="activeSection === 'devices' && workspace.deviceSourceStatus.allow_source_switch"
        class="device-source-bar"
        aria-label="设备数据源"
      >
        <div
          class="device-source-current"
          :title="`${activeDeviceSource?.description || ''} 当前只显示这一来源的设备。`"
        >
          <span class="sr-only">当前设备来源</span>
          <span class="device-source-icon" aria-hidden="true">
            <Globe2 v-if="activeDeviceSource?.icon === 'globe'" :size="16" />
            <FileSpreadsheet v-else-if="activeDeviceSource?.icon === 'spreadsheet'" :size="16" />
            <Plug v-else-if="activeDeviceSource?.icon === 'plug'" :size="16" />
            <Database v-else :size="16" />
          </span>
          <strong>{{ activeDeviceSource?.label || '正在识别…' }}</strong>
          <b v-if="workspace.deviceSourceStatus.active_source === workspace.deviceSourceStatus.default_source">默认</b>
          <b v-else data-variant="changed">已切换</b>
        </div>
        <label class="device-source-switch">
          <span class="sr-only">切换来源</span>
          <select
            :value="workspace.deviceSourceStatus.active_source"
            :disabled="workspace.deviceSourceBusy || workspace.sessions.length > 0"
            aria-label="切换设备来源"
            @change="switchDeviceSource"
          >
            <option
              v-for="source in workspace.deviceSourceStatus.sources"
              :key="source.id"
              :value="source.id"
              :disabled="!source.available"
              :title="source.unavailable_reason"
            >{{ source.label }}{{ source.id === workspace.deviceSourceStatus.default_source ? '（默认）' : '' }}</option>
          </select>
        </label>
        <button
          v-if="importDeviceSource"
          class="secondary-button device-import-button"
          type="button"
          :disabled="workspace.deviceImportBusy || workspace.sessions.length > 0"
          @click="chooseDeviceImport($event)"
        ><FileUp :size="13" />{{ workspace.deviceSourceStatus.imported_count ? '重新导入' : '导入 Excel' }}</button>
        <div class="device-source-context">
          <small v-if="workspace.sessions.length">关闭终端后可切换来源</small>
          <small v-else-if="activeDeviceSource?.supports_import && workspace.deviceSourceStatus.imported_count">
            {{ workspace.deviceSourceStatus.imported_count }} 台设备 · {{ workspace.deviceSourceStatus.imported_file }}
          </small>
          <button
            v-if="workspace.deviceSourceStatus.active_source !== workspace.deviceSourceStatus.default_source"
            type="button"
            :disabled="workspace.deviceSourceBusy || workspace.sessions.length > 0"
            @click="restoreDefaultDeviceSource"
          >恢复默认“{{ defaultDeviceSource?.label }}”</button>
        </div>
        <p
          v-if="workspace.deviceSourceStatus.plugin_warnings.length"
          class="device-source-plugin-warning"
          role="status"
          :title="workspace.deviceSourceStatus.plugin_warnings.join('\n')"
        ><CircleAlert :size="12" />{{ workspace.deviceSourceStatus.plugin_warnings[0] }}</p>
      </section>

      <section
        v-if="activeSection === 'devices' && !workspace.deviceSourceStatus.allow_source_switch && workspace.deviceSourceStatus.allow_import"
        class="device-import-bar"
        aria-label="设备表格"
      >
        <span class="device-import-summary">
          <span class="device-source-icon" aria-hidden="true"><FileSpreadsheet :size="16" /></span>
          <span>
            <strong>{{ workspace.deviceSourceStatus.imported_count ? '设备表格' : '导入设备表格' }}</strong>
            <small v-if="workspace.deviceSourceStatus.imported_count">
              {{ workspace.deviceSourceStatus.imported_file }} · {{ workspace.deviceSourceStatus.imported_count }} 台设备
            </small>
            <small v-else>选择 Excel、CSV 或 TSV 文件开始使用</small>
          </span>
        </span>
        <button
          class="secondary-button device-import-button"
          type="button"
          :disabled="workspace.deviceImportBusy || workspace.sessions.length > 0"
          @click="chooseDeviceImport($event)"
        ><FileUp :size="13" />{{ workspace.deviceSourceStatus.imported_count ? '更新设备表' : '选择文件' }}</button>
        <small v-if="workspace.sessions.length" class="device-import-hint">关闭全部终端后才能更新设备表。</small>
      </section>

      <section v-if="activeSection === 'devices' && activeDeviceSource?.requires_login" class="internal-account-bar" :data-authenticated="workspace.internalAuthStatus.authenticated">
        <button
          class="internal-account-main"
          type="button"
          :disabled="workspace.internalAuthBusy"
          @click="showInternalLogin"
        >
          <span class="internal-account-icon" aria-hidden="true">
            <UserRound :size="16" />
          </span>
          <span class="internal-account-copy">
            <strong>{{ workspace.internalAuthStatus.authenticated ? workspace.internalAuthStatus.username : `登录${activeDeviceSource?.label || '设备网站'}` }}</strong>
            <small
              v-if="workspace.internalAuthStatus.authenticated"
              :title="`Cookie 已连接${workspace.internalAuthStatus.auto_login ? ' · 自动登录已开启' : ''}`"
            >已连接 · CID {{ workspace.internalAuthStatus.cid }}</small>
            <small
              v-else
              :title="workspace.internalAuthStatus.configured
                ? (workspace.internalAuthStatus.remembered ? '密码已安全保存 · 点击登录' : '输入账号、密码和 CID 后加载设备')
                : '当前为本地数据 · 点击查看配置要求'"
            >点击登录加载设备</small>
          </span>
          <LogIn v-if="!workspace.internalAuthStatus.authenticated" :size="15" aria-hidden="true" />
          <span v-else class="internal-account-switch">切换</span>
        </button>
        <button
          v-if="workspace.internalAuthStatus.authenticated"
          class="icon-button internal-account-logout"
          type="button"
          :title="`退出${activeDeviceSource?.label || '设备网站'}`"
          :aria-label="`退出${activeDeviceSource?.label || '设备网站'}`"
          :disabled="workspace.internalAuthBusy"
          @click="logoutInternalService"
        >
          <LogOut :size="15" />
        </button>
      </section>

      <label class="search-field">
        <Search :size="15" aria-hidden="true" />
        <input
          v-if="activeSection === 'devices'"
          v-model="workspace.query"
          type="search"
          placeholder="搜索名称、ID、站点或型号"
        />
        <input
          v-else
          v-model="workspace.profileQuery"
          type="search"
          placeholder="搜索名称、地址、分组或备注"
        />
      </label>

      <div v-if="activeSection !== 'devices'" class="profile-summary-row" aria-label="连接配置统计">
        <span><b>{{ visibleProfiles.length }}</b> 个配置</span>
        <span v-if="activeSection === 'server'"><b>{{ visibleProfileGroupCount }}</b> 个分组</span>
        <span :class="visibleProfileCredentialCount ? 'ready' : 'attention'"><b>{{ visibleProfileCredentialCount }}</b> 凭据就绪</span>
      </div>

      <div v-if="activeSection === 'devices'" class="device-filter-panel" aria-label="设备筛选">
        <CompactSelect v-model="workspace.domainFilter" label="领域" :options="deviceDomainFilterOptions" />
        <CompactSelect v-model="workspace.statusFilter" label="状态" :options="deviceStatusFilterOptions" />
        <input v-model="workspace.cpuFilter" aria-label="CPU" placeholder="CPU" />
        <button
          class="filter-toggle"
          :class="{ active: workspace.mineOnly }"
          type="button"
          :aria-pressed="workspace.mineOnly"
          @click="workspace.mineOnly = !workspace.mineOnly"
        >我的 {{ workspace.myOccupancyCount }}</button>
      </div>

      <div v-if="activeSection === 'devices'" class="summary-row compact-summary" aria-label="设备统计">
        <span><b>{{ statusCounts.total }}</b> 台</span>
        <span class="idle"><b>{{ statusCounts.idle }}</b> 空闲</span>
        <span class="occupied"><b>{{ statusCounts.occupied }}</b> 占用</span>
        <span class="pipeline"><b>{{ statusCounts.pipeline }}</b> 流水线</span>
        <span class="other"><b>{{ statusCounts.other }}</b> 其他</span>
        <button
          v-if="workspace.hasActiveDeviceFilters"
          class="summary-clear"
          type="button"
          @click="workspace.clearDeviceFilters"
        >清空</button>
      </div>

      <div
        v-if="workspace.loading"
        class="navigator-loading"
        role="status"
        aria-live="polite"
        aria-label="正在载入设备"
      >
        <span class="sr-only">正在载入设备…</span>
        <div class="device-table-header" aria-hidden="true">
          <span>序号</span>
          <span>设备</span>
          <span>板类型</span>
          <span>CPU</span>
          <span>Slot</span>
          <span>状态</span>
        </div>
        <div class="device-loading-rows" aria-hidden="true">
          <div v-for="index in 7" :key="index" class="device-loading-row">
            <span><i></i></span>
            <span><i></i><i></i></span>
            <span><i></i></span>
            <span><i></i></span>
            <span><i></i></span>
            <span><i></i></span>
          </div>
        </div>
      </div>
      <div v-else-if="workspace.error" class="navigator-state error">{{ workspace.error }}</div>
      <div
        v-else-if="activeSection === 'devices'"
        ref="deviceListElement"
        class="device-list device-table-list"
        :role="workspace.filteredDevices.length ? 'table' : 'region'"
        aria-label="设备列表"
        tabindex="0"
        @scroll="handleDeviceListScroll"
        @keydown="handleDeviceTableKeydown"
      >
        <div class="device-table-header" role="row">
          <span role="columnheader">序号</span>
          <span role="columnheader">设备</span>
          <span role="columnheader">板类型</span>
          <span role="columnheader">CPU</span>
          <span role="columnheader">Slot</span>
          <span role="columnheader">状态</span>
        </div>
        <div
          v-if="virtualDeviceTopHeight"
          class="device-virtual-spacer"
          :style="{ height: `${virtualDeviceTopHeight}px` }"
          aria-hidden="true"
        ></div>
        <button
          v-for="(device, index) in renderedDevices"
          :key="device.row_id"
          class="device-row device-table-row"
          :class="{ selected: device.row_id === workspace.selectedDeviceRowId }"
          type="button"
          role="row"
          :aria-selected="device.row_id === workspace.selectedDeviceRowId"
          :data-device-row-id="device.row_id"
          :title="device.tooltip"
          @click="selectDevice(device.row_id)"
          @contextmenu.prevent="openDeviceContextMenu($event, device)"
        >
          <span class="device-index" role="cell">{{ device.board_id || virtualDeviceStart + index + 1 }}</span>
          <span class="device-copy device-name-cell" role="cell">
            <strong>{{ device.name }}</strong>
            <small>{{ device.id }} · {{ device.site || device.domain }}</small>
          </span>
          <span class="device-cell" role="cell" :title="device.tooltip || device.board_type">{{ device.board_type || device.device_type || '—' }}</span>
          <span class="device-cell mono" role="cell" :title="device.cpu">{{ device.cpu || '—' }}</span>
          <span class="device-cell" role="cell" :title="device.tooltip || device.slot">{{ device.slot || device.rack || '—' }}</span>
          <span class="device-status-cell" role="cell">
            <i class="status-dot" :data-status="statusKind(device.status)" aria-hidden="true"></i>
            <span :title="device.tooltip || device.status_text">{{ device.status_text || device.status }}</span>
          </span>
        </button>
        <div
          v-if="virtualDeviceBottomHeight"
          class="device-virtual-spacer"
          :style="{ height: `${virtualDeviceBottomHeight}px` }"
          aria-hidden="true"
        ></div>
        <div v-if="!workspace.filteredDevices.length" class="navigator-empty-state device-table-empty" role="status">
          <SearchX :size="22" aria-hidden="true" />
          <strong>{{ workspace.hasActiveDeviceFilters ? '没有匹配的设备' : '暂无设备数据' }}</strong>
          <span>{{ workspace.hasActiveDeviceFilters ? '尝试名称、ID、站点、CPU 或调整筛选条件。' : '刷新设备列表以重新从后端加载数据。' }}</span>
          <button v-if="workspace.hasActiveDeviceFilters" class="secondary-button" type="button" @click="workspace.clearDeviceFilters">清除全部筛选</button>
          <button v-else class="secondary-button" type="button" @click="workspace.initialize"><RefreshCw :size="13" />刷新设备</button>
        </div>
      </div>
      <div v-else class="device-list profile-list" role="listbox" aria-label="连接配置列表">
        <template v-if="activeSection === 'temporary'">
          <button
            v-for="profile in visibleProfiles"
            :key="profile.id"
            class="device-row"
            :class="{ selected: profile.id === selectedProfileId }"
            type="button"
            role="option"
            :aria-selected="profile.id === selectedProfileId"
            :data-profile-row-id="profile.id"
            @click="selectedProfileId = profile.id"
            @dblclick="openProfileIfReady(profile)"
            @contextmenu.prevent="openProfileContextMenu($event, profile)"
            @keydown="handleProfileKeydown($event, profile)"
          >
            <i class="status-dot" :data-status="profile[profile.preferred_protocol].has_password ? 'idle' : 'other'" aria-hidden="true"></i>
            <span class="device-copy">
              <strong>{{ profile.name }}</strong>
              <small>{{ profile.preferred_protocol.toUpperCase() }} · {{ profile[profile.preferred_protocol].host }}</small>
            </span>
            <ChevronRight :size="15" aria-hidden="true" />
          </button>
        </template>
        <section
          v-else
          v-for="group in groupedServerProfiles"
          :key="group.name"
          class="profile-group"
          role="group"
          :aria-label="group.name"
          :data-profile-group-name="group.name"
          :data-collapsed="profileGroupCollapsed(group.name)"
        >
          <header>
            <button
              class="profile-group-toggle"
              type="button"
              :aria-expanded="!profileGroupCollapsed(group.name)"
              :aria-label="`${profileGroupCollapsed(group.name) ? '展开' : '折叠'}分组 ${group.name}`"
              @click="toggleProfileGroup(group.name)"
            >
              <span>
                <ChevronRight v-if="profileGroupCollapsed(group.name)" :size="13" aria-hidden="true" />
                <ChevronDown v-else :size="13" aria-hidden="true" />
                {{ group.name }}
              </span>
              <b>{{ group.profiles.length }}</b>
            </button>
          </header>
          <div v-show="!profileGroupCollapsed(group.name)" class="profile-group-items">
            <button
              v-for="profile in group.profiles"
              :key="profile.id"
              class="device-row"
              :class="{ selected: profile.id === selectedProfileId }"
              type="button"
              role="option"
              :aria-selected="profile.id === selectedProfileId"
              :data-profile-row-id="profile.id"
              @click="selectedProfileId = profile.id"
              @dblclick="openProfileIfReady(profile)"
              @contextmenu.prevent="openProfileContextMenu($event, profile)"
              @keydown="handleProfileKeydown($event, profile)"
            >
              <i class="status-dot" :data-status="profile.ssh.has_password ? 'idle' : 'other'" aria-hidden="true"></i>
              <span class="device-copy">
                <strong>{{ profile.name }}</strong>
                <small>SSH · {{ profile.ssh.host }}:{{ profile.ssh.port }}</small>
              </span>
              <ChevronRight :size="15" aria-hidden="true" />
            </button>
            <p v-if="!group.profiles.length" class="empty-group">空分组</p>
          </div>
        </section>
        <div v-if="!visibleProfiles.length && (activeSection === 'temporary' || !groupedServerProfiles.length)" class="navigator-empty-state" role="status">
          <SearchX v-if="workspace.profileQuery" :size="22" aria-hidden="true" />
          <ServerCog v-else :size="22" aria-hidden="true" />
          <strong>{{ workspace.profileQuery ? '没有匹配的连接配置' : '还没有连接配置' }}</strong>
          <span>{{ workspace.profileQuery ? '尝试名称、地址、分组或备注中的关键词。' : '创建配置后，可直接打开 SSH、Telnet 或串口会话。' }}</span>
          <button v-if="workspace.profileQuery" class="secondary-button" type="button" @click="workspace.profileQuery = ''">清除搜索</button>
          <button v-else class="primary-button" type="button" @click="showProfileDialog(activeSection, null, $event)"><Plus :size="13" />新增连接</button>
        </div>
      </div>
      <section
        class="navigator-detail"
        :class="{ collapsed: navigatorDetailCollapsed }"
        :data-collapsed="navigatorDetailCollapsed ? 'true' : 'false'"
        aria-label="设备与连接详情"
      >
        <header class="navigator-detail-header">
          <div>
            <p class="eyebrow">{{ activeSection === 'devices' ? 'DEVICE DETAIL' : 'CONNECTION DETAIL' }}</p>
            <strong>{{ activeSection === 'devices' ? '设备详情' : '连接详情' }}</strong>
          </div>
          <button
            class="icon-button"
            type="button"
            :title="navigatorDetailCollapsed ? '展开详情' : '折叠详情'"
            :aria-label="navigatorDetailCollapsed ? '展开详情' : '折叠详情'"
            :aria-expanded="!navigatorDetailCollapsed"
            @click="toggleNavigatorDetail"
          >
            <ChevronRight v-if="navigatorDetailCollapsed" :size="15" />
            <ChevronDown v-else :size="15" />
          </button>
        </header>
        <div v-if="!navigatorDetailCollapsed" class="navigator-detail-content">
          <template v-if="activeSection === 'devices' && workspace.selectedDevice">
            <section
              class="device-identity"
              tabindex="0"
              title="右键打开设备快捷操作"
              @contextmenu.prevent="openDeviceInspectorContextMenu($event, workspace.selectedDevice)"
              @keydown="handleDeviceInspectorKeydown($event, workspace.selectedDevice)"
            >
              <div class="device-avatar"><ServerCog :size="21" /></div>
              <div>
                <strong>{{ workspace.selectedDevice.name }}</strong>
                <span>{{ workspace.selectedDevice.vendor }} {{ workspace.selectedDevice.model }}</span>
              </div>
              <button
                v-if="!workspace.selectedDevice.can_release"
                class="primary-button device-lease-button"
                type="button"
                :disabled="!workspace.selectedDevice.can_claim || Boolean(workspace.deviceAction)"
                :title="workspace.selectedDevice.can_claim ? '占用设备' : '当前设备不可占用或已被占用'"
                @click="workspace.runDeviceAction('claim')"
              >占用</button>
              <button
                v-else
                class="secondary-button device-lease-button"
                type="button"
                :disabled="!workspace.selectedDevice.can_release || Boolean(workspace.deviceAction)"
                :title="workspace.selectedDevice.can_release ? '释放设备' : '只有我的占用设备可释放'"
                @click="workspace.runDeviceAction('release')"
              >释放</button>
            </section>
            <section class="device-connection-panel" aria-label="当前设备连接">
              <header>
                <div>
                  <span>管理地址</span>
                  <strong class="mono">{{ workspace.selectedDevice.telnet_endpoint || workspace.selectedDevice.ssh_endpoint || workspace.selectedDevice.serial_endpoint || '连接时输入 IP 和端口' }}</strong>
                </div>
                <small>IP、端口、账号、密码均可修改</small>
              </header>
              <div v-if="!workspace.selectedDevice.is_simulated" class="device-protocol-list">
                <div class="device-protocol-action" data-protocol="ssh">
                  <button class="device-protocol-connect" type="button" :disabled="Boolean(connectionDisabledReason(workspace.selectedDevice, 'ssh')) || Boolean(workspace.openingKind)" :title="connectionDisabledReason(workspace.selectedDevice, 'ssh') || '一键连接 SSH'" @click="workspace.openSession('ssh')">
                    <span><b>SSH</b><small class="mono">{{ workspace.selectedDevice.ssh_endpoint || '未配置' }}</small></span><ChevronRight :size="15" aria-hidden="true" />
                  </button>
                  <button class="device-protocol-edit" type="button" :disabled="Boolean(workspace.openingKind)" title="编辑 SSH 的 IP、端口、账号和密码" aria-label="编辑 SSH 连接" @click="workspace.openCustomDeviceSession(workspace.selectedDevice, 'ssh')"><Pencil :size="13" /></button>
                </div>
                <div class="device-protocol-action" data-protocol="telnet">
                  <button class="device-protocol-connect" type="button" :disabled="Boolean(connectionDisabledReason(workspace.selectedDevice, 'telnet')) || Boolean(workspace.openingKind)" :title="connectionDisabledReason(workspace.selectedDevice, 'telnet') || '一键连接 Telnet'" @click="workspace.openSession('telnet')">
                    <span><b>Telnet</b><small class="mono">{{ workspace.selectedDevice.telnet_endpoint || '未配置' }}</small></span><ChevronRight :size="15" aria-hidden="true" />
                  </button>
                  <button class="device-protocol-edit" type="button" :disabled="Boolean(workspace.openingKind)" title="编辑 Telnet 的 IP、端口、账号和密码" aria-label="编辑 Telnet 连接" @click="workspace.openCustomDeviceSession(workspace.selectedDevice, 'telnet')"><Pencil :size="13" /></button>
                </div>
                <div class="device-protocol-action" data-protocol="serial">
                  <button class="device-protocol-connect" type="button" :disabled="Boolean(connectionDisabledReason(workspace.selectedDevice, 'serial')) || Boolean(workspace.openingKind)" :title="connectionDisabledReason(workspace.selectedDevice, 'serial') || '一键连接串口'" @click="workspace.openSession('serial')">
                    <span><b>串口</b><small class="mono">{{ workspace.selectedDevice.serial_endpoint || '未配置' }}</small></span><ChevronRight :size="15" aria-hidden="true" />
                  </button>
                  <button class="device-protocol-edit" type="button" :disabled="Boolean(workspace.openingKind)" title="编辑串口的 IP、端口、账号和密码" aria-label="编辑串口连接" @click="workspace.openCustomDeviceSession(workspace.selectedDevice, 'serial')"><Pencil :size="13" /></button>
                </div>
              </div>
              <button v-else class="primary-button simulated-connect-button" type="button" :disabled="Boolean(workspace.openingKind)" @click="workspace.openSimulatedSession"><MonitorDot :size="14" />打开模拟终端</button>
            </section>
            <dl
              class="property-list copyable-property-list"
              tabindex="0"
              title="右键打开设备快捷操作"
              @contextmenu.prevent="openDeviceInspectorContextMenu($event, workspace.selectedDevice)"
              @keydown="handleDeviceInspectorKeydown($event, workspace.selectedDevice)"
            >
              <div>
                <dt>状态</dt>
                <dd>
                  <span class="status-pill" :data-status="statusKind(workspace.selectedDevice.status)" :title="workspace.selectedDevice.tooltip">{{ workspace.selectedDevice.status_text || workspace.selectedDevice.status }}</span>
                  <button class="property-copy-button" type="button" title="复制状态" @click="copyDeviceInspectorField('状态', workspace.selectedDevice.status_text || workspace.selectedDevice.status)">复制</button>
                </dd>
              </div>
              <div>
                <dt>占用人</dt>
                <dd>
                  <span>{{ workspace.selectedDevice.owner || '未占用' }}</span>
                  <button class="property-copy-button" type="button" title="复制占用人" @click="copyDeviceInspectorField('占用人', workspace.selectedDevice.owner || '未占用')">复制</button>
                </dd>
              </div>
              <div>
                <dt>设备ID</dt>
                <dd>
                  <span>{{ workspace.selectedDevice.id }}</span>
                  <button class="property-copy-button" type="button" title="复制设备ID" @click="copyDeviceInspectorField('设备ID', workspace.selectedDevice.id)">复制</button>
                </dd>
              </div>
              <div>
                <dt>位置</dt>
                <dd>
                  <span>{{ workspace.selectedDevice.site }} / {{ workspace.selectedDevice.slot || workspace.selectedDevice.rack }}</span>
                  <button class="property-copy-button" type="button" title="复制位置" @click="copyDeviceInspectorField('位置', `${visibleDeviceFieldValue(workspace.selectedDevice.site)} / ${visibleDeviceFieldValue(workspace.selectedDevice.slot || workspace.selectedDevice.rack)}`)">复制</button>
                </dd>
              </div>
            </dl>
            <details :key="workspace.selectedDevice.row_id" class="device-more-details">
              <summary><span>更多设备信息</span><ChevronDown :size="14" aria-hidden="true" /></summary>
              <dl
                class="property-list copyable-property-list extended-property-list"
                tabindex="0"
                title="右键打开设备快捷操作"
                @contextmenu.prevent="openDeviceInspectorContextMenu($event, workspace.selectedDevice)"
                @keydown="handleDeviceInspectorKeydown($event, workspace.selectedDevice)"
              >
                <div>
                  <dt>板类型</dt>
                  <dd><span>{{ workspace.selectedDevice.board_type || workspace.selectedDevice.device_type || '—' }}</span><button class="property-copy-button" type="button" title="复制板类型" @click="copyDeviceInspectorField('板类型', workspace.selectedDevice.board_type || workspace.selectedDevice.device_type || '—')">复制</button></dd>
                </div>
                <div>
                  <dt>区域</dt>
                  <dd><span>{{ workspace.selectedDevice.domain || '—' }}</span><button class="property-copy-button" type="button" title="复制区域" @click="copyDeviceInspectorField('区域', visibleDeviceFieldValue(workspace.selectedDevice.domain))">复制</button></dd>
                </div>
                <div>
                  <dt>CPU</dt>
                  <dd><span>{{ workspace.selectedDevice.cpu || '—' }}</span><button class="property-copy-button" type="button" title="复制CPU" @click="copyDeviceInspectorField('CPU', visibleDeviceFieldValue(workspace.selectedDevice.cpu))">复制</button></dd>
                </div>
                <div>
                  <dt>版本</dt>
                  <dd><span>{{ workspace.selectedDevice.version || '—' }}</span><button class="property-copy-button" type="button" title="复制版本" @click="copyDeviceInspectorField('版本', visibleDeviceFieldValue(workspace.selectedDevice.version))">复制</button></dd>
                </div>
                <div>
                  <dt>SSH</dt>
                  <dd class="mono"><span>{{ workspace.selectedDevice.ssh_endpoint || '—' }}</span><button class="property-copy-button" type="button" title="复制 SSH" @click="copyDeviceInspectorField('SSH', visibleDeviceFieldValue(workspace.selectedDevice.ssh_endpoint))">复制</button></dd>
                </div>
                <div>
                  <dt>Telnet</dt>
                  <dd class="mono"><span>{{ workspace.selectedDevice.telnet_endpoint || '—' }}</span><button class="property-copy-button" type="button" title="复制 Telnet" @click="copyDeviceInspectorField('Telnet', visibleDeviceFieldValue(workspace.selectedDevice.telnet_endpoint))">复制</button></dd>
                </div>
                <div>
                  <dt>串口</dt>
                  <dd class="mono"><span>{{ workspace.selectedDevice.serial_display || workspace.selectedDevice.serial_endpoint || '—' }}</span><button class="property-copy-button" type="button" title="复制串口" @click="copyDeviceInspectorField('串口', visibleDeviceFieldValue(workspace.selectedDevice.serial_display || workspace.selectedDevice.serial_endpoint))">复制</button></dd>
                </div>
              </dl>
              <dl v-if="workspace.deviceFieldSchema.length" class="property-list copyable-property-list extended-property-list dynamic-property-list">
                <div v-for="field in workspace.deviceFieldSchema" :key="field.key">
                  <dt>{{ field.label }}</dt>
                  <dd>
                    <span>{{ dynamicDeviceFieldValue(workspace.selectedDevice, field.key) }}</span>
                    <button class="property-copy-button" type="button" :title="`复制${field.label}`" @click="copyDeviceInspectorField(field.label, dynamicDeviceFieldValue(workspace.selectedDevice, field.key))">复制</button>
                  </dd>
                </div>
              </dl>
              <button
                class="secondary-button danger-button device-power-button"
                type="button"
                :disabled="!workspace.selectedDevice.can_power_off || Boolean(workspace.deviceAction)"
                :title="workspace.selectedDevice.can_power_off ? '设备下电' : '仅我的占用且支持下电的资产设备可操作'"
                @click="workspace.runDeviceAction('power_off')"
              >设备下电</button>
            </details>
          </template>
          <template v-else-if="activeSection !== 'devices' && selectedProfile">
            <section class="device-identity">
              <div class="device-avatar"><ServerCog :size="21" /></div>
              <div>
                <strong>{{ selectedProfile.name }}</strong>
                <span>{{ selectedProfile.profile_type === 'server' ? selectedProfile.group || '未分组' : '临时连接' }}</span>
              </div>
            </section>
            <dl class="property-list">
              <div><dt>默认协议</dt><dd>{{ selectedProfile.preferred_protocol.toUpperCase() }}</dd></div>
              <div v-if="selectedProfile.ssh.host"><dt>SSH</dt><dd class="mono">{{ selectedProfile.ssh.host }}:{{ selectedProfile.ssh.port }}</dd></div>
              <div v-if="selectedProfile.telnet.host"><dt>Telnet</dt><dd class="mono">{{ selectedProfile.telnet.host }}:{{ selectedProfile.telnet.port }}</dd></div>
              <div v-if="selectedProfile.serial.host"><dt>串口</dt><dd class="mono">{{ selectedProfile.serial.host }}:{{ selectedProfile.serial.port }}</dd></div>
              <div><dt>凭据</dt><dd>{{ selectedProfile[selectedProfile.preferred_protocol].has_password ? '系统凭据库' : '未保存' }}</dd></div>
            </dl>
            <div v-if="selectedProfile.profile_type === 'server'" class="credential-actions" aria-label="管理连接凭据">
              <button v-if="selectedProfile.ssh.host" class="secondary-button" type="button" @click="workspace.manageProfileCredential(selectedProfile, 'ssh')">
                <KeyRound :size="13" />SSH 凭据
              </button>
              <button v-if="selectedProfile.telnet.host" class="secondary-button" type="button" @click="workspace.manageProfileCredential(selectedProfile, 'telnet')">
                <KeyRound :size="13" />Telnet 凭据
              </button>
              <button v-if="selectedProfile.serial.host" class="secondary-button" type="button" @click="workspace.manageProfileCredential(selectedProfile, 'serial')">
                <KeyRound :size="13" />串口凭据
              </button>
            </div>
            <div class="device-actions">
              <button class="secondary-button" type="button" @click="showProfileDialog(selectedProfile.profile_type, selectedProfile, $event)">
                <Pencil :size="14" />编辑
              </button>
              <button class="secondary-button danger-button" type="button" @click="deleteSelectedProfile">
                <Trash2 :size="14" />删除
              </button>
            </div>
            <div class="inspector-note">
              {{ selectedProfile.notes || '配置元数据存放于 SQLite，密码存放于操作系统凭据库。' }}
            </div>
          </template>
          <div v-else class="navigator-state">尚未选择项目</div>
        </div>
      </section>
      <div
        v-if="profileContextMenu"
        ref="profileContextMenuElement"
        class="profile-context-menu"
        role="menu"
        :style="{ left: `${profileContextMenu.x}px`, top: `${profileContextMenu.y}px` }"
        @click.stop
        @keydown="handleContextMenuKeydown($event, profileContextMenuElement, closeProfileContextMenuAndRestoreFocus)"
      >
        <p>{{ profileContextMenu.profile.name }}<small>{{ profileContextMenu.profile.profile_type === 'server' ? '服务器配置' : '临时连接' }}</small></p>
        <button
          v-if="profileCanConnect(profileContextMenu.profile)"
          type="button"
          role="menuitem"
          :disabled="Boolean(workspace.openingKind)"
          @click="openProfileFromContext()"
        >{{ profileDefaultOpenLabel(profileContextMenu.profile) }}</button>
        <button
          v-if="profileContextMenu.profile.ssh.host && profileContextMenu.profile.preferred_protocol !== 'ssh'"
          type="button"
          role="menuitem"
          :disabled="!profileCanConnect(profileContextMenu.profile, 'ssh') || Boolean(workspace.openingKind)"
          @click="openProfileFromContext('ssh')"
        >打开 SSH</button>
        <button
          v-if="profileContextMenu.profile.profile_type === 'temporary' && profileContextMenu.profile.telnet.host && profileContextMenu.profile.preferred_protocol !== 'telnet'"
          type="button"
          role="menuitem"
          :disabled="!profileCanConnect(profileContextMenu.profile, 'telnet') || Boolean(workspace.openingKind)"
          @click="openProfileFromContext('telnet')"
        >打开设备管理口</button>
        <button
          v-if="profileContextMenu.profile.profile_type === 'temporary' && profileContextMenu.profile.serial.host && profileContextMenu.profile.preferred_protocol !== 'serial'"
          type="button"
          role="menuitem"
          :disabled="!profileCanConnect(profileContextMenu.profile, 'serial') || Boolean(workspace.openingKind)"
          @click="openProfileFromContext('serial')"
        >打开串口</button>
        <button
          type="button"
          role="menuitem"
          @click="copyProfileText(profileConnectionCopyText(profileContextMenu.profile), `已复制连接信息: ${profileContextMenu.profile.name}`)"
        >复制连接信息</button>
        <hr v-if="profileContextMenu.profile.profile_type === 'server'" />
        <button
          v-if="profileContextMenu.profile.profile_type === 'server' && profileContextMenu.profile.ssh.host"
          type="button"
          role="menuitem"
          @click="manageProfileCredentialFromContext('ssh')"
        >管理 SSH 凭据</button>
        <button
          v-if="profileContextMenu.profile.profile_type === 'server' && profileContextMenu.profile.telnet.host"
          type="button"
          role="menuitem"
          @click="manageProfileCredentialFromContext('telnet')"
        >管理 Telnet 凭据</button>
        <button
          v-if="profileContextMenu.profile.profile_type === 'server' && profileContextMenu.profile.serial.host"
          type="button"
          role="menuitem"
          @click="manageProfileCredentialFromContext('serial')"
        >管理串口凭据</button>
        <template v-if="profileContextMenu.profile.profile_type === 'server' && (profileContextMenu.profile.group || workspace.profileGroups.some((group) => group !== profileContextMenu?.profile.group))">
          <hr />
          <button
            type="button"
            role="menuitem"
            v-if="profileContextMenu.profile.group"
            @click="moveProfileToGroupFromContext('')"
          >移动到未分组</button>
          <template v-for="group in workspace.profileGroups" :key="group">
            <button
              v-if="group !== profileContextMenu.profile.group"
              type="button"
              role="menuitem"
              @click="moveProfileToGroupFromContext(group)"
            >移动到 {{ group }}</button>
          </template>
        </template>
        <hr />
        <button type="button" role="menuitem" @click="editProfileFromContext">编辑</button>
        <button type="button" role="menuitem" class="danger-menu-item" @click="deleteProfileFromContext">删除</button>
      </div>
      <div
        v-if="deviceContextMenu"
        ref="deviceContextMenuElement"
        class="device-context-menu"
        role="menu"
        :style="{ left: `${deviceContextMenu.x}px`, top: `${deviceContextMenu.y}px` }"
        @click.stop
        @keydown="handleContextMenuKeydown($event, deviceContextMenuElement, closeDeviceContextMenuAndRestoreFocus)"
      >
        <p>{{ deviceContextMenu.device.name }}<small>{{ deviceContextMenu.device.id }}</small></p>
        <button
          v-if="deviceContextMenu.device.is_simulated"
          type="button"
          role="menuitem"
          :disabled="Boolean(workspace.openingKind)"
          @click="openDeviceContextSimulatedSession"
        >打开模拟终端</button>
        <button
          v-if="!deviceContextMenu.device.is_simulated && recommendedSessionKind(deviceContextMenu.device)"
          type="button"
          role="menuitem"
          :disabled="Boolean(workspace.openingKind)"
          title="按 SSH、Telnet、串口的优先级打开第一个可用终端"
          @click="openDeviceContextRecommendedSession"
        >快速打开推荐终端 · {{ sessionKindLabel(recommendedSessionKind(deviceContextMenu.device)) }}</button>
        <button
          v-if="deviceContextMenu.device.can_connect_telnet"
          type="button"
          role="menuitem"
          :disabled="Boolean(workspace.openingKind)"
          title="打开设备管理口"
          @click="openDeviceContextSession('telnet')"
        >打开设备管理口</button>
        <button
          v-if="deviceContextMenu.device.can_connect_ssh"
          type="button"
          role="menuitem"
          :disabled="Boolean(workspace.openingKind)"
          title="打开 Linux 后台"
          @click="openDeviceContextSession('ssh')"
        >打开 Linux 后台</button>
        <button
          v-if="deviceContextMenu.device.can_connect_serial"
          type="button"
          role="menuitem"
          :disabled="Boolean(workspace.openingKind)"
          title="打开串口"
          @click="openDeviceContextSession('serial')"
        >打开串口</button>
        <hr />
        <button
          type="button"
          role="menuitem"
          @click="copyDeviceText(deviceRowCopyText(deviceContextMenu.device), `已复制设备行: ${deviceContextMenu.device.name}`)"
        >复制设备行</button>
        <button
          v-if="endpointHost(deviceContextMenu.device.ssh_endpoint) && !deviceContextMenu.device.is_simulated"
          type="button"
          role="menuitem"
          @click="copyDeviceText(endpointHost(deviceContextMenu.device.ssh_endpoint), `已复制 SSH IP: ${deviceContextMenu.device.name}`)"
        >复制 SSH IP</button>
        <button
          v-if="endpointHost(deviceContextMenu.device.telnet_endpoint) && !deviceContextMenu.device.is_simulated"
          type="button"
          role="menuitem"
          @click="copyDeviceText(endpointHost(deviceContextMenu.device.telnet_endpoint), `已复制 Telnet IP: ${deviceContextMenu.device.name}`)"
        >复制 Telnet IP</button>
        <button
          v-if="copyableSerialText(deviceContextMenu.device)"
          type="button"
          role="menuitem"
          @click="copyDeviceText(copyableSerialText(deviceContextMenu.device), `已复制串口地址: ${deviceContextMenu.device.name}`)"
        >复制串口地址</button>
        <button
          v-if="!deviceContextMenu.device.is_simulated"
          type="button"
          role="menuitem"
          @click="copyDeviceText(deviceConnectionCopyText(deviceContextMenu.device), `已复制连接信息: ${deviceContextMenu.device.name}`)"
        >复制连接信息</button>
        <hr v-if="deviceContextMenu.device.can_claim || deviceContextMenu.device.can_release || deviceContextMenu.device.can_power_off" />
        <button
          v-if="deviceContextMenu.device.can_claim"
          type="button"
          role="menuitem"
          :disabled="Boolean(workspace.deviceAction)"
          title="占用设备"
          @click="runDeviceContextAction('claim')"
        >占用设备</button>
        <button
          v-if="deviceContextMenu.device.can_release"
          type="button"
          role="menuitem"
          :disabled="Boolean(workspace.deviceAction)"
          title="释放设备"
          @click="runDeviceContextAction('release')"
        >释放设备</button>
        <button
          v-if="deviceContextMenu.device.can_power_off"
          type="button"
          role="menuitem"
          class="danger-menu-item"
          :disabled="Boolean(workspace.deviceAction)"
          title="设备掉电"
          @click="runDeviceContextAction('power_off')"
        >设备掉电…</button>
      </div>
      <div
        class="navigator-resize-handle"
        data-testid="navigator-resize-handle"
        role="separator"
        aria-label="调整设备工作台宽度"
        aria-orientation="vertical"
        :aria-valuemin="NAVIGATOR_MIN_WIDTH"
        :aria-valuemax="navigatorMaxWidth"
        :aria-valuenow="effectiveNavigatorWidth"
        tabindex="0"
        title="拖动调整设备工作台宽度；双击恢复默认"
        @pointerdown="startNavigatorResize"
        @keydown="handleNavigatorResizeKeydown"
        @dblclick="resetNavigatorWidth"
      ><span aria-hidden="true"></span></div>
    </aside>

    <AutomationWorkspace v-if="workspace.automationPanelOpen" />
    <TransferWorkspace v-if="workspace.transferPanelOpen" />
    <UpgradeWorkspace v-if="workspace.upgradePanelOpen" />
    <PackageBuildWorkspace v-if="workspace.packageBuildPanelOpen" />
    <div
      v-if="operationPanelOpen"
      class="navigator-resize-handle operation-panel-resize-handle"
      data-testid="operation-panel-resize-handle"
      role="separator"
      aria-label="调整左侧工作台宽度"
      aria-orientation="vertical"
      :aria-valuemin="NAVIGATOR_MIN_WIDTH"
      :aria-valuemax="navigatorMaxWidth"
      :aria-valuenow="effectiveNavigatorWidth"
      tabindex="0"
      title="拖动调整左侧工作台宽度；双击恢复默认"
      @pointerdown="startNavigatorResize"
      @keydown="handleNavigatorResizeKeydown"
      @dblclick="resetNavigatorWidth"
    ><span aria-hidden="true"></span></div>

    <main class="workspace-stage">
      <header
        class="workspace-header"
        :class="{ 'has-device-tabs': workspace.sessions.length && sessionTabLayout === 'top' }"
      >
        <div
          v-if="!workspace.sessions.length || sessionTabLayout !== 'top'"
          class="workspace-title-block"
        >
          <p class="eyebrow">LIVE WORKSPACE</p>
          <h2 data-testid="live-workspace-title">{{ liveWorkspaceTitle }}</h2>
        </div>
        <div
          v-if="workspace.sessions.length && sessionTabLayout === 'top'"
          class="device-session-tabs"
          role="tablist"
          aria-label="设备会话"
        >
          <div
            v-for="group in sessionDeviceGroups"
            :key="group.id"
            class="device-session-tab"
            :class="{ active: group.id === activeSessionDeviceId }"
            :data-device-tab-id="group.id"
            @contextmenu.prevent="openDeviceSessionTabContextMenu($event, group.id)"
          >
            <button
              class="device-session-tab-select"
              type="button"
              role="tab"
              :title="`${group.label} · ${group.sessions.length} 个终端 · ${sessionHealthLabel(group.health)}`"
              :aria-label="`${group.label}，${group.sessions.length} 个终端，${sessionHealthLabel(group.health)}`"
              :aria-selected="group.id === activeSessionDeviceId"
              @click="activateSessionDevice(group.id)"
              @keydown="handleDeviceSessionTabKeydown($event, group.id)"
            >
              <span class="device-session-health" :data-state="group.health" aria-hidden="true">
                <MonitorDot :size="13" />
                <i></i>
              </span>
              <span :data-testid="group.id === activeSessionDeviceId ? 'live-workspace-title' : undefined">{{ group.label }}</span>
              <em class="device-session-health-label" :data-state="group.health">{{ sessionHealthShortLabel(group.health) }}</em>
              <small>{{ group.sessions.length }}</small>
            </button>
            <button
              class="tab-close"
              type="button"
              :aria-label="`关闭 ${group.label} 的全部终端`"
              @click.stop="closeSessionDevice(group.id)"
            ><X :size="13" /></button>
          </div>
        </div>
        <div v-if="activeSection !== 'devices'" class="connection-actions" aria-label="打开连接配置">
          <button
            v-if="selectedProfile?.ssh.host"
            class="secondary-button"
            type="button"
            :title="selectedProfile.ssh.has_password ? '打开 SSH' : '连接时输入 SSH 密码'"
            :disabled="!profileCanConnect(selectedProfile, 'ssh') || Boolean(workspace.openingKind)"
            @click="workspace.openProfileSession(selectedProfile, 'ssh')"
          >SSH</button>
          <button
            v-if="selectedProfile?.telnet.host"
            class="secondary-button"
            type="button"
            :title="selectedProfile.telnet.has_password ? '打开 Telnet' : '连接时输入 Telnet 密码'"
            :disabled="!profileCanConnect(selectedProfile, 'telnet') || Boolean(workspace.openingKind)"
            @click="workspace.openProfileSession(selectedProfile, 'telnet')"
          >Telnet</button>
          <button
            v-if="selectedProfile?.serial.host"
            class="secondary-button"
            type="button"
            :title="selectedProfile.serial.has_password ? '打开串口' : '连接时输入串口密码'"
            :disabled="!profileCanConnect(selectedProfile, 'serial') || Boolean(workspace.openingKind)"
            @click="workspace.openProfileSession(selectedProfile, 'serial')"
          >串口</button>
          <button
            class="primary-button"
            type="button"
            :disabled="!selectedProfile || !profileCanConnect(selectedProfile) || Boolean(workspace.openingKind)"
            @click="selectedProfile && workspace.openProfileSession(selectedProfile)"
          ><Plus :size="16" />连接</button>
        </div>
      </header>

      <div v-if="backendFailure" class="system-banner" data-state="backend" role="alert">
        <CircleAlert :size="15" aria-hidden="true" />
        <div>
          <strong>Python 后端连接中断</strong>
          <span>{{ backendFailure }}。应用正在自动恢复服务，也可以立即重试。</span>
        </div>
        <button type="button" title="立即重试工作区" :disabled="workspaceRecoveryBusy" @click="retryWorkspaceRecovery">
          <RefreshCw :class="{ 'spinning-icon': workspaceRecoveryBusy }" :size="13" aria-hidden="true" />
          {{ workspaceRecoveryBusy ? '重试中…' : '立即重试' }}
        </button>
      </div>
      <div v-if="workspace.error && !backendFailure" class="system-banner" role="alert">
        <CircleAlert :size="15" aria-hidden="true" />
        <div>
          <strong>工作区载入失败</strong>
          <span>{{ workspace.error }}</span>
        </div>
        <button type="button" title="立即重试工作区" :disabled="workspaceRecoveryBusy" @click="retryWorkspaceRecovery">
          <RefreshCw :class="{ 'spinning-icon': workspaceRecoveryBusy }" :size="13" aria-hidden="true" />
          {{ workspaceRecoveryBusy ? '重试中…' : '重新载入' }}
        </button>
      </div>
      <div
        class="session-workspace"
        :class="{ empty: !workspace.sessions.length }"
        :data-tab-layout="sessionTabLayout"
        :data-tab-collapsed="sessionTabLayout === 'side' && sessionTabRailCollapsed ? 'true' : 'false'"
      >
      <template v-if="workspace.sessions.length && sessionTabLayout === 'top'">
      <div class="session-tabs session-child-tabs" role="tablist" :aria-label="`${liveWorkspaceTitle} 的终端会话`">
        <div
          v-for="session in activeDeviceSessions"
          :key="session.id"
          class="session-tab"
          :class="{ active: session.id === workspace.activeSessionId }"
          :data-session-tab-id="session.id"
          draggable="true"
          @dragstart="startSessionTabDrag($event, session)"
          @contextmenu.prevent="openSessionContextMenu($event, session)"
        >
          <button
            class="session-tab-select"
            type="button"
            role="tab"
            :aria-label="`${liveWorkspaceTitle} ${activeProtocolLabels[session.id]}，${sessionStatusLabel(session.status)}`"
            :title="`${liveWorkspaceTitle} · ${activeProtocolLabels[session.id]} · ${sessionStatusLabel(session.status)}`"
            :aria-selected="session.id === workspace.activeSessionId"
            @click="activateSession(session.id)"
            @keydown="handleSessionTabKeydown($event, session)"
          >
            <i :data-state="session.status" aria-hidden="true"></i>
            <span>{{ activeProtocolLabels[session.id] }}</span>
          </button>
          <button
            class="tab-close"
            type="button"
            aria-label="关闭会话"
            @click="workspace.closeSession(session.id)"
          ><X :size="13" /></button>
        </div>
      </div>
      </template>
      <div
        v-if="sessionManagerDeviceContextMenu"
        ref="sessionManagerDeviceContextMenuElement"
        class="session-context-menu session-device-context-menu"
        role="menu"
        :style="{ left: `${sessionManagerDeviceContextMenu.x}px`, top: `${sessionManagerDeviceContextMenu.y}px` }"
        @click.stop
        @keydown="handleContextMenuKeydown($event, sessionManagerDeviceContextMenuElement, closeSessionManagerDeviceContextMenuAndRestoreFocus)"
      >
        <p>{{ sessionManagerContextDevice()?.name || sessionManagerDeviceContextMenu.deviceId }}<small>设备会话组</small></p>
        <button type="button" role="menuitem" @click="locateSessionManagerDevice()">定位到设备列表</button>
        <template v-if="sessionManagerContextDevice()">
          <button
            v-if="sessionManagerContextDevice()?.can_connect_telnet && !sessionManagerDeviceHasSession('telnet')"
            type="button"
            role="menuitem"
            :disabled="Boolean(workspace.openingKind)"
            @click="openSessionManagerDeviceSession('telnet')"
          >新建设备管理口会话</button>
          <button
            v-if="sessionManagerContextDevice()?.can_connect_ssh && !sessionManagerDeviceHasSession('ssh')"
            type="button"
            role="menuitem"
            :disabled="Boolean(workspace.openingKind)"
            @click="openSessionManagerDeviceSession('ssh')"
          >新建 Linux 后台会话</button>
          <button
            v-if="sessionManagerContextDevice()?.can_connect_serial && !sessionManagerDeviceHasSession('serial')"
            type="button"
            role="menuitem"
            :disabled="Boolean(workspace.openingKind)"
            @click="openSessionManagerDeviceSession('serial')"
          >新建串口会话</button>
        </template>
        <hr />
        <button
          type="button"
          role="menuitem"
          :disabled="!canCloseDeviceSessions(sessionManagerDeviceContextMenu.deviceId, 'current')"
          @click="runSessionManagerDeviceClose('current')"
        >关闭此设备全部会话</button>
        <button
          v-if="canCloseDeviceSessions(sessionManagerDeviceContextMenu.deviceId, 'others')"
          type="button"
          role="menuitem"
          @click="runSessionManagerDeviceClose('others')"
        >关闭其他设备会话</button>
        <button
          v-if="canCloseDeviceSessions(sessionManagerDeviceContextMenu.deviceId, 'others')"
          type="button"
          role="menuitem"
          @click="runSessionManagerDeviceClose('all')"
        >关闭所有设备会话</button>
      </div>
      <div
        v-if="sessionContextMenu"
        ref="sessionContextMenuElement"
        class="session-context-menu"
        role="menu"
        :style="{ left: `${sessionContextMenu.x}px`, top: `${sessionContextMenu.y}px` }"
        @click.stop
        @keydown="handleContextMenuKeydown($event, sessionContextMenuElement, closeSessionContextMenuAndRestoreFocus)"
      >
        <p>{{ sessionContextMenu.session.title }}<small>{{ sessionKindLabel(sessionContextMenu.session.kind) }} · {{ sessionStatusLabel(sessionContextMenu.session.status) }}</small></p>
        <button
          v-if="canReconnectSession(sessionContextMenu.session)"
          type="button"
          role="menuitem"
          :disabled="workspace.sessionActionId === sessionContextMenu.session.id"
          @click="runSessionConnectionAction('reconnect')"
        >重新连接</button>
        <button
          v-else-if="canDisconnectSession(sessionContextMenu.session)"
          type="button"
          role="menuitem"
          :disabled="workspace.sessionActionId === sessionContextMenu.session.id"
          @click="runSessionConnectionAction('disconnect')"
        >断开连接</button>
        <button type="button" role="menuitem" @click="copySessionInfoFromContext">复制会话信息</button>
        <button
          v-if="sessionDevice(sessionContextMenu.session)"
          type="button"
          role="menuitem"
          @click="locateSessionDevice(sessionContextMenu.session)"
        >定位到设备列表</button>
        <hr />
        <button
          type="button"
          role="menuitem"
          @click="runSessionContextClose('current')"
        >{{ sessionContextMenu.source === 'tab' ? '关闭当前页签' : '关闭会话' }}</button>
        <button
          v-if="sessionContextMenu.source === 'tab' && canCloseSessionRelative(sessionContextMenu.session, 'left')"
          type="button"
          role="menuitem"
          @click="runSessionContextClose('left')"
        >关闭左侧页签</button>
        <button
          v-if="sessionContextMenu.source === 'tab' && canCloseSessionRelative(sessionContextMenu.session, 'right')"
          type="button"
          role="menuitem"
          @click="runSessionContextClose('right')"
        >关闭右侧页签</button>
        <button
          v-if="canCloseSessionRelative(sessionContextMenu.session, 'others')"
          type="button"
          role="menuitem"
          @click="runSessionContextClose('others')"
        >{{ sessionContextMenu.source === 'tab' ? '关闭其他页签' : '关闭此设备其他会话' }}</button>
        <button
          v-if="canCloseSessionRelative(sessionContextMenu.session, 'others')"
          type="button"
          role="menuitem"
          @click="runSessionContextClose('all')"
        >{{ sessionContextMenu.source === 'tab' ? '关闭此设备全部页签' : '关闭此设备全部会话' }}</button>
        <template v-if="canSplitSession(sessionContextMenu.session)">
          <hr />
          <button type="button" role="menuitem" @click="splitSessionFromContext('left')">分屏到左侧</button>
          <button type="button" role="menuitem" @click="splitSessionFromContext('right')">分屏到右侧</button>
          <button type="button" role="menuitem" @click="splitSessionFromContext('top')">分屏到上方</button>
          <button type="button" role="menuitem" @click="splitSessionFromContext('bottom')">分屏到下方</button>
        </template>
        <button
          v-if="terminalSplitActive"
          type="button"
          role="menuitem"
          @click="resetTerminalSplit"
        >退出分屏</button>
      </div>

      <TerminalSplitWorkspace
        v-for="group in warmSessionDeviceGroups"
        v-show="group.id === activeSessionDeviceId"
        :key="group.id"
        :ref="(instance) => setTerminalSplitWorkspace(group.id, instance)"
        :active="group.id === activeSessionDeviceId"
        :device-id="group.id"
        :sessions="group.sessions"
        :active-session-id="activeSessionIdForDevice(group.id, group.sessions)"
        :protocol-actions="deviceProtocolActions(group.id)"
        @activate="activateSession"
        @open-protocol="openOrActivateDeviceProtocol(group.id, $event)"
        @status="workspace.updateSessionStatus"
        @automation="openSessionAutomation"
        @transfer="openSessionTransfer"
        @upgrade="openSessionUpgrade"
        @split-change="updateTerminalSplitState(group.id, $event)"
      />
      <section v-if="!workspace.activeSession" class="empty-workspace">
        <div class="empty-icon">
          <MonitorDot v-if="activeSection === 'devices'" :size="26" />
          <ServerCog v-else :size="26" />
        </div>
        <h3>{{ activeSection === 'devices' ? '准备开始设备会话' : '准备打开连接配置' }}</h3>
        <p v-if="activeSection === 'devices'">从左侧选择设备并创建终端。连接由 Python SessionHub 持有，界面刷新不会销毁会话。</p>
        <p v-else>从左侧选择连接配置。凭据由 Python 后端从操作系统凭据库读取，不会随配置列表返回。</p>
        <div v-if="activeSection === 'devices'" class="empty-workspace-context" aria-label="首个终端目标">
          <span>当前目标</span>
          <strong>{{ workspace.selectedDevice?.name || '尚未选择设备' }}</strong>
          <div v-if="availableDeviceProtocolLabels.length" aria-label="可用连接协议">
            <small v-for="label in availableDeviceProtocolLabels" :key="label">{{ label }}</small>
          </div>
          <em v-else>当前设备没有可用连接协议</em>
        </div>
        <button
          v-if="activeSection === 'devices'"
          class="primary-button"
          type="button"
          :disabled="!recommendedDeviceSessionKind || Boolean(workspace.openingKind)"
          :title="recommendedDeviceSessionKind ? `使用推荐协议打开 ${workspace.selectedDevice?.name}` : '当前设备没有可用连接协议'"
          @click="openRecommendedDeviceSession()"
        >
          <Plus :size="16" />{{ workspace.openingKind ? '正在创建终端…' : emptyWorkspaceActionLabel }}
        </button>
        <button
          v-else
          class="primary-button"
          type="button"
          :disabled="!selectedProfile || !profileCanConnect(selectedProfile)"
          @click="selectedProfile && workspace.openProfileSession(selectedProfile)"
        >
          <Plus :size="16" />连接
        </button>
      </section>
      </div>
      <CommandWorkspace />
    </main>

    <aside
      v-if="showSessionSidebar"
      class="session-sidebar"
      aria-label="右侧会话栏"
    >
      <SessionManager
        :devices="workspace.devices"
        :sessions="workspace.sessions"
        :active-session-id="workspace.activeSessionId"
        :collapsed="sessionTabRailCollapsed"
        @activate="activateSession"
        @close="workspace.closeSession"
        @session-context="openSessionManagerSessionContextMenu"
        @device-context="openSessionManagerDeviceContextMenu"
        @locate-device="locateSessionManagerDevice"
        @update-collapsed="setSessionTabRailCollapsed"
      />
    </aside>

    <footer
      class="global-status-bar"
      :data-state="workspace.notice ? (noticeRequiresAttention ? 'attention' : 'success') : 'idle'"
      role="status"
      aria-live="polite"
      aria-atomic="true"
    >
      <div class="global-status-message">
        <CircleAlert v-if="workspace.notice && noticeRequiresAttention" :size="13" aria-hidden="true" />
        <CircleCheck v-else :size="13" aria-hidden="true" />
        <span v-if="workspace.notice" data-role="notice">{{ workspace.notice }}</span>
        <span v-else data-role="idle">就绪</span>
      </div>
      <div class="global-status-context" aria-label="工作区状态">
        <span v-if="workspace.selectedDevice">{{ workspace.selectedDevice.name }}</span>
        <span>{{ workspace.connectedSessions.length }}/{{ workspace.sessions.length }} 已连接</span>
      </div>
      <button
        v-if="workspace.notice"
        type="button"
        title="关闭通知"
        aria-label="关闭通知"
        @click="clearWorkspaceNotice"
      ><X :size="12" aria-hidden="true" /></button>
    </footer>

    <ConnectionProfileDialog
      v-if="dialogType"
      :profile-type="dialogType"
      :profile="editingProfile"
      :groups="workspace.profileGroups"
      :saving="savingProfile"
      :return-focus="profileDialogReturnFocus"
      @close="dialogType = ''; editingProfile = null"
      @save="saveProfile"
    />
    <ConnectionGroupDialog
      v-if="groupDialogOpen"
      :saving="savingGroup"
      :return-focus="groupDialogReturnFocus"
      @close="groupDialogOpen = false"
      @save="createGroup"
    />
    <DeviceImportDialog
      v-if="workspace.deviceImportPreview"
      :preview="workspace.deviceImportPreview"
      :busy="workspace.deviceImportBusy"
      :return-focus="deviceImportReturnFocus"
      @close="workspace.cancelDeviceImport"
      @commit="workspace.commitDeviceImport"
    />
    <SettingsPanel
      :open="settingsPanelOpen"
      :theme-mode="themeMode"
      :always-on-top="alwaysOnTop"
      :session-tab-layout="sessionTabLayout"
      :session-tab-rail-collapsed="sessionTabRailCollapsed"
      :allow-plugin-management="workspace.deviceSourceStatus.allow_plugin_management"
      :return-focus="settingsReturnFocus"
      @close="settingsPanelOpen = false"
      @set-theme="applyRendererTheme"
      @set-always-on-top="setAlwaysOnTop"
      @set-session-tab-layout="setSessionTabLayout"
      @set-session-tab-rail-collapsed="setSessionTabRailCollapsed"
      @device-sources-changed="workspace.initialize"
    />
    <HelpPanel :open="helpPanelOpen" :return-focus="helpReturnFocus" @close="helpPanelOpen = false" />
  </div>
  </div>
</template>
