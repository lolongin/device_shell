import type { TaskRecord } from '../../types'

export type WorkflowRunTarget = {
  deviceId: string
  sessionId?: string
}

export type WorkflowRunRequest = {
  device_id: string
  device_ids: string[]
  session_ids: Record<string, string>
  protocol: 'auto' | 'simulated'
  inputs: Record<string, unknown>
  draft?: boolean
  version?: string | number
  dry_run?: boolean
  confirmed_risks?: boolean
  step_id?: string
}

export function buildWorkflowTargets(
  deviceIds: string[],
  sessions: Array<{ device_id: string; id: string; status: string }>,
  fallbackDeviceId = '',
): WorkflowRunTarget[] {
  const ids = deviceIds.length ? deviceIds : (fallbackDeviceId ? [fallbackDeviceId] : [])
  return ids.map((deviceId) => ({
    deviceId,
    sessionId: sessions.find((session) => session.device_id === deviceId && session.status === 'connected')?.id,
  }))
}

export function buildWorkflowRunRequest(
  targets: WorkflowRunTarget[],
  inputs: Record<string, unknown>,
  options: Omit<WorkflowRunRequest, 'device_id' | 'device_ids' | 'session_ids' | 'inputs'> & { inputs?: Record<string, unknown> } = { protocol: 'auto' },
): WorkflowRunRequest {
  const deviceIds = targets.map((target) => target.deviceId)
  return {
    device_id: deviceIds[0] || '',
    device_ids: deviceIds,
    session_ids: Object.fromEntries(targets.filter((target) => target.sessionId).map((target) => [target.deviceId, target.sessionId as string])),
    inputs: options.inputs || inputs,
    ...options,
  }
}

export function mergeTasks(existing: TaskRecord[], tasks: TaskRecord[]): TaskRecord[] {
  const ids = new Set(tasks.map((task) => task.id))
  return [...tasks, ...existing.filter((task) => !ids.has(task.id))]
}

export function taskFailureMessage(task: TaskRecord): string {
  return task.message || task.error_code || task.checkpoint?.error_message || ''
}
