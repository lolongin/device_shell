"""Tasking protocol models and compatibility result records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from device_tui.application.device_control import DeviceTarget

from .protocol import (
    Action,
    Checkpoint,
    Decision,
    DecisionActor,
    DecisionContext,
    DecisionMode,
    ProtocolModel,
    StepStatus,
    Task,
    TaskStatus,
    ToolError,
    ToolResult,
    ToolStatus,
    WorkflowCheckpoint,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStep,
    WorkflowStepState,
)


@dataclass(frozen=True, slots=True)
class DecisionRequest(ProtocolModel):
    """Legacy internal request retained while DecisionContext is adopted."""

    task_id: str
    step: WorkflowStep
    context: dict[str, Any]
    outputs: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DecisionResult(ProtocolModel):
    approved: bool
    action: Action | str = ""
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkflowStepResult(ProtocolModel):
    step_id: str
    status: StepStatus | str
    action: Action | str = ""
    output: str = ""
    error_code: str = ""
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowStepResult:
        raw_action = payload.get("action", "")
        action = Action.from_dict(raw_action) if isinstance(raw_action, Mapping) else str(raw_action or "")
        return cls(
            step_id=str(payload.get("step_id") or ""),
            status=str(payload.get("status") or "failed"),
            action=action,
            output=str(payload.get("output") or ""),
            error_code=str(payload.get("error_code") or ""),
            message=str(payload.get("message") or ""),
            data=dict(payload.get("data") or {}),
        )


@dataclass(frozen=True, slots=True)
class WorkflowResult(ProtocolModel):
    status: TaskStatus | str
    steps: tuple[WorkflowStepResult, ...]
    outputs: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""
    message: str = ""

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> WorkflowResult:
        return cls(
            status=str(payload.get("status") or "failed"),
            steps=tuple(
                WorkflowStepResult.from_dict(item)
                for item in payload.get("steps", ())
                if isinstance(item, Mapping)
            ),
            outputs=dict(payload.get("outputs") or {}),
            error_code=str(payload.get("error_code") or ""),
            message=str(payload.get("message") or ""),
        )


@dataclass(frozen=True, slots=True)
class TaskRecord(ProtocolModel):
    """Existing TaskManager snapshot; new integrations should use Task."""

    id: str
    status: TaskStatus | str
    workflow_id: str
    device_id: str
    session_id: str = ""
    source: str = "unknown"
    created_at: str = ""
    updated_at: str = ""
    progress_percent: int = 0
    current_step_id: str = ""
    error_code: str = ""
    message: str = ""
    result: WorkflowResult | None = None
    checkpoint: Checkpoint | None = None
    plan_id: str = ""
    plan_hash: str = ""
    parent_task_id: str = ""
    plan_revision: int = 0

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TaskRecord:
        raw_result = payload.get("result")
        raw_checkpoint = payload.get("checkpoint")
        return cls(
            id=str(payload.get("id") or ""),
            status=str(payload.get("status") or TaskStatus.PENDING.value),
            workflow_id=str(payload.get("workflow_id") or ""),
            device_id=str(payload.get("device_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            source=str(payload.get("source") or "unknown"),
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            progress_percent=int(payload.get("progress_percent") or 0),
            current_step_id=str(payload.get("current_step_id") or ""),
            error_code=str(payload.get("error_code") or ""),
            message=str(payload.get("message") or ""),
            result=WorkflowResult.from_dict(raw_result) if isinstance(raw_result, Mapping) else None,
            checkpoint=Checkpoint.from_dict(raw_checkpoint) if isinstance(raw_checkpoint, Mapping) else None,
            plan_id=str(payload.get("plan_id") or ""),
            plan_hash=str(payload.get("plan_hash") or ""),
            parent_task_id=str(payload.get("parent_task_id") or ""),
            plan_revision=max(0, int(payload.get("plan_revision") or 0)),
        )


@dataclass(frozen=True, slots=True)
class TaskCreate(ProtocolModel):
    workflow: WorkflowDefinition
    target: DeviceTarget
    source: str = "unknown"
    context: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> TaskCreate:
        raw_workflow = payload.get("workflow")
        raw_target = payload.get("target")
        if not isinstance(raw_workflow, Mapping) or not isinstance(raw_target, Mapping):
            raise ValueError("TaskCreate requires workflow and target objects")
        return cls(
            workflow=WorkflowDefinition.from_dict(raw_workflow),
            target=DeviceTarget(
                device_id=str(raw_target.get("device_id") or ""),
                session_id=str(raw_target.get("session_id") or ""),
                protocol=str(raw_target.get("protocol") or "auto"),
            ),
            source=str(payload.get("source") or "unknown"),
            context=dict(payload.get("context") or {}),
        )


__all__ = [
    "Action",
    "Checkpoint",
    "Decision",
    "DecisionActor",
    "DecisionContext",
    "DecisionMode",
    "DecisionRequest",
    "DecisionResult",
    "StepStatus",
    "Task",
    "TaskCreate",
    "TaskRecord",
    "TaskStatus",
    "ToolError",
    "ToolResult",
    "ToolStatus",
    "WorkflowCheckpoint",
    "WorkflowDefinition",
    "WorkflowInstance",
    "WorkflowResult",
    "WorkflowStep",
    "WorkflowStepResult",
    "WorkflowStepState",
]
