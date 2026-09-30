import { computed, nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { ConnectionProfileSummary, DeviceSummary, SessionKind, SessionSummary } from '../types'
import { groupSessionsByDevice, resolveSessionSource } from '../app/session-groups'
import { protocolActionsForDevice, protocolLabelsForSessions } from '../app/session-actions'
import { rememberedSessionId, warmWorkspaceIds } from '../app/session-workspace'
import { sessionKindLabel as sessionKindLabelImpl } from '../app/session-display'
import { aggregateSessionHealth } from '../sessionStatus'

type DeviceProtocolKind = 'ssh' | 'telnet' | 'serial'
type SessionSourceKind = 'device' | 'temporary' | 'server' | 'local'
type SplitDirection = 'left' | 'right' | 'top' | 'bottom'

export interface SessionWorkspaceStore {
  sessions: SessionSummary[]
  activeSessionId: string
  readonly activeSession: SessionSummary | null
  readonly devices: DeviceSummary[]
  readonly profiles: ConnectionProfileSummary[]
  openSessionForDevice(device: DeviceSummary, kind: SessionKind): Promise<unknown> | unknown
  openProfileSession(profile: ConnectionProfileSummary, kind?: DeviceProtocolKind): Promise<unknown> | unknown
  closeDeviceSessionGroups(deviceId: string, mode: 'current' | 'left' | 'right' | 'others' | 'all'): Promise<unknown> | unknown
}

export interface SessionWorkspaceOptions {
  workspace: SessionWorkspaceStore
  activeSection: Ref<'devices' | 'temporary' | 'server'>
  selectedProfile: ComputedRef<ConnectionProfileSummary | null>
  maxWarmWorkspaces?: number
  terminalSplitWorkspace: Ref<{ splitDeviceGroup(deviceId: string, direction: SplitDirection): void; resetSplit(): void } | null>
  profileCanConnect: (profile: ConnectionProfileSummary, kind?: DeviceProtocolKind) => boolean
}

export function useSessionWorkspace(options: SessionWorkspaceOptions) {
  const { workspace } = options
  const maxWarmWorkspaces = options.maxWarmWorkspaces ?? 3
  const lastActiveSessionByDevice = ref<Record<string, string>>({})
  const warmDeviceWorkspaceIds = ref<string[]>([])
  const terminalSplitActive = ref(false)
  const deviceById = computed(() => new Map(workspace.devices.map((device) => [device.id, device])))
  const profileById = computed(() => new Map(workspace.profiles.map((profile) => [profile.id, profile])))
  const sessionsByDevice = computed(() => groupSessionsByDevice(workspace.sessions))
  const activeSessionDeviceId = computed(() => workspace.activeSession?.device_id || '')
  const sessionDeviceGroups = computed(() => [...sessionsByDevice.value.entries()].map(([deviceId, sessions]) => {
    const device = deviceById.value.get(deviceId) || null
    const source = resolveSessionSource(deviceId, sessions, profileById.value, deviceById.value)
    return {
      id: deviceId,
      label: profileById.value.get(deviceId)?.name || device?.name
        || (sessions[0]?.kind === 'local' ? sessions[0]?.title : sessions[0]?.title.split(' · ').slice(1).join(' · '))
        || deviceId,
      health: aggregateSessionHealth(sessions), sessions,
      sourceKind: source.kind as SessionSourceKind, sourceLabel: source.label
    }
  }))
  const warmSessionDeviceGroups = computed(() => {
    const warmIds = new Set([...warmDeviceWorkspaceIds.value, activeSessionDeviceId.value])
    return sessionDeviceGroups.value.filter((group) => warmIds.has(group.id))
  })
  const activeDeviceSessions = computed(() => sessionsByDevice.value.get(activeSessionDeviceId.value) || [])
  const activeProtocolLabels = computed<Record<string, string>>(() =>
    protocolLabelsForSessions(activeDeviceSessions.value, sessionKindLabelImpl))
  const protocolActionsBySession = computed<Record<string, Array<{ kind: DeviceProtocolKind; label: string; opened: boolean }>>>(() =>
    Object.fromEntries(workspace.sessions.map((session) => [session.id, protocolActionsForDevice(
      deviceById.value.get(session.device_id), sessionsByDevice.value.get(session.device_id) || []
    )])))

  function sessionKindLabel(kind: string): string { return sessionKindLabelImpl(kind) }
  function activateSession(sessionId: string): void {
    if (workspace.sessions.some((session) => session.id === sessionId)) workspace.activeSessionId = sessionId
  }
  function activateSessionDevice(deviceId: string): void {
    const sessions = sessionsByDevice.value.get(deviceId) || []
    if (!sessions.length) return
    const remembered = lastActiveSessionByDevice.value[deviceId]
    activateSession(sessions.some((session) => session.id === remembered) ? remembered : sessions[0].id)
  }
  function activeSessionIdForDevice(deviceId: string, sessions: SessionSummary[]): string {
    return rememberedSessionId(deviceId, activeSessionDeviceId.value, workspace.activeSessionId, sessions, lastActiveSessionByDevice.value[deviceId] || '')
  }
  function touchWarmDeviceWorkspace(deviceId: string): void {
    warmDeviceWorkspaceIds.value = warmWorkspaceIds(deviceId, warmDeviceWorkspaceIds.value,
      new Set(sessionDeviceGroups.value.map((group) => group.id)), maxWarmWorkspaces)
  }
  function updateTerminalSplitState(active: boolean): void { terminalSplitActive.value = active }
  function setTerminalSplitWorkspace(instance: unknown): void {
    options.terminalSplitWorkspace.value = instance as SessionWorkspaceOptions['terminalSplitWorkspace']['value']
  }
  function openOrActivateDeviceSession(device: DeviceSummary, kind: DeviceProtocolKind): void {
    const existing = workspace.sessions.find((session) => session.device_id === device.id && session.kind === kind)
    if (existing) return activateSession(existing.id)
    void workspace.openSessionForDevice(device, kind)
  }
  function openOrActivateDeviceProtocol(sessionId: string, kind: DeviceProtocolKind): void {
    const session = workspace.sessions.find((candidate) => candidate.id === sessionId)
    if (!session) return
    const device = deviceById.value.get(session.device_id)
    if (device) return openOrActivateDeviceSession(device, kind)
    const profile = profileById.value.get(session.device_id)
    if (profile && options.profileCanConnect(profile, kind)) void workspace.openProfileSession(profile, kind)
  }
  function splitDeviceById(deviceId: string, direction: SplitDirection): void {
    const sessions = sessionsByDevice.value.get(deviceId) || []
    const sessionId = activeSessionIdForDevice(deviceId, sessions) || sessions[0]?.id || ''
    if (!sessionId) return
    activateSession(sessionId)
    void nextTick(() => options.terminalSplitWorkspace.value?.splitDeviceGroup(deviceId, direction))
  }
  function resetTerminalSplit(): void { options.terminalSplitWorkspace.value?.resetSplit() }
  watch(activeSessionDeviceId, touchWarmDeviceWorkspace, { immediate: true })
  watch(() => workspace.activeSession, (session) => {
    if (session) lastActiveSessionByDevice.value = { ...lastActiveSessionByDevice.value, [session.device_id]: session.id }
  })
  return { deviceById, profileById, sessionsByDevice, activeSessionDeviceId, sessionDeviceGroups,
    warmSessionDeviceGroups, activeDeviceSessions, activeProtocolLabels, protocolActionsBySession,
    lastActiveSessionByDevice, warmDeviceWorkspaceIds, terminalSplitActive, sessionKindLabel,
    activateSession, activateSessionDevice, activeSessionIdForDevice, touchWarmDeviceWorkspace,
    updateTerminalSplitState, setTerminalSplitWorkspace, openOrActivateDeviceSession,
    openOrActivateDeviceProtocol, splitDeviceById, resetTerminalSplit }
}
