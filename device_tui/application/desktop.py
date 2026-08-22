"""Composition root for desktop-facing Python application services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from device_tui.domain.devices.repository import DeviceRepository
from .automation import AutomationService, AutomationStore, MemoryAutomationStore
from .credentials import CredentialResolver, RepositoryCredentialResolver
from .commands import CommandService, CommandStore, MemoryCommandStore
from .devices import DeviceService
from .device_control import DeviceControlService
from .events import EventBus
from .profiles import (
    CompositeCredentialResolver,
    ConnectionProfileService,
    ConnectionProfileStore,
    MemoryConnectionProfileStore,
)
from .operations import MemoryOperationStore, OperationManager, OperationStore
from .secrets import MemorySecretStore, SecretStore
from .sessions import SessionManager, SessionService
from .settings import MemorySettingsStore, SettingsStore
from .transfers import (
    ManagedTransferService,
    MemoryTransferStore,
    TerminalPlanExecutor,
    TransferStore,
    UnavailableTerminalPlanExecutor,
)
from .upgrades import PackageUpgradeService
from .tasking import DeviceExecutionTool, MemoryTaskStore, TaskManager, TaskStore


@dataclass(frozen=True, slots=True)
class DesktopApplication:
    devices: DeviceService
    sessions: SessionService
    events: EventBus
    credentials: CredentialResolver
    settings: SettingsStore
    profiles: ConnectionProfileService
    secrets: SecretStore
    commands: CommandService
    automation: AutomationService
    operations: OperationManager
    transfers: ManagedTransferService
    upgrades: PackageUpgradeService
    control: DeviceControlService
    tasks: TaskManager


def build_desktop_application(
    repository: DeviceRepository,
    session_manager: SessionManager,
    *,
    profile_store: ConnectionProfileStore | None = None,
    secret_store: SecretStore | None = None,
    command_store: CommandStore | None = None,
    automation_store: AutomationStore | None = None,
    transfer_store: TransferStore | None = None,
    operation_store: OperationStore | None = None,
    settings_store: SettingsStore | None = None,
    terminal_executor: TerminalPlanExecutor | None = None,
    transfer_root: Path | None = None,
    task_store: TaskStore | None = None,
) -> DesktopApplication:
    events = EventBus()
    devices = DeviceService(repository)
    secrets = secret_store or MemorySecretStore()
    profiles = ConnectionProfileService(
        profile_store or MemoryConnectionProfileStore(),
        secrets,
    )
    credentials = CompositeCredentialResolver(
        RepositoryCredentialResolver(repository),
        profiles,
    )
    sessions = SessionService(devices, credentials, session_manager, events)
    automation = AutomationService(
        automation_store or MemoryAutomationStore(),
        sessions,
        secrets,
        events,
    )
    automation.bind_event_source(session_manager)
    operations = OperationManager(
        events,
        operation_store or MemoryOperationStore(),
        persistent_kinds={"managed_file_transfer"},
        history_limit=200,
    )
    executor = terminal_executor or UnavailableTerminalPlanExecutor()
    transfers = ManagedTransferService(
        transfer_store or MemoryTransferStore(),
        secrets,
        sessions,
        operations,
        events,
        terminal_executor=executor,
        default_root=transfer_root,
    )
    upgrades = PackageUpgradeService(sessions, operations, transfers, executor)
    control = DeviceControlService(devices, sessions, transfers, operations, executor, upgrades)
    tasks = TaskManager(DeviceExecutionTool(control), events, store=task_store or MemoryTaskStore())
    return DesktopApplication(
        devices=devices,
        sessions=sessions,
        events=events,
        credentials=credentials,
        settings=settings_store or MemorySettingsStore(),
        profiles=profiles,
        secrets=secrets,
        commands=CommandService(command_store or MemoryCommandStore(), sessions),
        automation=automation,
        operations=operations,
        transfers=transfers,
        upgrades=upgrades,
        control=control,
        tasks=tasks,
    )
