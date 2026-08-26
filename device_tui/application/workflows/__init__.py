"""Generic, device-agnostic workflow framework.

The legacy ``application.tasking`` package remains the compatibility API used
by the current desktop surface.  This package contains the framework contracts
that new workflows should implement: events, expectations, reconciliation,
watchdogs, decisions, adapters, and a durable-friendly runtime model.
"""

from .decisions import DecisionEngine, DecisionSubmission, DecisionValidationError
from .dsl import WorkflowDslError, compile_workflow
from .events import Event, MemoryWorkflowEventStore, WorkflowEventStore
from .builtins import build_default_adapter_registry, build_default_workflow_registry
from .huawei_package import HuaweiVrpPackageUpgradeProvider, HuaweiVrpWorkflowAdapter
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
    AdapterRegistry,
    DeviceAdapter,
    ReconcileRegistry,
    ReconcileProvider,
    WorkflowProvider,
    WorkflowRegistry,
)
from .runtime import MemoryWorkflowRunStore, WorkflowRuntime
from .watchdog import Watchdog, WatchdogIncident

__all__ = [
    "ActionAttempt",
    "ActionHandler",
    "ActionRegistry",
    "ActionResult",
    "ActionSpec",
    "ActionStatus",
    "AdapterRegistry",
    "DecisionEngine",
    "DecisionPoint",
    "DecisionSubmission",
    "DecisionValidationError",
    "DeviceAdapter",
    "DeviceStateSnapshot",
    "Event",
    "Expectation",
    "InteractionPolicy",
    "MemoryWorkflowEventStore",
    "MemoryWorkflowRunStore",
    "Option",
    "ProgressSnapshot",
    "ReconcileClassification",
    "ReconcileProvider",
    "ReconcilePolicy",
    "ReconcileRegistry",
    "ReconcileResult",
    "RetryPolicy",
    "RunStatus",
    "StateNode",
    "Watchdog",
    "WatchdogIncident",
    "WorkflowDefinition",
    "WorkflowDslError",
    "WorkflowEventStore",
    "WorkflowProvider",
    "WorkflowRegistry",
    "WorkflowRun",
    "WorkflowRuntime",
    "HuaweiVrpPackageUpgradeProvider",
    "HuaweiVrpWorkflowAdapter",
    "build_default_adapter_registry",
    "build_default_workflow_registry",
    "compile_workflow",
]
