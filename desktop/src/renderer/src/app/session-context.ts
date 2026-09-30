import type { SessionSummary } from '../types'

export type SessionCloseMode = 'current' | 'left' | 'right' | 'others' | 'all'

export function closeCount(sessions: SessionSummary[], session: SessionSummary, mode: SessionCloseMode): number {
  const deviceSessions = sessions.filter((candidate) => candidate.device_id === session.device_id)
  const index = deviceSessions.findIndex((candidate) => candidate.id === session.id)
  if (index < 0 && mode !== 'all') return 0
  if (mode === 'current') return 1
  if (mode === 'left') return index
  if (mode === 'right') return Math.max(0, deviceSessions.length - index - 1)
  if (mode === 'others') return Math.max(0, deviceSessions.length - 1)
  return deviceSessions.length
}

export function canCloseSessionRelative(sessions: SessionSummary[], session: SessionSummary, mode: SessionCloseMode): boolean {
  const deviceSessions = sessions.filter((candidate) => candidate.device_id === session.device_id)
  const index = deviceSessions.findIndex((candidate) => candidate.id === session.id)
  if (mode === 'all') return deviceSessions.length > 0
  if (index < 0) return false
  if (mode === 'current') return true
  if (mode === 'left') return index > 0
  if (mode === 'right') return index < deviceSessions.length - 1
  return deviceSessions.length > 1
}

export function canCloseDeviceSessions(sessions: SessionSummary[], deviceId: string, mode: SessionCloseMode): boolean {
  const deviceIds = [...new Set(sessions.map((session) => session.device_id))]
  const index = deviceIds.indexOf(deviceId)
  if (mode === 'all') return deviceIds.length > 0
  if (index < 0) return false
  if (mode === 'current') return true
  if (mode === 'left') return index > 0
  if (mode === 'right') return index < deviceIds.length - 1
  return deviceIds.length > 1
}

export function canReconnectSession(session: SessionSummary): boolean {
  return ['disconnected', 'detached', 'error', 'failed'].includes(session.status)
}
export function canDisconnectSession(session: SessionSummary): boolean {
  return ['connected', 'connecting'].includes(session.status)
}
