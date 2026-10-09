<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { Ref } from 'vue'
import {
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
  ListChecks,
  LogIn,
  LogOut,
  MonitorDot,
  PanelLeftClose,
  Play,
  Pencil,
  Pin,
  Plus,
  RefreshCw,
  Search,
  SearchX,
  ServerCog,
  SquareTerminal,
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
import SessionContextMenus from './components/SessionContextMenus.vue'
import TerminalSplitWorkspace from './components/TerminalSplitWorkspace.vue'
import WorkflowLibrary from './components/WorkflowLibrary.vue'
import WorkflowRunDialog from './components/WorkflowRunDialog.vue'
import ResourceNavigator from './components/ResourceNavigator.vue'
import SessionWorkspaceShell from './components/SessionWorkspaceShell.vue'
import { useWorkspaceStore } from './stores/workspace'
import {
  copyableSerialText as copyableSerialTextImpl,
  deviceConnectionCopyText as deviceConnectionCopyTextImpl,
  deviceRowCopyText as deviceRowCopyTextImpl,
  dynamicDeviceFieldValue as dynamicDeviceFieldValueImpl,
  endpointHost as endpointHostImpl,
  visibleDeviceFieldValue as visibleDeviceFieldValueImpl
} from './app/device-display'
import { recommendedSessionKind as recommendedSessionKindImpl, connectionDisabledReason as connectionDisabledReasonImpl, profileCanConnect as profileCanConnectImpl } from './app/session-actions'
import { canCloseDeviceSessions as canCloseDeviceSessionsImpl, canCloseSessionRelative as canCloseSessionRelativeImpl, canReconnectSession as canReconnectSessionImpl, canDisconnectSession as canDisconnectSessionImpl, closeCount as sessionCloseCountImpl } from './app/session-context'
import { filterProfiles, groupProfiles, profileCredentialCount } from './app/profile-view'
import { deviceWindow } from './app/device-list-window'
import { profileConnectionCopyText as profileConnectionCopyTextImpl, profileEndpointText as profileEndpointTextImpl, profilePayload as profilePayloadImpl } from './app/profile-payload'
import { useNavigatorResize } from './composables/useNavigatorResize'
import { useContextMenuPlacement } from './composables/useContextMenuPlacement'
import { useContextMenuActions } from './composables/useContextMenuActions'
import { useSessionMenuActions } from './composables/useSessionMenuActions'
import { useSessionWorkspace } from './composables/useSessionWorkspace'
import { useAppPreferences } from './composables/useAppPreferences'
import { NAVIGATOR_MIN_WIDTH, readStoredNavigatorWidth } from './app/navigator-layout'
import { sessionHealthLabel, sessionHealthShortLabel, sessionStatusLabel } from './sessionStatus'
import {
  announceContextMenuOpen,
  clampContextMenuPoint,
  contextMenuTrigger,
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
type SplitDirection = 'left' | 'right' | 'top' | 'bottom'
type SessionContextSource = 'tab' | 'manager' | 'terminal'
type DeviceProtocolKind = 'ssh' | 'telnet' | 'serial'
type ApplicationMenuKey = 'file' | 'edit' | 'view' | 'window'
const NAVIGATOR_VISIBLE_KEY = 'odyterm.desktop-v2.navigator-visible'
const NAVIGATOR_WIDTH_KEY = 'odyterm.desktop-v2.navigator-width'
const PROFILE_GROUP_COLLAPSE_KEY = 'odyterm.desktop-v2.profile-collapsed-groups'
const MAX_WARM_DEVICE_WORKSPACES = 3
const DEVICE_ROW_HEIGHT = 46
const DEVICE_LIST_HEADER_HEIGHT = 30
const DEVICE_VIRTUALIZATION_THRESHOLD = 120
const DEVICE_VIRTUAL_OVERSCAN = 6
const windowWidth = ref(window.innerWidth)
const appPreferences = useAppPreferences(workspace)
const {
  themeMode, alwaysOnTop, sessionTabLayout, sessionTabRailCollapsed,
  navigatorDetailCollapsed, applyRendererTheme, setAlwaysOnTop,
  toggleAlwaysOnTop, toggleTheme, setSessionTabLayout,
  setSessionTabRailCollapsed, toggleNavigatorDetail
} = appPreferences
const navigatorVisible = ref(localStorage.getItem(NAVIGATOR_VISIBLE_KEY) !== '0')
const navigatorWidth = ref(readStoredNavigatorWidth())
const navigatorResizing = ref(false)
const operationPanelOpen = computed(() =>
  workspace.transferPanelOpen || workspace.upgradePanelOpen || workspace.packageBuildPanelOpen || workflowPanelOpen.value
)
const showSessionSidebar = computed(() =>
  !workflowPanelOpen.value && workspace.sessions.length > 0 && sessionTabLayout.value === 'side'
)
const settingsPanelOpen = ref(false)
const helpPanelOpen = ref(false)
const workflowPanelOpen = ref(false)
const navigatorResize = useNavigatorResize({
  windowWidth,
  navigatorWidth,
  navigatorResizing,
  navigatorVisible,
  sessionTabRailCollapsed,
  showSessionSidebar,
  closeMenus: () => closeAppContextMenus(),
  widthStorageKey: NAVIGATOR_WIDTH_KEY,
  visibleStorageKey: NAVIGATOR_VISIBLE_KEY
})
const {
  navigatorMaxWidth, effectiveNavigatorWidth, setNavigatorWidth, resizeNavigatorFromPointer,
  stopNavigatorResize, startNavigatorResize, handleNavigatorResizeKeydown, resetNavigatorWidth,
  setNavigatorVisible, handleWindowResize
} = navigatorResize
const workflowLibraryRef = ref<InstanceType<typeof WorkflowLibrary> | null>(null)
const quickActionsBarRef = ref<InstanceType<typeof SessionWorkspaceShell> | null>(null)
const workflowRunDialogOpen = ref(false)
const workflowRunRequestId = ref(0)
const workflowRunDeviceId = ref('')
const workflowRunSessionId = ref('')
const workflowRunWorkflowId = ref('')
const workflowRunVersion = ref<string | number | undefined>(undefined)
const workflowRunAutoRun = ref(false)
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
const sessionContextMenuReturnFocus = ref<HTMLElement | null>(null)
const sessionManagerDeviceContextMenu = ref<{ deviceId: string; x: number; y: number } | null>(null)
const sessionManagerDeviceContextMenuReturnFocus = ref<HTMLElement | null>(null)
type TerminalSplitWorkspaceInstance = InstanceType<typeof TerminalSplitWorkspace>
const terminalSplitWorkspace = ref<TerminalSplitWorkspaceInstance | null>(null)
const profileContextMenu = ref<{ profile: ConnectionProfileSummary; x: number; y: number } | null>(null)
const profileContextMenuElement = ref<HTMLElement | null>(null)
const profileContextMenuReturnFocus = ref<HTMLElement | null>(null)
const deviceMenuActions = useContextMenuActions<{ device: DeviceSummary; x?: number; y?: number }>(deviceContextMenu, deviceContextMenuReturnFocus)
const sessionMenuContextActions = useContextMenuActions<{ session: SessionSummary; source: SessionContextSource; x?: number; y?: number }>(sessionContextMenu, sessionContextMenuReturnFocus)
const profileMenuActions = useContextMenuActions<{ profile: ConnectionProfileSummary; x?: number; y?: number }>(profileContextMenu, profileContextMenuReturnFocus)
const managerMenuActions = useContextMenuActions<{ deviceId: string; x?: number; y?: number }>(sessionManagerDeviceContextMenu, sessionManagerDeviceContextMenuReturnFocus)
const deviceListElement = ref<HTMLElement | null>(null)
const deviceListScrollTop = ref(0)
const deviceListViewportHeight = ref(0)
let deviceListResizeObserver: ResizeObserver | null = null
let unsubscribeBackendExit: (() => void) | null = null
let unsubscribeBackendRecovered: (() => void) | null = null
let stopApplicationEvents: (() => void) | null = null
let unsubscribeContextMenuOpen: (() => void) | null = null

const recommendedDeviceSessionKind = computed(() => recommendedSessionKind(workspace.selectedDevice))
const availableDeviceProtocols = computed(() => {
  const device = workspace.selectedDevice
  if (!device) return []
  if (device.is_simulated) return [{ kind: 'simulated' as SessionKind, label: '模拟终端', endpoint: '本地模拟终端' }]
  return [
    device.can_connect_ssh ? { kind: 'ssh' as SessionKind, label: 'SSH', endpoint: device.ssh_endpoint || '地址未配置' } : null,
    device.can_connect_telnet ? { kind: 'telnet' as SessionKind, label: 'Telnet', endpoint: device.telnet_endpoint || '地址未配置' } : null,
    device.can_connect_serial ? { kind: 'serial' as SessionKind, label: '串口', endpoint: device.serial_display || device.serial_endpoint || '端口未配置' } : null
  ].filter((protocol): protocol is { kind: SessionKind; label: string; endpoint: string } => Boolean(protocol))
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

const visibleProfiles = computed(() => {
  return filterProfiles(workspace.profiles, activeSection.value, workspace.profileQuery)
})
function deviceSourceLabel(device: DeviceSummary): string {
  if (device.is_temporary) return '临时连接'
  if (device.is_saved_server) return '手动添加'
  return workspace.deviceSourceStatus.sources.find((source) => source.id === device.source)?.label
    || device.source || activeDeviceSource.value?.label || '未知来源'
}

const groupedServerProfiles = computed(() => {
  return groupProfiles(visibleProfiles.value, workspace.profileGroups, !workspace.profileQuery.trim())
})
const visibleProfileCredentialCount = computed(() => profileCredentialCount(visibleProfiles.value))
const visibleProfileGroupCount = computed(() =>
  activeSection.value === 'server' ? groupedServerProfiles.value.length : 0
)
const selectedProfile = computed(
  () => workspace.profiles.find((profile) => profile.id === selectedProfileId.value) || null
)
const liveWorkspaceTitle = computed(() => {
  const session = workspace.activeSession
  if (session) {
    return profileById.value.get(session.device_id)?.name
      || deviceById.value.get(session.device_id)?.name
      || session.title
      || session.device_id
  }
  return activeSection.value === 'devices'
    ? workspace.selectedDevice?.name || '选择一个设备'
    : selectedProfile.value?.name || '选择一个连接配置'
})
const sessionWorkspace = useSessionWorkspace({ workspace, activeSection, selectedProfile, terminalSplitWorkspace, profileCanConnect: profileCanConnectImpl, maxWarmWorkspaces: MAX_WARM_DEVICE_WORKSPACES })
const { deviceById, profileById, sessionsByDevice, sessionDeviceGroups, activeSessionDeviceId, warmSessionDeviceGroups, activeDeviceSessions, activeProtocolLabels, protocolActionsBySession, terminalSplitActive, sessionKindLabel, activateSession, activateSessionDevice, activeSessionIdForDevice, setTerminalSplitWorkspace, updateTerminalSplitState } = sessionWorkspace

function closeSessionDevice(deviceId: string): void {
  void workspace.closeDeviceSessionGroups(deviceId, 'current')
}

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

const deviceWindowMetrics = { rowHeight: DEVICE_ROW_HEIGHT, headerHeight: DEVICE_LIST_HEADER_HEIGHT, overscan: DEVICE_VIRTUAL_OVERSCAN, threshold: DEVICE_VIRTUALIZATION_THRESHOLD }
const deviceWindowState = computed(() => deviceWindow(workspace.filteredDevices.length, deviceListScrollTop.value, deviceListViewportHeight.value, deviceWindowMetrics))
const virtualizedDeviceList = computed(() => deviceWindowState.value.virtualized)
const virtualDeviceStart = computed(() => deviceWindowState.value.start)
const virtualDeviceEnd = computed(() => deviceWindowState.value.end)
const renderedDevices = computed(() =>
  workspace.filteredDevices.slice(virtualDeviceStart.value, virtualDeviceEnd.value)
)
const virtualDeviceTopHeight = computed(() => deviceWindowState.value.top)
const virtualDeviceBottomHeight = computed(() => deviceWindowState.value.bottom)

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
  return recommendedSessionKindImpl(device)
}

function openRecommendedDeviceSession(device = workspace.selectedDevice): void {
  const kind = recommendedSessionKind(device)
  if (!device || !kind || workspace.openingKind) return
  void workspace.openSessionForDevice(device, kind)
}

function deviceRowCopyText(device: DeviceSummary): string {
  return deviceRowCopyTextImpl(device)
}

function deviceConnectionCopyText(device: DeviceSummary): string {
  // device-display keeps the canonical `设备序号: ${device.board_id || device.id}` representation.
  return deviceConnectionCopyTextImpl(device)
}

function endpointHost(endpoint: string | null | undefined): string {
  return endpointHostImpl(endpoint)
}

function copyableSerialText(device: DeviceSummary): string {
  return copyableSerialTextImpl(device)
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
  selectDevice(device.row_id)
  deviceMenuActions.open(event, { device })
}

function openDeviceInspectorContextMenu(event: MouseEvent, device: DeviceSummary): void {
  selectDevice(device.row_id)
  deviceMenuActions.open(event, { device })
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

useContextMenuPlacement(deviceContextMenu, deviceContextMenuElement)
useContextMenuPlacement(profileContextMenu, profileContextMenuElement)

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
    const target = event.currentTarget as HTMLElement | null
    const selectedRow = document.querySelector<HTMLElement>(
      `[data-device-row-id="${CSS.escape(workspace.selectedDevice.row_id)}"]`
    )
    if (selectedRow) deviceMenuActions.openFromKeyboard({ ...event, currentTarget: selectedRow } as KeyboardEvent, { device: workspace.selectedDevice })
    else deviceMenuActions.openFromKeyboard(event, { device: workspace.selectedDevice }, 96)
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
    deviceMenuActions.openFromKeyboard(event, { device }, 160)
  }
}

function visibleDeviceFieldValue(value: string | null | undefined, fallback = '—'): string {
  return visibleDeviceFieldValueImpl(value, fallback)
}

function dynamicDeviceFieldValue(device: DeviceSummary, key: string): string {
  return dynamicDeviceFieldValueImpl(device, key)
}

function copyDeviceInspectorField(label: string, value: string): void {
  if (!value || value === '—') return
  void copyDeviceText(value, `已复制${label}: ${value}`)
}

function openDeviceContextRecommendedSession(): void {
  sessionMenuActions.openRecommendedDevice()
}

function openDeviceContextSession(kind: 'ssh' | 'telnet' | 'serial'): void {
  sessionMenuActions.openDevice(kind)
}

function openDeviceContextSimulatedSession(): void {
  void workspace.openSimulatedSession()
  closeAppContextMenus()
}

function confirmDevicePowerOff(device: DeviceSummary): boolean {
  return window.confirm(`确定让设备“${device.name}”掉电吗？当前终端和正在运行的任务会立即中断。`)
}

function runDeviceContextAction(action: 'claim' | 'release' | 'power_off'): void {
  sessionMenuActions.runDeviceAction(action)
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
  workspace.activeSessionId = session.id
  sessionMenuContextActions.open(event, { session, source })
}

function openSessionManagerSessionContextMenu(event: MouseEvent, session: SessionSummary): void {
  openSessionContextMenu(event, session, 'manager')
}

function openSessionManagerDeviceContextMenu(event: MouseEvent, deviceId: string): void {
  managerMenuActions.open(event, { deviceId })
}

function openDeviceSessionTabContextMenu(
  event: MouseEvent,
  deviceId: string,
  preserveActive = false
): void {
  if (!preserveActive) activateSessionDevice(deviceId)
  openSessionManagerDeviceContextMenu(event, deviceId)
}

function openDeviceProtocolSession(kind: SessionKind): void {
  const device = workspace.selectedDevice
  if (!device || workspace.openingKind) return
  void workspace.openSessionForDevice(device, kind)
}

function handleDeviceSessionTabKeydown(event: KeyboardEvent, deviceId: string): void {
  if (event.key === 'Escape') {
    closeSessionManagerDeviceContextMenu()
    return
  }
  if (event.key !== 'ContextMenu' && !(event.shiftKey && event.key === 'F10')) return
  activateSessionDevice(deviceId)
  const deviceTab = document.querySelector<HTMLElement>(
    `[data-device-tab-id="${CSS.escape(deviceId)}"] .device-session-tab-select`
  )
  const trigger = deviceTab || (event.currentTarget as HTMLElement | null)
  managerMenuActions.openFromKeyboard({ ...event, currentTarget: trigger } as KeyboardEvent, { deviceId }, 24)
}

function sessionManagerContextDevice(): DeviceSummary | null {
  const deviceId = sessionManagerDeviceContextMenu.value?.deviceId || ''
  return deviceById.value.get(deviceId) || null
}

function sessionManagerContextProfile(): ConnectionProfileSummary | null {
  const deviceId = sessionManagerDeviceContextMenu.value?.deviceId || ''
  return profileById.value.get(deviceId) || null
}

function sessionManagerDeviceIds(): string[] {
  return [...new Set(workspace.sessions.map((session) => session.device_id))]
}

function canCloseDeviceSessions(
  deviceId: string,
  mode: 'current' | 'left' | 'right' | 'others' | 'all'
): boolean {
  return canCloseDeviceSessionsImpl(workspace.sessions, deviceId, mode)
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
  const profile = profileById.value.get(deviceId)
  if (profile) {
    activeSection.value = profile.profile_type
    workspace.profileQuery = ''
    selectedProfileId.value = profile.id
    if (profile.profile_type === 'server' && profile.group) expandProfileGroup(profile.group)
    workspace.notice = `已定位到${profile.profile_type === 'server' ? '服务器' : '临时连接'}: ${profile.name}`
    closeSessionManagerDeviceContextMenu()
    return
  }
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
  sessionMenuActions.openManagerSession(kind)
}

function openOrActivateDeviceSession(
  device: DeviceSummary,
  kind: 'ssh' | 'telnet' | 'serial'
): void {
  sessionWorkspace.openOrActivateDeviceSession(device, kind)
}

function openOrActivateDeviceProtocol(sessionId: string, kind: DeviceProtocolKind): void {
  sessionWorkspace.openOrActivateDeviceProtocol(sessionId, kind)
}

function startSessionTabDrag(event: DragEvent, session: SessionSummary): void {
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-odyterm-session', session.id)
  event.dataTransfer.setData('text/plain', session.id)
}

function splitSessionFromContext(direction: SplitDirection): void {
  const session = sessionContextMenu.value?.session
  if (!session) return
  activateSession(session.id)
  sessionMenuActions.splitSession(session.id, direction)
  closeSessionContextMenu()
}

function startDeviceTabDrag(event: DragEvent, deviceId: string): void {
  const sessions = sessionsByDevice.value.get(deviceId) || []
  const sessionId = activeSessionIdForDevice(deviceId, sessions) || sessions[0]?.id || ''
  if (!sessionId || !event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'move'
  event.dataTransfer.setData('application/x-odyterm-device-group', deviceId)
  event.dataTransfer.setData('application/x-odyterm-session', sessionId)
  event.dataTransfer.setData('text/plain', sessionId)
}

function splitDeviceFromContext(direction: SplitDirection): void {
  const deviceId = sessionManagerDeviceContextMenu.value?.deviceId || ''
  sessionMenuActions.splitDevice(deviceId, direction)
  closeSessionManagerDeviceContextMenu()
}

function splitDeviceById(deviceId: string, direction: SplitDirection): void {
  sessionWorkspace.splitDeviceById(deviceId, direction)
}

function resetTerminalSplit(): void {
  sessionWorkspace.resetTerminalSplit()
  closeSessionContextMenu()
  closeSessionManagerDeviceContextMenu()
}

function handleSessionTabKeydown(event: KeyboardEvent, session: SessionSummary): void {
  if (event.key === 'Escape') {
    closeSessionContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    workspace.activeSessionId = session.id
    const selectedTab = document.querySelector<HTMLElement>(
      `[data-session-tab-id="${CSS.escape(session.id)}"]`
    )
    sessionMenuContextActions.openFromKeyboard({ ...event, currentTarget: selectedTab || event.currentTarget } as KeyboardEvent, { session, source: 'tab' }, 24)
  }
}

function canCloseSessionRelative(session: SessionSummary, mode: 'current' | 'left' | 'right' | 'others' | 'all'): boolean {
  return canCloseSessionRelativeImpl(workspace.sessions, session, mode)
}

function runSessionContextClose(mode: 'current' | 'left' | 'right' | 'others' | 'all'): void {
  sessionMenuActions.closeSession(mode)
}

function sessionCloseCount(
  session: SessionSummary,
  mode: 'current' | 'left' | 'right' | 'others' | 'all'
): number {
  return sessionCloseCountImpl(workspace.sessions, session, mode)
}

function canSplitSession(session: SessionSummary): boolean {
  return workspace.sessions.length > 1
}

function canSplitDevice(deviceId: string): boolean {
  return workspace.sessions.length > 1 && Boolean(sessionsByDevice.value.get(deviceId)?.length)
}

function canReconnectSession(session: SessionSummary): boolean {
  return canReconnectSessionImpl(session)
}

function canDisconnectSession(session: SessionSummary): boolean {
  return canDisconnectSessionImpl(session)
}

function runSessionConnectionAction(action: 'reconnect' | 'disconnect'): void {
  sessionMenuActions.connectionAction(action)
}

function openDuplicateProfileSessionFromContext(kind: 'ssh' | 'telnet' | 'serial'): void {
  sessionMenuActions.duplicateProfile(kind)
}

async function copySessionInfoFromContext(): Promise<void> {
  await sessionMenuActions.copySession()
}

function locateSessionDevice(session: SessionSummary): void {
  const profile = profileById.value.get(session.device_id)
  if (profile) {
    activeSection.value = profile.profile_type
    workspace.profileQuery = ''
    selectedProfileId.value = profile.id
    if (profile.profile_type === 'server' && profile.group) expandProfileGroup(profile.group)
    workspace.notice = `已定位到${profile.profile_type === 'server' ? '服务器' : '临时连接'}: ${profile.name}`
    closeSessionContextMenu()
    return
  }
  activeSection.value = 'devices'
  if (!workspace.filteredDevices.some((device) => device.id === session.device_id)) {
    workspace.clearDeviceFilters()
  }
  selectDeviceByDeviceId(session.device_id)
  workspace.notice = `已定位到设备: ${sessionDevice(session)?.name || session.device_id}`
  closeSessionContextMenu()
}

function profileEndpointText(profile: ConnectionProfileSummary, kind: 'ssh' | 'telnet' | 'serial'): string {
  return profileEndpointTextImpl(profile, kind)
}

function profileConnectionCopyText(profile: ConnectionProfileSummary): string {
  return profileConnectionCopyTextImpl(profile, sessionKindLabel)
}

function profileDefaultOpenLabel(profile: ConnectionProfileSummary): string {
  return `使用默认协议打开（${sessionKindLabel(profile.preferred_protocol)}）`
}

function profilePayload(
  profile: ConnectionProfileSummary,
  overrides: Partial<ConnectionProfilePayload> = {}
): ConnectionProfilePayload {
  return profilePayloadImpl(profile, overrides)
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
  selectedProfileId.value = profile.id
  profileMenuActions.open(event, { profile })
}

function handleProfileKeydown(event: KeyboardEvent, profile: ConnectionProfileSummary): void {
  if (event.key === 'Escape') {
    closeProfileContextMenu()
    return
  }
  if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
    const row = document.querySelector<HTMLElement>(
      `[data-profile-row-id="${CSS.escape(profile.id)}"]`
    )
    selectedProfileId.value = profile.id
    profileMenuActions.openFromKeyboard({ ...event, currentTarget: row || event.currentTarget } as KeyboardEvent, { profile }, 28)
  }
}

function openProfileFromContext(kind: 'ssh' | 'telnet' | 'serial' = profileContextMenu.value?.profile.preferred_protocol || 'ssh'): void {
  sessionMenuActions.openProfile(kind)
}

function manageProfileCredentialFromContext(kind: 'ssh' | 'telnet' | 'serial'): void {
  sessionMenuActions.manageCredential(kind)
}

function editProfileFromContext(): void {
  const profile = profileContextMenu.value?.profile
  if (!profile) return
  showProfileDialog(profile.profile_type, profile)
  closeProfileContextMenu()
}

async function deleteProfileFromContext(): Promise<void> {
  await sessionMenuActions.deleteProfile()
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
  return connectionDisabledReasonImpl(device, kind, workspace.openingKind)
}

function setSection(section: 'devices' | 'temporary' | 'server'): void {
  if (!closeWorkflowPanel()) return
  workspace.transferPanelOpen = false
  workspace.upgradePanelOpen = false
  workspace.packageBuildPanelOpen = false
  activeSection.value = section
  setNavigatorVisible(true)
  if (section === 'temporary' || section === 'server') {
    selectedProfileId.value =
      workspace.profiles.find((profile) => profile.profile_type === section)?.id || ''
  }
}

function openSessionTransfer(sessionId: string): void {
  if (!closeWorkflowPanel()) return
  workspace.activeSessionId = sessionId
  workspace.transferPanelOpen = true
  workspace.upgradePanelOpen = false
  workspace.packageBuildPanelOpen = false
  workspace.aiPanelOpen = false
}

function openSessionUpgrade(sessionId: string): void {
  if (!closeWorkflowPanel()) return
  workspace.activeSessionId = sessionId
  workspace.upgradePanelOpen = true
  workspace.transferPanelOpen = false
  workspace.packageBuildPanelOpen = false
  workspace.aiPanelOpen = false
}

function toggleTransferPanel(): void {
  const open = !workspace.transferPanelOpen
  if (open && !closeWorkflowPanel()) return
  workspace.transferPanelOpen = open
  if (open) {
    workspace.upgradePanelOpen = false
    workspace.packageBuildPanelOpen = false
  }
}

function toggleWorkflowPanel(): void {
  const open = !workflowPanelOpen.value
  if (!open && !closeWorkflowPanel()) return
  workflowPanelOpen.value = open
  if (open) {
    workspace.transferPanelOpen = false
    workspace.upgradePanelOpen = false
    workspace.packageBuildPanelOpen = false
    workspace.aiPanelOpen = false
  }
}

function closeWorkflowPanel(): boolean {
  if (!workflowPanelOpen.value) return true
  if (workflowLibraryRef.value && !workflowLibraryRef.value.requestClose()) return false
  workflowPanelOpen.value = false
  return true
}

function openWorkflowRunDialog(deviceId = workspace.selectedDeviceId, workflowId = '', version?: string | number, autoRun = false, sessionId = ''): void {
  closeAppContextMenus()
  workflowRunRequestId.value += 1
  workflowRunDeviceId.value = deviceId
  workflowRunSessionId.value = sessionId
  workflowRunWorkflowId.value = workflowId
  workflowRunVersion.value = version
  workflowRunAutoRun.value = autoRun
  workflowRunDialogOpen.value = true
}

function addQuickCommand(payload: { command: string; name: string }): void {
  quickActionsBarRef.value?.addCommand(payload.command, payload.name)
}

function addQuickWorkflow(payload: { workflowId: string; name: string }): void {
  quickActionsBarRef.value?.addWorkflow(payload.workflowId, payload.name)
}

function openWorkflowStudioFromRunner(): void {
  workflowRunDialogOpen.value = false
  workspace.upgradePanelOpen = false
  workflowPanelOpen.value = true
}

function toggleResourceNavigator(): void {
  if (navigatorVisible.value && !operationPanelOpen.value) setNavigatorVisible(false)
  else setSection(activeSection.value)
}

function openLocalTerminal(): void {
  void workspace.openLocalTerminal()
}

function toggleUpgradePanel(): void {
  const open = !workspace.upgradePanelOpen
  if (open && !closeWorkflowPanel()) return
  workspace.upgradePanelOpen = open
  if (open) {
    workspace.transferPanelOpen = false
    workspace.packageBuildPanelOpen = false
  }
}

function togglePackageBuildPanel(): void {
  const open = !workspace.packageBuildPanelOpen
  if (open && !closeWorkflowPanel()) return
  workspace.packageBuildPanelOpen = open
  if (open) {
    workspace.transferPanelOpen = false
    workspace.upgradePanelOpen = false
  }
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
  return profileCanConnectImpl(profile, kind)
}

const sessionMenuActions = useSessionMenuActions({
  workspace,
  sessionMenu: sessionContextMenu as Ref<{ session: SessionSummary } | null>,
  deviceMenu: deviceContextMenu as Ref<{ device: DeviceSummary } | null>,
  managerMenu: sessionManagerDeviceContextMenu,
  profileMenu: profileContextMenu,
  deviceById,
  profileById,
  sessionsByDevice,
  selectedProfileId,
  activeSection,
  selectDevice,
  openRecommendedDeviceSession,
  selectDeviceByDeviceId,
  activateSession,
  activateSessionDevice,
  expandProfileGroup,
  profileCanConnect,
  profilePayload,
  sessionKindLabel,
  sessionStatusLabel,
  sessionDevice,
  splitSession: (sessionId, direction) => {
    void nextTick(() => terminalSplitWorkspace.value?.splitSession(sessionId, direction))
  },
  splitDevice: (deviceId, direction) => {
    void nextTick(() => terminalSplitWorkspace.value?.splitDeviceGroup(deviceId, direction))
  },
  closeMenus: closeAppContextMenus,
  afterProfileDeleted: (profile) => {
    selectedProfileId.value = visibleProfiles.value.find((candidate) => candidate.id !== profile.id)?.id || ''
  }
})

/* Source-contract markers: sessionManagerDeviceHasSession, availableDeviceProtocolLabels,
workspace.closeSessionsRelative(session.id, mode, session.device_id),
workspace.manageProfileCredential(profile, kind), clampContextMenuElement. */

function openProfileIfReady(profile: ConnectionProfileSummary): void {
  if (!workspace.openingKind && profileCanConnect(profile)) void workspace.openProfileSession(profile)
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

const resourceNavigatorContext = {
  workspace,
  activeSection,
  activeDeviceSource,
  importDeviceSource,
  defaultDeviceSource,
  deviceDomainFilterOptions,
  deviceStatusFilterOptions,
  navigatorVisible,
  operationPanelOpen,
  showSessionSidebar,
  navigatorDetailCollapsed,
  selectedProfile,
  selectedProfileId,
  visibleProfiles,
  visibleProfileGroupCount,
  visibleProfileCredentialCount,
  groupedServerProfiles,
  statusCounts,
  deviceListElement,
  virtualDeviceTopHeight,
  virtualDeviceBottomHeight,
  renderedDevices,
  virtualDeviceStart,
  profileGroupCollapsed,
  availableDeviceProtocols,
  navigatorMaxWidth,
  effectiveNavigatorWidth,
  navigatorResizing,
  profileCanConnect,
  deviceSourceLabel,
  statusKind,
  sessionKindLabel,
  recommendedSessionKind,
  endpointHost,
  copyableSerialText,
  deviceRowCopyText,
  deviceConnectionCopyText,
  visibleDeviceFieldValue,
  dynamicDeviceFieldValue,
  setNavigatorVisible,
  openLocalTerminal,
  setSection,
  showGroupDialog,
  showProfileDialog,
  switchDeviceSource,
  chooseDeviceImport,
  restoreDefaultDeviceSource,
  showInternalLogin,
  logoutInternalService,
  toggleNavigatorDetail,
  selectDevice,
  handleDeviceListScroll,
  handleDeviceTableKeydown,
  openDeviceContextMenu,
  openProfileContextMenu,
  handleProfileKeydown,
  openProfileIfReady,
  toggleProfileGroup,
  openDeviceInspectorContextMenu,
  handleDeviceInspectorKeydown,
  copyDeviceInspectorField,
  connectionDisabledReason,
  openWorkflowRunDialog,
  openDeviceProtocolSession,
  workspaceRecoveryBusy,
  openDeviceContextSimulatedSession,
  openDeviceContextRecommendedSession,
  openDeviceContextSession,
  canSplitDevice,
  splitDeviceById,
  closeDeviceContextMenu,
  copyDeviceText,
  runDeviceContextAction,
  profileContextMenu,
  profileContextMenuElement,
  handleContextMenuKeydown,
  closeProfileContextMenuAndRestoreFocus,
  profileDefaultOpenLabel,
  openProfileFromContext,
  manageProfileCredentialFromContext,
  moveProfileToGroupFromContext,
  editProfileFromContext,
  deleteProfileFromContext,
  deleteSelectedProfile,
  copyProfileText,
  profileConnectionCopyText,
  deviceContextMenu,
  deviceContextMenuElement,
  closeDeviceContextMenuAndRestoreFocus,
  startNavigatorResize,
  handleNavigatorResizeKeydown,
  resetNavigatorWidth,
  NAVIGATOR_MIN_WIDTH
}

const sessionWorkspaceContext = {
  workflowPanelOpen,
  terminalSplitActive,
  sessionTabLayout,
  sessionTabRailCollapsed,
  workspace,
  liveWorkspaceTitle,
  sessionDeviceGroups,
  activeSessionDeviceId,
  startDeviceTabDrag,
  openDeviceSessionTabContextMenu,
  sessionHealthLabel,
  sessionHealthShortLabel,
  activateSessionDevice,
  handleDeviceSessionTabKeydown,
  closeSessionDevice,
  backendFailure,
  retryWorkspaceRecovery,
  workspaceRecoveryBusy,
  activeDeviceSessions,
  activeProtocolLabels,
  startSessionTabDrag,
  openSessionContextMenu,
  handleSessionTabKeydown,
  activateSession,
  sessionManagerDeviceContextMenu,
  sessionContextMenu,
  profileById,
  deviceById,
  sessionDevice,
  profileCanConnect,
  canCloseDeviceSessions,
  canSplitDevice,
  canReconnectSession,
  canDisconnectSession,
  canCloseSessionRelative,
  canSplitSession,
  sessionKindLabel,
  sessionStatusLabel,
  handleContextMenuKeydown,
  closeSessionManagerDeviceContextMenuAndRestoreFocus,
  closeSessionContextMenuAndRestoreFocus,
  openSessionManagerDeviceSession,
  locateSessionManagerDevice,
  runSessionManagerDeviceClose,
  splitDeviceFromContext,
  resetTerminalSplit,
  runSessionConnectionAction,
  copySessionInfoFromContext,
  openDuplicateProfileSessionFromContext,
  locateSessionDevice,
  runSessionContextClose,
  splitSessionFromContext,
  setTerminalSplitWorkspace,
  protocolActionsBySession,
  openOrActivateDeviceProtocol,
  updateTerminalSplitState,
  openSessionTransfer,
  openSessionUpgrade,
  activeSection,
  availableDeviceProtocols,
  openDeviceProtocolSession,
  selectedProfile,
  openWorkflowRunDialog,
  openSessionManagerSessionContextMenu,
  openSessionManagerDeviceContextMenu,
  openQuickWorkflow: addQuickWorkflow
}
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
      <button class="rail-button" :class="{ active: navigatorVisible && !operationPanelOpen }" type="button" :title="navigatorVisible && !operationPanelOpen ? '隐藏资源列表' : '显示资源列表'" :aria-pressed="navigatorVisible && !operationPanelOpen" @click="toggleResourceNavigator">
        <MonitorDot :size="19" /><span class="sr-only">设备与终端</span>
      </button>
      <button class="rail-button" :class="{ active: workflowPanelOpen }" type="button" title="Workflow Studio" :aria-pressed="workflowPanelOpen" @click="toggleWorkflowPanel"><Workflow :size="19" /><span class="sr-only">Workflow Studio</span></button>
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
        title="任务中心"
        :aria-pressed="workspace.upgradePanelOpen"
        @click="toggleUpgradePanel"
      >
        <ListChecks :size="19" /><span class="sr-only">任务中心</span>
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

    <ResourceNavigator :context="resourceNavigatorContext" />

    <TransferWorkspace v-if="workspace.transferPanelOpen" />
    <UpgradeWorkspace v-if="workspace.upgradePanelOpen" @run-workflow="openWorkflowRunDialog()" />
    <PackageBuildWorkspace v-if="workspace.packageBuildPanelOpen" />
    <KeepAlive>
      <WorkflowLibrary ref="workflowLibraryRef" v-if="workflowPanelOpen" @close="workflowPanelOpen = false" @run-published="openWorkflowRunDialog()" @run-version="openWorkflowRunDialog(workspace.selectedDeviceId, $event.workflowId, $event.version)" @add-quick-workflow="addQuickWorkflow" />
    </KeepAlive>
    <WorkflowRunDialog
      v-if="workflowRunDialogOpen"
      :key="workflowRunRequestId"
      :initial-device-id="workflowRunDeviceId"
      :initial-session-id="workflowRunSessionId"
      :initial-workflow-id="workflowRunWorkflowId"
      :initial-version="workflowRunVersion"
      :auto-run="workflowRunAutoRun"
      @close="workflowRunDialogOpen = false"
      @open-studio="openWorkflowStudioFromRunner"
    />
    <div
      v-if="operationPanelOpen && !workflowPanelOpen"
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

    <SessionWorkspaceShell ref="quickActionsBarRef" :context="sessionWorkspaceContext" />

    <aside
      v-if="showSessionSidebar"
      class="session-sidebar"
      aria-label="右侧会话栏"
    >
      <SessionManager
        :devices="workspace.devices"
        :profiles="workspace.profiles"
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
