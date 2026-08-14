import type { SessionSummary } from './types'

export type SessionHealthState = 'connected' | 'connecting' | 'disconnected' | 'failed'

export function sessionStatusLabel(status: string): string {
  return status === 'connected' ? '已连接'
    : status === 'connecting' || status === 'reconnecting' ? '连接中'
      : status === 'disconnected' ? '已断开'
        : status === 'detached' ? '通道已分离'
          : status === 'failed' ? '连接失败'
            : status === 'error' ? '连接错误'
              : status === 'closed' ? '已关闭'
                : status
}

export function aggregateSessionHealth(sessions: SessionSummary[]): SessionHealthState {
  const statuses = new Set(sessions.map((session) => session.status))
  if (statuses.has('failed') || statuses.has('error')) return 'failed'
  if (statuses.has('disconnected') || statuses.has('detached') || statuses.has('closed')) return 'disconnected'
  if (statuses.has('connecting') || statuses.has('reconnecting')) return 'connecting'
  return 'connected'
}

export function sessionHealthLabel(health: SessionHealthState): string {
  return health === 'failed' ? '存在连接失败'
    : health === 'disconnected' ? '存在已断开会话'
      : health === 'connecting' ? '会话连接中'
        : '全部已连接'
}

export function sessionHealthShortLabel(health: SessionHealthState): string {
  return health === 'failed' ? '失败'
    : health === 'disconnected' ? '已断开'
      : health === 'connecting' ? '连接中'
        : '正常'
}
