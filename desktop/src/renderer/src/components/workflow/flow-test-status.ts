export function flowTestStepStatusLabel(status: string): string {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'resumed') return '执行中'
  if (normalized === 'success' || normalized === 'succeeded' || normalized === 'completed') return '已完成'
  if (normalized === 'failed') return '失败'
  if (normalized === 'cancelled') return '已取消'
  if (normalized === 'skipped') return '已跳过'
  if (normalized === 'waiting_for_user' || normalized === 'waiting_for_decision') return '等待输入'
  if (normalized === 'pending' || normalized === 'waiting' || !normalized) return '等待调度'
  return status
}

export function normalizeFlowTestStepStatus(status: string): string {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'success' || normalized === 'succeeded' || normalized === 'completed') return 'success'
  if (normalized === 'failed' || normalized === 'cancelled') return 'failed'
  if (normalized === 'running' || normalized === 'resumed') return 'running'
  if (normalized === 'waiting_for_user' || normalized === 'waiting_for_decision') return 'waiting'
  if (normalized === 'skipped') return 'skipped'
  return 'pending'
}
