"""FastAPI gateway used by the Electron/Vue desktop application."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from device_tui.application import (
    ConnectionProfileStore,
    AutomationStore,
    TransferStore,
    CommandStore,
    AiApplicationService,
    KeyringSecretStore,
    MemoryConnectionProfileStore,
    MemoryCommandStore,
    MemoryAutomationStore,
    MemoryTransferStore,
    MemorySecretStore,
    WorkflowCatalog,
    WorkflowRuntime,
    build_desktop_application,
)
from device_tui.application.settings import MemorySettingsStore, SettingsStore
from device_tui.application.ai.agent import AgentToolExecutor, DeviceAgent
from device_tui.application.ai.llm import OpenAiCompatibleClient
from device_tui.device_sources.import_parser import ParsedDeviceImport
from device_tui.device_sources.imported import ImportedDeviceStore, MemoryImportedDeviceStore
from device_tui.device_sources.plugins import DeviceSourcePlugin
from device_tui.device_sources.profile import ProductProfile
from device_tui.device_sources.service import DeviceSourceService
from device_tui.domain.devices.repository import DeviceRepository
from device_tui.infrastructure.persistence.sqlite_desktop import SQLiteDesktopStore
from device_tui.infrastructure.persistence.sqlite_settings import SQLiteSettingsStore
from device_tui.infrastructure.persistence.sqlite_workflows import (
    SQLiteTaskRunStore,
    SQLiteWorkflowEventStore,
    SQLiteWorkflowRunStore,
)
from .session_hub import SessionHub
from .terminal_executor import BackendTerminalExecutor
from .mcp_service import DesktopMcpService
from .data_migration import PersistenceMigrationStatus, prepare_persistent_data, sqlite_user_version
from .session_logging import FileSessionLogSink
from .ws_tickets import WebSocketTicketStore
from .context import BackendContext
from .errors import install_exception_handlers
from .lifespan import build_lifespan
from .serializers import attempt_internal_auto_login as _attempt_internal_auto_login
from .routers.health import router as health_router
from .routers.ai import legacy_router as legacy_ai_router
from .routers.ai import router as ai_router
from .routers.tasks import router as tasks_router
from .routers.device_sources import router as device_sources_router
from .routers.mcp import router as mcp_router
from .routers.operations import router as operations_router
from .routers.package_builds import router as package_builds_router
from .routers.devices import router as devices_router
from .routers.profiles import router as profiles_router
from .routers.sessions import router as sessions_router
from .routers.commands import router as commands_router
from .routers.automation import router as automation_router
from .routers.transfers import router as transfers_router
from .routers.auth import router as auth_router
from .routers.ws_tickets import router as ws_tickets_router
from .routers.session_logs import router as session_logs_router
from .routers.websocket import (
    _coalesce_terminal_events,
    router as websocket_router,
)


SESSION_LOG_DIRECTORY_SETTING = "session_logs.directory"
SESSION_LOG_MAX_BYTES_SETTING = "session_logs.max_bytes"
SESSION_LOG_BACKUPS_SETTING = "session_logs.backup_count"
INTERNAL_AUTH_USERNAME_SETTING = "internal_auth.username"
INTERNAL_AUTH_CID_SETTING = "internal_auth.cid"
INTERNAL_AUTH_AUTO_LOGIN_SETTING = "internal_auth.auto_login"
INTERNAL_AUTH_AUTO_LOGIN_ERROR_SETTING = "internal_auth.auto_login_error"


def _source_auth_setting_key(base_key: str, source_id: str) -> str:
    return f"{base_key}.{source_id}"


def _source_auth_secret_key(source_id: str) -> str:
    return f"internal-auth/{source_id}/password"


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
        os.getenv("DEVICE_TUI_DATA_DIR", str(Path.home() / ".odyterm"))
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
        SQLiteDesktopStore(data_root / "odyterm.sqlite3")
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
            SQLiteWorkflowRunStore(data_root / "odyterm.sqlite3")
            if production_defaults and framework_runtime is None
            else None
        ),
        framework_event_store=(
            SQLiteWorkflowEventStore(data_root / "odyterm.sqlite3")
            if production_defaults and framework_runtime is None
            else None
        ),
        framework_task_run_store=(
            SQLiteTaskRunStore(data_root / "odyterm.sqlite3")
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
    try:
        agent_max_iterations = int(os.getenv("DEVICE_AI_MAX_ITERATIONS", "30"))
    except ValueError:
        agent_max_iterations = 30
    ai_agent = DeviceAgent(
        OpenAiCompatibleClient.from_env(),
        AgentToolExecutor(ai_service),
        max_iterations=agent_max_iterations,
        event_callback=lambda event: desktop.events.publish(event.type, data=event.data),
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
    import_previews: dict[str, tuple[float, ParsedDeviceImport]] = {}
    log_policy = {
        "session_log_max_bytes": session_log_max_bytes,
        "session_log_backups": session_log_backups,
        "audit_log_max_bytes": audit_log_max_bytes,
        "audit_log_backups": audit_log_backups,
    }
    context = BackendContext(
        desktop=desktop,
        repository=repo,
        hub=hub,
        terminal_executor=terminal_executor,
        ai_service=ai_service,
        ai_agent=ai_agent,
        mcp_service=mcp_service,
        ticket_store=ticket_store,
        access_token=access_token,
        persistence_status=persistence_status,
        import_previews=import_previews,
        legacy_import=legacy_import,
        legacy_command_import=legacy_command_import,
        legacy_automation_import=legacy_automation_import,
        legacy_transfer_import=legacy_transfer_import,
        log_policy=log_policy,
        data_root=data_root,
    )

    app = FastAPI(
        title="OdyTerm Desktop API",
        version="1",
        lifespan=build_lifespan(context),
    )
    app.state.context = context
    app.state.repository = repo
    app.state.session_hub = hub
    app.state.desktop_application = desktop
    app.state.legacy_profile_import = legacy_import
    app.state.legacy_command_import = legacy_command_import
    app.state.legacy_automation_import = legacy_automation_import
    app.state.legacy_transfer_import = legacy_transfer_import
    app.state.persistence_status = persistence_status
    app.state.log_policy = log_policy
    app.state.terminal_executor = terminal_executor
    app.state.access_token = access_token
    app.state.ai_service = ai_service
    app.state.mcp_service = mcp_service
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(health_router)
    app.include_router(ai_router)
    app.include_router(legacy_ai_router)
    app.include_router(tasks_router)
    app.include_router(device_sources_router)
    app.include_router(mcp_router)
    app.include_router(operations_router)
    app.include_router(package_builds_router)
    app.include_router(devices_router)
    app.include_router(profiles_router)
    app.include_router(sessions_router)
    app.include_router(commands_router)
    app.include_router(automation_router)
    app.include_router(transfers_router)
    app.include_router(auth_router)
    app.include_router(ws_tickets_router)
    app.include_router(session_logs_router)
    app.include_router(websocket_router)

    install_exception_handlers(app)
    return app
