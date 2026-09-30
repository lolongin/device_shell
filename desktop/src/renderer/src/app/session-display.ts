import type { SessionSummary } from '../types'

export function sessionKindLabel(kind: string): string {
  return ({ local: '本地终端', ssh: 'SSH', telnet: 'Telnet', serial: '串口', simulated: '模拟终端' } as Record<string, string>)[kind]
    || kind.toLocaleUpperCase()
}

export function activeSessionIdForDevice(
  deviceId: string,
  activeDeviceId: string,
  activeSessionId: string,
  sessions: SessionSummary[],
  rememberedId: string,
): string {
  if (deviceId === activeDeviceId) return activeSessionId
  return sessions.some((session) => session.id === rememberedId) ? rememberedId : sessions[0]?.id || ''
}
