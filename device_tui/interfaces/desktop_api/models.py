"""Versioned API models shared by the desktop backend endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


API_VERSION = 1


class DeviceFieldDescriptorModel(BaseModel):
    key: str
    label: str
    kind: Literal["text", "number", "boolean", "datetime", "enum"] = "text"
    group: str = "其他"
    order: int = 100
    searchable: bool = True
    filterable: bool = False
    default_visible: bool = False


class DeviceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    row_id: str
    board_id: str
    name: str
    domain: str
    device_type: str
    cpu: str
    status: str
    owner: str | None
    vendor: str
    model: str
    site: str
    rack: str
    board_type: str
    slot: str
    status_text: str
    tooltip: str
    version: str
    ssh_endpoint: str | None = None
    telnet_endpoint: str | None = None
    serial_endpoint: str | None = None
    serial_display: str = ""
    can_connect_telnet: bool = False
    can_connect_ssh: bool = False
    can_connect_serial: bool = False
    can_claim: bool = False
    can_release: bool = False
    can_power_off: bool = False
    is_simulated: bool = False
    is_temporary: bool = False
    is_saved_server: bool = False
    supports_power_off: bool = False
    source: str = "unknown"
    kind: str = "device"
    attributes: dict[str, object] = Field(default_factory=dict)
    extensions: dict[str, object] = Field(default_factory=dict)
    capabilities: dict[str, bool] = Field(default_factory=dict)
    parent_id: str | None = None
    children: list[str] = Field(default_factory=list)


class DeviceListResponse(BaseModel):
    api_version: int = API_VERSION
    current_user: str
    owned_device_ids: list[str]
    devices: list[DeviceSummary]
    field_schema: list[DeviceFieldDescriptorModel] = Field(default_factory=list)


class DeviceSourceOptionModel(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9._-]*$")
    label: str
    description: str
    icon: Literal["database", "globe", "spreadsheet", "plug"] = "plug"
    available: bool
    unavailable_reason: str = ""
    requires_login: bool = False
    supports_import: bool = False


class DeviceSourceStatusModel(BaseModel):
    api_version: int = API_VERSION
    product_mode: Literal["universal", "web", "spreadsheet"] = "universal"
    allow_source_switch: bool = True
    allow_plugin_management: bool = True
    allow_import: bool = True
    active_source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9._-]*$")
    default_source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9._-]*$")
    sources: list[DeviceSourceOptionModel]
    plugin_warnings: list[str] = Field(default_factory=list)
    imported_count: int = 0
    imported_file: str = ""
    imported_sheet: str = ""
    imported_at: str = ""


class DeviceSourceSwitchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9._-]*$")


class PluginConfigOptionModel(BaseModel):
    value: str
    label: str


class PluginConfigFieldModel(BaseModel):
    key: str
    label: str
    kind: Literal["text", "url", "number", "boolean", "select", "secret"]
    value: str | int | float | bool | None = None
    description: str = ""
    placeholder: str = ""
    required: bool = False
    advanced: bool = False
    minimum: float | None = None
    maximum: float | None = None
    options: list[PluginConfigOptionModel] = Field(default_factory=list)
    secret_configured: bool = False


class DeviceSourcePluginModel(BaseModel):
    id: str
    label: str
    description: str
    icon: Literal["database", "globe", "spreadsheet", "plug"] = "plug"
    version: str
    publisher: str = ""
    built_in: bool
    enabled: bool
    available: bool
    unavailable_reason: str = ""
    active: bool
    default: bool
    requires_login: bool = False
    supports_import: bool = False
    config_fields: list[PluginConfigFieldModel] = Field(default_factory=list)


class DeviceSourcePluginListResponse(BaseModel):
    api_version: int = API_VERSION
    plugins: list[DeviceSourcePluginModel]
    warnings: list[str] = Field(default_factory=list)


class DeviceSourcePluginUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    config: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    secrets: dict[str, str | None] = Field(default_factory=dict)


class DeviceSourcePluginTestResponse(BaseModel):
    api_version: int = API_VERSION
    success: bool
    message: str
    plugin: DeviceSourcePluginModel


class DeviceImportPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4_096)


class DeviceImportIssueModel(BaseModel):
    row: int
    message: str


class DeviceImportPreviewModel(BaseModel):
    api_version: int = API_VERSION
    token: str
    file_name: str
    sheet_name: str
    headers: list[str]
    total_rows: int
    valid_rows: int
    skipped_rows: int
    preview_rows: list[dict[str, str]]
    errors: list[DeviceImportIssueModel]
    warnings: list[str]


class DeviceImportCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=160)


class DeviceImportCommitResponse(BaseModel):
    api_version: int = API_VERSION
    imported_count: int
    source: DeviceSourceStatusModel


class InternalAuthStatusModel(BaseModel):
    api_version: int = API_VERSION
    available: bool
    configured: bool
    authenticated: bool
    username: str = ""
    cid: str = ""
    remembered: bool = False
    auto_login: bool = False
    auto_login_error: str = ""
    credential_warning: str = ""


class InternalAuthPasswordModel(BaseModel):
    api_version: int = API_VERSION
    password: str = Field(default="", max_length=4_096, repr=False)


class InternalAuthLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=255)
    password: str = Field(default="", max_length=4_096, repr=False)
    cid: str = Field(min_length=1, max_length=255)
    remember: bool = False
    auto_login: bool = False
    use_saved_password: bool = False


class DeviceActionResponse(BaseModel):
    api_version: int = API_VERSION
    device_id: str
    action: str
    message: str
    device: DeviceSummary
    current_user: str
    owned_device_ids: list[str]
    devices: list[DeviceSummary]
    field_schema: list[DeviceFieldDescriptorModel] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    kind: Literal["simulated", "ssh", "telnet", "serial"] = "simulated"
    title: str = Field(default="", max_length=120)
    cols: int = Field(default=160, ge=20, le=1_000)
    rows: int = Field(default=40, ge=5, le=500)


class SessionSummary(BaseModel):
    id: str
    device_id: str
    kind: str
    title: str
    status: str
    sequence: int
    generation: int = 0


class SessionListResponse(BaseModel):
    api_version: int = API_VERSION
    sessions: list[SessionSummary]


class SessionLogResponse(BaseModel):
    api_version: int = API_VERSION
    session_id: str
    content: str
    truncated: bool = False


class SessionLogSettingsModel(BaseModel):
    api_version: int = API_VERSION
    directory: str
    rotate_size_mb: int = Field(ge=1, le=1024)
    backup_count: int = Field(ge=1, le=50)
    configurable: bool = True
    moved_active_logs: int = 0


class SessionLogSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    directory: str = Field(min_length=1, max_length=4_096)
    rotate_size_mb: int = Field(ge=1, le=1024)


class SessionLogActionResponse(BaseModel):
    api_version: int = API_VERSION
    session_id: str
    path: str
    archived_path: str = ""


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    api_version: int = API_VERSION


class PersistenceDiagnostics(BaseModel):
    data_root: str
    database_path: str
    schema_version_before: int
    schema_version_after: int
    target_schema_version: int
    migrated: bool
    backup_created: bool
    backup_path: str | None = None


class DiagnosticsResponse(BaseModel):
    api_version: int = API_VERSION
    persistence: PersistenceDiagnostics | None = None
    legacy_imports: dict[str, dict[str, int]]
    log_policy: dict[str, int]


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    api_version: int = API_VERSION
    detail: str
    error: ErrorDetail


class WebSocketTicketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["terminal", "events"]
    resource_id: str = Field(default="", max_length=160)


class WebSocketTicketResponse(BaseModel):
    api_version: int = API_VERSION
    ticket: str
    expires_in_seconds: int


class ProfileEndpointModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(default="", max_length=255)
    port: int = Field(default=0, ge=0, le=65535)
    username: str = Field(default="", max_length=255)
    has_password: bool = False


class ConnectionProfileSummary(BaseModel):
    id: str
    profile_type: Literal["temporary", "server"]
    name: str
    group: str
    notes: str
    preferred_protocol: Literal["simulated", "ssh", "telnet", "serial"]
    telnet: ProfileEndpointModel
    ssh: ProfileEndpointModel
    serial: ProfileEndpointModel
    created_at: str
    updated_at: str


class ConnectionProfileListResponse(BaseModel):
    api_version: int = API_VERSION
    profiles: list[ConnectionProfileSummary]
    groups: list[str]


class ConnectionProfileGroupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)


class ConnectionProfileGroupListResponse(BaseModel):
    api_version: int = API_VERSION
    groups: list[str]


class ProfileCredentialUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=4_096, repr=False)


class OneTimeCredentialSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1, max_length=160)
    kind: Literal["ssh", "telnet", "serial"]
    password: str = Field(min_length=1, max_length=4_096, repr=False)
    title: str = Field(default="", max_length=120)
    cols: int = Field(default=160, ge=20, le=1_000)
    rows: int = Field(default=40, ge=5, le=500)


class DirectCredentialSessionRequest(BaseModel):
    """One-time device target assembled inside the trusted desktop boundary."""

    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=1, max_length=160)
    kind: Literal["ssh", "telnet", "serial"]
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=4_096, repr=False)
    title: str = Field(default="", max_length=120)
    cols: int = Field(default=160, ge=20, le=1_000)
    rows: int = Field(default=40, ge=5, le=500)


class CommandGroupModel(BaseModel):
    id: str
    name: str
    content: str
    sort_order: int
    created_at: str
    updated_at: str


class CommandHistoryModel(BaseModel):
    command: str
    device_id: str
    session_kind: str
    count: int
    last_used_at: float


class CommandWorkspaceResponse(BaseModel):
    api_version: int = API_VERSION
    groups: list[CommandGroupModel]
    current_group_id: str
    enter_sends: bool
    history: list[CommandHistoryModel]


class CommandGroupCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=160)


class CommandGroupUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=160)
    content: str | None = Field(default=None, max_length=1_000_000)


class CommandGroupOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_ids: list[str] = Field(min_length=1, max_length=100)


class CommandWorkspacePreferencesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_group_id: str | None = Field(default=None, max_length=160)
    enter_sends: bool | None = None


class CommandSuggestionResponse(BaseModel):
    api_version: int = API_VERSION
    suggestions: list[str]


class CommandSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=160)
    command: str = Field(min_length=1, max_length=100_000)


class CommandRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=160)
    command: str = Field(min_length=1, max_length=100_000)


class CommandBroadcastRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=100_000)
    session_ids: list[str] = Field(default_factory=list, max_length=256)


class CommandDispatchResponse(BaseModel):
    api_version: int = API_VERSION
    command: str
    session_ids: list[str]


class AutomationRuleModel(BaseModel):
    id: str
    rule: dict[str, object]
    created_at: str
    updated_at: str


class AutomationSessionStatusModel(BaseModel):
    session_id: str
    running_rule_ids: list[str]
    waiting_rule_ids: list[str]
    triggered_rule_ids: list[str]


class QuickSendButtonModel(BaseModel):
    id: str
    name: str
    response_text: str
    append_enter: bool
    sensitive: bool


class AutomationActivityModel(BaseModel):
    id: str
    timestamp: str
    event: str
    session_id: str
    rule_id: str
    name: str
    message: str
    target_session_id: str = ""


class AutomationWorkspaceResponse(BaseModel):
    api_version: int = API_VERSION
    rules: list[AutomationRuleModel]
    sessions: list[AutomationSessionStatusModel]
    quick_send_buttons: list[QuickSendButtonModel]
    activity: list[AutomationActivityModel]


class AutomationRuleUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: dict[str, object]


class AutomationPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule: dict[str, object]
    session_id: str = Field(default="", max_length=160)
    sample_output: str = Field(default="", max_length=100_000)
    max_steps: int = Field(default=200, ge=1, le=500)


class AutomationPreviewResponse(BaseModel):
    api_version: int = API_VERSION
    steps: list[dict[str, object]]
    variables: dict[str, object]
    warnings: list[str]
    truncated: bool
    sample_output: str


class AutomationRuleEnabledRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class AutomationRuleTriggerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=160)


class QuickSendButtonUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=160)
    response_text: str = Field(min_length=1, max_length=100_000)
    append_enter: bool = False
    sensitive: bool = False


class QuickSendDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=160)


class QuickSendDispatchResponse(BaseModel):
    api_version: int = API_VERSION
    button_id: str
    session_id: str
    status: Literal["sent"]


class AutomationDispatchResponse(BaseModel):
    api_version: int = API_VERSION
    rule_id: str
    session_id: str
    status: Literal["started", "cancelled"]


class TransferSettingsModel(BaseModel):
    api_version: int = API_VERSION
    protocol: Literal["ftp"]
    host: str
    advertised_host: str
    port: int
    root: str
    username: str
    writable: bool
    has_password: bool
    service_running: bool
    bound_port: int
    idle_stop_at: str = ""


class TransferSettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: Literal["ftp"] = "ftp"
    host: str = Field(default="0.0.0.0", max_length=255)
    advertised_host: str = Field(default="", max_length=255)
    port: int = Field(default=0, ge=0, le=65535)
    root: str = Field(min_length=1, max_length=4_096)
    username: str = Field(min_length=1, max_length=255)
    password: str | None = Field(default=None, max_length=1_024)
    writable: bool = True


class TransferPasswordResponse(BaseModel):
    api_version: int = API_VERSION
    password: str = Field(default="", repr=False)


class TransferServiceLogResponse(BaseModel):
    api_version: int = API_VERSION
    entries: list[str]
    content: str
    client_command: str


class TransferNetworkAddressesResponse(BaseModel):
    api_version: int = API_VERSION
    addresses: list[str]
    recommended: str = ""


class SharedFileModel(BaseModel):
    relative_path: str
    name: str
    size_bytes: int
    modified_at: str


class SharedFileListResponse(BaseModel):
    api_version: int = API_VERSION
    files: list[SharedFileModel]
    count: int
    truncated: bool
    total: int = 0
    next_offset: int | None = None


class ManagedTransferStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["upload", "download"] = "upload"
    session_id: str = Field(min_length=1, max_length=160)
    source_path: str = Field(min_length=1, max_length=4_096)
    destination_path: str = Field(min_length=1, max_length=4_096)
    overwrite: bool = False
    terminal_environment: Literal["auto", "linux", "vrp"] = "auto"
    command_mode: Literal["vrp", "ftpget"] = "vrp"


class PackageUpgradeStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=160)
    package_path: str = Field(min_length=1, max_length=4_096)
    include_slave: bool = True
    auto_delete_old_packages: bool = True
    reboot_after_setting: bool = False
    master_storage: str = Field(default="flash:/", min_length=1, max_length=255)
    slave_storage: str = Field(default="slave#flash:/", min_length=1, max_length=255)


class PackageUpgradeManualPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=160)
    package_path: str = Field(min_length=1, max_length=4_096)
    startup_output: str = Field(default="", max_length=500_000)
    master_dir_output: str = Field(default="", max_length=500_000)
    slave_dir_output: str = Field(default="", max_length=500_000)
    include_slave: bool = True
    auto_delete_old_packages: bool = True
    reboot_after_setting: bool = False
    master_storage: str = Field(default="flash:/", min_length=1, max_length=255)
    slave_storage: str = Field(default="slave#flash:/", min_length=1, max_length=255)


class PackageUpgradeManualPlanResponse(BaseModel):
    api_version: int = API_VERSION
    script: str
    package_name: str
    cleanup_paths: list[str]
    notes: list[str]
    password_placeholder: str


class PackageUpgradeManualScriptSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=160)
    script: str = Field(min_length=1, max_length=100_000)
    interval_ms: int = Field(default=900, ge=0, le=5_000)


class PackageUpgradeManualScriptSendResponse(BaseModel):
    api_version: int = API_VERSION
    session_id: str
    command_count: int


class OperationModel(BaseModel):
    id: str
    kind: str
    direction: str
    device_id: str
    session_id: str
    status: str
    stage: str
    message: str
    progress_percent: int
    bytes_transferred: int
    total_bytes: int
    bytes_per_second: int
    eta_seconds: int | None
    queue_position: int | None
    retry_of: str | None
    cancellable: bool
    error_code: str
    revision: int
    created_at: str
    updated_at: str
    data: dict[str, object]


class OperationResponse(BaseModel):
    api_version: int = API_VERSION
    operation: OperationModel


class OperationListResponse(BaseModel):
    api_version: int = API_VERSION
    operations: list[OperationModel]


class TransferQueueResumeResponse(BaseModel):
    api_version: int = API_VERSION
    session_id: str
    resumed_count: int


class DeleteHistoryResponse(BaseModel):
    api_version: int = API_VERSION
    deleted_count: int


class AiPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective: str = Field(min_length=1, max_length=20_000)
    selected_device_id: str = Field(default="", max_length=160)


class AiPlanResponse(BaseModel):
    api_version: int = API_VERSION
    objective: str
    summary: str
    actions: list[dict[str, object]]
    warnings: list[str]


class AiCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1, max_length=100_000)
    session_id: str = Field(min_length=1, max_length=160)
    approval_token: str | None = Field(default=None, max_length=512, repr=False)
    idempotency_key: str | None = Field(default=None, max_length=160)


class AiBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    commands: list[str] = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=160)
    command_timeout_seconds: int = Field(default=30, ge=1, le=600)
    approval_token: str | None = Field(default=None, max_length=512, repr=False)
    idempotency_key: str | None = Field(default=None, max_length=160)


class AiResultResponse(BaseModel):
    api_version: int = API_VERSION
    result: dict[str, object]


class AiApprovalResponse(BaseModel):
    api_version: int = API_VERSION
    approval: dict[str, object]


class AiApprovalListResponse(BaseModel):
    api_version: int = API_VERSION
    approvals: list[dict[str, object]]


class AiAuditResponse(BaseModel):
    api_version: int = API_VERSION
    entries: list[dict[str, object]]


class ConnectionProfileUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_type: Literal["temporary", "server"]
    name: str = Field(min_length=1, max_length=160)
    group: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=4_000)
    preferred_protocol: Literal["ssh", "telnet", "serial"] = "ssh"
    telnet: ProfileEndpointModel = Field(default_factory=lambda: ProfileEndpointModel(port=23))
    ssh: ProfileEndpointModel = Field(default_factory=lambda: ProfileEndpointModel(port=22))
    serial: ProfileEndpointModel = Field(default_factory=lambda: ProfileEndpointModel(port=23))
    telnet_password: str | None = Field(default=None, max_length=4_096)
    ssh_password: str | None = Field(default=None, max_length=4_096)
    serial_password: str | None = Field(default=None, max_length=4_096)
    allow_duplicate: bool = False
