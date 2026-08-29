"""Transport-neutral contracts for staged side-effecting Activities.

Activities are the execution boundary used by future workflows.  The current
Action contracts remain supported; this module gives new code an explicit way
to describe preconditions, protocol acknowledgements, long-running monitors,
and postcondition verification without coupling those concerns to a vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol

from .events import Event
from .models import FrameworkModel, ReconcilePolicy, RetryPolicy, WorkflowRun


class ActivityStatus(str, Enum):
    PLANNED = "planned"
    PRECONDITION_CHECKING = "precondition_checking"
    PREPARING = "preparing"
    DISPATCHING = "dispatching"
    WAITING_ACK = "waiting_ack"
    MONITORING = "monitoring"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value


class IdempotencyPolicy(str, Enum):
    SAFE = "safe"
    CONDITIONAL = "conditional"
    UNSAFE = "unsafe"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class GuardSpec(FrameworkModel):
    """A read-only precondition and the optional preparation it enables."""

    id: str
    probe: str
    predicate: dict[str, Any] = field(default_factory=dict)
    on_failure: str = "fail"
    preparation_activity: str = ""

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.probe.strip():
            raise ValueError("guard id and probe are required")
        if self.on_failure not in {"fail", "prepare", "decision"}:
            raise ValueError("guard on_failure must be fail, prepare, or decision")
        if self.on_failure == "prepare" and not self.preparation_activity.strip():
            raise ValueError("guard preparation_activity is required when on_failure is prepare")


@dataclass(frozen=True, slots=True)
class ExchangeSpec(FrameworkModel):
    """One send/ack protocol exchange inside an Activity."""

    id: str
    send: str = ""
    secret_ref: str = ""
    accepted_signals: tuple[str, ...] = ()
    failure_signals: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    max_matches: int = 1

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("exchange id is required")
        if not self.send and not self.secret_ref:
            raise ValueError("exchange requires send or secret_ref")
        if self.timeout_seconds <= 0:
            raise ValueError("exchange timeout_seconds must be positive")
        if self.max_matches < 1:
            raise ValueError("exchange max_matches must be positive")


@dataclass(frozen=True, slots=True)
class MonitorSpec(FrameworkModel):
    """Observation policy for an operation that outlives its dispatch call."""

    id: str
    operation_id_path: str = "operation_id"
    progress_signals: tuple[str, ...] = ()
    completion_signals: tuple[str, ...] = ()
    failure_signals: tuple[str, ...] = ()
    poller: str = ""
    timeout_seconds: float = 300.0
    idle_timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("monitor id is required")
        if not self.completion_signals and not self.poller:
            raise ValueError("monitor requires completion_signals or poller")
        if self.timeout_seconds <= 0:
            raise ValueError("monitor timeout_seconds must be positive")
        if self.idle_timeout_seconds < 0:
            raise ValueError("monitor idle_timeout_seconds cannot be negative")


@dataclass(frozen=True, slots=True)
class VerificationSpec(FrameworkModel):
    """Business-level postcondition checked after protocol completion."""

    id: str
    verifier: str
    input_mapping: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    required: bool = True

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.verifier.strip():
            raise ValueError("verification id and verifier are required")
        if self.timeout_seconds <= 0:
            raise ValueError("verification timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class ActivityDefinition(FrameworkModel):
    """Declarative contract for one reusable side-effecting Activity."""

    id: str
    version: str = "1"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    preconditions: tuple[GuardSpec, ...] = ()
    preparation: tuple[str, ...] = ()
    exchanges: tuple[ExchangeSpec, ...] = ()
    monitor: MonitorSpec | None = None
    verification: VerificationSpec | None = None
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    idempotency: IdempotencyPolicy | str = IdempotencyPolicy.CONDITIONAL
    reconcile: ReconcilePolicy = field(default_factory=ReconcilePolicy)
    required_capabilities: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.id.strip() or not self.version.strip():
            raise ValueError("activity id and version are required")
        if len({item.id for item in self.preconditions}) != len(self.preconditions):
            raise ValueError("activity precondition ids must be unique")
        if len({item.id for item in self.exchanges}) != len(self.exchanges):
            raise ValueError("activity exchange ids must be unique")
        if self.monitor is not None and not self.exchanges and not self.preparation:
            raise ValueError("monitored activity must define dispatch behavior")
        try:
            IdempotencyPolicy(str(self.idempotency))
        except ValueError as exc:
            raise ValueError("invalid activity idempotency policy") from exc


@dataclass(frozen=True, slots=True)
class ActivityInvocation(FrameworkModel):
    activity_id: str
    invocation_id: str
    workflow_run_id: str
    attempt: int = 1
    inputs: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.activity_id.strip() or not self.invocation_id.strip() or not self.workflow_run_id.strip():
            raise ValueError("activity invocation identifiers are required")
        if self.attempt < 1:
            raise ValueError("activity invocation attempt must be positive")


@dataclass(frozen=True, slots=True)
class ActivityResult(FrameworkModel):
    status: ActivityStatus | str
    outputs: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[dict[str, Any], ...] = ()
    operation_id: str = ""
    error: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ActivityContext(FrameworkModel):
    workflow_run: WorkflowRun
    invocation: ActivityInvocation


class ProgressReporter(Protocol):
    def __call__(self, event: Event) -> Event: ...


class ActivityHandler(Protocol):
    activity_id: str

    async def execute(
        self,
        invocation: ActivityInvocation,
        context: ActivityContext,
        report: ProgressReporter,
    ) -> ActivityResult: ...

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext) -> None: ...


class ActivityProbe(Protocol):
    """Read-only probe used to evaluate an Activity precondition."""

    probe_id: str

    async def probe(
        self,
        specification: GuardSpec,
        context: ActivityContext,
    ) -> Any: ...


class ActivityVerifier(Protocol):
    verifier_id: str

    async def verify(
        self,
        specification: VerificationSpec,
        result: ActivityResult,
        context: ActivityContext,
    ) -> ActivityResult: ...


class ActivityReconciler(Protocol):
    reconcile_id: str

    async def reconcile(
        self,
        definition: ActivityDefinition,
        invocation: ActivityInvocation,
        context: ActivityContext,
        reason: str,
        report: ProgressReporter,
    ) -> ActivityResult: ...


__all__ = [
    "ActivityContext",
    "ActivityDefinition",
    "ActivityHandler",
    "ActivityInvocation",
    "ActivityReconciler",
    "ActivityResult",
    "ActivityStatus",
    "ActivityProbe",
    "ActivityVerifier",
    "ExchangeSpec",
    "GuardSpec",
    "IdempotencyPolicy",
    "MonitorSpec",
    "ProgressReporter",
    "VerificationSpec",
]
