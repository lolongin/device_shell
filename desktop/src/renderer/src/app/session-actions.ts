import type { DeviceSummary, SessionSummary } from '../types'

export type DeviceProtocolKind = 'ssh' | 'telnet' | 'serial'
export interface DeviceProtocolAction { kind: DeviceProtocolKind; label: string; opened: boolean }

export function recommendedSessionKind(device: DeviceSummary | null): 'simulated' | DeviceProtocolKind | '' {
  if (!device) return ''
  if (device.is_simulated) return 'simulated'
  if (device.can_connect_ssh) return 'ssh'
  if (device.can_connect_telnet) return 'telnet'
  if (device.can_connect_serial) return 'serial'
  return ''
}

export function connectionDisabledReason(device: DeviceSummary | null, kind: DeviceProtocolKind, openingKind = ''): string {
  if (!device) return '请先选择设备'
  if (openingKind) return '正在创建终端会话'
  if (kind === 'ssh' && !device.can_connect_ssh) return device.is_simulated ? '模拟终端不支持 SSH' : '设备 SSH 地址不可用'
  if (kind === 'telnet' && !device.can_connect_telnet) return device.is_simulated ? '模拟终端不支持 Telnet' : device.is_saved_server ? '保存服务器请使用 SSH' : '设备 Telnet 地址不可用'
  if (kind === 'serial' && !device.can_connect_serial) {
    if (device.is_simulated) return '模拟终端不支持串口'
    if (device.is_temporary) return '临时连接不进入设备串口通道'
    if (device.is_saved_server) return '保存服务器不支持设备串口'
    return device.serial_display || '请先占用设备后再连接串口'
  }
  return ''
}

export function profileCanConnect(profile: { ssh: { host: string }; telnet: { host: string }; serial: { host: string }; preferred_protocol: DeviceProtocolKind }, kind: DeviceProtocolKind = profile.preferred_protocol): boolean {
  return Boolean(profile[kind].host)
}

export function protocolActionsForDevice(device: DeviceSummary | undefined, sessions: SessionSummary[]): DeviceProtocolAction[] {
  if (!device || device.is_simulated) return []
  const available = [
    { kind: 'ssh' as const, label: 'SSH', available: device.can_connect_ssh },
    { kind: 'telnet' as const, label: 'Telnet', available: device.can_connect_telnet },
    { kind: 'serial' as const, label: '串口', available: device.can_connect_serial }
  ]
  return available.filter((action) => action.available).map((action) => ({ kind: action.kind, label: action.label, opened: sessions.some((session) => session.kind === action.kind) }))
}

export function protocolLabelsForSessions(sessions: SessionSummary[], labelForKind: (kind: string) => string): Record<string, string> {
  const totals = new Map<string, number>()
  const seen = new Map<string, number>()
  for (const session of sessions) {
    const label = labelForKind(session.kind)
    totals.set(label, (totals.get(label) || 0) + 1)
  }
  return Object.fromEntries(sessions.map((session) => {
    const label = labelForKind(session.kind)
    const index = (seen.get(label) || 0) + 1
    seen.set(label, index)
    return [session.id, (totals.get(label) || 0) > 1 ? `${label} #${index}` : label]
  }))
}
