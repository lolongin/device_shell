import type {
  DeviceActionResponse,
  DeviceListResponse,
  DeviceSourceId,
  DeviceSourcePluginListResponse,
  DeviceSourcePluginTestResponse,
  DeviceSourcePluginUpdate,
  DeviceSourceStatus,
  DeviceImportCommitResponse,
  InternalAuthStatus,
  ConnectionProfileListResponse,
  ConnectionProfileGroupListResponse,
  ConnectionProfilePayload,
  ConnectionProfileSecrets,
  ConnectionProfileSummary,
  CommandWorkspaceResponse,
  CommandSuggestionResponse,
  CommandDispatchResponse,
  AutoResponseRulePayload,
  QuickSendButtonPayload,
  AutomationDispatchResponse,
  AutomationPreviewResponse,
  AutomationWorkspaceResponse,
  TransferSettings,
  TransferServiceLogResponse,
  TransferNetworkAddressesResponse,
  SharedFileListResponse,
  OperationListResponse,
  OperationResponse,
  PackageUpgradeManualPlanResponse,
  PackageUpgradeManualScriptSendResponse,
  SessionKind,
  SessionLogActionResponse,
  SessionLogResponse,
  SessionLogSettings,
  SessionSummary,
  TaskResponse,
  TaskRecord,
  TaskListResponse,
  TaskDecisionResponse,
  TaskDecisionActionPayload,
  WorkflowCatalogResponse,
  AiPlanResponse,
  AiApprovalListResponse,
  AiApproval,
  McpResponse,
  WorkflowPlanValidation
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

function backendDetailMessage(detail: unknown): string {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((issue) => {
        if (!issue || typeof issue !== 'object') return ''
        const item = issue as { loc?: unknown; msg?: unknown; type?: unknown }
        const location = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== 'body').map(String).join('.')
          : ''
        if (item.type === 'extra_forbidden' && location) {
          return `当前 Python 后端不支持参数“${location}”，请重启应用后再试。`
        }
        const message = typeof item.msg === 'string' ? item.msg : ''
        if (location && message) return `请求参数 ${location}：${message}`
        return message
      })
      .filter(Boolean)
      .join('；')
  }
  if (detail && typeof detail === 'object') {
    const item = detail as { message?: unknown; detail?: unknown }
    if (typeof item.message === 'string') return item.message
    return backendDetailMessage(item.detail)
  }
  return ''
}

export function parseBackendResponse<T>(response: BackendResponse): T {
  if (response.status < 200 || response.status >= 300) {
    const raw = response.body
    let message = raw
    let code = ''
    try {
      const payload = JSON.parse(raw) as {
        detail?: unknown
        error?: { code?: unknown; message?: unknown }
      }
      const errorMessage = typeof payload.error?.message === 'string'
        ? payload.error.message
        : ''
      message = errorMessage || backendDetailMessage(payload.detail) || raw
      code = typeof payload.error?.code === 'string' ? payload.error.code : ''
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

async function request<T>(path: string, init: RequestOptions = {}): Promise<T> {
  const response = await window.desktopApi.request({
    path,
    method: init.method,
    body: init.body
  })
  return parseBackendResponse<T>(response)
}

export const desktopApi = {
  deviceSource: (): Promise<DeviceSourceStatus> => request('/api/v1/device-source'),
  deviceSourcePlugins: (): Promise<DeviceSourcePluginListResponse> =>
    request('/api/v1/device-source/plugins'),
  updateDeviceSourcePlugin: (
    sourceId: DeviceSourceId,
    update: DeviceSourcePluginUpdate
  ): Promise<DeviceSourcePluginListResponse> =>
    request(`/api/v1/device-source/plugins/${encodeURIComponent(sourceId)}`, {
      method: 'PUT',
      body: JSON.stringify(update)
    }),
  testDeviceSourcePlugin: (sourceId: DeviceSourceId): Promise<DeviceSourcePluginTestResponse> =>
    request(`/api/v1/device-source/plugins/${encodeURIComponent(sourceId)}/test`, {
      method: 'POST'
    }),
  switchDeviceSource: (source: DeviceSourceId): Promise<DeviceSourceStatus> =>
    request('/api/v1/device-source', {
      method: 'PUT',
      body: JSON.stringify({ source })
    }),
  commitDeviceImport: (token: string): Promise<DeviceImportCommitResponse> =>
    request('/api/v1/device-source/import/commit', {
      method: 'POST',
      body: JSON.stringify({ token })
    }),
  internalAuthStatus: (): Promise<InternalAuthStatus> => request('/api/v1/internal-auth'),
  logoutInternalService: (): Promise<InternalAuthStatus> => request('/api/v1/internal-auth/session', {
    method: 'DELETE'
  }),
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
  saveTemporaryProfileWithSecrets: async (
    profileId: string,
    payload: ConnectionProfilePayload,
    secrets: ConnectionProfileSecrets
  ): Promise<ConnectionProfileSummary> => parseBackendResponse<ConnectionProfileSummary>(
    await window.desktopApi.saveTemporaryProfile({
      ...(profileId ? { profileId } : {}),
      payload,
      secrets
    })
  ),
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
  reorderCommandGroups: (groupIds: string[]): Promise<CommandWorkspaceResponse> =>
    request('/api/v1/commands/groups/order', {
      method: 'PUT',
      body: JSON.stringify({ group_ids: groupIds })
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
  previewAutomationRule: (
    rule: AutoResponseRulePayload,
    sessionId = '',
    sampleOutput = ''
  ): Promise<AutomationPreviewResponse> =>
    request('/api/v1/automation/preview', {
      method: 'POST',
      body: JSON.stringify({
        rule,
        session_id: sessionId,
        sample_output: sampleOutput,
        max_steps: 200
      })
    }),
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
  cloneAutomationRule: (ruleId: string): Promise<AutomationWorkspaceResponse> =>
    request(`/api/v1/automation/rules/${encodeURIComponent(ruleId)}/clone`, {
      method: 'POST'
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
    settings: Pick<TransferSettings, 'protocol' | 'host' | 'advertised_host' | 'port' | 'root' | 'username' | 'writable'> & {
      password?: string
    }
  ): Promise<TransferSettings> =>
    window.desktopApi.saveTransferSettings(settings).then(parseBackendResponse<TransferSettings>),
  startTransferService: (): Promise<TransferSettings> =>
    request('/api/v1/file-transfer/service/start', { method: 'POST' }),
  stopTransferService: (): Promise<TransferSettings> =>
    request('/api/v1/file-transfer/service/stop', { method: 'POST' }),
  transferServiceLog: (): Promise<TransferServiceLogResponse> =>
    request('/api/v1/file-transfer/service/log'),
  transferNetworkAddresses: (sessionId = ''): Promise<TransferNetworkAddressesResponse> =>
    request(`/api/v1/file-transfer/network-addresses?session_id=${encodeURIComponent(sessionId)}`),
  clearTransferServiceLog: (): Promise<TransferServiceLogResponse> =>
    request('/api/v1/file-transfer/service/log', { method: 'DELETE' }),
  sharedTransferFiles: (options: {
    query?: string
    sort?: 'name' | 'size' | 'modified'
    order?: 'asc' | 'desc'
    offset?: number
    limit?: number
  } = {}): Promise<SharedFileListResponse> => {
    const params = new URLSearchParams({
      limit: String(options.limit ?? 100),
      offset: String(options.offset ?? 0),
      query: options.query ?? '',
      sort: options.sort ?? 'name',
      order: options.order ?? 'asc'
    })
    return request(`/api/v1/file-transfer/files?${params.toString()}`)
  },
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
  workflows: (): Promise<WorkflowCatalogResponse> => request('/api/v1/workflows'),
  createTask: (payload: { workflow_id: string; device_id: string; parameters?: Record<string, unknown>; package?: string; options?: Record<string, unknown>; source?: string }): Promise<TaskResponse> =>
    request('/api/v1/tasks', { method: 'POST', body: JSON.stringify(payload) }),
  workflowPlanValidate: (plan: Record<string, unknown>): Promise<McpResponse<WorkflowPlanValidation>> =>
    request('/api/v1/mcp/workflow.plan.validate', { method: 'POST', body: JSON.stringify({ plan, source: 'desktop' }) }),
  workflowPlanApprove: (planId: string, planHash: string, reason = ''): Promise<McpResponse<Record<string, unknown>>> =>
    request('/api/v1/mcp/workflow.plan.approve', { method: 'POST', body: JSON.stringify({ plan_id: planId, plan_hash: planHash, reason, source: 'desktop' }) }),
  workflowRunPlan: (planId: string, planHash: string): Promise<McpResponse<{ task: TaskRecord }>> =>
    request('/api/v1/mcp/workflow.run', { method: 'POST', body: JSON.stringify({ plan_id: planId, plan_hash: planHash, source: 'desktop' }) }),
  getTask: (taskId: string): Promise<TaskResponse> =>
    request(`/api/v1/tasks/${encodeURIComponent(taskId)}`),
  listTasks: (): Promise<TaskListResponse> => request('/api/v1/tasks'),
  pauseTask: (taskId: string): Promise<TaskResponse> =>
    request(`/api/v1/tasks/${encodeURIComponent(taskId)}/pause`, { method: 'POST' }),
  resumeTask: (taskId: string, stepId = ''): Promise<TaskResponse> =>
    request(`/api/v1/tasks/${encodeURIComponent(taskId)}/resume`, { method: 'POST', body: JSON.stringify({ step_id: stepId }) }),
  cancelTask: (taskId: string): Promise<TaskResponse> =>
    request(`/api/v1/tasks/${encodeURIComponent(taskId)}/cancel`, { method: 'POST' }),
  getTaskDecision: (taskId: string): Promise<TaskDecisionResponse> =>
    request(`/api/v1/tasks/${encodeURIComponent(taskId)}/decision`),
  applyTaskDecision: (taskId: string, payload: { action: TaskDecisionActionPayload; expected_revision?: number; reason?: string }): Promise<TaskResponse> =>
    request(`/api/v1/tasks/${encodeURIComponent(taskId)}/decision`, { method: 'POST', body: JSON.stringify(payload) }),
  startManagedTransfer: async (payload: {
    direction: 'upload' | 'download'
    device_id: string
    session_id?: string
    protocol?: 'auto' | 'simulated' | 'ssh' | 'telnet' | 'serial'
    source_path: string
    destination_path: string
    overwrite: boolean
    terminal_environment: 'auto' | 'linux' | 'vrp'
    command_mode: 'vrp' | 'ftpget'
  }): Promise<OperationResponse> => {
    const send = (body: object): Promise<OperationResponse> =>
      request('/api/v1/file-transfers', {
        method: 'POST',
        body: JSON.stringify(body)
      })
    try {
      return await send(payload)
    } catch (cause) {
      const oldBackendRejectedCommandMode = cause instanceof BackendApiError
        && cause.status === 422
        && cause.message.includes('command_mode')
        && cause.message.includes('不支持参数')
      if (payload.command_mode !== 'vrp' || !oldBackendRejectedCommandMode) throw cause
      const { command_mode: _commandMode, ...legacyPayload } = payload
      return send(legacyPayload)
    }
  },
  retryManagedTransfer: (operationId: string): Promise<OperationResponse> =>
    request(`/api/v1/file-transfers/${encodeURIComponent(operationId)}/retry`, { method: 'POST' }),
  resumeTransferQueue: (sessionId: string): Promise<{ api_version: number; session_id: string; resumed_count: number }> =>
    request(`/api/v1/file-transfers/queues/${encodeURIComponent(sessionId)}/resume`, { method: 'POST' }),
  clearTransferHistory: (): Promise<{ api_version: number; deleted_count: number }> =>
    request('/api/v1/file-transfers/history', { method: 'DELETE' }),
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
