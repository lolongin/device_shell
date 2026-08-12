import type {
  DeviceActionResponse,
  DeviceListResponse,
  ConnectionProfileListResponse,
  ConnectionProfileGroupListResponse,
  ConnectionProfilePayload,
  ConnectionProfileSummary,
  CommandWorkspaceResponse,
  CommandSuggestionResponse,
  CommandDispatchResponse,
  AutoResponseRulePayload,
  QuickSendButtonPayload,
  AutomationDispatchResponse,
  AutomationWorkspaceResponse,
  TransferSettings,
  TransferServiceLogResponse,
  SharedFileListResponse,
  OperationListResponse,
  OperationResponse,
  PackageUpgradeManualPlanResponse,
  PackageUpgradeManualScriptSendResponse,
  SessionKind,
  SessionLogActionResponse,
  SessionLogResponse,
  SessionLogSettings,
  SessionSummary
  ,AiPlanResponse, AiApprovalListResponse, AiApproval
} from '../types'

let runtimePromise: Promise<BackendRuntime> | null = null

export function getRuntime(refresh = false): Promise<BackendRuntime> {
  if (refresh) runtimePromise = null
  runtimePromise ||= window.desktopApi.getRuntimeConfig()
  return runtimePromise
}

interface RequestOptions {
  method?: string
  body?: string
}

export class BackendApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string
  ) {
    super(message)
    this.name = 'BackendApiError'
  }
}

async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const response = await window.desktopApi.request({
    path,
    method: init.method,
    body: init.body
  })
  if (response.status < 200 || response.status >= 300) {
    const raw = response.body
    let message = raw
    let code = ''
    try {
      const payload = JSON.parse(raw) as {
        detail?: string
        error?: { code?: string; message?: string }
      }
      message = payload.error?.message || payload.detail || raw
      code = payload.error?.code || ''
    } catch {
      // Keep a non-JSON backend response as-is.
    }
    throw new BackendApiError(
      message || `Request failed (${response.status})`,
      response.status,
      code
    )
  }
  if (response.status === 204) return undefined as T
  return JSON.parse(response.body) as T
}

export const desktopApi = {
  devices: (): Promise<DeviceListResponse> => request('/api/v1/devices'),
  connectionProfiles: (): Promise<ConnectionProfileListResponse> =>
    request('/api/v1/connection-profiles'),
  createConnectionProfileGroup: (name: string): Promise<ConnectionProfileGroupListResponse> =>
    request('/api/v1/connection-profile-groups', {
      method: 'POST',
      body: JSON.stringify({ name })
    }),
  createConnectionProfile: (
    payload: ConnectionProfilePayload
  ): Promise<ConnectionProfileSummary> =>
    request('/api/v1/connection-profiles', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  updateConnectionProfile: (
    profileId: string,
    payload: ConnectionProfilePayload
  ): Promise<ConnectionProfileSummary> =>
    request(`/api/v1/connection-profiles/${profileId}`, {
      method: 'PUT',
      body: JSON.stringify(payload)
    }),
  deleteConnectionProfile: (profileId: string): Promise<void> =>
    request(`/api/v1/connection-profiles/${profileId}`, { method: 'DELETE' }),
  commandWorkspace: (): Promise<CommandWorkspaceResponse> =>
    request('/api/v1/commands/workspace'),
  createCommandGroup: (name = ''): Promise<CommandWorkspaceResponse> =>
    request('/api/v1/commands/groups', {
      method: 'POST',
      body: JSON.stringify({ name })
    }),
  updateCommandGroup: (
    groupId: string,
    update: { name?: string; content?: string }
  ): Promise<CommandWorkspaceResponse> =>
    request(`/api/v1/commands/groups/${encodeURIComponent(groupId)}`, {
      method: 'PUT',
      body: JSON.stringify(update)
    }),
  deleteCommandGroup: (groupId: string): Promise<CommandWorkspaceResponse> =>
    request(`/api/v1/commands/groups/${encodeURIComponent(groupId)}`, { method: 'DELETE' }),
  updateCommandPreferences: (
    update: { current_group_id?: string; enter_sends?: boolean }
  ): Promise<CommandWorkspaceResponse> =>
    request('/api/v1/commands/preferences', {
      method: 'PUT',
      body: JSON.stringify(update)
    }),
  commandSuggestions: (query: string, sessionId = ''): Promise<CommandSuggestionResponse> => {
    const params = new URLSearchParams({ query, limit: '5' })
    if (sessionId) params.set('session_id', sessionId)
    return request(`/api/v1/commands/suggestions?${params.toString()}`)
  },
  sendCommand: (sessionId: string, command: string): Promise<CommandDispatchResponse> =>
    request('/api/v1/commands/send', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, command })
    }),
  recordCommand: (sessionId: string, command: string): Promise<void> =>
    request('/api/v1/commands/history', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, command })
    }),
  broadcastCommand: (command: string): Promise<CommandDispatchResponse> =>
    request('/api/v1/commands/broadcast', {
      method: 'POST',
      body: JSON.stringify({ command })
    }),
  automationWorkspace: (): Promise<AutomationWorkspaceResponse> =>
    request('/api/v1/automation/workspace'),
  createAutomationRule: (
    rule: AutoResponseRulePayload
  ): Promise<AutomationWorkspaceResponse> =>
    request('/api/v1/automation/rules', {
      method: 'POST',
      body: JSON.stringify({ rule })
    }),
  updateAutomationRule: (
    ruleId: string,
    rule: AutoResponseRulePayload
  ): Promise<AutomationWorkspaceResponse> =>
    request(`/api/v1/automation/rules/${encodeURIComponent(ruleId)}`, {
      method: 'PUT',
      body: JSON.stringify({ rule })
    }),
  setAutomationRuleEnabled: (
    ruleId: string,
    enabled: boolean
  ): Promise<AutomationWorkspaceResponse> =>
    request(`/api/v1/automation/rules/${encodeURIComponent(ruleId)}/enabled`, {
      method: 'PUT',
      body: JSON.stringify({ enabled })
    }),
  deleteAutomationRule: (ruleId: string): Promise<void> =>
    request(`/api/v1/automation/rules/${encodeURIComponent(ruleId)}`, {
      method: 'DELETE'
    }),
  triggerAutomationRule: (
    ruleId: string,
    sessionId: string
  ): Promise<AutomationDispatchResponse> =>
    request(`/api/v1/automation/rules/${encodeURIComponent(ruleId)}/trigger`, {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId })
    }),
  cancelSessionAutomation: (sessionId: string): Promise<AutomationDispatchResponse> =>
    request(`/api/v1/automation/sessions/${encodeURIComponent(sessionId)}/cancel`, {
      method: 'POST'
    }),
  createQuickSendButton: (button: QuickSendButtonPayload): Promise<AutomationWorkspaceResponse> =>
    request('/api/v1/automation/quick-send-buttons', {
      method: 'POST',
      body: JSON.stringify(button)
    }),
  updateQuickSendButton: (
    buttonId: string,
    button: QuickSendButtonPayload
  ): Promise<AutomationWorkspaceResponse> =>
    request(`/api/v1/automation/quick-send-buttons/${encodeURIComponent(buttonId)}`, {
      method: 'PUT',
      body: JSON.stringify(button)
    }),
  deleteQuickSendButton: (buttonId: string): Promise<void> =>
    request(`/api/v1/automation/quick-send-buttons/${encodeURIComponent(buttonId)}`, {
      method: 'DELETE'
    }),
  sendQuickSendButton: (buttonId: string, sessionId: string): Promise<void> =>
    request(`/api/v1/automation/quick-send-buttons/${encodeURIComponent(buttonId)}/send`, {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId })
    }),
  transferSettings: (): Promise<TransferSettings> =>
    request('/api/v1/file-transfer/settings'),
  updateTransferSettings: (
    settings: Pick<TransferSettings, 'protocol' | 'host' | 'port' | 'root' | 'username' | 'writable'>
  ): Promise<TransferSettings> =>
    request('/api/v1/file-transfer/settings', {
      method: 'PUT',
      body: JSON.stringify(settings)
    }),
  startTransferService: (): Promise<TransferSettings> =>
    request('/api/v1/file-transfer/service/start', { method: 'POST' }),
  stopTransferService: (): Promise<TransferSettings> =>
    request('/api/v1/file-transfer/service/stop', { method: 'POST' }),
  transferServiceLog: (): Promise<TransferServiceLogResponse> =>
    request('/api/v1/file-transfer/service/log'),
  clearTransferServiceLog: (): Promise<TransferServiceLogResponse> =>
    request('/api/v1/file-transfer/service/log', { method: 'DELETE' }),
  sharedTransferFiles: (): Promise<SharedFileListResponse> =>
    request('/api/v1/file-transfer/files?limit=500'),
  operations: (kind = ''): Promise<OperationListResponse> => {
    const query = kind ? `?kind=${encodeURIComponent(kind)}` : ''
    return request(`/api/v1/operations${query}`)
  },
  aiPlan: (objective: string, selectedDeviceId = ''): Promise<AiPlanResponse> =>
    request('/api/v1/ai/plan', { method: 'POST', body: JSON.stringify({ objective, selected_device_id: selectedDeviceId }) }),
  aiApprovals: (): Promise<AiApprovalListResponse> => request('/api/v1/ai/approvals'),
  aiApprove: (approvalId: string): Promise<{ approval: AiApproval }> =>
    request(`/api/v1/ai/approvals/${encodeURIComponent(approvalId)}/approve`, { method: 'POST' }),
  aiReject: (approvalId: string): Promise<{ approval: AiApproval }> =>
    request(`/api/v1/ai/approvals/${encodeURIComponent(approvalId)}/reject`, { method: 'POST' }),
  startManagedTransfer: (payload: {
    direction: 'upload' | 'download'
    session_id: string
    source_path: string
    destination_path: string
    overwrite: boolean
  }): Promise<OperationResponse> =>
    request('/api/v1/file-transfers', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  startPackageUpgrade: (payload: {
    session_id: string
    package_path: string
    include_slave: boolean
    auto_delete_old_packages: boolean
    reboot_after_setting: boolean
    master_storage: string
    slave_storage: string
  }): Promise<OperationResponse> =>
    request('/api/v1/package-upgrades', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  approvePackageUpgradeReboot: (operationId: string): Promise<OperationResponse> =>
    request(`/api/v1/package-upgrades/${encodeURIComponent(operationId)}/approve-reboot`, {
      method: 'POST'
    }),
  packageUpgradeManualTerminal: (sessionId: string): Promise<SessionLogResponse> =>
    request(`/api/v1/package-upgrades/manual/${encodeURIComponent(sessionId)}/terminal`),
  generatePackageUpgradeManualPlan: (payload: {
    session_id: string
    package_path: string
    startup_output: string
    master_dir_output: string
    slave_dir_output: string
    include_slave: boolean
    auto_delete_old_packages: boolean
    reboot_after_setting: boolean
    master_storage: string
    slave_storage: string
  }): Promise<PackageUpgradeManualPlanResponse> =>
    request('/api/v1/package-upgrades/manual/plan', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  sendPackageUpgradeManualScript: (payload: {
    session_id: string
    script: string
    interval_ms?: number
  }): Promise<PackageUpgradeManualScriptSendResponse> =>
    request('/api/v1/package-upgrades/manual/send', {
      method: 'POST',
      body: JSON.stringify(payload)
    }),
  cancelOperation: (operationId: string): Promise<OperationResponse> =>
    request(`/api/v1/operations/${encodeURIComponent(operationId)}/cancel`, {
      method: 'POST'
    }),
  claimDevice: (deviceId: string): Promise<DeviceActionResponse> =>
    request(`/api/v1/devices/${deviceId}/claim`, { method: 'POST' }),
  releaseDevice: (deviceId: string): Promise<DeviceActionResponse> =>
    request(`/api/v1/devices/${deviceId}/release`, { method: 'POST' }),
  powerOffDevice: (deviceId: string): Promise<DeviceActionResponse> =>
    request(`/api/v1/devices/${deviceId}/power-off`, { method: 'POST' }),
  sessions: async (): Promise<SessionSummary[]> => {
    const response = await request<{ sessions: SessionSummary[] }>('/api/v1/sessions')
    return response.sessions
  },
  createSession: (deviceId: string, kind: SessionKind): Promise<SessionSummary> =>
    request('/api/v1/sessions', {
      method: 'POST',
      body: JSON.stringify({ device_id: deviceId, kind })
    }),
  reconnectSession: (sessionId: string): Promise<SessionSummary> =>
    request(`/api/v1/sessions/${sessionId}/reconnect`, { method: 'POST' }),
  disconnectSession: (sessionId: string): Promise<SessionSummary> =>
    request(`/api/v1/sessions/${sessionId}/disconnect`, { method: 'POST' }),
  sessionLog: (sessionId: string): Promise<SessionLogResponse> =>
    request(`/api/v1/sessions/${sessionId}/log`),
  sessionLogSettings: (): Promise<SessionLogSettings> =>
    request('/api/v1/settings/session-logs'),
  updateSessionLogSettings: (
    settings: Pick<SessionLogSettings, 'directory' | 'rotate_size_mb'>
  ): Promise<SessionLogSettings> =>
    request('/api/v1/settings/session-logs', {
      method: 'PUT',
      body: JSON.stringify(settings)
    }),
  createSessionLog: (sessionId: string): Promise<SessionLogActionResponse> =>
    request(`/api/v1/sessions/${encodeURIComponent(sessionId)}/log/new`, { method: 'POST' }),
  closeSession: (sessionId: string): Promise<void> =>
    request(`/api/v1/sessions/${sessionId}`, { method: 'DELETE' })
}

export async function terminalSocketUrl(sessionId: string, after = 0): Promise<string> {
  const runtime = await getRuntime(true)
  const ticketResponse = await request<{ ticket: string }>('/api/v1/ws-tickets', {
    method: 'POST',
    body: JSON.stringify({ scope: 'terminal', resource_id: sessionId })
  })
  const url = new URL(runtime.apiBaseUrl)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = `/ws/v1/terminals/${sessionId}`
  url.searchParams.set('ticket', ticketResponse.ticket)
  url.searchParams.set('after', String(after))
  return url.toString()
}

export async function applicationEventSocketUrl(after = 0): Promise<string> {
  const runtime = await getRuntime(true)
  const ticketResponse = await request<{ ticket: string }>('/api/v1/ws-tickets', {
    method: 'POST',
    body: JSON.stringify({ scope: 'events', resource_id: '' })
  })
  const url = new URL(runtime.apiBaseUrl)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = '/ws/v1/events'
  url.searchParams.set('ticket', ticketResponse.ticket)
  url.searchParams.set('after', String(after))
  return url.toString()
}
