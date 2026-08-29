"""Generic, device-agnostic workflow framework.

The legacy ``application.tasking`` package remains the compatibility API used
by the current desktop surface.  This package contains the framework contracts
that new workflows should implement: events, expectations, reconciliation,
watchdogs, decisions, adapters, and a durable-friendly runtime model.
"""

from .decisions import DecisionEngine, DecisionSubmission, DecisionValidationError
from .activity import (
    ActivityContext,
    ActivityDefinition,
    ActivityHandler,
    ActivityInvocation,
    ActivityProbe,
    ActivityReconciler,
    ActivityResult,
    ActivityStatus,
    ActivityVerifier,
    ExchangeSpec,
    GuardSpec,
    IdempotencyPolicy,
    MonitorSpec,
    ProgressReporter,
    VerificationSpec,
)
from .activity_executor import ActivityActionHandler, ActivityExecutionError, ActivityExecutor
from .orchestrator import (
    MemoryTaskRunStore,
    TaskOrchestrator,
    TaskPlan,
    TaskRun,
    TaskRunStatus,
    TaskRunStore,
    WorkflowNode,
)
from .dsl import WorkflowDslError, compile_workflow
from .events import Event, MemoryWorkflowEventStore, WorkflowEventStore
from .models import (
    ActionAttempt,
    ActionResult,
    ActionSpec,
    ActionStatus,
    DeviceStateSnapshot,
    DecisionPoint,
    Expectation,
    InteractionPolicy,
    Option,
    ProgressSnapshot,
    ReconcileClassification,
    ReconcileResult,
    ReconcilePolicy,
    RetryPolicy,
    RunStatus,
    StateNode,
    WorkflowDefinition,
    WorkflowRun,
)
from .plugins import (
    ActionHandler,
    ActionRegistry,
    ActivityRegistry,
    AdapterRegistry,
    DeviceAdapter,
    DeviceVendorAdapter,
    ReconcileRegistry,
    ReconcileProvider,
    WorkflowProvider,
    WorkflowRegistry,
)
from .runtime import MemoryWorkflowRunStore, WorkflowRuntime
from .resources import LeaseResourceCoordinator, ResourceCoordinator, ResourceLease, ResourceRequest
from .supervisor import ActionSupervisor, SupervisedActionResult
from .watchdog import Watchdog, WatchdogIncident

__all__ = [
    "ActivityContext",
    "ActivityDefinition",
    "ActivityActionHandler",
    "ActivityExecutionError",
    "ActivityExecutor",
    "ActivityHandler",
    "ActivityInvocation",
    "ActivityProbe",
    "ActivityRegistry",
    "ActivityReconciler",
    "ActivityResult",
    "ActivityStatus",
    "ActivityVerifier",
    "TaskOrchestrator",
    "MemoryTaskRunStore",
    "TaskPlan",
    "TaskRun",
    "TaskRunStatus",
    "TaskRunStore",
    "ActionAttempt",
    "ActionHandler",
    "ActionRegistry",
    "ActionResult",
    "ActionSpec",
    "ActionSupervisor",
    "ActionStatus",
    "AdapterRegistry",
    "DecisionEngine",
    "DecisionPoint",
    "DecisionSubmission",
    "DecisionValidationError",
    "DeviceAdapter",
    "DeviceVendorAdapter",
    "DeviceStateSnapshot",
    "Event",
    "ExchangeSpec",
    "Expectation",
    "GuardSpec",
    "IdempotencyPolicy",
    "InteractionPolicy",
    "MemoryWorkflowEventStore",
    "MemoryWorkflowRunStore",
    "MonitorSpec",
    "Option",
    "ProgressSnapshot",
    "ProgressReporter",
    "ReconcileClassification",
    "ReconcileProvider",
    "ReconcilePolicy",
    "ReconcileRegistry",
    "ReconcileResult",
    "RetryPolicy",
    "RunStatus",
    "StateNode",
    "SupervisedActionResult",
    "Watchdog",
    "WatchdogIncident",
    "WorkflowDefinition",
    "WorkflowDslError",
    "WorkflowEventStore",
    "WorkflowProvider",
    "WorkflowRegistry",
    "WorkflowRun",
    "WorkflowNode",
    "WorkflowRuntime",
    "LeaseResourceCoordinator",
    "ResourceCoordinator",
    "ResourceLease",
    "ResourceRequest",
    "VerificationSpec",
    # Compatibility exports. New code should import these from
    # ``application.workflow_plugins``.
    "HuaweiVrpPackageUpgradeProvider",
    "HuaweiVrpWorkflowAdapter",
    "build_default_adapter_registry",
    "build_default_workflow_registry",
    "compile_workflow",
]


def __getattr__(name: str):
    """Load shipped domain plugins only for legacy imports.

    The framework's normal import path remains vendor-neutral. Existing
    callers importing the old names continue to work during migration.
    """
    if name in {"HuaweiVrpPackageUpgradeProvider", "HuaweiVrpWorkflowAdapter"}:
        from device_tui.application.workflow_plugins.huawei_package import (
            HuaweiVrpPackageUpgradeProvider,
            HuaweiVrpWorkflowAdapter,
        )
        return {"HuaweiVrpPackageUpgradeProvider": HuaweiVrpPackageUpgradeProvider,
                "HuaweiVrpWorkflowAdapter": HuaweiVrpWorkflowAdapter}[name]
    if name in {"build_default_adapter_registry", "build_default_workflow_registry", "build_default_activity_executor"}:
        from device_tui.application.workflow_plugins.builtins import (
            build_default_activity_executor,
            build_default_adapter_registry,
            build_default_workflow_registry,
        )
        return {"build_default_adapter_registry": build_default_adapter_registry,
                "build_default_workflow_registry": build_default_workflow_registry,
                "build_default_activity_executor": build_default_activity_executor}[name]
    raise AttributeError(name)
