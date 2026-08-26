"""Composition root for desktop-facing Python application services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from device_tui.domain.devices.repository import DeviceRepository
from .automation import AutomationService, AutomationStore, MemoryAutomationStore
from .credentials import CredentialResolver, RepositoryCredentialResolver
from .commands import CommandService, CommandStore, MemoryCommandStore
from .devices import DeviceService
from .device_control import DeviceControlService, DeviceLeaseService
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
from .tasking import (
    DeviceExecutionTool,
    MemoryTaskStore,
    TaskManager,
    TaskStore,
    WorkflowCatalog,
    build_default_workflow_catalog,
)
from .workflows import (
    AdapterRegistry,
    WorkflowRegistry,
    WorkflowRuntime,
    build_default_adapter_registry,
    build_default_workflow_registry,
)
from .workflows.events import WorkflowEventStore
from .workflows.runtime import WorkflowRunStore
from .workflows.device_bridge import build_device_action_registry, build_device_reconcile_registry


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
    leases: DeviceLeaseService
    control: DeviceControlService
    tasks: TaskManager
    workflows: WorkflowCatalog
    framework_workflows: WorkflowRegistry
    framework_adapters: AdapterRegistry
    workflow_runtime: WorkflowRuntime


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
    workflow_catalog: WorkflowCatalog | None = None,
    framework_workflow_registry: WorkflowRegistry | None = None,
    framework_adapter_registry: AdapterRegistry | None = None,
    workflow_runtime: WorkflowRuntime | None = None,
    framework_run_store: WorkflowRunStore | None = None,
    framework_event_store: WorkflowEventStore | None = None,
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
    upgrades = PackageUpgradeService(sessions, transfers, devices=devices)
    # Device upgrades and long terminal plans may legitimately run beyond the
    # short operation timeout. Process restart clears these in-memory leases;
    # normal completion, pause, and cancellation release them explicitly.
    leases = DeviceLeaseService(ttl_seconds=21_600)
    control = DeviceControlService(devices, sessions, transfers, operations, executor, leases=leases)
    execution = DeviceExecutionTool(control)
    workflows = workflow_catalog or build_default_workflow_catalog()
    framework_workflows = framework_workflow_registry or build_default_workflow_registry()
    framework_adapters = framework_adapter_registry or build_default_adapter_registry()
    runtime = workflow_runtime or WorkflowRuntime(
        actions=build_device_action_registry(execution, framework_adapters, transfers),
        reconciliations=build_device_reconcile_registry(execution, control),
        runs=framework_run_store,
        events=framework_event_store,
        leases=leases,
    )
    tasks = TaskManager(
        execution,
        events,
        store=task_store or MemoryTaskStore(),
        leases=leases,
        framework_runtime=runtime,
        framework_workflows=framework_workflows,
    )
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
        leases=leases,
        control=control,
        tasks=tasks,
        workflows=workflows,
        framework_workflows=framework_workflows,
        framework_adapters=framework_adapters,
        workflow_runtime=runtime,
    )
