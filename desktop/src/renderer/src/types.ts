export interface DeviceSummary {
  id: string
  row_id: string
  board_id: string
  name: string
  domain: string
  device_type: string
  cpu: string
  status: string
  owner: string | null
  vendor: string
  model: string
  site: string
  rack: string
  board_type: string
  slot: string
  status_text: string
  tooltip: string
  version: string
  ssh_endpoint: string | null
  telnet_endpoint: string | null
  serial_endpoint: string | null
  serial_display: string
  can_connect_telnet: boolean
  can_connect_ssh: boolean
  can_connect_serial: boolean
  can_claim: boolean
  can_release: boolean
  can_power_off: boolean
  is_simulated: boolean
  is_temporary: boolean
  is_saved_server: boolean
  supports_power_off: boolean
}

export interface DeviceActionResponse {
  api_version: number
  device_id: string
  action: string
  message: string
  device: DeviceSummary
}

export type ProfileType = 'temporary' | 'server'

export interface ProfileEndpoint {
  host: string
  port: number
  username: string
  has_password: boolean
}

export interface ConnectionProfileSummary {
  id: string
  profile_type: ProfileType
  name: string
  group: string
  notes: string
  preferred_protocol: Exclude<SessionKind, 'simulated'>
  telnet: ProfileEndpoint
  ssh: ProfileEndpoint
  serial: ProfileEndpoint
  created_at: string
  updated_at: string
}

export interface ConnectionProfileListResponse {
  api_version: number
  profiles: ConnectionProfileSummary[]
  groups: string[]
}

export interface ConnectionProfileGroupListResponse {
  api_version: number
  groups: string[]
}

export interface ConnectionProfilePayload {
  profile_type: ProfileType
  name: string
  group: string
  notes: string
  preferred_protocol: Exclude<SessionKind, 'simulated'>
  telnet: Omit<ProfileEndpoint, 'has_password'>
  ssh: Omit<ProfileEndpoint, 'has_password'>
  serial: Omit<ProfileEndpoint, 'has_password'>
  allow_duplicate?: boolean
}

export type ConnectionProfileSecrets = Partial<Record<'telnet' | 'ssh' | 'serial', string>>

export interface CommandGroup {
  id: string
  name: string
  content: string
  sort_order: number
  created_at: string
  updated_at: string
}

export interface CommandHistoryItem {
  command: string
  device_id: string
  session_kind: string
  count: number
  last_used_at: number
}

export interface CommandWorkspaceResponse {
  api_version: number
  groups: CommandGroup[]
  current_group_id: string
  enter_sends: boolean
  history: CommandHistoryItem[]
}

export interface CommandSuggestionResponse {
  api_version: number
  suggestions: string[]
}

export interface CommandDispatchResponse {
  api_version: number
  command: string
  session_ids: string[]
}

export interface AutoResponseStep {
  pattern: string
  responses: string[]
  response_texts: string[]
  response_targets: string[]
  response_delays: number[]
  response_append_enters: boolean[]
  timeout_ms: number
}

export interface AutoResponseAction {
  kind: 'send' | 'wait' | 'loop' | 'exit' | 'condition' | 'set'
  text: string
  target: string
  delay_ms: number
  append_enter: boolean
  repeat_count: number
  interval_ms: number
  exit_pattern: string
  exit_scope: 'loop' | 'rule'
  condition_pattern: string
  condition_match_type: 'contains' | 'regex' | 'expression'
  variable_name: string
  variable_value: string
  variable_operation: 'set' | 'add' | 'subtract' | 'multiply'
  actions?: AutoResponseAction[]
}

export interface AutomationTargetOption {
  value: string
  label: string
}

export interface AutoResponseRulePayload {
  name: string
  pattern: string
  response: string
  response_text: string
  append_enter: boolean
  enabled: boolean
  case_sensitive: boolean
  once: boolean
  match_type: 'contains' | 'regex'
  delay_ms: number
  max_triggers: number
  trigger_type: 'match' | 'immediate' | 'connected' | 'delay' | 'manual'
  trigger_delay_ms: number
  loop_count: number
  kind: string
  allow_startup_trigger: boolean
  trigger_count: number
  steps?: AutoResponseStep[]
  actions?: AutoResponseAction[]
}

export interface AutomationRuleRecord {
  id: string
  rule: AutoResponseRulePayload
  created_at: string
  updated_at: string
}

export interface AutomationSessionStatus {
  session_id: string
  running_rule_ids: string[]
  waiting_rule_ids: string[]
  triggered_rule_ids: string[]
}

export interface AutomationActivityRecord {
  id: string
  timestamp: string
  event: 'started' | 'sent' | 'waiting' | 'completed' | 'failed' | 'cancelled'
  session_id: string
  rule_id: string
  name: string
  message: string
  target_session_id: string
}

export interface QuickSendButtonRecord {
  id: string
  name: string
  response_text: string
  append_enter: boolean
  sensitive: boolean
}

export interface QuickSendButtonPayload {
  name: string
  response_text: string
  append_enter: boolean
  sensitive: boolean
}

export interface AutomationWorkspaceResponse {
  api_version: number
  rules: AutomationRuleRecord[]
  sessions: AutomationSessionStatus[]
  quick_send_buttons: QuickSendButtonRecord[]
  activity: AutomationActivityRecord[]
}

export interface AutomationPreviewStep {
  path: string
  kind: 'send' | 'wait' | 'loop' | 'exit' | 'condition' | 'set'
  title: string
  detail: string
  variables: Record<string, unknown>
  text?: string
  target?: string
  append_enter?: boolean
  matched?: boolean
  operation?: string
}

export interface AutomationPreviewResponse {
  api_version: number
  steps: AutomationPreviewStep[]
  variables: Record<string, unknown>
  warnings: string[]
  truncated: boolean
  sample_output: string
}

export interface AutomationDispatchResponse {
  api_version: number
  rule_id: string
  session_id: string
  status: 'started' | 'cancelled'
}

export interface TransferSettings {
  api_version: number
  protocol: 'ftp' | 'sftp'
  host: string
  port: number
  root: string
  username: string
  writable: boolean
  has_password: boolean
  service_running: boolean
  bound_port: number
}

export interface TransferServiceLogResponse {
  api_version: number
  entries: string[]
  content: string
  client_command: string
}

export interface SharedTransferFile {
  relative_path: string
  name: string
  size_bytes: number
  modified_at: string
}

export interface SharedFileListResponse {
  api_version: number
  files: SharedTransferFile[]
  count: number
  truncated: boolean
}

export interface OperationRecord {
  id: string
  kind: string
  direction: string
  device_id: string
  session_id: string
  status: string
  stage: string
  message: string
  progress_percent: number
  cancellable: boolean
  error_code: string
  revision: number
  created_at: string
  updated_at: string
  data: Record<string, unknown>
}

export interface OperationResponse {
  api_version: number
  operation: OperationRecord
}

export interface OperationListResponse {
  api_version: number
  operations: OperationRecord[]
}

export interface PackageUpgradeManualPlanResponse {
  api_version: number
  script: string
  package_name: string
  cleanup_paths: string[]
  notes: string[]
  password_placeholder: string
}

export interface PackageUpgradeManualScriptSendResponse {
  api_version: number
  session_id: string
  command_count: number
}

export interface AiPlanResponse {
  api_version: number
  objective: string
  summary: string
  actions: Array<Record<string, unknown>>
  warnings: string[]
}

export interface AiApproval {
  id: string
  status: string
  source: string
  reason: string
  risk: string
  action: Record<string, unknown>
  created_at: string
  expires_at: string
  approval_token?: string
}

export interface AiApprovalListResponse {
  api_version: number
  approvals: AiApproval[]
}

export interface DeviceListResponse {
  api_version: number
  current_user: string
  owned_device_ids: string[]
  devices: DeviceSummary[]
}

export interface SessionSummary {
  id: string
  device_id: string
  kind: string
  title: string
  status: string
  sequence: number
  generation: number
}

export type SessionKind = 'simulated' | 'ssh' | 'telnet' | 'serial'

export interface SessionLogResponse {
  api_version: number
  session_id: string
  content: string
  truncated: boolean
}

export interface SessionLogSettings {
  api_version: number
  directory: string
  rotate_size_mb: number
  backup_count: number
  configurable: boolean
  moved_active_logs: number
}

export interface SessionLogActionResponse {
  api_version: number
  session_id: string
  path: string
  archived_path: string
}

export interface TerminalEvent {
  version: number
  type: 'terminal.output' | 'terminal.status' | 'terminal.error' | 'terminal.gap'
  sessionId: string
  sequence: number
  generation: number
  data?: string
  status?: string
  code?: string
  fromSequence?: number
  toSequence?: number
}

export interface ApplicationEvent {
  version: number
  type: string
  resourceId: string
  sequence: number
  data: Record<string, unknown>
}
