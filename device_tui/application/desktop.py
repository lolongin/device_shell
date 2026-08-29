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
    TaskService,
    TaskStore,
    WorkflowCatalog,
    build_default_workflow_catalog,
)
from device_tui.framework import (
    ActivityExecutor,
    AdapterRegistry,
    LeaseResourceCoordinator,
    TaskOrchestrator,
    TaskRunStore,
    WorkflowRegistry,
    WorkflowRuntime,
)
from .workflow_plugins.builtins import build_default_adapter_registry, build_default_workflow_registry
from .workflow_plugins.builtins import build_default_activity_executor
from device_tui.framework.events import WorkflowEventStore
from device_tui.framework.runtime import WorkflowRunStore
from .workflow_plugins.device_bridge import build_device_action_registry, build_device_reconcile_registry
from device_tui.infrastructure.vendor_adapters.huawei_vrp.commands import HuaweiVrpDeviceCommandProfile


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
    task_service: TaskService
    workflows: WorkflowCatalog
    framework_workflows: WorkflowRegistry
    framework_adapters: AdapterRegistry
    workflow_runtime: WorkflowRuntime
    activity_executor: ActivityExecutor
    task_orchestrator: TaskOrchestrator


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
    framework_task_run_store: TaskRunStore | None = None,
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
    resources = LeaseResourceCoordinator(device_leases=leases, default_ttl_seconds=21_600)
    command_profile = HuaweiVrpDeviceCommandProfile()
    control = DeviceControlService(
        devices,
        sessions,
        transfers,
        operations,
        executor,
        leases=leases,
        command_profile=command_profile,
    )
    execution = DeviceExecutionTool(control, command_profile=command_profile)
    workflows = workflow_catalog or build_default_workflow_catalog()
    framework_workflows = framework_workflow_registry or build_default_workflow_registry()
    framework_adapters = framework_adapter_registry or build_default_adapter_registry()
    activity_executor = build_default_activity_executor(
        control,
        execution,
        adapters=framework_adapters,
        transfers=transfers,
    )
    runtime = workflow_runtime or WorkflowRuntime(
        actions=build_device_action_registry(
            execution,
            framework_adapters,
            transfers,
            activity_executor=activity_executor,
        ),
        reconciliations=build_device_reconcile_registry(execution, control),
        runs=framework_run_store,
        events=framework_event_store,
        resource_coordinator=resources,
    )
    # Fence persisted in-flight WorkflowRuns before any new work is accepted.
    # Resume APIs will perform reconcile before retrying their last Activity.
    runtime.recover_inflight()
    task_orchestrator = TaskOrchestrator(
        runtime,
        framework_workflows,
        store=framework_task_run_store,
        resource_coordinator=resources,
    )
    tasks = TaskManager(
        execution,
        events,
        store=task_store or MemoryTaskStore(),
        leases=leases,
        framework_runtime=runtime,
        framework_workflows=framework_workflows,
        resource_coordinator=resources,
        task_orchestrator=task_orchestrator,
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
        task_service=TaskService(
            tasks,
            task_orchestrator,
            operation_status=lambda operation_id: control.get_operation(operation_id).status,
        ),
        workflows=workflows,
        framework_workflows=framework_workflows,
        framework_adapters=framework_adapters,
        workflow_runtime=runtime,
        activity_executor=activity_executor,
        task_orchestrator=task_orchestrator,
    )
