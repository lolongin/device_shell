"""FastAPI gateway used by the Electron/Vue desktop application."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import AsyncIterator, Iterable
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from device_tui.application import (
    ApplicationError,
    ApplicationConflictError,
    CommandRequest,
    ControlContext,
    DeviceActionResult,
    DeviceSnapshot,
    DeviceTarget,
    ResourceNotFoundError,
    SessionRecord,
    UnsupportedOperationError,
    ConnectionProfileStore,
    AutomationStore,
    TransferStore,
    CommandStore,
    CommandGroup,
    ConnectionProfile,
    Action,
    Decision,
    DecisionActor,
    ConnectionProfileDraft,
    ConnectionTarget,
    DesktopApplication,
    AiApplicationService,
    KeyringSecretStore,
    MemoryConnectionProfileStore,
    MemoryCommandStore,
    MemoryAutomationStore,
    MemoryTransferStore,
    MemorySecretStore,
    SecretStore,
    SessionCredential,
    TransferRequest,
    TaskCreate,
    WorkflowCatalogError,
    WorkflowCatalog,
    WorkflowTarget,
    WorkflowRuntime,
    ProfileEndpoint,
    redact_command_secrets,
    build_desktop_application,
)
from device_tui.application.settings import MemorySettingsStore, SettingsStore
from device_tui.device_sources.import_parser import (
    DeviceImportError,
    ParsedDeviceImport,
    parse_device_import,
)
from device_tui.device_sources.imported import ImportedDeviceStore, MemoryImportedDeviceStore
from device_tui.device_sources.plugins import (
    DeviceSourcePlugin,
    DeviceSourcePluginError,
)
from device_tui.device_sources.profile import ProductProfile
from device_tui.device_sources.service import DeviceSourceService, DeviceSourceServiceError
from device_tui.domain.devices.repository import (
    DeviceRepository,
    InternalAuthStatus,
    RepositoryError,
)
from device_tui.infrastructure.persistence.sqlite_desktop import SQLiteDesktopStore
from device_tui.infrastructure.persistence.sqlite_settings import SQLiteSettingsStore
from device_tui.infrastructure.persistence.sqlite_workflows import SQLiteWorkflowEventStore, SQLiteWorkflowRunStore
from device_tui.interfaces.mcp.core import AppControlError
from .models import (
    DeviceListResponse,
    DeviceFieldDescriptorModel,
    DeviceActionResponse,
    DeviceImportCommitRequest,
    DeviceImportCommitResponse,
    DeviceImportIssueModel,
    DeviceImportPreviewModel,
    DeviceImportPreviewRequest,
    DeviceSourceOptionModel,
    DeviceSourcePluginListResponse,
    DeviceSourcePluginModel,
    DeviceSourcePluginTestResponse,
    DeviceSourcePluginUpdateRequest,
    DeviceSourceStatusModel,
    DeviceSourceSwitchRequest,
    PluginConfigFieldModel,
    PluginConfigOptionModel,
    InternalAuthPasswordModel,
    InternalAuthLoginRequest,
    InternalAuthStatusModel,
    ConnectionProfileListResponse,
    ConnectionProfileGroupCreateRequest,
    ConnectionProfileGroupListResponse,
    ProfileCredentialUpdateRequest,
    OneTimeCredentialSessionRequest,
    DirectCredentialSessionRequest,
    CommandGroupModel,
    CommandHistoryModel,
    CommandWorkspaceResponse,
    CommandGroupCreateRequest,
    CommandGroupOrderRequest,
    CommandGroupUpdateRequest,
    CommandWorkspacePreferencesRequest,
    CommandSuggestionResponse,
    CommandSendRequest,
    CommandRecordRequest,
    CommandBroadcastRequest,
    CommandDispatchResponse,
    AutomationRuleModel,
    AutomationActivityModel,
    AutomationSessionStatusModel,
    QuickSendButtonModel,
    AutomationWorkspaceResponse,
    AutomationRuleUpsertRequest,
    AutomationPreviewRequest,
    AutomationPreviewResponse,
    AutomationRuleEnabledRequest,
    AutomationRuleTriggerRequest,
    AutomationDispatchResponse,
    QuickSendButtonUpsertRequest,
    QuickSendDispatchRequest,
    QuickSendDispatchResponse,
    TransferSettingsModel,
    TransferSettingsUpdateRequest,
    TransferPasswordResponse,
    TransferServiceLogResponse,
    TransferNetworkAddressesResponse,
    SharedFileModel,
    SharedFileListResponse,
    ManagedTransferStartRequest,
    PackageUpgradeManualPlanRequest,
    PackageUpgradeManualPlanResponse,
    PackageUpgradeManualScriptSendRequest,
    PackageUpgradeManualScriptSendResponse,
    OperationModel,
    OperationResponse,
    OperationListResponse,
    TransferQueueResumeResponse,
    DeleteHistoryResponse,
    ConnectionProfileSummary,
    ConnectionProfileUpsertRequest,
    ProfileEndpointModel,
    DeviceSummary,
    DiagnosticsResponse,
    ErrorResponse,
    HealthResponse,
    PersistenceDiagnostics,
    SessionCreateRequest,
    SessionListResponse,
    SessionLogResponse,
    SessionLogActionResponse,
    SessionLogSettingsModel,
    SessionLogSettingsUpdateRequest,
    SessionSummary,
    WebSocketTicketRequest,
    WebSocketTicketResponse,
    AiPlanRequest,
    AiPlanResponse,
    AiCommandRequest,
    AiBatchRequest,
    AiResultResponse,
    AiApprovalResponse,
    AiApprovalListResponse,
    AiAuditResponse,
    WorkflowStepRequest,
    TaskCreateRequest,
    TaskResumeRequest,
    TaskModel,
    TaskResponse,
    TaskListResponse,
)
from .session_hub import SessionHub, TerminalEvent
from .terminal_executor import BackendTerminalExecutor
from .mcp_service import DesktopMcpService
from .data_migration import PersistenceMigrationStatus, prepare_persistent_data, sqlite_user_version
from .session_logging import FileSessionLogSink
from .ws_tickets import WebSocketTicketStore


TERMINAL_SOCKET_BATCH_EVENTS = 128
TERMINAL_SOCKET_BATCH_CHARS = 64 * 1024


def _coalesce_terminal_events(
    events: list[TerminalEvent],
    *,
    max_events: int = TERMINAL_SOCKET_BATCH_EVENTS,
    max_chars: int = TERMINAL_SOCKET_BATCH_CHARS,
) -> list[TerminalEvent]:
    """Merge contiguous output events without crossing status or gap boundaries."""
    result: list[TerminalEvent] = []
    pending: list[TerminalEvent] = []
    pending_chars = 0

    def flush() -> None:
        nonlocal pending_chars
        if not pending:
            return
        if len(pending) == 1:
            result.append(pending[0])
        else:
            first = pending[0]
            last = pending[-1]
            result.append(TerminalEvent(
                type="terminal.output",
                session_id=first.session_id,
                sequence=last.sequence,
                data="".join(event.data for event in pending),
                generation=first.generation,
                metadata=dict(first.metadata),
            ))
        pending.clear()
        pending_chars = 0

    for event in events:
        can_merge = (
            event.type == "terminal.output"
            and (
                not pending
                or (
                    event.session_id == pending[-1].session_id
                    and event.generation == pending[-1].generation
                    and event.metadata == pending[-1].metadata
                    and event.sequence == pending[-1].sequence + 1
                )
            )
        )
        would_exceed = pending and (
            len(pending) >= max_events
            or pending_chars + len(event.data) > max_chars
        )
        if not can_merge or would_exceed:
            flush()
        if event.type == "terminal.output":
            pending.append(event)
            pending_chars += len(event.data)
        else:
            result.append(event)
    flush()
    return result


SESSION_LOG_DIRECTORY_SETTING = "session_logs.directory"
SESSION_LOG_MAX_BYTES_SETTING = "session_logs.max_bytes"
SESSION_LOG_BACKUPS_SETTING = "session_logs.backup_count"
INTERNAL_AUTH_USERNAME_SETTING = "internal_auth.username"
INTERNAL_AUTH_CID_SETTING = "internal_auth.cid"
INTERNAL_AUTH_AUTO_LOGIN_SETTING = "internal_auth.auto_login"
INTERNAL_AUTH_AUTO_LOGIN_ERROR_SETTING = "internal_auth.auto_login_error"
IMPORT_PREVIEW_TTL_SECONDS = 10 * 60


def _device_summary(device: DeviceSnapshot) -> DeviceSummary:
    return DeviceSummary(
        id=device.id,
        row_id=device.row_id,
        board_id=device.board_id,
        name=device.name,
        domain=device.domain,
        device_type=device.device_type,
        cpu=device.cpu,
        status=device.status,
        owner=device.owner,
        vendor=device.vendor,
        model=device.model,
        site=device.site,
        rack=device.rack,
        board_type=device.board_type,
        slot=device.slot,
        status_text=device.status_text,
        tooltip=device.tooltip,
        version=device.version,
        ssh_endpoint=device.ssh_endpoint,
        telnet_endpoint=device.telnet_endpoint,
        serial_endpoint=device.serial_endpoint,
        serial_display=device.serial_display,
        can_connect_telnet=device.can_connect_telnet,
        can_connect_ssh=device.can_connect_ssh,
        can_connect_serial=device.can_connect_serial,
        can_claim=device.can_claim,
        can_release=device.can_release,
        can_power_off=device.can_power_off,
        is_simulated=device.is_simulated,
        is_temporary=device.is_temporary,
        is_saved_server=device.is_saved_server,
        supports_power_off=device.supports_power_off,
        source=device.source,
        kind=device.kind,
        attributes=device.attributes,
        extensions=device.extensions,
        capabilities=device.capabilities,
        parent_id=device.parent_id,
        children=list(device.children),
    )


def _device_field_schema(service: DeviceSourceService) -> list[DeviceFieldDescriptorModel]:
    return [
        DeviceFieldDescriptorModel(
            key=field.key,
            label=field.label,
            kind=field.kind,
            group=field.group,
            order=field.order,
            searchable=field.searchable,
            filterable=field.filterable,
            default_visible=field.default_visible,
        )
        for field in service.registry.device_fields(service.active_source)
    ]


def _internal_auth_status_model(
    repository: DeviceRepository,
    settings: SettingsStore,
    secrets: SecretStore,
    status: InternalAuthStatus | None = None,
    *,
    credential_warning: str = "",
    source_id: str,
) -> InternalAuthStatusModel:
    current = status or repository.internal_auth_status()
    username_key = _source_auth_setting_key(INTERNAL_AUTH_USERNAME_SETTING, source_id)
    cid_key = _source_auth_setting_key(INTERNAL_AUTH_CID_SETTING, source_id)
    auto_login_key = _source_auth_setting_key(INTERNAL_AUTH_AUTO_LOGIN_SETTING, source_id)
    auto_login_error_key = _source_auth_setting_key(
        INTERNAL_AUTH_AUTO_LOGIN_ERROR_SETTING,
        source_id,
    )
    password_key = _source_auth_secret_key(source_id)
    stored_username = str(settings.get(username_key, "") or "").strip()
    stored_cid = str(settings.get(cid_key, "") or "").strip()
    warning = credential_warning
    try:
        remembered = bool(secrets.get(password_key))
    except ApplicationError as exc:
        remembered = False
        warning = warning or exc.message
    auto_login = bool(settings.get(auto_login_key, False)) and remembered
    return InternalAuthStatusModel(
        available=current.available,
        configured=current.configured,
        authenticated=current.authenticated,
        username=current.username or stored_username,
        cid=current.cid or stored_cid,
        remembered=remembered,
        auto_login=auto_login,
        auto_login_error=str(
            settings.get(auto_login_error_key, "") or ""
        ),
        credential_warning=warning,
    )


def _device_source_status_model(
    service: DeviceSourceService,
) -> DeviceSourceStatusModel:
    metadata = service.imported_store.imported_device_metadata()
    source_ids = set(service.source_ids())
    options: list[DeviceSourceOptionModel] = []
    descriptors = service.registry.descriptors()
    if service.product_profile.source_locked:
        descriptors = tuple(
            descriptor
            for descriptor in descriptors
            if descriptor.id == service.active_source
        )
    for descriptor in descriptors:
        available = descriptor.id in source_ids
        unavailable_reason = service.registry.unavailable_reason(descriptor.id)
        if (
            descriptor.supports_import
            and metadata.row_count <= 0
            and service.product_profile.mode != "spreadsheet"
        ):
            available = False
            unavailable_reason = unavailable_reason or "尚未导入设备文件。"
        options.append(DeviceSourceOptionModel(
            id=descriptor.id,
            label=descriptor.label,
            description=descriptor.description,
            icon=descriptor.icon,  # type: ignore[arg-type]
            available=available,
            unavailable_reason=unavailable_reason,
            requires_login=descriptor.requires_login,
            supports_import=descriptor.supports_import,
        ))
    return DeviceSourceStatusModel(
        product_mode=service.product_profile.mode,
        allow_source_switch=service.product_profile.allow_source_switch,
        allow_plugin_management=service.product_profile.allow_plugin_management,
        allow_import=service.product_profile.allow_import,
        active_source=service.active_source,
        default_source=service.default_source,
        sources=options,
        plugin_warnings=list(service.registry.warnings()),
        imported_count=metadata.row_count,
        imported_file=metadata.source_name,
        imported_sheet=metadata.sheet_name,
        imported_at=metadata.imported_at,
    )


def _device_source_plugin_model(
    source_id: str,
    service: DeviceSourceService,
) -> DeviceSourcePluginModel:
    registration = service.registry.registration(source_id)
    descriptor = registration.descriptor
    values = service.registry.configuration(source_id)
    fields = [
        PluginConfigFieldModel(
            key=item.key,
            label=item.label,
            kind=item.kind,
            value=None if item.kind == "secret" else values.get(item.key),
            description=item.description,
            placeholder=item.placeholder,
            required=item.required,
            advanced=item.advanced,
            minimum=item.minimum,
            maximum=item.maximum,
            options=[
                PluginConfigOptionModel(value=option.value, label=option.label)
                for option in item.options
            ],
            secret_configured=(
                service.registry.secret_configured(source_id, item.key)
                if item.kind == "secret"
                else False
            ),
        )
        for item in registration.config_fields
    ]
    return DeviceSourcePluginModel(
        id=descriptor.id,
        label=descriptor.label,
        description=descriptor.description,
        icon=descriptor.icon,  # type: ignore[arg-type]
        version=descriptor.version,
        publisher=descriptor.publisher,
        built_in=registration.built_in,
        enabled=service.registry.enabled(source_id),
        available=source_id in service.source_ids(),
        unavailable_reason=service.registry.unavailable_reason(source_id),
        active=source_id == service.active_source,
        default=source_id == service.default_source,
        requires_login=descriptor.requires_login,
        supports_import=descriptor.supports_import,
        config_fields=fields,
    )


def _attempt_internal_auto_login(
    repository: DeviceRepository,
    settings: SettingsStore,
    secrets: SecretStore,
    source_id: str,
) -> None:
    username_key = _source_auth_setting_key(INTERNAL_AUTH_USERNAME_SETTING, source_id)
    cid_key = _source_auth_setting_key(INTERNAL_AUTH_CID_SETTING, source_id)
    auto_login_key = _source_auth_setting_key(INTERNAL_AUTH_AUTO_LOGIN_SETTING, source_id)
    auto_login_error_key = _source_auth_setting_key(
        INTERNAL_AUTH_AUTO_LOGIN_ERROR_SETTING,
        source_id,
    )
    password_key = _source_auth_secret_key(source_id)
    if not bool(settings.get(auto_login_key, False)):
        return
    username = str(settings.get(username_key, "") or "").strip()
    cid = str(settings.get(cid_key, "") or "").strip()
    try:
        status = repository.internal_auth_status()
        password = secrets.get(password_key)
        if not status.available or not status.configured or not username or not cid or not password:
            return
        repository.login_internal(username, password, cid)
        settings.delete(auto_login_error_key)
    except (ApplicationError, RepositoryError) as exc:
        message = exc.message if isinstance(exc, ApplicationError) else str(exc)
        settings.set(auto_login_error_key, message[:500])


def _source_auth_setting_key(base_key: str, source_id: str) -> str:
    return f"{base_key}.{source_id}"


def _source_auth_secret_key(source_id: str) -> str:
    return f"internal-auth/{source_id}/password"


def _session_summary(session: SessionRecord) -> SessionSummary:
    return SessionSummary(**{
        "id": session.id,
        "device_id": session.device_id,
        "kind": session.kind,
        "title": session.title,
        "status": session.status,
        "sequence": session.sequence,
        "generation": session.generation,
    })


def _profile_summary(
    desktop: DesktopApplication,
    profile: ConnectionProfile,
) -> ConnectionProfileSummary:
    def endpoint(protocol: str, value: ProfileEndpoint) -> ProfileEndpointModel:
        return ProfileEndpointModel(
            host=value.host,
            port=value.port,
            username=value.username,
            has_password=desktop.profiles.has_password(profile.id, protocol),
        )

    return ConnectionProfileSummary(
        id=profile.id,
        profile_type=profile.profile_type,
        name=profile.name,
        group=profile.group,
        notes=profile.notes,
        preferred_protocol=profile.preferred_protocol,
        telnet=endpoint("telnet", profile.telnet),
        ssh=endpoint("ssh", profile.ssh),
        serial=endpoint("serial", profile.serial),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _profile_draft(
    request: ConnectionProfileUpsertRequest,
    profile_id: str = "",
) -> ConnectionProfileDraft:
    return ConnectionProfileDraft(
        profile_type=request.profile_type,
        profile_id=profile_id,
        name=request.name,
        group=request.group,
        notes=request.notes,
        preferred_protocol=request.preferred_protocol,
        telnet=ProfileEndpoint(request.telnet.host, request.telnet.port or 23, request.telnet.username),
        ssh=ProfileEndpoint(request.ssh.host, request.ssh.port or 22, request.ssh.username),
        serial=ProfileEndpoint(request.serial.host, request.serial.port or 23, request.serial.username),
        passwords={
            "telnet": request.telnet_password,
            "ssh": request.ssh_password,
            "serial": request.serial_password,
        },
    )


def _command_group(group: CommandGroup) -> CommandGroupModel:
    return CommandGroupModel(
        id=group.id,
        name=group.name,
        content=group.content,
        sort_order=group.sort_order,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


def _command_workspace(desktop: DesktopApplication) -> CommandWorkspaceResponse:
    return CommandWorkspaceResponse(
        groups=[_command_group(group) for group in desktop.commands.list_groups()],
        current_group_id=desktop.commands.current_group_id(),
        enter_sends=desktop.commands.enter_sends(),
        history=[
            CommandHistoryModel(
                command=item.command,
                device_id=item.device_id,
                session_kind=item.session_kind,
                count=item.count,
                last_used_at=item.last_used_at,
            )
            for item in desktop.commands.history(limit=200)
        ],
    )


def _automation_workspace(desktop: DesktopApplication) -> AutomationWorkspaceResponse:
    return AutomationWorkspaceResponse(
        rules=[
            AutomationRuleModel(
                id=record.id,
                rule=desktop.automation.serialize_rule(
                    desktop.automation.public_rule(record)
                ),
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in desktop.automation.list_rules()
        ],
        sessions=[
            AutomationSessionStatusModel(
                session_id=status.session_id,
                running_rule_ids=list(status.running_rule_ids),
                waiting_rule_ids=list(status.waiting_rule_ids),
                triggered_rule_ids=list(status.triggered_rule_ids),
            )
            for status in desktop.automation.statuses()
        ],
        quick_send_buttons=[
            QuickSendButtonModel(**asdict(record))
            for record in desktop.automation.list_quick_send_buttons()
        ],
        activity=[
            AutomationActivityModel(**asdict(record))
            for record in desktop.automation.activities(limit=100)
        ],
    )


def _operation_model(record: object) -> OperationModel:
    payload = asdict(record)
    if "operation_id" in payload and "id" not in payload:
        payload["id"] = payload.pop("operation_id")
    payload.setdefault("direction", "")
    payload.setdefault("bytes_transferred", 0)
    payload.setdefault("total_bytes", 0)
    payload.setdefault("bytes_per_second", 0)
    payload.setdefault("eta_seconds", None)
    payload.setdefault("queue_position", None)
    payload.setdefault("retry_of", None)
    payload.setdefault("cancellable", True)
    payload.setdefault("revision", 0)
    payload.setdefault("created_at", "")
    payload.setdefault("updated_at", "")
    return OperationModel(**payload)  # type: ignore[arg-type]


def _task_model(record: object) -> TaskModel:
    payload = asdict(record)
    return TaskModel(**payload)


def _transfer_settings(desktop: DesktopApplication) -> TransferSettingsModel:
    return TransferSettingsModel(**asdict(desktop.transfers.settings()))


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default
    return min(max(value, minimum), maximum)


def _setting_int(
    settings: SettingsStore,
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(settings.get(key, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def _resolve_legacy_state_path(path: Path | None, enabled: bool) -> Path | None:
    if not enabled or path is not None:
        return path
    configured = os.getenv("DEVICE_TUI_LEGACY_STATE_PATH", "").strip()
    if configured:
        return Path(configured)
    appdata = os.getenv("APPDATA", "").strip()
    return (
        Path(appdata) / "device_tui" / "desktop_state.json"
        if appdata
        else Path.home() / ".device_tui" / "desktop_state.json"
    )


def _import_legacy_log_settings(
    settings: SettingsStore,
    legacy_state_path: Path | None,
) -> None:
    if legacy_state_path is None or not legacy_state_path.exists():
        return
    if settings.get(SESSION_LOG_DIRECTORY_SETTING) is not None:
        return
    try:
        payload = json.loads(legacy_state_path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return
    if not isinstance(payload, dict):
        return
    directory = str(payload.get("log_directory") or "").strip()
    if directory:
        settings.set(SESSION_LOG_DIRECTORY_SETTING, directory)
    try:
        rotate_size_mb = int(payload.get("log_rotate_size_mb", 0))
    except (TypeError, ValueError):
        rotate_size_mb = 0
    if rotate_size_mb > 0:
        settings.set(
            SESSION_LOG_MAX_BYTES_SETTING,
            min(1024, max(1, rotate_size_mb)) * 1024 * 1024,
        )


def _persistence_diagnostics(
    status: PersistenceMigrationStatus | None,
) -> PersistenceDiagnostics | None:
    if status is None:
        return None
    return PersistenceDiagnostics(
        data_root=str(status.data_root),
        database_path=str(status.database_path),
        schema_version_before=status.schema_version_before,
        schema_version_after=status.schema_version_after,
        target_schema_version=status.target_schema_version,
        migrated=status.migrated,
        backup_created=status.backup_created,
        backup_path=str(status.backup_path) if status.backup_path is not None else None,
    )


def _session_log_settings(hub: SessionHub, *, moved_count: int = 0) -> SessionLogSettingsModel:
    configuration = hub.log_configuration()
    if configuration is None:
        return SessionLogSettingsModel(
            directory="",
            rotate_size_mb=24,
            backup_count=5,
            configurable=False,
        )
    return SessionLogSettingsModel(
        directory=str(configuration["root"]),
        rotate_size_mb=max(1, int(configuration["max_bytes"]) // (1024 * 1024)),
        backup_count=int(configuration["backup_count"]),
        configurable=True,
        moved_active_logs=moved_count,
    )


def create_app(
    *,
    token: str | None = None,
    repository: DeviceRepository | None = None,
    session_hub: SessionHub | None = None,
    profile_store: ConnectionProfileStore | None = None,
    secret_store: SecretStore | None = None,
    legacy_state_path: Path | None = None,
    command_store: CommandStore | None = None,
    automation_store: AutomationStore | None = None,
    transfer_store: TransferStore | None = None,
    transfer_root: Path | None = None,
    imported_device_store: ImportedDeviceStore | None = None,
    device_source_plugins: Iterable[DeviceSourcePlugin] = (),
    discover_source_plugins: bool = True,
    product_mode: str | None = None,
    product_source: str | None = None,
    workflow_catalog: WorkflowCatalog | None = None,
    framework_runtime: WorkflowRuntime | None = None,
) -> FastAPI:
    access_token = token if token is not None else os.getenv("DEVICE_TUI_DESKTOP_TOKEN", "")
    data_root = Path(
        os.getenv("DEVICE_TUI_DATA_DIR", str(Path.home() / ".device-tui"))
    )
    production_defaults = session_hub is None
    uses_default_persistence = (
        production_defaults
        and (
            profile_store is None
            or command_store is None
            or automation_store is None
            or transfer_store is None
        )
    )
    persistence_status: PersistenceMigrationStatus | None = (
        prepare_persistent_data(
            data_root,
            target_schema_version=SQLiteDesktopStore.SCHEMA_VERSION,
        )
        if uses_default_persistence
        else None
    )
    desktop_store = (
        SQLiteDesktopStore(data_root / "device-tui.sqlite3")
        if uses_default_persistence
        else None
    )
    if persistence_status is not None:
        persistence_status = persistence_status.with_schema_version_after(
            sqlite_user_version(persistence_status.database_path)
        )
    settings_store: SettingsStore = (
        SQLiteSettingsStore(desktop_store)
        if desktop_store is not None
        else MemorySettingsStore()
    )
    should_import_legacy = production_defaults or legacy_state_path is not None
    legacy_state_path = _resolve_legacy_state_path(legacy_state_path, should_import_legacy)
    if should_import_legacy:
        _import_legacy_log_settings(settings_store, legacy_state_path)

    if secret_store is None:
        secret_store = KeyringSecretStore() if production_defaults else MemorySecretStore()
    imported_store = imported_device_store or desktop_store or MemoryImportedDeviceStore()
    product_profile = ProductProfile.from_environment(
        mode=product_mode,
        source_id=product_source,
    )
    repo = DeviceSourceService.create(
        imported_store=imported_store,
        settings=settings_store,
        secrets=secret_store,
        product_profile=product_profile,
        plugins=device_source_plugins,
        discover_plugins=discover_source_plugins,
        injected_repository=repository,
    )

    stored_log_max_bytes = _setting_int(
        settings_store,
        SESSION_LOG_MAX_BYTES_SETTING,
        24 * 1024 * 1024,
        minimum=64 * 1024,
        maximum=1024 * 1024 * 1024,
    )
    session_log_max_bytes = _env_int(
        "DEVICE_TUI_SESSION_LOG_MAX_BYTES",
        stored_log_max_bytes,
        minimum=64 * 1024,
        maximum=1024 * 1024 * 1024,
    )
    stored_log_backups = _setting_int(
        settings_store,
        SESSION_LOG_BACKUPS_SETTING,
        5,
        minimum=1,
        maximum=50,
    )
    session_log_backups = _env_int(
        "DEVICE_TUI_SESSION_LOG_BACKUPS",
        stored_log_backups,
        minimum=1,
        maximum=50,
    )
    audit_log_max_bytes = _env_int(
        "DEVICE_TUI_AUDIT_LOG_MAX_BYTES",
        10 * 1024 * 1024,
        minimum=64 * 1024,
        maximum=1024 * 1024 * 1024,
    )
    audit_log_backups = _env_int(
        "DEVICE_TUI_AUDIT_LOG_BACKUPS",
        5,
        minimum=1,
        maximum=50,
    )
    if session_hub is None:
        configured_log_root = os.getenv("DEVICE_TUI_SESSION_LOG_ROOT", "").strip()
        stored_log_root = str(
            settings_store.get(
                SESSION_LOG_DIRECTORY_SETTING,
                str(data_root / "logs" / "sessions"),
            )
            or ""
        ).strip()
        session_log_root = Path(
            configured_log_root or stored_log_root or data_root / "logs" / "sessions"
        ).expanduser()
        hub = SessionHub(
            log_sink=FileSessionLogSink(
                session_log_root,
                max_bytes=session_log_max_bytes,
                backup_count=session_log_backups,
            )
        )
    else:
        hub = session_hub
    if profile_store is None:
        profile_store = desktop_store or MemoryConnectionProfileStore()
    if command_store is None:
        command_store = desktop_store or MemoryCommandStore()
    if automation_store is None:
        automation_store = desktop_store or MemoryAutomationStore()
    if transfer_store is None:
        transfer_store = desktop_store or MemoryTransferStore()
    if transfer_root is None:
        transfer_root = data_root / "transfers" if production_defaults else Path.cwd()
    if production_defaults:
        transfer_root.mkdir(parents=True, exist_ok=True)
    terminal_executor = BackendTerminalExecutor(hub, lambda _reference: "")
    desktop = build_desktop_application(
        repo,
        hub,
        profile_store=profile_store,
        secret_store=secret_store,
        command_store=command_store,
        automation_store=automation_store,
        transfer_store=transfer_store,
        operation_store=desktop_store,
        settings_store=settings_store,
        terminal_executor=terminal_executor,
        transfer_root=transfer_root,
        task_store=desktop_store,
        workflow_catalog=workflow_catalog,
        workflow_runtime=framework_runtime,
        framework_run_store=(
            SQLiteWorkflowRunStore(data_root / "device-tui.sqlite3")
            if production_defaults and framework_runtime is None
            else None
        ),
        framework_event_store=(
            SQLiteWorkflowEventStore(data_root / "device-tui.sqlite3")
            if production_defaults and framework_runtime is None
            else None
        ),
    )
    _attempt_internal_auto_login(
        repo,
        desktop.settings,
        desktop.secrets,
        repo.active_source,
    )
    terminal_executor.set_secret_resolver(desktop.transfers.resolve_secret)
    ai_service = AiApplicationService(
        desktop,
        audit_path=data_root / "logs" / "ai-audit.jsonl",
        approval_mode=os.getenv("DEVICE_TUI_APPROVAL_MODE", "disabled"),
        terminal_executor=terminal_executor,
        audit_max_bytes=audit_log_max_bytes,
        audit_backup_count=audit_log_backups,
    )
    mcp_service = DesktopMcpService(
        desktop,
        terminal_executor,
        ai_service,
        plan_store=desktop_store,
        source_service=repo,
    )
    legacy_import = (
        desktop.profiles.import_legacy_state(legacy_state_path)
        if should_import_legacy and legacy_state_path is not None
        else {"temporary": 0, "servers": 0, "groups": 0}
    )
    legacy_command_import = (
        desktop.commands.import_legacy_state(legacy_state_path)
        if should_import_legacy and legacy_state_path is not None
        else {"groups": 0, "history": 0}
    )
    legacy_automation_import = (
        desktop.automation.import_legacy_state(legacy_state_path)
        if should_import_legacy and legacy_state_path is not None
        else {"rules": 0, "secrets": 0}
    )
    legacy_transfer_import = (
        desktop.transfers.import_legacy_state(legacy_state_path)
        if should_import_legacy and legacy_state_path is not None
        else {"settings": 0, "secrets": 0}
    )
    ticket_store = WebSocketTicketStore()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await desktop.tasks.close()
        await desktop.upgrades.close()
        await desktop.transfers.close()
        await desktop.automation.close()
        terminal_executor.close()
        await desktop.sessions.close_all()
        hub.shutdown_logging()

    app = FastAPI(title="Device TUI Desktop API", version="1", lifespan=lifespan)
    app.state.repository = repo
    app.state.session_hub = hub
    app.state.desktop_application = desktop
    app.state.legacy_profile_import = legacy_import
    app.state.legacy_command_import = legacy_command_import
    app.state.legacy_automation_import = legacy_automation_import
    app.state.legacy_transfer_import = legacy_transfer_import
    app.state.persistence_status = persistence_status
    app.state.log_policy = {
        "session_log_max_bytes": session_log_max_bytes,
        "session_log_backups": session_log_backups,
        "audit_log_max_bytes": audit_log_max_bytes,
        "audit_log_backups": audit_log_backups,
    }
    app.state.terminal_executor = terminal_executor
    app.state.access_token = access_token
    app.state.ai_service = ai_service
    app.state.mcp_service = mcp_service
    import_previews: dict[str, tuple[float, ParsedDeviceImport]] = {}
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def authorize(authorization: str = Header(default="")) -> None:
        if access_token and authorization != f"Bearer {access_token}":
            raise HTTPException(status_code=401, detail="Invalid desktop token")

    @app.exception_handler(ApplicationError)
    async def application_error_handler(
        _request: Request,
        exc: ApplicationError,
    ) -> JSONResponse:
        status_code = 400
        if isinstance(exc, ResourceNotFoundError):
            status_code = 404
        elif isinstance(exc, ApplicationConflictError):
            status_code = 409
        elif isinstance(exc, UnsupportedOperationError):
            status_code = 400
        payload = ErrorResponse(
            detail=exc.message,
            error={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
            },
        )
        return JSONResponse(status_code=status_code, content=payload.model_dump())

    @app.exception_handler(AppControlError)
    async def app_control_error_handler(
        _request: Request,
        exc: AppControlError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "api_version": 1,
                "detail": str(exc),
                "error": {"code": exc.code, "message": str(exc), "details": exc.details},
            },
        )

    @app.get("/api/v1/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @app.get(
        "/api/v1/diagnostics",
        response_model=DiagnosticsResponse,
        dependencies=[Depends(authorize)],
    )
    async def diagnostics() -> DiagnosticsResponse:
        return DiagnosticsResponse(
            persistence=_persistence_diagnostics(persistence_status),
            legacy_imports={
                "profiles": dict(legacy_import),
                "commands": dict(legacy_command_import),
                "automation": dict(legacy_automation_import),
                "transfers": dict(legacy_transfer_import),
            },
            log_policy=dict(app.state.log_policy),
        )

    @app.post(
        "/api/v1/mcp/{tool}",
        dependencies=[Depends(authorize)],
    )
    async def invoke_mcp_tool(tool: str, request: dict[str, object]) -> JSONResponse:
        status, payload = await mcp_service.invoke(tool, dict(request))
        return JSONResponse(status_code=status, content=payload)

    @app.post("/api/v1/tasks", response_model=TaskResponse, dependencies=[Depends(authorize)])
    async def task_create(request: TaskCreateRequest) -> TaskResponse:
        session_id = request.session_id
        device_id = request.device_id
        if session_id:
            session = next((item for item in desktop.sessions.list_sessions() if item.id == session_id), None)
            if session is None:
                raise ResourceNotFoundError("Unknown session", details={"session_id": session_id})
            device_id = session.device_id
        if not device_id:
            raise UnsupportedOperationError("device_id or session_id is required")
        if not session_id:
            view = await desktop.control.open_session(DeviceTarget(device_id=device_id, protocol=request.protocol), reuse=True, context=ControlContext(source=request.source))
            session_id = view.session_id
        if desktop.workflows.contains(request.workflow_id):
            parameters = {**dict(request.options), **dict(request.parameters)}
            if request.package:
                parameters.setdefault("package_path", request.package)
            descriptor = desktop.workflows.descriptor(request.workflow_id)
            for definition in descriptor.parameters:
                if not definition.stage_to_transfer_root:
                    continue
                raw_value = parameters.get(definition.name)
                if not isinstance(raw_value, str) or not raw_value.strip():
                    continue
                local_path = Path(raw_value).expanduser()
                if not local_path.is_absolute():
                    continue
                if request.source != "desktop":
                    raise UnsupportedOperationError("An absolute workflow file path is only accepted from the desktop file picker.")
                if definition.file_extensions and local_path.suffix.casefold() not in {item.casefold() for item in definition.file_extensions}:
                    raise UnsupportedOperationError(f"请选择 {', '.join(definition.file_extensions)} 文件。")
                if not local_path.is_file():
                    raise UnsupportedOperationError("请选择存在的文件。")
                transfer_root = Path(desktop.transfers.settings().root).resolve()
                transfer_root.mkdir(parents=True, exist_ok=True)
                staged_path = (transfer_root / local_path.name).resolve()
                if staged_path != local_path.resolve():
                    try:
                        shutil.copy2(local_path, staged_path)
                    except OSError as exc:
                        raise UnsupportedOperationError(f"无法将文件放入文件服务目录：{exc}") from exc
                parameters[definition.name] = staged_path.relative_to(transfer_root).as_posix()
            try:
                workflow = desktop.workflows.build(
                    request.workflow_id,
                    WorkflowTarget(device_id=device_id, session_id=session_id, protocol=request.protocol),
                    parameters,
                    legacy_steps=tuple(item.model_dump() for item in request.steps),
                )
            except WorkflowCatalogError as exc:
                raise UnsupportedOperationError(str(exc)) from exc
        else:
            raise UnsupportedOperationError(
                f"Unknown workflow_id: {request.workflow_id}. Register a WorkflowProvider or submit a WorkflowPlan."
            )
        record = desktop.tasks.create(TaskCreate(workflow=workflow, target=DeviceTarget(device_id=device_id, session_id=session_id, protocol=request.protocol), source=request.source, context=dict(request.context)))
        return TaskResponse(task=_task_model(record))

    @app.get("/api/v1/workflows", dependencies=[Depends(authorize)])
    async def workflow_catalog() -> dict[str, object]:
        return {"workflows": [item.public_dict() for item in desktop.workflows.list()]}

    @app.get("/api/v1/framework/workflows", dependencies=[Depends(authorize)])
    async def framework_workflow_catalog() -> dict[str, object]:
        return {
            "workflows": [
                {
                    "id": provider.id,
                    "version": provider.version,
                    "capabilities": sorted(
                        desktop.framework_workflows.build(
                            provider.id,
                            {"package_ref": "<artifact>", "expected_version": "<version>"},
                        ).required_capabilities
                    )
                    if provider.id == "network.package_upgrade"
                    else [],
                }
                for provider in desktop.framework_workflows.list()
            ]
        }

    @app.post("/api/v1/framework/workflows/{workflow_id}/preview", dependencies=[Depends(authorize)])
    async def framework_workflow_preview(workflow_id: str, request: dict[str, object]) -> dict[str, object]:
        try:
            definition = desktop.framework_workflows.build(workflow_id, dict(request))
        except (KeyError, ValueError) as exc:
            raise UnsupportedOperationError(str(exc)) from exc
        return {"workflow": definition.to_dict()}

    @app.get("/api/v1/tasks", response_model=TaskListResponse, dependencies=[Depends(authorize)])
    async def task_list(limit: int = Query(default=200, ge=1, le=500)) -> TaskListResponse:
        return TaskListResponse(tasks=[_task_model(item) for item in desktop.tasks.list(limit=limit)])

    @app.get("/api/v1/tasks/{task_id}", response_model=TaskResponse, dependencies=[Depends(authorize)])
    async def task_get(task_id: str) -> TaskResponse:
        return TaskResponse(task=_task_model(desktop.tasks.get(task_id)))

    @app.post("/api/v1/tasks/{task_id}/cancel", response_model=TaskResponse, dependencies=[Depends(authorize)])
    async def task_cancel(task_id: str) -> TaskResponse:
        return TaskResponse(task=_task_model(desktop.tasks.cancel(task_id)))

    @app.post("/api/v1/tasks/{task_id}/pause", response_model=TaskResponse, dependencies=[Depends(authorize)])
    async def task_pause(task_id: str) -> TaskResponse:
        return TaskResponse(task=_task_model(desktop.tasks.pause(task_id)))

    @app.get("/api/v1/tasks/{task_id}/decision", dependencies=[Depends(authorize)])
    async def task_decision_get(task_id: str) -> dict[str, object]:
        decision = desktop.tasks.get_decision(task_id)
        return {"decision": decision.to_dict() if decision is not None else None}

    @app.post("/api/v1/tasks/{task_id}/resume", response_model=TaskResponse, dependencies=[Depends(authorize)])
    async def task_resume(task_id: str, request: TaskResumeRequest) -> TaskResponse:
        return TaskResponse(task=_task_model(desktop.tasks.resume(task_id, context=dict(request.context), step_id=request.step_id)))

    @app.post("/api/v1/tasks/{task_id}/decision", response_model=TaskResponse, dependencies=[Depends(authorize)])
    async def task_decision(task_id: str, request: dict[str, object]) -> TaskResponse:
        raw_action = request.get("action")
        if isinstance(raw_action, str):
            action = Action(raw_action, target_step=str(request.get("target_step") or ""), parameters=dict(request.get("parameters") or {}))
        elif isinstance(raw_action, dict):
            action = Action.from_dict(raw_action)
        else:
            raise UnsupportedOperationError("Decision action is required")
        decision = Decision(
            decision_id=str(request.get("decision_id") or uuid4()),
            actor=DecisionActor(type=str(request.get("actor_type") or "user"), id=str(request.get("actor_id") or "")),
            action=action, reason=str(request.get("reason") or ""),
            task_id=task_id, expected_revision=(int(request["expected_revision"]) if request.get("expected_revision") is not None else None),
        )
        return TaskResponse(task=_task_model(desktop.tasks.apply_decision(task_id, decision)))

    @app.post(
        "/api/v1/ai/plan",
        response_model=AiPlanResponse,
        dependencies=[Depends(authorize)],
    )
    async def ai_plan(request: AiPlanRequest) -> AiPlanResponse:
        plan = ai_service.plan(
            request.objective,
            selected_device_id=request.selected_device_id,
        )
        return AiPlanResponse(
            objective=plan.objective,
            summary=plan.summary,
            actions=list(plan.actions),
            warnings=list(plan.warnings),
        )

    @app.post(
        "/api/v1/ai/execute-command",
        response_model=AiResultResponse,
        dependencies=[Depends(authorize)],
    )
    async def ai_execute_command(request: AiCommandRequest) -> AiResultResponse | JSONResponse:
        result = await ai_service.execute_command(
            request.command,
            session_id=request.session_id,
            approval_token=request.approval_token,
            source="desktop-api",
            idempotency_key=request.idempotency_key,
        )
        if result.get("status") == "needs_approval":
            return JSONResponse(status_code=409, content={"api_version": 1, **result})
        return AiResultResponse(result=result)

    @app.post(
        "/api/v1/ai/execute-batch",
        response_model=AiResultResponse,
        dependencies=[Depends(authorize)],
    )
    async def ai_execute_batch(request: AiBatchRequest) -> AiResultResponse | JSONResponse:
        result = await ai_service.execute_batch(
            request.commands,
            session_id=request.session_id,
            command_timeout_seconds=request.command_timeout_seconds,
            approval_token=request.approval_token,
            source="desktop-api",
            idempotency_key=request.idempotency_key,
        )
        if result.get("status") == "needs_approval":
            return JSONResponse(status_code=409, content={"api_version": 1, **result})
        return AiResultResponse(result=result)

    @app.get(
        "/api/v1/ai/results/{result_id}",
        response_model=AiResultResponse,
        dependencies=[Depends(authorize)],
    )
    async def ai_result(
        result_id: str,
        include_raw: bool = Query(default=False),
    ) -> AiResultResponse:
        return AiResultResponse(result=ai_service.get_result(result_id, include_raw=include_raw))

    @app.get(
        "/api/v1/ai/approvals",
        response_model=AiApprovalListResponse,
        dependencies=[Depends(authorize)],
    )
    async def ai_approvals() -> AiApprovalListResponse:
        return AiApprovalListResponse(approvals=ai_service.pending_approvals())

    @app.get(
        "/api/v1/ai/approvals/{approval_id}",
        response_model=AiApprovalResponse,
        dependencies=[Depends(authorize)],
    )
    async def ai_approval(approval_id: str) -> AiApprovalResponse:
        return AiApprovalResponse(approval=ai_service.approval(approval_id))

    @app.post(
        "/api/v1/ai/approvals/{approval_id}/approve",
        response_model=AiApprovalResponse,
        dependencies=[Depends(authorize)],
    )
    async def ai_approve(approval_id: str) -> AiApprovalResponse:
        return AiApprovalResponse(approval=ai_service.approve(approval_id))

    @app.post(
        "/api/v1/ai/approvals/{approval_id}/reject",
        response_model=AiApprovalResponse,
        dependencies=[Depends(authorize)],
    )
    async def ai_reject(approval_id: str) -> AiApprovalResponse:
        return AiApprovalResponse(approval=ai_service.reject(approval_id))

    @app.get(
        "/api/v1/ai/audit",
        response_model=AiAuditResponse,
        dependencies=[Depends(authorize)],
    )
    async def ai_audit(limit: int = Query(default=100, ge=1, le=500)) -> AiAuditResponse:
        return AiAuditResponse(entries=ai_service.audit_entries(limit))

    @app.get(
        "/api/v1/device-source",
        response_model=DeviceSourceStatusModel,
        dependencies=[Depends(authorize)],
    )
    async def device_source_status() -> DeviceSourceStatusModel:
        return _device_source_status_model(repo)

    @app.get(
        "/api/v1/device-source/plugins",
        response_model=DeviceSourcePluginListResponse,
        dependencies=[Depends(authorize)],
    )
    async def device_source_plugins() -> DeviceSourcePluginListResponse:
        return DeviceSourcePluginListResponse(
            plugins=[
                _device_source_plugin_model(
                    registration.descriptor.id,
                    repo,
                )
                for registration in repo.registry.registrations()
            ],
            warnings=list(repo.registry.warnings()),
        )

    @app.put(
        "/api/v1/device-source/plugins/{source_id}",
        response_model=DeviceSourcePluginListResponse,
        dependencies=[Depends(authorize)],
    )
    async def update_device_source_plugin(
        source_id: str,
        request: DeviceSourcePluginUpdateRequest,
    ) -> DeviceSourcePluginListResponse:
        if not product_profile.allow_plugin_management:
            raise ApplicationConflictError(
                "当前产品的数据来源由开发配置固定，不能在应用内修改插件。"
            )
        try:
            repo.registry.registration(source_id)
        except DeviceSourcePluginError as exc:
            raise ResourceNotFoundError(str(exc)) from exc
        if source_id == repo.active_source and request.enabled is False:
            raise ApplicationConflictError("当前正在使用的数据源不能禁用。")
        if (
            source_id == repo.active_source
            and desktop.sessions.list_sessions()
            and (request.config or request.secrets)
        ):
            raise ApplicationConflictError("请先关闭全部终端会话，再修改当前数据源配置。")
        try:
            repository = repo.apply_plugin_configuration(
                source_id,
                config_updates=request.config,
                secret_updates=request.secrets,
                enabled=request.enabled,
            )
        except DeviceSourcePluginError as exc:
            raise ApplicationError(str(exc)) from exc
        if repository is not None and source_id == repo.active_source:
            _attempt_internal_auto_login(
                repo,
                desktop.settings,
                desktop.secrets,
                source_id,
            )
        return await device_source_plugins()

    @app.post(
        "/api/v1/device-source/plugins/{source_id}/test",
        response_model=DeviceSourcePluginTestResponse,
        dependencies=[Depends(authorize)],
    )
    async def test_device_source_plugin(source_id: str) -> DeviceSourcePluginTestResponse:
        if not product_profile.allow_plugin_management:
            raise ApplicationConflictError(
                "当前产品的数据来源由开发配置固定，不能在应用内测试插件。"
            )
        try:
            result = repo.test_plugin_configuration(source_id)
        except DeviceSourcePluginError as exc:
            raise ResourceNotFoundError(str(exc)) from exc
        return DeviceSourcePluginTestResponse(
            success=result.success,
            message=result.message,
            plugin=_device_source_plugin_model(
                source_id,
                repo,
            ),
        )

    @app.put(
        "/api/v1/device-source",
        response_model=DeviceSourceStatusModel,
        dependencies=[Depends(authorize)],
    )
    async def switch_device_source(
        request: DeviceSourceSwitchRequest,
    ) -> DeviceSourceStatusModel:
        if request.source == repo.active_source:
            return _device_source_status_model(repo)
        if desktop.sessions.list_sessions():
            raise ApplicationConflictError("请先关闭全部终端会话，再切换设备数据源。")
        try:
            descriptor = repo.activate(request.source)
            if descriptor.requires_login:
                _attempt_internal_auto_login(
                    repo,
                    desktop.settings,
                    desktop.secrets,
                    request.source,
                )
        except DeviceSourceServiceError as exc:
            raise ApplicationConflictError(str(exc)) from exc
        return _device_source_status_model(repo)

    @app.post(
        "/api/v1/device-source/import/preview",
        response_model=DeviceImportPreviewModel,
        dependencies=[Depends(authorize)],
    )
    async def preview_device_import(
        request: DeviceImportPreviewRequest,
    ) -> DeviceImportPreviewModel:
        if not product_profile.allow_import:
            raise ApplicationConflictError("当前产品不提供设备表格导入。")
        now = monotonic()
        for expired_token, (expires_at, _preview) in list(import_previews.items()):
            if expires_at <= now:
                import_previews.pop(expired_token, None)
        try:
            parsed = await asyncio.to_thread(parse_device_import, Path(request.path))
        except DeviceImportError as exc:
            raise ApplicationError(str(exc)) from exc
        preview_token = uuid4().hex
        import_previews[preview_token] = (
            now + IMPORT_PREVIEW_TTL_SECONDS,
            parsed,
        )
        return DeviceImportPreviewModel(
            token=preview_token,
            file_name=parsed.source_path.name,
            sheet_name=parsed.sheet_name,
            headers=list(parsed.headers),
            total_rows=parsed.total_rows,
            valid_rows=len(parsed.devices),
            skipped_rows=parsed.skipped_rows,
            preview_rows=[dict(row) for row in parsed.preview_rows],
            errors=[
                DeviceImportIssueModel(row=issue.row, message=issue.message)
                for issue in parsed.errors[:100]
            ],
            warnings=list(parsed.warnings),
        )

    @app.post(
        "/api/v1/device-source/import/commit",
        response_model=DeviceImportCommitResponse,
        dependencies=[Depends(authorize)],
    )
    async def commit_device_import(
        request: DeviceImportCommitRequest,
    ) -> DeviceImportCommitResponse:
        if not product_profile.allow_import:
            raise ApplicationConflictError("当前产品不提供设备表格导入。")
        if desktop.sessions.list_sessions():
            raise ApplicationConflictError("请先关闭全部终端会话，再覆盖导入设备。")
        cached = import_previews.get(request.token)
        if cached is None or cached[0] <= monotonic():
            import_previews.pop(request.token, None)
            raise ApplicationConflictError("导入预览已失效，请重新选择文件。")
        parsed = cached[1]
        try:
            metadata = await asyncio.to_thread(
                repo.replace_imported_devices,
                list(parsed.devices),
                source_name=parsed.source_path.name,
                sheet_name=parsed.sheet_name,
                imported_at=datetime.now(timezone.utc).isoformat(),
            )
        except (OSError, ValueError, RepositoryError, DeviceSourceServiceError) as exc:
            raise ApplicationError(f"无法保存导入设备：{exc}") from exc
        import_previews.pop(request.token, None)
        return DeviceImportCommitResponse(
            imported_count=metadata.row_count,
            source=_device_source_status_model(repo),
        )

    @app.post(
        "/api/v1/ws-tickets",
        response_model=WebSocketTicketResponse,
        dependencies=[Depends(authorize)],
    )
    async def issue_websocket_ticket(
        request: WebSocketTicketRequest,
    ) -> WebSocketTicketResponse:
        if request.scope == "terminal":
            try:
                hub.get(request.resource_id)
            except KeyError as exc:
                raise ResourceNotFoundError(
                    f"Unknown session: {request.resource_id}",
                    details={
                        "resource": "session",
                        "session_id": request.resource_id,
                    },
                ) from exc
        elif request.resource_id:
            raise UnsupportedOperationError(
                "The events ticket does not accept a resource id."
            )
        ticket = ticket_store.issue(request.scope, request.resource_id)
        return WebSocketTicketResponse(ticket=ticket.value, expires_in_seconds=30)

    @app.get(
        "/api/v1/internal-auth",
        response_model=InternalAuthStatusModel,
        dependencies=[Depends(authorize)],
    )
    async def internal_auth_status() -> InternalAuthStatusModel:
        try:
            return _internal_auth_status_model(
                repo,
                desktop.settings,
                desktop.secrets,
                source_id=repo.active_source,
            )
        except RepositoryError as exc:
            raise ApplicationError(str(exc)) from exc

    @app.get(
        "/api/v1/internal-auth/password",
        response_model=InternalAuthPasswordModel,
        dependencies=[Depends(authorize)],
    )
    async def internal_auth_password() -> InternalAuthPasswordModel:
        password = desktop.secrets.get(_source_auth_secret_key(repo.active_source)) or ""
        return InternalAuthPasswordModel(password=password)

    @app.post(
        "/api/v1/internal-auth/login",
        response_model=InternalAuthStatusModel,
        dependencies=[Depends(authorize)],
    )
    async def internal_auth_login(
        request: InternalAuthLoginRequest,
    ) -> InternalAuthStatusModel:
        source_id = repo.active_source
        username_key = _source_auth_setting_key(INTERNAL_AUTH_USERNAME_SETTING, source_id)
        cid_key = _source_auth_setting_key(INTERNAL_AUTH_CID_SETTING, source_id)
        auto_login_key = _source_auth_setting_key(INTERNAL_AUTH_AUTO_LOGIN_SETTING, source_id)
        auto_login_error_key = _source_auth_setting_key(
            INTERNAL_AUTH_AUTO_LOGIN_ERROR_SETTING,
            source_id,
        )
        password_key = _source_auth_secret_key(source_id)
        username = request.username.strip()
        cid = request.cid.strip()
        if not username or not cid:
            raise ApplicationError("账号和 CID 不能为空。")
        password = request.password
        if not password and request.use_saved_password:
            password = desktop.secrets.get(password_key) or ""
        if not password:
            raise ApplicationError("请输入密码，或先启用记住登录。")
        try:
            status = repo.login_internal(username, password, cid)
        except RepositoryError as exc:
            raise ApplicationError(str(exc)) from exc
        desktop.settings.set(username_key, username)
        desktop.settings.set(cid_key, cid)
        remember = request.remember or request.auto_login
        warning = ""
        try:
            if remember:
                desktop.secrets.set(password_key, password)
            else:
                desktop.secrets.delete(password_key)
        except ApplicationError as exc:
            remember = False
            warning = exc.message
        desktop.settings.set(
            auto_login_key,
            bool(request.auto_login and remember),
        )
        desktop.settings.delete(auto_login_error_key)
        return _internal_auth_status_model(
            repo,
            desktop.settings,
            desktop.secrets,
            status,
            credential_warning=warning,
            source_id=source_id,
        )

    @app.delete(
        "/api/v1/internal-auth/session",
        response_model=InternalAuthStatusModel,
        dependencies=[Depends(authorize)],
    )
    async def internal_auth_logout() -> InternalAuthStatusModel:
        source_id = repo.active_source
        auto_login_key = _source_auth_setting_key(INTERNAL_AUTH_AUTO_LOGIN_SETTING, source_id)
        auto_login_error_key = _source_auth_setting_key(
            INTERNAL_AUTH_AUTO_LOGIN_ERROR_SETTING,
            source_id,
        )
        try:
            status = repo.logout_internal()
        except RepositoryError as exc:
            raise ApplicationError(str(exc)) from exc
        desktop.settings.set(auto_login_key, False)
        desktop.settings.delete(auto_login_error_key)
        return _internal_auth_status_model(
            repo,
            desktop.settings,
            desktop.secrets,
            status,
            source_id=source_id,
        )

    @app.get(
        "/api/v1/devices",
        response_model=DeviceListResponse,
        dependencies=[Depends(authorize)],
    )
    async def devices() -> DeviceListResponse:
        descriptor = repo.registry.descriptor(repo.active_source)
        if descriptor.requires_login:
            try:
                auth_status = repo.internal_auth_status()
            except RepositoryError as exc:
                raise ApplicationError(str(exc)) from exc
            if not auth_status.authenticated:
                return DeviceListResponse(
                    current_user=auth_status.username,
                    owned_device_ids=[],
                    devices=[],
                    field_schema=_device_field_schema(repo),
                )
        inventory = desktop.devices.list_inventory()
        return DeviceListResponse(
            current_user=inventory.current_user,
            owned_device_ids=list(inventory.owned_device_ids),
            devices=[_device_summary(device) for device in inventory.devices],
            field_schema=_device_field_schema(repo),
        )

    @app.get(
        "/api/v1/connection-profiles",
        response_model=ConnectionProfileListResponse,
        dependencies=[Depends(authorize)],
    )
    async def connection_profiles(
        profile_type: str = Query(default="", alias="type"),
    ) -> ConnectionProfileListResponse:
        normalized_type = profile_type if profile_type in {"temporary", "server"} else None
        profiles = desktop.profiles.list_profiles(normalized_type)  # type: ignore[arg-type]
        return ConnectionProfileListResponse(
            profiles=[_profile_summary(desktop, profile) for profile in profiles],
            groups=desktop.profiles.list_groups(),
        )

    @app.post(
        "/api/v1/connection-profile-groups",
        response_model=ConnectionProfileGroupListResponse,
        dependencies=[Depends(authorize)],
    )
    async def create_connection_profile_group(
        request: ConnectionProfileGroupCreateRequest,
    ) -> ConnectionProfileGroupListResponse:
        desktop.profiles.create_group(request.name)
        return ConnectionProfileGroupListResponse(groups=desktop.profiles.list_groups())

    @app.post(
        "/api/v1/connection-profiles",
        response_model=ConnectionProfileSummary,
        dependencies=[Depends(authorize)],
    )
    async def create_connection_profile(
        request: ConnectionProfileUpsertRequest,
    ) -> ConnectionProfileSummary:
        return _profile_summary(
            desktop,
            desktop.profiles.save(
                _profile_draft(request),
                allow_duplicate=request.allow_duplicate,
            ),
        )

    @app.put(
        "/api/v1/connection-profiles/{profile_id}",
        response_model=ConnectionProfileSummary,
        dependencies=[Depends(authorize)],
    )
    async def update_connection_profile(
        profile_id: str,
        request: ConnectionProfileUpsertRequest,
    ) -> ConnectionProfileSummary:
        desktop.profiles.get_profile(profile_id)
        return _profile_summary(
            desktop,
            desktop.profiles.save(
                _profile_draft(request, profile_id),
                allow_duplicate=request.allow_duplicate,
            ),
        )

    @app.delete(
        "/api/v1/connection-profiles/{profile_id}",
        status_code=204,
        dependencies=[Depends(authorize)],
    )
    async def delete_connection_profile(profile_id: str) -> None:
        profile = desktop.profiles.get_profile(profile_id)
        if profile.profile_type == "temporary" and any(
            session.device_id == profile_id
            for session in desktop.sessions.list_sessions()
        ):
            raise ApplicationConflictError(
                "Close the temporary connection's terminal sessions before deleting it.",
                details={"profile_id": profile_id},
            )
        desktop.profiles.delete(profile_id)

    @app.put(
        "/api/v1/connection-profiles/{profile_id}/credentials/{protocol}",
        response_model=ConnectionProfileSummary,
        dependencies=[Depends(authorize)],
    )
    async def save_connection_profile_credential(
        profile_id: str,
        protocol: str,
        request: ProfileCredentialUpdateRequest,
    ) -> ConnectionProfileSummary:
        desktop.profiles.set_password(profile_id, protocol, request.password)
        return _profile_summary(desktop, desktop.profiles.get_profile(profile_id))

    @app.delete(
        "/api/v1/connection-profiles/{profile_id}/credentials/{protocol}",
        response_model=ConnectionProfileSummary,
        dependencies=[Depends(authorize)],
    )
    async def delete_connection_profile_credential(
        profile_id: str,
        protocol: str,
    ) -> ConnectionProfileSummary:
        desktop.profiles.set_password(profile_id, protocol, "")
        return _profile_summary(desktop, desktop.profiles.get_profile(profile_id))

    def device_action_response(result: DeviceActionResult) -> DeviceActionResponse:
        return DeviceActionResponse(
            device_id=result.device_id,
            action=result.action,
            message=result.message,
            device=_device_summary(result.device),
            current_user=result.inventory.current_user,
            owned_device_ids=list(result.inventory.owned_device_ids),
            devices=[_device_summary(device) for device in result.inventory.devices],
            field_schema=_device_field_schema(repo),
        )

    @app.post(
        "/api/v1/devices/{device_id}/claim",
        response_model=DeviceActionResponse,
        dependencies=[Depends(authorize)],
    )
    async def claim_device(device_id: str) -> DeviceActionResponse:
        return device_action_response(desktop.devices.claim(device_id))

    @app.post(
        "/api/v1/devices/{device_id}/release",
        response_model=DeviceActionResponse,
        dependencies=[Depends(authorize)],
    )
    async def release_device(device_id: str) -> DeviceActionResponse:
        return device_action_response(desktop.devices.release(device_id))

    @app.post(
        "/api/v1/devices/{device_id}/toggle",
        response_model=DeviceActionResponse,
        dependencies=[Depends(authorize)],
    )
    async def toggle_device(device_id: str) -> DeviceActionResponse:
        return device_action_response(desktop.devices.toggle(device_id))

    @app.post(
        "/api/v1/devices/{device_id}/power-off",
        response_model=DeviceActionResponse,
        dependencies=[Depends(authorize)],
    )
    async def power_off_device(device_id: str) -> DeviceActionResponse:
        return device_action_response(
            desktop.control.power_off(
                device_id,
                context=ControlContext(source="electron"),
            )
        )

    @app.get(
        "/api/v1/sessions",
        response_model=SessionListResponse,
        dependencies=[Depends(authorize)],
    )
    async def sessions() -> SessionListResponse:
        return SessionListResponse(
            sessions=[_session_summary(session) for session in desktop.sessions.list_sessions()]
        )

    @app.post(
        "/api/v1/sessions",
        response_model=SessionSummary,
        dependencies=[Depends(authorize)],
    )
    async def create_session(request: SessionCreateRequest) -> SessionSummary:
        view = await desktop.control.open_session(
            DeviceTarget(device_id=request.device_id, protocol=request.kind),
            reuse=False,
            title=request.title,
            term_size=(request.cols, request.rows),
            context=ControlContext(source="electron"),
        )
        return _session_summary(next(item for item in desktop.sessions.list_sessions() if item.id == view.session_id))

    @app.post(
        "/api/v1/sessions/with-credential",
        response_model=SessionSummary,
        dependencies=[Depends(authorize)],
    )
    async def create_session_with_one_time_credential(
        request: OneTimeCredentialSessionRequest,
    ) -> SessionSummary:
        target = desktop.profiles.resolve_target_with_password(
            request.profile_id,
            request.kind,
            request.password,
        )
        view = await desktop.control.open_connection(
            target,
            reuse=False,
            title=request.title,
            term_size=(request.cols, request.rows),
            context=ControlContext(source="electron"),
        )
        return _session_summary(next(item for item in desktop.sessions.list_sessions() if item.id == view.session_id))

    @app.post(
        "/api/v1/sessions/direct",
        response_model=SessionSummary,
        dependencies=[Depends(authorize)],
    )
    async def create_direct_credential_session(
        request: DirectCredentialSessionRequest,
    ) -> SessionSummary:
        if request.password:
            credentials = (SessionCredential(request.username.strip(), request.password),)
        else:
            base_target = desktop.credentials.resolve(request.device_id, request.kind)
            credentials = tuple(
                SessionCredential(request.username.strip() or credential.username, credential.password)
                for credential in base_target.credentials
            )
        target = ConnectionTarget(
            device_id=request.device_id,
            protocol=request.kind,
            host=request.host.strip(),
            port=request.port,
            credentials=credentials,
        )
        view = await desktop.control.open_connection(
            target,
            reuse=False,
            title=request.title,
            term_size=(request.cols, request.rows),
            context=ControlContext(source="electron"),
        )
        return _session_summary(next(item for item in desktop.sessions.list_sessions() if item.id == view.session_id))

    @app.get(
        "/api/v1/commands/workspace",
        response_model=CommandWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def command_workspace() -> CommandWorkspaceResponse:
        return _command_workspace(desktop)

    @app.post(
        "/api/v1/commands/groups",
        response_model=CommandWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def create_command_group(
        request: CommandGroupCreateRequest,
    ) -> CommandWorkspaceResponse:
        desktop.commands.create_group(request.name)
        return _command_workspace(desktop)

    @app.put(
        "/api/v1/commands/groups/order",
        response_model=CommandWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def reorder_command_groups(
        request: CommandGroupOrderRequest,
    ) -> CommandWorkspaceResponse:
        desktop.commands.reorder_groups(request.group_ids)
        return _command_workspace(desktop)

    @app.put(
        "/api/v1/commands/groups/{group_id}",
        response_model=CommandWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def update_command_group(
        group_id: str,
        request: CommandGroupUpdateRequest,
    ) -> CommandWorkspaceResponse:
        desktop.commands.update_group(
            group_id,
            name=request.name,
            content=request.content,
        )
        return _command_workspace(desktop)

    @app.delete(
        "/api/v1/commands/groups/{group_id}",
        response_model=CommandWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def delete_command_group(group_id: str) -> CommandWorkspaceResponse:
        desktop.commands.delete_group(group_id)
        return _command_workspace(desktop)

    @app.put(
        "/api/v1/commands/preferences",
        response_model=CommandWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def update_command_preferences(
        request: CommandWorkspacePreferencesRequest,
    ) -> CommandWorkspaceResponse:
        if request.current_group_id is not None:
            desktop.commands.set_current_group(request.current_group_id)
        if request.enter_sends is not None:
            desktop.commands.set_enter_sends(request.enter_sends)
        return _command_workspace(desktop)

    @app.get(
        "/api/v1/commands/suggestions",
        response_model=CommandSuggestionResponse,
        dependencies=[Depends(authorize)],
    )
    async def command_suggestions(
        query: str = Query(min_length=1, max_length=10_000),
        session_id: str = Query(default="", max_length=160),
        limit: int = Query(default=5, ge=1, le=20),
    ) -> CommandSuggestionResponse:
        device_id = ""
        session_kind = ""
        if session_id:
            session = next(
                (item for item in desktop.sessions.list_sessions() if item.id == session_id),
                None,
            )
            if session is None:
                raise ResourceNotFoundError(
                    f"Unknown session: {session_id}",
                    details={"resource": "session", "session_id": session_id},
                )
            device_id = session.device_id
            session_kind = session.kind
        return CommandSuggestionResponse(suggestions=desktop.commands.suggestions(
            query,
            device_id=device_id,
            session_kind=session_kind,
            limit=limit,
        ))

    @app.post(
        "/api/v1/commands/send",
        response_model=CommandDispatchResponse,
        dependencies=[Depends(authorize)],
    )
    async def send_command(request: CommandSendRequest) -> CommandDispatchResponse:
        session = next(
            (item for item in desktop.sessions.list_sessions() if item.id == request.session_id),
            None,
        )
        if session is None:
            raise ResourceNotFoundError(
                f"Unknown session: {request.session_id}",
                details={"session_id": request.session_id},
            )
        await desktop.control.send_raw(
            DeviceTarget(device_id=session.device_id, session_id=session.id),
            request.command,
            context=ControlContext(source="electron"),
        )
        # Preserve the command-workspace history side effect while the transport
        # itself is now routed through DeviceControlService.
        desktop.commands.record_for_session(request.session_id, request.command)
        return CommandDispatchResponse(
            command=redact_command_secrets(request.command),
            session_ids=[session.id],
        )

    @app.post(
        "/api/v1/commands/history",
        status_code=204,
        dependencies=[Depends(authorize)],
    )
    async def record_command(request: CommandRecordRequest) -> None:
        desktop.commands.record_for_session(request.session_id, request.command)

    @app.post(
        "/api/v1/commands/broadcast",
        response_model=CommandDispatchResponse,
        dependencies=[Depends(authorize)],
    )
    async def broadcast_command(
        request: CommandBroadcastRequest,
    ) -> CommandDispatchResponse:
        result = await desktop.control.broadcast(
            request.command,
            session_ids=request.session_ids or None,
            context=ControlContext(source="electron"),
        )
        for session_id in result.session_ids:
            desktop.commands.record_for_session(session_id, request.command)
        return CommandDispatchResponse(
            command=redact_command_secrets(request.command),
            session_ids=list(result.session_ids),
        )

    @app.get(
        "/api/v1/automation/workspace",
        response_model=AutomationWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def automation_workspace() -> AutomationWorkspaceResponse:
        return _automation_workspace(desktop)

    @app.post(
        "/api/v1/automation/preview",
        response_model=AutomationPreviewResponse,
        dependencies=[Depends(authorize)],
    )
    async def preview_automation_rule(
        request: AutomationPreviewRequest,
    ) -> AutomationPreviewResponse:
        result = desktop.automation.preview_rule(
            desktop.automation.deserialize_rule(request.rule),
            session_id=request.session_id,
            sample_output=request.sample_output,
            max_steps=request.max_steps,
        )
        return AutomationPreviewResponse(**result)

    @app.post(
        "/api/v1/automation/rules",
        response_model=AutomationWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def create_automation_rule(
        request: AutomationRuleUpsertRequest,
    ) -> AutomationWorkspaceResponse:
        desktop.automation.create_rule(
            desktop.automation.deserialize_rule(request.rule)
        )
        return _automation_workspace(desktop)

    @app.put(
        "/api/v1/automation/rules/{rule_id}",
        response_model=AutomationWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def update_automation_rule(
        rule_id: str,
        request: AutomationRuleUpsertRequest,
    ) -> AutomationWorkspaceResponse:
        desktop.automation.update_rule(
            rule_id,
            desktop.automation.deserialize_rule(request.rule),
        )
        return _automation_workspace(desktop)

    @app.post(
        "/api/v1/automation/rules/{rule_id}/clone",
        response_model=AutomationWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def clone_automation_rule(rule_id: str) -> AutomationWorkspaceResponse:
        desktop.automation.clone_rule(rule_id)
        return _automation_workspace(desktop)

    @app.put(
        "/api/v1/automation/rules/{rule_id}/enabled",
        response_model=AutomationWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def set_automation_rule_enabled(
        rule_id: str,
        request: AutomationRuleEnabledRequest,
    ) -> AutomationWorkspaceResponse:
        desktop.automation.set_enabled(rule_id, request.enabled)
        return _automation_workspace(desktop)

    @app.delete(
        "/api/v1/automation/rules/{rule_id}",
        status_code=204,
        dependencies=[Depends(authorize)],
    )
    async def delete_automation_rule(rule_id: str) -> None:
        desktop.automation.delete_rule(rule_id)

    @app.post(
        "/api/v1/automation/rules/{rule_id}/trigger",
        response_model=AutomationDispatchResponse,
        dependencies=[Depends(authorize)],
    )
    async def trigger_automation_rule(
        rule_id: str,
        request: AutomationRuleTriggerRequest,
    ) -> AutomationDispatchResponse:
        desktop.automation.trigger_rule(rule_id, request.session_id)
        return AutomationDispatchResponse(
            rule_id=rule_id,
            session_id=request.session_id,
            status="started",
        )

    @app.post(
        "/api/v1/automation/sessions/{session_id}/cancel",
        response_model=AutomationDispatchResponse,
        dependencies=[Depends(authorize)],
    )
    async def cancel_session_automation(
        session_id: str,
    ) -> AutomationDispatchResponse:
        if not any(
            session.id == session_id
            for session in desktop.sessions.list_sessions()
        ):
            raise ResourceNotFoundError(
                f"Unknown session: {session_id}",
                details={"resource": "session", "session_id": session_id},
            )
        desktop.automation.cancel_session(session_id, reason="user_cancelled")
        return AutomationDispatchResponse(
            rule_id="",
            session_id=session_id,
            status="cancelled",
        )

    @app.post(
        "/api/v1/automation/quick-send-buttons",
        response_model=AutomationWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def create_quick_send_button(
        request: QuickSendButtonUpsertRequest,
    ) -> AutomationWorkspaceResponse:
        desktop.automation.create_quick_send_button(**request.model_dump())
        return _automation_workspace(desktop)

    @app.put(
        "/api/v1/automation/quick-send-buttons/{button_id}",
        response_model=AutomationWorkspaceResponse,
        dependencies=[Depends(authorize)],
    )
    async def update_quick_send_button(
        button_id: str,
        request: QuickSendButtonUpsertRequest,
    ) -> AutomationWorkspaceResponse:
        desktop.automation.update_quick_send_button(button_id, **request.model_dump())
        return _automation_workspace(desktop)

    @app.delete(
        "/api/v1/automation/quick-send-buttons/{button_id}",
        status_code=204,
        dependencies=[Depends(authorize)],
    )
    async def delete_quick_send_button(button_id: str) -> None:
        desktop.automation.delete_quick_send_button(button_id)

    @app.post(
        "/api/v1/automation/quick-send-buttons/{button_id}/send",
        response_model=QuickSendDispatchResponse,
        dependencies=[Depends(authorize)],
    )
    async def send_quick_send_button(
        button_id: str,
        request: QuickSendDispatchRequest,
    ) -> QuickSendDispatchResponse:
        await desktop.automation.send_quick_send_button(button_id, request.session_id)
        return QuickSendDispatchResponse(
            button_id=button_id,
            session_id=request.session_id,
            status="sent",
        )

    @app.get(
        "/api/v1/file-transfer/settings",
        response_model=TransferSettingsModel,
        dependencies=[Depends(authorize)],
    )
    async def file_transfer_settings() -> TransferSettingsModel:
        return _transfer_settings(desktop)

    @app.put(
        "/api/v1/file-transfer/settings",
        response_model=TransferSettingsModel,
        dependencies=[Depends(authorize)],
    )
    async def update_file_transfer_settings(
        request: TransferSettingsUpdateRequest,
    ) -> TransferSettingsModel:
        await desktop.transfers.reconfigure(
            protocol=request.protocol,
            host=request.host,
            advertised_host=request.advertised_host,
            port=request.port,
            root=request.root,
            username=request.username,
            password=request.password,
            writable=request.writable,
        )
        return _transfer_settings(desktop)

    @app.get(
        "/api/v1/file-transfer/password",
        response_model=TransferPasswordResponse,
        dependencies=[Depends(authorize)],
    )
    async def file_transfer_password() -> TransferPasswordResponse:
        return TransferPasswordResponse(
            password=desktop.transfers.resolve_secret("file_transfer.password"),
        )

    @app.post(
        "/api/v1/file-transfer/service/start",
        response_model=TransferSettingsModel,
        dependencies=[Depends(authorize)],
    )
    async def start_file_transfer_service() -> TransferSettingsModel:
        # Manual service starts are user-owned and should keep listening until stopped explicitly.
        await desktop.transfers.start_service(auto_stop_when_idle=False)
        return _transfer_settings(desktop)

    @app.post(
        "/api/v1/file-transfer/service/stop",
        response_model=TransferSettingsModel,
        dependencies=[Depends(authorize)],
    )
    async def stop_file_transfer_service() -> TransferSettingsModel:
        await desktop.transfers.stop_service()
        return _transfer_settings(desktop)

    @app.get(
        "/api/v1/file-transfer/service/log",
        response_model=TransferServiceLogResponse,
        dependencies=[Depends(authorize)],
    )
    async def file_transfer_service_log() -> TransferServiceLogResponse:
        entries = desktop.transfers.service_log()
        return TransferServiceLogResponse(
            entries=entries,
            content="\n".join(entries),
            client_command=desktop.transfers.client_command_hint(),
        )

    @app.get(
        "/api/v1/file-transfer/network-addresses",
        response_model=TransferNetworkAddressesResponse,
        dependencies=[Depends(authorize)],
    )
    async def file_transfer_network_addresses(
        session_id: str = Query(default="", max_length=160),
    ) -> TransferNetworkAddressesResponse:
        addresses, recommended = desktop.transfers.network_addresses(session_id)
        return TransferNetworkAddressesResponse(
            addresses=addresses,
            recommended=recommended,
        )

    @app.delete(
        "/api/v1/file-transfer/service/log",
        response_model=TransferServiceLogResponse,
        dependencies=[Depends(authorize)],
    )
    async def clear_file_transfer_service_log() -> TransferServiceLogResponse:
        desktop.transfers.clear_service_log()
        return TransferServiceLogResponse(
            entries=[],
            content="",
            client_command=desktop.transfers.client_command_hint(),
        )

    @app.get(
        "/api/v1/file-transfer/files",
        response_model=SharedFileListResponse,
        dependencies=[Depends(authorize)],
    )
    async def shared_transfer_files(
        path: str = Query(default="", max_length=4_096),
        recursive: bool = Query(default=True),
        limit: int = Query(default=200, ge=1, le=1_000),
        query: str = Query(default="", max_length=512),
        sort: str = Query(default="name", pattern="^(name|size|modified)$"),
        order: str = Query(default="asc", pattern="^(asc|desc)$"),
        offset: int = Query(default=0, ge=0),
    ) -> SharedFileListResponse:
        catalog = desktop.transfers.list_files(
            relative_path=path,
            recursive=recursive,
            limit=limit,
            query=query,
            sort=sort,
            order=order,
            offset=offset,
        )
        return SharedFileListResponse(
            files=[SharedFileModel(**item.public_dict()) for item in catalog.files],
            count=len(catalog.files),
            truncated=catalog.truncated,
            total=catalog.total,
            next_offset=catalog.next_offset,
        )

    @app.post(
        "/api/v1/file-transfers",
        response_model=OperationResponse,
        dependencies=[Depends(authorize)],
    )
    async def start_managed_file_transfer(
        request: ManagedTransferStartRequest,
    ) -> OperationResponse:
        session = next(
            (item for item in desktop.sessions.list_sessions() if item.id == request.session_id),
            None,
        )
        if session is None:
            raise ResourceNotFoundError(
                f"Unknown session: {request.session_id}",
                details={"session_id": request.session_id},
            )
        operation = desktop.control.transfer(
            DeviceTarget(device_id=session.device_id, session_id=session.id),
            TransferRequest(
                direction=request.direction,
                source_path=request.source_path,
                destination_path=request.destination_path,
                overwrite=request.overwrite,
                terminal_environment=request.terminal_environment,
                command_mode=request.command_mode,
            ),
            context=ControlContext(source="electron"),
        )
        return OperationResponse(
            operation=_operation_model(desktop.control.get_operation(operation.operation_id))
        )

    @app.post(
        "/api/v1/file-transfers/{operation_id}/retry",
        response_model=OperationResponse,
        dependencies=[Depends(authorize)],
    )
    async def retry_managed_file_transfer(operation_id: str) -> OperationResponse:
        return OperationResponse(
            operation=_operation_model(desktop.transfers.retry(operation_id))
        )

    @app.post(
        "/api/v1/file-transfers/queues/{session_id}/resume",
        response_model=TransferQueueResumeResponse,
        dependencies=[Depends(authorize)],
    )
    async def resume_managed_file_transfer_queue(
        session_id: str,
    ) -> TransferQueueResumeResponse:
        return TransferQueueResumeResponse(
            session_id=session_id,
            resumed_count=desktop.transfers.resume_queue(session_id),
        )

    @app.delete(
        "/api/v1/file-transfers/history",
        response_model=DeleteHistoryResponse,
        dependencies=[Depends(authorize)],
    )
    async def clear_managed_file_transfer_history() -> DeleteHistoryResponse:
        return DeleteHistoryResponse(deleted_count=desktop.transfers.clear_history())

    @app.get(
        "/api/v1/package-upgrades/manual/{session_id}/terminal",
        response_model=SessionLogResponse,
        dependencies=[Depends(authorize)],
    )
    async def package_upgrade_manual_terminal(session_id: str) -> SessionLogResponse:
        content, truncated = desktop.upgrades.manual_terminal_snapshot(session_id)
        return SessionLogResponse(
            session_id=session_id,
            content=content,
            truncated=truncated,
        )

    @app.post(
        "/api/v1/package-upgrades/manual/plan",
        response_model=PackageUpgradeManualPlanResponse,
        dependencies=[Depends(authorize)],
    )
    async def package_upgrade_manual_plan(
        request: PackageUpgradeManualPlanRequest,
    ) -> PackageUpgradeManualPlanResponse:
        plan = await desktop.upgrades.generate_manual_plan(
            session_id=request.session_id,
            package_path=request.package_path,
            startup_output=request.startup_output,
            master_dir_output=request.master_dir_output,
            slave_dir_output=request.slave_dir_output,
            include_slave=request.include_slave,
            auto_delete_old_packages=request.auto_delete_old_packages,
            reboot_after_setting=request.reboot_after_setting,
            master_storage=request.master_storage,
            slave_storage=request.slave_storage,
        )
        return PackageUpgradeManualPlanResponse(
            script=plan.script,
            package_name=plan.package_name,
            cleanup_paths=plan.cleanup_paths,
            notes=plan.notes,
            password_placeholder=plan.password_placeholder,
        )

    @app.post(
        "/api/v1/package-upgrades/manual/send",
        response_model=PackageUpgradeManualScriptSendResponse,
        dependencies=[Depends(authorize)],
    )
    async def package_upgrade_manual_send(
        request: PackageUpgradeManualScriptSendRequest,
    ) -> PackageUpgradeManualScriptSendResponse:
        command_count = await desktop.upgrades.send_manual_script(
            session_id=request.session_id,
            script=request.script,
            interval_ms=request.interval_ms,
        )
        return PackageUpgradeManualScriptSendResponse(
            session_id=request.session_id,
            command_count=command_count,
        )

    @app.get(
        "/api/v1/operations",
        response_model=OperationListResponse,
        dependencies=[Depends(authorize)],
    )
    async def list_operations(
        kind: str = Query(default="", max_length=160),
        limit: int = Query(default=200, ge=1, le=1_000),
    ) -> OperationListResponse:
        return OperationListResponse(operations=[
            _operation_model(record)
            for record in desktop.control.list_operations(kind=kind, limit=limit)
        ])

    @app.get(
        "/api/v1/operations/{operation_id}",
        response_model=OperationResponse,
        dependencies=[Depends(authorize)],
    )
    async def get_operation(operation_id: str) -> OperationResponse:
        return OperationResponse(
            operation=_operation_model(desktop.control.get_operation(operation_id))
        )

    @app.post(
        "/api/v1/operations/{operation_id}/cancel",
        response_model=OperationResponse,
        dependencies=[Depends(authorize)],
    )
    async def cancel_operation(operation_id: str) -> OperationResponse:
        return OperationResponse(
            operation=_operation_model(desktop.control.cancel_operation(operation_id))
        )

    @app.post(
        "/api/v1/sessions/{session_id}/reconnect",
        response_model=SessionSummary,
        dependencies=[Depends(authorize)],
    )
    async def reconnect_session(session_id: str) -> SessionSummary:
        desktop.tasks.cancel_session(session_id)
        desktop.transfers.cancel_session(session_id)
        record = next(
            (item for item in desktop.sessions.list_sessions() if item.id == session_id),
            None,
        )
        if record is None:
            raise ResourceNotFoundError(
                f"Unknown session: {session_id}", details={"session_id": session_id}
            )
        view = await desktop.control.reconnect_session(
            DeviceTarget(device_id=record.device_id, session_id=session_id),
            context=ControlContext(source="electron"),
        )
        return _session_summary(next(item for item in desktop.sessions.list_sessions() if item.id == view.session_id))

    @app.post(
        "/api/v1/sessions/{session_id}/disconnect",
        response_model=SessionSummary,
        dependencies=[Depends(authorize)],
    )
    async def disconnect_session(session_id: str) -> SessionSummary:
        desktop.tasks.cancel_session(session_id)
        desktop.transfers.cancel_session(session_id)
        record = next(
            (item for item in desktop.sessions.list_sessions() if item.id == session_id),
            None,
        )
        if record is None:
            raise ResourceNotFoundError(
                f"Unknown session: {session_id}", details={"session_id": session_id}
            )
        view = await desktop.control.disconnect_session(
            DeviceTarget(device_id=record.device_id, session_id=session_id),
            context=ControlContext(source="electron"),
        )
        return _session_summary(next(item for item in desktop.sessions.list_sessions() if item.id == view.session_id))

    @app.get(
        "/api/v1/settings/session-logs",
        response_model=SessionLogSettingsModel,
        dependencies=[Depends(authorize)],
    )
    async def session_log_settings() -> SessionLogSettingsModel:
        return _session_log_settings(hub)

    @app.put(
        "/api/v1/settings/session-logs",
        response_model=SessionLogSettingsModel,
        dependencies=[Depends(authorize)],
    )
    async def update_session_log_settings(
        request: SessionLogSettingsUpdateRequest,
    ) -> SessionLogSettingsModel:
        directory = Path(request.directory).expanduser()
        if not directory.is_absolute():
            raise HTTPException(status_code=422, detail="日志目录必须是绝对路径。")
        current = hub.log_configuration()
        if current is None:
            raise HTTPException(status_code=409, detail="当前会话日志不是文件日志，无法更改设置。")
        try:
            result = await asyncio.to_thread(
                hub.reconfigure_logging,
                directory,
                max_bytes=request.rotate_size_mb * 1024 * 1024,
                backup_count=int(current["backup_count"]),
            )
        except (OSError, RuntimeError, TimeoutError) as exc:
            raise HTTPException(status_code=400, detail=f"日志设置应用失败: {exc}") from exc
        desktop.settings.set(SESSION_LOG_DIRECTORY_SETTING, str(result["root"]))
        desktop.settings.set(SESSION_LOG_MAX_BYTES_SETTING, int(result["max_bytes"]))
        desktop.settings.set(SESSION_LOG_BACKUPS_SETTING, int(result["backup_count"]))
        app.state.log_policy["session_log_max_bytes"] = int(result["max_bytes"])
        app.state.log_policy["session_log_backups"] = int(result["backup_count"])
        return _session_log_settings(hub, moved_count=int(result.get("moved_count", 0)))

    @app.get(
        "/api/v1/sessions/{session_id}/log",
        response_model=SessionLogResponse,
        dependencies=[Depends(authorize)],
    )
    async def session_log(
        session_id: str,
        max_chars: int = Query(default=200_000, ge=1_024, le=2_000_000),
    ) -> SessionLogResponse:
        record = desktop.sessions.read_log(session_id, max_chars)
        return SessionLogResponse(
            session_id=record.session_id,
            content=record.content,
            truncated=record.truncated,
        )

    @app.get(
        "/api/v1/sessions/{session_id}/log-path",
        response_model=SessionLogActionResponse,
        dependencies=[Depends(authorize)],
    )
    async def session_log_path(session_id: str) -> SessionLogActionResponse:
        try:
            path = hub.log_path(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Session not found.") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return SessionLogActionResponse(session_id=session_id, path=str(path))

    @app.post(
        "/api/v1/sessions/{session_id}/log/new",
        response_model=SessionLogActionResponse,
        dependencies=[Depends(authorize)],
    )
    async def create_session_log(session_id: str) -> SessionLogActionResponse:
        try:
            archived_path = await asyncio.to_thread(hub.start_new_log, session_id)
            path = hub.log_path(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Session not found.") from exc
        except (OSError, RuntimeError, TimeoutError) as exc:
            raise HTTPException(status_code=400, detail=f"新建会话日志失败: {exc}") from exc
        return SessionLogActionResponse(
            session_id=session_id,
            path=str(path),
            archived_path=archived_path,
        )

    @app.delete(
        "/api/v1/sessions/{session_id}",
        status_code=204,
        dependencies=[Depends(authorize)],
    )
    async def close_session(session_id: str) -> None:
        desktop.automation.cancel_session(session_id, reason="session_closed")
        desktop.tasks.cancel_session(session_id)
        desktop.transfers.cancel_session(session_id)
        record = next(
            (item for item in desktop.sessions.list_sessions() if item.id == session_id),
            None,
        )
        if record is None:
            raise ResourceNotFoundError(
                f"Unknown session: {session_id}", details={"session_id": session_id}
            )
        await desktop.control.close_session(
            DeviceTarget(device_id=record.device_id, session_id=session_id),
            context=ControlContext(source="electron"),
        )

    @app.websocket("/ws/v1/events")
    async def event_socket(
        websocket: WebSocket,
        access: str = Query(default=""),
        ticket: str = Query(default=""),
        after: int = Query(default=0, ge=0),
    ) -> None:
        authorized = bool(access_token and access == access_token)
        authorized = authorized or ticket_store.consume(ticket, "events")
        if not authorized:
            await websocket.close(code=4401, reason="Invalid desktop token")
            return
        queue, replay = desktop.events.subscribe(after_sequence=after)
        await websocket.accept()
        try:
            for event in replay:
                await websocket.send_json(event.to_payload())
            while True:
                event = await queue.get()
                await websocket.send_json(event.to_payload())
        except WebSocketDisconnect:
            pass
        finally:
            desktop.events.unsubscribe(queue)

    @app.websocket("/ws/v1/terminals/{session_id}")
    async def terminal_socket(
        websocket: WebSocket,
        session_id: str,
        access: str = Query(default=""),
        ticket: str = Query(default=""),
        after: int = Query(default=0, ge=0),
    ) -> None:
        authorized = bool(access_token and access == access_token)
        authorized = authorized or ticket_store.consume(ticket, "terminal", session_id)
        if not authorized:
            await websocket.close(code=4401, reason="Invalid desktop token")
            return
        try:
            queue, replay = hub.subscribe(session_id, after_sequence=after)
        except KeyError:
            await websocket.close(code=4404, reason="Unknown session")
            return
        await websocket.accept()
        for event in _coalesce_terminal_events(replay):
            await websocket.send_json(event.to_payload())

        async def send_events() -> None:
            while True:
                events: list[TerminalEvent] = [await queue.get()]
                for _ in range(TERMINAL_SOCKET_BATCH_EVENTS - 1):
                    try:
                        events.append(queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                for event in _coalesce_terminal_events(events):
                    await websocket.send_json(event.to_payload())

        async def receive_commands() -> None:
            while True:
                message = await websocket.receive_json()
                kind = str(message.get("type") or "")
                try:
                    if kind == "terminal.input":
                        await hub.write(session_id, str(message.get("data") or ""))
                    elif kind == "terminal.resize":
                        await hub.resize(
                            session_id,
                            int(message.get("cols") or 80),
                            int(message.get("rows") or 24),
                        )
                    elif kind == "terminal.reconnect":
                        await hub.reconnect(session_id)
                except KeyError:
                    await websocket.close(code=4404, reason="Session closed")
                    return

        sender = asyncio.create_task(send_events())
        receiver = asyncio.create_task(receive_commands())
        try:
            done, pending = await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                with suppress(WebSocketDisconnect):
                    task.result()
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            receiver.cancel()
            hub.unsubscribe(session_id, queue)

    return app
