"""Stable, transport-neutral protocol models for tasks and workflows.

These objects deliberately contain state and facts only.  Workflow branching,
policy evaluation, and operator decisions belong to services above this layer.
All models use JSON-compatible dictionaries so they can be stored in SQLite,
sent over REST/MCP, or written to an audit/event stream without leaking
implementation-specific objects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from enum import Enum
import json
from typing import Any, Literal, Mapping, TypeVar


T = TypeVar("T", bound="ProtocolModel")


class _StringEnum(str, Enum):
    def __str__(self) -> str:
        return self.value


class TaskStatus(_StringEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_DECISION = "waiting_for_decision"
    WAITING_FOR_USER = "waiting_for_user"
    PAUSED = "paused"
    # Resumed is an observable transition/event state.  A runtime may move
    # immediately from RESUMED to RUNNING after recording the checkpoint.
    RESUMED = "resumed"
    COMPLETED = "completed"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(_StringEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_FOR_DECISION = "waiting_for_decision"
    WAITING_FOR_USER = "waiting_for_user"
    PAUSED = "paused"
    RESUMED = "resumed"
    COMPLETED = "completed"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ToolStatus(_StringEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RUNNING = "running"
    WAITING = "waiting"
    CANCELLED = "cancelled"


class DecisionMode(_StringEnum):
    USER = "user"
    AGENT = "agent"


class ProtocolModel:
    """Small serialization contract shared by all public protocol models."""

    def to_dict(self) -> dict[str, Any]:
        return _jsonable(asdict(self))

    def to_json(self, *, sort_keys: bool = True) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=sort_keys, separators=(",", ":"))

    @classmethod
    def from_json(cls: type[T], value: str) -> T:
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise ValueError(f"{cls.__name__} JSON payload must be an object")
        return cls.from_dict(payload)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, ProtocolModel):
        return value.to_dict()
    if is_dataclass(value):
        return {item.name: _jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_jsonable(item) for item in sorted(value, key=str)]
    return value


@dataclass(frozen=True, slots=True)
class ToolError(ProtocolModel):
    code: str = ""
    message: str = ""
    error_class: str = "unknown"
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ToolError:
        return cls(
            code=str(payload.get("code") or ""),
            message=str(payload.get("message") or ""),
            error_class=str(payload.get("error_class") or "unknown"),
            retryable=bool(payload.get("retryable", False)),
            details=dict(payload.get("details") or {}),
        )


@dataclass(frozen=True, slots=True)
class ToolResult(ProtocolModel):
    """Facts returned by a Tool; it never contains a next-action decision."""

    tool: str
    status: ToolStatus | str
    facts: dict[str, Any] = field(default_factory=dict)
    output: str = ""
    error: ToolError | None = None
    operation_id: str = ""
    execution_id: str = ""
    started_at: str = ""
    finished_at: str = ""
    attempt: int = 1
    evidence: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> ToolResult:
        raw_error = payload.get("error")
        return cls(
            tool=str(payload.get("tool") or ""),
            status=str(payload.get("status") or ToolStatus.FAILED.value),
            facts=dict(payload.get("facts") or {}),
            output=str(payload.get("output") or ""),
            error=ToolError.from_dict(raw_error) if isinstance(raw_error, Mapping) else None,
            operation_id=str(payload.get("operation_id") or ""),
            execution_id=str(payload.get("execution_id") or ""),
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            attempt=max(1, int(payload.get("attempt") or 1)),
            evidence=tuple(dict(item) for item in payload.get("evidence", ()) if isinstance(item, Mapping)),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class Action(ProtocolModel):
    """A structured operator action, never an untyped command string."""

    name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    target_step: str = ""
    expected_revision: int | None = None
    risk: str = "normal"
    confirmation_required: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("Action name cannot be empty")

    # Compatibility helpers allow legacy code that used a string action to
    # inspect a structured Action while the workflow engine is migrated.
    def __bool__(self) -> bool:
        return bool(self.name)

    def casefold(self) -> str:
        return self.name.casefold()

    def __str__(self) -> str:
        return self.name

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Action:
        return cls(
            name=str(payload.get("name") or ""),
            parameters=dict(payload.get("parameters") or {}),
            target_step=str(payload.get("target_step") or ""),
            expected_revision=(int(payload["expected_revision"]) if payload.get("expected_revision") is not None else None),
            risk=str(payload.get("risk") or "normal"),
            confirmation_required=bool(payload.get("confirmation_required", False)),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class WorkflowStep(ProtocolModel):
    id: str
    kind: str = "tool"
    # String remains accepted for backward compatibility; new protocol users
    # should provide Action.  Serialization preserves the structured form.
    action: Action | str = ""
    depends_on: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)
    retry_policy: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowStep:
        raw_action = payload.get("action", "")
        action = Action.from_dict(raw_action) if isinstance(raw_action, Mapping) else str(raw_action or "")
        return cls(
            id=str(payload.get("id") or ""),
            kind=str(payload.get("kind") or "tool"),
            action=action,
            depends_on=tuple(str(item) for item in payload.get("depends_on", ()) if str(item)),
            params=dict(payload.get("params") or {}),
            retry_policy=dict(payload.get("retry_policy") or {}),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class WorkflowDefinition(ProtocolModel):
    id: str
    steps: tuple[WorkflowStep, ...]
    version: str = "1"
    name: str = ""
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    max_steps: int = 50
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowDefinition:
        return cls(
            id=str(payload.get("id") or ""),
            steps=tuple(WorkflowStep.from_dict(item) for item in payload.get("steps", ()) if isinstance(item, Mapping)),
            version=str(payload.get("version") or "1"),
            name=str(payload.get("name") or ""),
            description=str(payload.get("description") or ""),
            input_schema=dict(payload.get("input_schema") or {}),
            max_steps=max(1, int(payload.get("max_steps") or 50)),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class WorkflowStepState(ProtocolModel):
    step_id: str
    status: StepStatus | str = StepStatus.PENDING
    attempt: int = 0
    result: ToolResult | None = None
    error: ToolError | None = None
    started_at: str = ""
    finished_at: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowStepState:
        raw_result = payload.get("result")
        raw_error = payload.get("error")
        return cls(
            step_id=str(payload.get("step_id") or ""),
            status=str(payload.get("status") or StepStatus.PENDING.value),
            attempt=max(0, int(payload.get("attempt") or 0)),
            result=ToolResult.from_dict(raw_result) if isinstance(raw_result, Mapping) else None,
            error=ToolError.from_dict(raw_error) if isinstance(raw_error, Mapping) else None,
            started_at=str(payload.get("started_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
        )


@dataclass(frozen=True, slots=True)
class Checkpoint(ProtocolModel):
    id: str = ""
    task_id: str = ""
    workflow_instance_id: str = ""
    revision: int = 0
    current_step: str = ""
    completed_steps: tuple[str, ...] = ()
    step_states: tuple[WorkflowStepState, ...] = ()
    outputs: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    failed_step_id: str = ""
    attempts: dict[str, int] = field(default_factory=dict)
    pending_decision_id: str = ""
    operation_ids: tuple[str, ...] = ()
    error_code: str = ""
    error_message: str = ""
    created_at: str = ""
    # Decisions are kept in the checkpoint so a process restart does not lose
    # the audit trail or a decision that is waiting to be applied.
    decisions: tuple[Decision, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Checkpoint:
        return cls(
            id=str(payload.get("id") or ""),
            task_id=str(payload.get("task_id") or ""),
            workflow_instance_id=str(payload.get("workflow_instance_id") or ""),
            revision=max(0, int(payload.get("revision") or 0)),
            current_step=str(payload.get("current_step") or ""),
            completed_steps=tuple(str(item) for item in payload.get("completed_steps", ()) if str(item)),
            step_states=tuple(WorkflowStepState.from_dict(item) for item in payload.get("step_states", ()) if isinstance(item, Mapping)),
            outputs=dict(payload.get("outputs") or {}),
            context=dict(payload.get("context") or {}),
            failed_step_id=str(payload.get("failed_step_id") or ""),
            attempts={str(key): int(value) for key, value in dict(payload.get("attempts") or {}).items()},
            pending_decision_id=str(payload.get("pending_decision_id") or ""),
            operation_ids=tuple(str(item) for item in payload.get("operation_ids", ()) if str(item)),
            error_code=str(payload.get("error_code") or ""),
            error_message=str(payload.get("error_message") or ""),
            created_at=str(payload.get("created_at") or ""),
            decisions=tuple(Decision.from_dict(item) for item in payload.get("decisions", ()) if isinstance(item, Mapping)),
        )


# Compatibility name used by the first TaskManager implementation.
WorkflowCheckpoint = Checkpoint


@dataclass(frozen=True, slots=True)
class WorkflowInstance(ProtocolModel):
    id: str
    task_id: str
    workflow_id: str
    workflow_version: str = "1"
    status: TaskStatus | str = TaskStatus.PENDING
    current_step: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    step_states: tuple[WorkflowStepState, ...] = ()
    checkpoint: Checkpoint | None = None
    created_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
    error: ToolError | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    decisions: tuple[Decision, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowInstance:
        raw_checkpoint = payload.get("checkpoint")
        raw_error = payload.get("error")
        return cls(
            id=str(payload.get("id") or ""),
            task_id=str(payload.get("task_id") or ""),
            workflow_id=str(payload.get("workflow_id") or ""),
            workflow_version=str(payload.get("workflow_version") or "1"),
            status=str(payload.get("status") or TaskStatus.PENDING.value),
            current_step=str(payload.get("current_step") or ""),
            inputs=dict(payload.get("inputs") or {}),
            outputs=dict(payload.get("outputs") or {}),
            step_states=tuple(WorkflowStepState.from_dict(item) for item in payload.get("step_states", ()) if isinstance(item, Mapping)),
            checkpoint=Checkpoint.from_dict(raw_checkpoint) if isinstance(raw_checkpoint, Mapping) else None,
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            finished_at=str(payload.get("finished_at") or ""),
            error=ToolError.from_dict(raw_error) if isinstance(raw_error, Mapping) else None,
            metadata=dict(payload.get("metadata") or {}),
            decisions=tuple(Decision.from_dict(item) for item in payload.get("decisions", ()) if isinstance(item, Mapping)),
        )


@dataclass(frozen=True, slots=True)
class Task(ProtocolModel):
    id: str
    workflow_instance_id: str
    status: TaskStatus | str = TaskStatus.PENDING
    operator_type: Literal["user", "agent"] = "user"
    operator_id: str = ""
    device_id: str = ""
    source: str = "unknown"
    created_at: str = ""
    updated_at: str = ""
    workflow: WorkflowInstance | None = None
    checkpoint: Checkpoint | None = None
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    decisions: tuple[Decision, ...] = ()

    def __post_init__(self) -> None:
        if self.operator_type not in {"user", "agent"}:
            raise ValueError("Task operator_type must be 'user' or 'agent'")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Task:
        raw_workflow = payload.get("workflow")
        raw_checkpoint = payload.get("checkpoint")
        return cls(
            id=str(payload.get("id") or ""),
            workflow_instance_id=str(payload.get("workflow_instance_id") or ""),
            status=str(payload.get("status") or TaskStatus.PENDING.value),
            operator_type=str(payload.get("operator_type") or "user"),  # type: ignore[arg-type]
            operator_id=str(payload.get("operator_id") or ""),
            device_id=str(payload.get("device_id") or ""),
            source=str(payload.get("source") or "unknown"),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            workflow=WorkflowInstance.from_dict(raw_workflow) if isinstance(raw_workflow, Mapping) else None,
            checkpoint=Checkpoint.from_dict(raw_checkpoint) if isinstance(raw_checkpoint, Mapping) else None,
            context=dict(payload.get("context") or {}),
            metadata=dict(payload.get("metadata") or {}),
            decisions=tuple(Decision.from_dict(item) for item in payload.get("decisions", ()) if isinstance(item, Mapping)),
        )


@dataclass(frozen=True, slots=True)
class DecisionActor(ProtocolModel):
    type: Literal["user", "agent"]
    id: str = ""
    name: str = ""

    def __post_init__(self) -> None:
        if self.type not in {"user", "agent"}:
            raise ValueError("Decision actor.type must be 'user' or 'agent'")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DecisionActor:
        return cls(type=str(payload.get("type") or "user"), id=str(payload.get("id") or ""), name=str(payload.get("name") or ""))  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class DecisionContext(ProtocolModel):
    task_id: str
    workflow_id: str
    current_step: str
    error: ToolError | dict[str, Any] | None = None
    result: ToolResult | dict[str, Any] | None = None
    context: dict[str, Any] = field(default_factory=dict)
    available_actions: tuple[Action, ...] = ()
    decision_modes: tuple[str, ...] = (DecisionMode.USER.value, DecisionMode.AGENT.value)
    workflow_instance_id: str = ""
    checkpoint_revision: int = 0

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DecisionContext:
        raw_error = payload.get("error")
        raw_result = payload.get("result")
        return cls(
            task_id=str(payload.get("task_id") or ""),
            workflow_id=str(payload.get("workflow_id") or ""),
            current_step=str(payload.get("current_step") or ""),
            error=ToolError.from_dict(raw_error) if isinstance(raw_error, Mapping) and "error_class" in raw_error else (dict(raw_error) if isinstance(raw_error, Mapping) else None),
            result=ToolResult.from_dict(raw_result) if isinstance(raw_result, Mapping) and "tool" in raw_result else (dict(raw_result) if isinstance(raw_result, Mapping) else None),
            context=dict(payload.get("context") or {}),
            available_actions=tuple(Action.from_dict(item) for item in payload.get("available_actions", ()) if isinstance(item, Mapping)),
            decision_modes=tuple(str(item) for item in payload.get("decision_modes", ()) if str(item)),
            workflow_instance_id=str(payload.get("workflow_instance_id") or ""),
            checkpoint_revision=max(0, int(payload.get("checkpoint_revision") or 0)),
        )


@dataclass(frozen=True, slots=True)
class Decision(ProtocolModel):
    decision_id: str
    actor: DecisionActor
    action: Action
    reason: str = ""
    timestamp: str = ""
    task_id: str = ""
    workflow_id: str = ""
    expected_revision: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if isinstance(self.action, str):
            object.__setattr__(self, "action", Action(name=self.action))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> Decision:
        raw_actor = payload.get("actor")
        raw_action = payload.get("action")
        if not isinstance(raw_actor, Mapping) or not isinstance(raw_action, Mapping):
            raise ValueError("Decision actor and action must be objects")
        return cls(
            decision_id=str(payload.get("decision_id") or ""),
            actor=DecisionActor.from_dict(raw_actor),
            action=Action.from_dict(raw_action),
            reason=str(payload.get("reason") or ""),
            timestamp=str(payload.get("timestamp") or ""),
            task_id=str(payload.get("task_id") or ""),
            workflow_id=str(payload.get("workflow_id") or ""),
            expected_revision=(int(payload["expected_revision"]) if payload.get("expected_revision") is not None else None),
            metadata=dict(payload.get("metadata") or {}),
        )
