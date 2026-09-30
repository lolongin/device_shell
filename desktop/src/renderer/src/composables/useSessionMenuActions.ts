import type { ComputedRef, Ref } from 'vue'
import type { ConnectionProfileSummary, DeviceSummary, SessionSummary } from '../types'
import type { SessionCloseMode } from '../app/session-context'

type Protocol = 'ssh' | 'telnet' | 'serial'
type SplitDirection = 'left' | 'right' | 'top' | 'bottom'
type MenuState<T> = Ref<T | null>

export interface SessionMenuWorkspace {
  sessions: SessionSummary[]
  activeSessionId: string
  openingKind: string
  notice: string
  error: string
  profileQuery: string
  filteredDevices: DeviceSummary[]
  openSessionForDevice(device: DeviceSummary, kind: Protocol): Promise<unknown> | unknown
  openProfileSession(profile: ConnectionProfileSummary, kind?: Protocol): Promise<unknown> | unknown
  manageProfileCredential(profile: ConnectionProfileSummary, kind: Protocol): Promise<unknown> | unknown
  closeDeviceSessionGroups(deviceId: string, mode: SessionCloseMode): Promise<unknown> | unknown
  closeSessionsRelative(sessionId: string, mode: SessionCloseMode, deviceId: string): Promise<unknown> | unknown
  reconnectSession(sessionId: string): Promise<unknown> | unknown
  disconnectSession(sessionId: string): Promise<unknown> | unknown
  deleteProfile(profileId: string): Promise<unknown> | unknown
  saveProfile(payload: unknown, profileId?: string): Promise<ConnectionProfileSummary | null>
  clearDeviceFilters(): void
  runDeviceAction(action: 'claim' | 'release' | 'power_off'): Promise<unknown> | unknown
}

export interface SessionMenuActionsOptions {
  workspace: SessionMenuWorkspace
  sessionMenu: MenuState<{ session: SessionSummary }>
  deviceMenu: MenuState<{ device: DeviceSummary }>
  managerMenu: MenuState<{ deviceId: string }>
  profileMenu: MenuState<{ profile: ConnectionProfileSummary }>
  deviceById: ComputedRef<Map<string, DeviceSummary>>
  profileById: ComputedRef<Map<string, ConnectionProfileSummary>>
  sessionsByDevice: ComputedRef<Map<string, SessionSummary[]>>
  selectedProfileId: Ref<string>
  activeSection: Ref<'devices' | 'temporary' | 'server'>
  selectDevice(rowId: string): void
  openRecommendedDeviceSession(device: DeviceSummary): void
  selectDeviceByDeviceId(deviceId: string): boolean
  activateSession(sessionId: string): void
  activateSessionDevice(deviceId: string): void
  expandProfileGroup(name: string): void
  profileCanConnect(profile: ConnectionProfileSummary, kind: Protocol): boolean
  profilePayload(profile: ConnectionProfileSummary, overrides?: Record<string, unknown>): unknown
  sessionKindLabel(kind: string): string
  sessionStatusLabel(status: string): string
  sessionDevice(session: SessionSummary): DeviceSummary | null
  splitSession(sessionId: string, direction: SplitDirection): void
  splitDevice(deviceId: string, direction: SplitDirection): void
  closeMenus(): void
  afterProfileDeleted?(profile: ConnectionProfileSummary): void
}

export function useSessionMenuActions(options: SessionMenuActionsOptions) {
  const { workspace, sessionMenu, deviceMenu, managerMenu, profileMenu } = options
  const close = options.closeMenus

  function openDevice(kind: Protocol): void {
    const entry = deviceMenu.value
    if (!entry) return
    options.selectDevice(entry.device.row_id)
    void workspace.openSessionForDevice(entry.device, kind)
    close()
  }
  function openRecommendedDevice(): void {
    const entry = deviceMenu.value
    if (!entry) return
    options.selectDevice(entry.device.row_id)
    options.openRecommendedDeviceSession(entry.device)
    close()
  }
  function runDeviceAction(action: 'claim' | 'release' | 'power_off'): void {
    const entry = deviceMenu.value
    if (!entry) return
    options.selectDevice(entry.device.row_id)
    if (action === 'power_off' && !window.confirm(`确定让设备“${entry.device.name}”掉电吗？当前终端和正在运行的任务会立即中断。`)) return
    void workspace.runDeviceAction(action)
    close()
  }
  function closeDeviceSessions(mode: SessionCloseMode): void {
    const entry = managerMenu.value
    if (!entry) return
    const count = workspace.sessions.filter((session) => mode === 'current' ? session.device_id === entry.deviceId : mode === 'others' ? session.device_id !== entry.deviceId : true).length
    if (count > 1 && !window.confirm(`关闭 ${count} 个设备会话吗？`)) return
    void workspace.closeDeviceSessionGroups(entry.deviceId, mode)
    close()
  }
  function openManagerSession(kind: Protocol): void {
    const entry = managerMenu.value
    if (!entry) return
    const profile = options.profileById.value.get(entry.deviceId)
    if (profile) {
      if (options.profileCanConnect(profile, kind)) void workspace.openProfileSession(profile, kind)
    } else {
      const device = options.deviceById.value.get(entry.deviceId)
      if (device) void workspace.openSessionForDevice(device, kind)
    }
    close()
  }
  function closeSession(mode: SessionCloseMode): void {
    const entry = sessionMenu.value
    if (!entry) return
    void workspace.closeSessionsRelative(entry.session.id, mode, entry.session.device_id)
    close()
  }
  function connectionAction(action: 'reconnect' | 'disconnect'): void {
    const session = sessionMenu.value?.session
    if (!session) return
    if (action === 'reconnect') void workspace.reconnectSession(session.id)
    else void workspace.disconnectSession(session.id)
    close()
  }
  function duplicateProfile(kind: Protocol): void {
    const session = sessionMenu.value?.session
    const profile = session ? options.profileById.value.get(session.device_id) : null
    if (profile && options.profileCanConnect(profile, kind)) void workspace.openProfileSession(profile, kind)
    close()
  }
  async function copySession(): Promise<void> {
    const session = sessionMenu.value?.session
    if (!session) return
    const device = options.sessionDevice(session)
    await navigator.clipboard.writeText([`会话: ${session.title}`, `协议: ${options.sessionKindLabel(session.kind)}`, `状态: ${options.sessionStatusLabel(session.status)}`, `设备: ${device?.name || session.device_id}`, `设备 ID: ${session.device_id}`].join('\n'))
    workspace.notice = `已复制会话信息: ${session.title}`
    close()
  }
  function openProfile(kind: Protocol): void {
    const profile = profileMenu.value?.profile
    if (profile) void workspace.openProfileSession(profile, kind)
    close()
  }
  function manageCredential(kind: Protocol): void {
    const profile = profileMenu.value?.profile
    if (profile) void workspace.manageProfileCredential(profile, kind)
    close()
  }
  async function deleteProfile(): Promise<void> {
    const profile = profileMenu.value?.profile
    close()
    if (!profile || !window.confirm(`确定删除“${profile.name}”吗？`)) return
    if (await workspace.deleteProfile(profile.id)) options.afterProfileDeleted?.(profile)
  }
  return {
    openDevice,
    openRecommendedDevice,
    runDeviceAction,
    closeDeviceSessions,
    openManagerSession,
    closeSession,
    connectionAction,
    duplicateProfile,
    copySession,
    openProfile,
    manageCredential,
    deleteProfile,
    splitSession: options.splitSession,
    splitDevice: options.splitDevice
  }
}
