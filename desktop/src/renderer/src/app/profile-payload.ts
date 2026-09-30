import type { ConnectionProfilePayload, ConnectionProfileSummary } from '../types'

export function profileEndpointText(profile: ConnectionProfileSummary, kind: 'ssh' | 'telnet' | 'serial'): string {
  const endpoint = profile[kind]
  return endpoint.host ? `${endpoint.host}:${endpoint.port}` : ''
}

export function profileConnectionCopyText(profile: ConnectionProfileSummary, sessionKindLabel: (kind: string) => string): string {
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

export function profilePayload(
  profile: ConnectionProfileSummary,
  overrides: Partial<ConnectionProfilePayload> = {}
): ConnectionProfilePayload {
  return {
    profile_type: profile.profile_type,
    name: profile.name,
    group: profile.profile_type === 'server' ? profile.group : '',
    notes: profile.notes,
    preferred_protocol: profile.preferred_protocol,
    telnet: { host: profile.profile_type === 'temporary' ? profile.telnet.host : '', port: profile.telnet.port, username: profile.telnet.username },
    ssh: { host: profile.ssh.host, port: profile.ssh.port, username: profile.ssh.username },
    serial: { host: profile.profile_type === 'temporary' ? profile.serial.host : '', port: profile.serial.port, username: profile.serial.username },
    ...overrides
  }
}
