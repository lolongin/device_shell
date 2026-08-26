"""Transport-neutral models for the generic workflow framework."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from enum import Enum
from typing import Any, Mapping


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class RunStatus(_StringEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_RECONCILE = "waiting_reconcile"
    WAITING_DECISION = "waiting_decision"
    RECOVERING = "recovering"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActionStatus(_StringEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class ReconcileClassification(_StringEnum):
    SUCCESS = "confirmed_success"
    NOT_STARTED = "confirmed_not_started"
    IN_PROGRESS = "confirmed_in_progress"
    FAILED = "confirmed_failed"
    INDETERMINATE = "indeterminate"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


class FrameworkModel:
    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))


@dataclass(frozen=True, slots=True)
class RetryPolicy(FrameworkModel):
    max_attempts: int = 1
    retryable_classes: tuple[str, ...] = ("transient", "timeout")
    backoff_seconds: float = 0.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds cannot be negative")


@dataclass(frozen=True, slots=True)
class Expectation(FrameworkModel):
    event_type: str
    timeout_seconds: float = 30.0
    idle_timeout_seconds: float = 0.0
    predicate: dict[str, Any] = field(default_factory=dict)
    terminal: bool = True
    progress: bool = False

    def __post_init__(self) -> None:
        if not self.event_type.strip():
            raise ValueError("expectation event_type is required")
        if self.timeout_seconds <= 0:
            raise ValueError("expectation timeout_seconds must be positive")
        if self.idle_timeout_seconds < 0:
            raise ValueError("expectation idle_timeout_seconds cannot be negative")


@dataclass(frozen=True, slots=True)
class InteractionPolicy(FrameworkModel):
    """Prompt handling belongs here, never in DecisionPoint."""

    confirmations: dict[str, str] = field(default_factory=dict)
    secret_refs: tuple[str, ...] = ()
    max_prompt_matches: int = 3


@dataclass(frozen=True, slots=True)
class ReconcilePolicy(FrameworkModel):
    provider: str = ""
    probes: tuple[str, ...] = ()
    budget_seconds: float = 60.0
    on_classification: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Option(FrameworkModel):
    id: str
    kind: str
    label: str
    description: str = ""
    risk: str = "normal"
    allowed_actors: tuple[str, ...] = ("human", "agent", "rule")
    requires_reason: bool = False
    input_schema: dict[str, Any] = field(default_factory=dict)
    preconditions: tuple[dict[str, Any], ...] = ()
    next_state: str = ""


@dataclass(frozen=True, slots=True)
class ActionSpec(FrameworkModel):
    id: str
    operation: str
    params: dict[str, Any] = field(default_factory=dict)
    expectations: tuple[Expectation, ...] = ()
    timeout_seconds: float = 60.0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    interaction: InteractionPolicy = field(default_factory=InteractionPolicy)
    reconcile: ReconcilePolicy = field(default_factory=ReconcilePolicy)
    idempotency_key: str = ""
    risk: str = "normal"

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.operation.strip():
            raise ValueError("action id and operation are required")
        if self.timeout_seconds <= 0:
            raise ValueError("action timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class StateNode(FrameworkModel):
    id: str
    action: ActionSpec | None = None
    next_state: str = ""
    transitions: dict[str, str] = field(default_factory=dict)
    decision_options: tuple[Option, ...] = ()
    terminal: bool = False
    # Provider-owned presentation metadata. The runtime only uses the stable
    # identifier; clients can render this without maintaining workflow maps.
    label: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowDefinition(FrameworkModel):
    id: str
    version: str
    start_state: str
    states: tuple[StateNode, ...]
    required_capabilities: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id.strip() or not self.version.strip():
            raise ValueError("workflow id and version are required")
        if not self.states:
            raise ValueError("workflow must contain at least one state")
        by_id = {state.id: state for state in self.states}
        if len(by_id) != len(self.states) or self.start_state not in by_id:
            raise ValueError("workflow states or start_state are invalid")
        references = []
        for state in self.states:
            if state.next_state:
                references.append(state.next_state)
            references.extend(state.transitions.values())
            if state.action is not None and state.action.reconcile.provider == "":
                risky = state.action.risk.casefold() in {"high", "critical"}
                if risky and not state.action.reconcile.probes:
                    raise ValueError(f"destructive state requires reconcile probes: {state.id}")
        if any(reference not in by_id for reference in references):
            raise ValueError("workflow references an unknown state")


@dataclass(frozen=True, slots=True)
class DeviceStateSnapshot(FrameworkModel):
    reachability: str = "unknown"
    transport: str = "unknown"
    cli: str = "unknown"
    facts: dict[str, Any] = field(default_factory=dict)
    observed_at: str = ""


@dataclass(frozen=True, slots=True)
class ProgressSnapshot(FrameworkModel):
    stage: str = ""
    last_event_type: str = ""
    last_progress_at: str = ""
    completed_units: int = 0
    total_units: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActionAttempt(FrameworkModel):
    id: str
    action_id: str
    attempt: int
    status: ActionStatus | str = ActionStatus.PLANNED
    started_at: str = ""
    deadline_at: str = ""
    last_progress_at: str = ""
    last_event_type: str = ""
    session_id: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ActionResult(FrameworkModel):
    status: ActionStatus | str
    events: tuple[Any, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ReconcileResult(FrameworkModel):
    classification: ReconcileClassification | str
    facts: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[dict[str, Any], ...] = ()
    safe_options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DecisionPoint(FrameworkModel):
    id: str
    run_id: str
    revision: int
    reason_code: str
    summary: str
    options: tuple[Option, ...]
    evidence: tuple[dict[str, Any], ...] = ()
    expires_at: str = ""


@dataclass(frozen=True, slots=True)
class WorkflowRun(FrameworkModel):
    id: str
    workflow_id: str
    workflow_version: str
    device_id: str
    status: RunStatus | str = RunStatus.PENDING
    current_state: str = ""
    revision: int = 0
    context: dict[str, Any] = field(default_factory=dict)
    device_state: DeviceStateSnapshot = field(default_factory=DeviceStateSnapshot)
    progress: ProgressSnapshot = field(default_factory=ProgressSnapshot)
    attempts: tuple[ActionAttempt, ...] = ()
    decision_point: DecisionPoint | None = None
    error: dict[str, Any] | None = None
