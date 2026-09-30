import type { SessionSummary } from '../types'

export function warmWorkspaceIds(
  deviceId: string,
  currentIds: string[],
  knownDeviceIds: Set<string>,
  max: number,
): string[] {
  if (!deviceId) return currentIds.filter((id) => knownDeviceIds.has(id)).slice(0, max)
  return [deviceId, ...currentIds.filter((id) => id !== deviceId && knownDeviceIds.has(id))].slice(0, max)
}

export function rememberedSessionId(
  deviceId: string,
  activeDeviceId: string,
  activeSessionId: string,
  sessions: SessionSummary[],
  rememberedId: string,
): string {
  if (!sessions.length) return ''
  if (deviceId === activeDeviceId && sessions.some((session) => session.id === activeSessionId)) {
    return activeSessionId
  }
  if (sessions.some((session) => session.id === rememberedId)) return rememberedId
  return sessions[0].id
}
