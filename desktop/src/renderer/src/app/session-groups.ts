import type { ConnectionProfileSummary, DeviceSummary, SessionSummary } from '../types'

export function groupSessionsByDevice(sessions: SessionSummary[]): Map<string, SessionSummary[]> {
  const groups = new Map<string, SessionSummary[]>()
  for (const session of sessions) {
    const current = groups.get(session.device_id)
    if (current) current.push(session)
    else groups.set(session.device_id, [session])
  }
  return groups
}

export function resolveSessionSource(
  deviceId: string,
  sessions: SessionSummary[],
  profiles: Map<string, ConnectionProfileSummary>,
  devices: Map<string, DeviceSummary>,
): { kind: 'device' | 'temporary' | 'server' | 'local'; label: string } {
  const profile = profiles.get(deviceId)
  if (profile?.profile_type === 'temporary') return { kind: 'temporary', label: '临时' }
  if (profile?.profile_type === 'server') return { kind: 'server', label: '服务器' }
  const device = devices.get(deviceId)
  if (device?.is_temporary) return { kind: 'temporary', label: '临时' }
  if (device?.is_saved_server) return { kind: 'server', label: '服务器' }
  if (sessions.some((session) => session.kind === 'local')) return { kind: 'local', label: '本地' }
  return { kind: 'device', label: '设备' }
}
