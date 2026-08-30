"""Task-level orchestration for composing independent Workflow runs."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Protocol
from uuid import uuid4

from .models import FrameworkModel, RunStatus, WorkflowDefinition, WorkflowRun
from .resources import ResourceCoordinator, ResourceLease, ResourceRequest
from .runtime import WorkflowRuntime


class TaskRunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_CHILD = "waiting_child"
    WAITING_DECISION = "waiting_decision"
    WAITING_RECONCILE = "waiting_reconcile"
    UNKNOWN = "unknown"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class WorkflowNode(FrameworkModel):
    id: str
    workflow_id: str
    depends_on: tuple[str, ...] = ()
    # Values may be literal JSON-compatible inputs or ``${path}`` references
    # resolved against the parent TaskRun inputs/outputs.
    input_mapping: dict[str, Any] = field(default_factory=dict)
    version: str = "1"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowNode":
        return cls(
            id=str(payload.get("id") or ""),
            workflow_id=str(payload.get("workflow_id") or payload.get("workflow") or ""),
            depends_on=tuple(str(item) for item in payload.get("depends_on", ()) if str(item)),
            input_mapping={str(key): value for key, value in dict(payload.get("input_mapping") or payload.get("inputs") or {}).items()},
            version=str(payload.get("version") or "1"),
        )


@dataclass(frozen=True, slots=True)
class TaskPlan(FrameworkModel):
    id: str
    version: str = "1"
    nodes: tuple[WorkflowNode, ...] = ()

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TaskPlan":
        raw_nodes = payload.get("nodes") or payload.get("workflows") or ()
        return cls(
            id=str(payload.get("id") or payload.get("plan_id") or ""),
            version=str(payload.get("version") or "1"),
            nodes=tuple(
                WorkflowNode.from_dict(item)
                for item in raw_nodes
                if isinstance(item, Mapping)
            ),
        )

    def validate(self) -> None:
        if not self.id.strip() or not self.version.strip() or not self.nodes:
            raise ValueError("task plan id, version, and nodes are required")
        ids = {node.id for node in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("task plan node ids must be unique")
        for node in self.nodes:
            if node.workflow_id.strip() == "":
                raise ValueError(f"workflow id is required for node: {node.id}")
            unknown = set(node.depends_on) - ids
            if unknown:
                raise ValueError(f"node {node.id} depends on unknown nodes: {', '.join(sorted(unknown))}")
        self._ordered_nodes()

    def _ordered_nodes(self) -> tuple[WorkflowNode, ...]:
        pending = {node.id: node for node in self.nodes}
        ordered: list[WorkflowNode] = []
        while pending:
            ready = [node for node in pending.values() if set(node.depends_on) <= {item.id for item in ordered}]
            if not ready:
                raise ValueError("task plan contains a dependency cycle")
            for node in sorted(ready, key=lambda item: item.id):
                ordered.append(node)
                pending.pop(node.id)
        return tuple(ordered)


@dataclass(frozen=True, slots=True)
class TaskRun(FrameworkModel):
    id: str
    plan_id: str
    device_id: str
    status: TaskRunStatus | str = TaskRunStatus.CREATED
    inputs: dict[str, Any] = field(default_factory=dict)
    node_runs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    context: dict[str, Any] = field(default_factory=dict)


class TaskRunStore(Protocol):
    def save(self, run: TaskRun) -> TaskRun: ...
    def get(self, task_run_id: str) -> TaskRun: ...
    def list(self, *, limit: int = 500) -> list[TaskRun]: ...
    def delete(self, task_run_id: str) -> None: ...


class MemoryTaskRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, TaskRun] = {}

    def save(self, run: TaskRun) -> TaskRun:
        self._runs[run.id] = run
        return run

    def get(self, task_run_id: str) -> TaskRun:
        try:
            return self._runs[task_run_id]
        except KeyError as exc:
            raise KeyError(f"task run not found: {task_run_id}") from exc

    def list(self, *, limit: int = 500) -> list[TaskRun]:
        return list(self._runs.values())[:max(0, limit)]

    def delete(self, task_run_id: str) -> None:
        self._runs.pop(task_run_id, None)


class WorkflowBuilder(Protocol):
    def build(self, workflow_id: str, inputs: dict[str, Any]) -> WorkflowDefinition: ...


class TaskOrchestrator:
    """Compose WorkflowRuns without making Workflow implementations aware of Tasks."""

    def __init__(
        self,
        runtime: WorkflowRuntime,
        workflows: WorkflowBuilder,
        *,
        store: TaskRunStore | None = None,
        resource_coordinator: ResourceCoordinator | None = None,
    ) -> None:
        self.runtime = runtime
        self.workflows = workflows
        self.store = store or MemoryTaskRunStore()
        self.resource_coordinator = resource_coordinator
        self._runs: dict[str, TaskRun] = {}
        self._resource_leases: dict[str, ResourceLease] = {}
        for run in self.store.list():
            # A TaskRun is a durable parent boundary. On process restart any
            # in-flight parent must be fenced until its child WorkflowRun has
            # gone through the runtime recovery path. This keeps the parent
            # projection from advertising ``running`` while the child is
            # paused/recovering, including tasks that had not created a child
            # yet when the process stopped.
            if str(run.status) in {
                TaskRunStatus.RUNNING.value,
                TaskRunStatus.WAITING_CHILD.value,
            }:
                run = replace(
                    run,
                    status=TaskRunStatus.WAITING_RECONCILE,
                    context={
                        **run.context,
                        "framework.recovery": {
                            "required": True,
                            "reason": "process_restart",
                        },
                    },
                )
                self.store.save(run)
            self._runs[run.id] = run

    def start(
        self,
        plan: TaskPlan,
        *,
        device_id: str,
        inputs: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        task_run_id: str | None = None,
        child_run_id: str | None = None,
    ) -> TaskRun:
        plan.validate()
        if not device_id.strip():
            raise ValueError("device_id is required")
        resolved_id = task_run_id or str(uuid4())
        run_context = dict(context or {})
        run_context.setdefault("resource_owner_id", resolved_id)
        if child_run_id:
            if len(plan.nodes) != 1:
                raise ValueError("child_run_id is only supported for single-node TaskPlans")
            run_context["orchestrator.child_run_id"] = str(child_run_id)
        if self.resource_coordinator is not None:
            self._resource_leases[resolved_id] = self.resource_coordinator.acquire(
                ResourceRequest("device", device_id, resolved_id)
            )
        run = TaskRun(
            id=resolved_id,
            plan_id=plan.id,
            device_id=device_id,
            status=TaskRunStatus.RUNNING,
            inputs=dict(inputs or {}),
            context=run_context,
        )
        self._save(run)
        return run

    def get(self, task_run_id: str) -> TaskRun:
        try:
            return self._runs[task_run_id]
        except KeyError:
            run = self.store.get(task_run_id)
            self._runs[run.id] = run
            return run

    def list(self, *, limit: int = 500) -> list[TaskRun]:
        """List task runs from the in-memory index, backed by the store."""
        return list(self._runs.values())[:max(0, limit)]

    def pause(self, task_run_id: str) -> TaskRun:
        """Pause the active child workflow and persist the task boundary."""
        task = self.get(task_run_id)
        if str(task.status) in {
            TaskRunStatus.SUCCEEDED.value,
            TaskRunStatus.FAILED.value,
            TaskRunStatus.CANCELLED.value,
        }:
            return task
        child = self._active_child(task)
        if child is not None:
            self.runtime.pause(child.id)
        return self._save(replace(task, status=TaskRunStatus.WAITING_RECONCILE))

    def resume(self, task_run_id: str, *, context: Mapping[str, Any] | None = None) -> TaskRun:
        """Resume a task; child recovery remains owned by ``WorkflowRuntime``."""
        task = self.get(task_run_id)
        child = self._active_child(task)
        if child is not None:
            self.runtime.resume(child.id, context=dict(context or {}))
        return self._save(replace(task, status=TaskRunStatus.RUNNING, context={**task.context, **dict(context or {})}))

    def cancel(self, task_run_id: str) -> TaskRun:
        """Cancel the active child workflow and release task resources."""
        task = self.get(task_run_id)
        if str(task.status) in {
            TaskRunStatus.SUCCEEDED.value,
            TaskRunStatus.FAILED.value,
            TaskRunStatus.CANCELLED.value,
        }:
            return task
        child = self._active_child(task)
        if child is not None:
            self.runtime.cancel(child.id)
        return self._save(replace(task, status=TaskRunStatus.CANCELLED))

    def delete(self, task_run_id: str) -> None:
        """Remove a terminal TaskRun from the task history store."""
        task = self.get(task_run_id)
        if str(task.status) not in {
            TaskRunStatus.SUCCEEDED.value,
            TaskRunStatus.FAILED.value,
            TaskRunStatus.CANCELLED.value,
        }:
            raise ValueError("only terminal task runs can be deleted")
        self._runs.pop(task_run_id, None)
        delete = getattr(self.store, "delete", None)
        if callable(delete):
            delete(task_run_id)

    def apply_decision(self, task_run_id: str, submission: Any) -> TaskRun:
        """Apply a decision to the active child Workflow and project status."""
        task = self.get(task_run_id)
        child = self._active_child(task)
        if child is None:
            raise ValueError("task is not waiting for a child Workflow decision")
        updated_child = self.runtime.apply_decision(child.id, submission)
        status = self._aggregate_child_status(str(updated_child.status))
        if str(updated_child.status) == RunStatus.RUNNING.value:
            status = TaskRunStatus.RUNNING
        elif str(updated_child.status) == RunStatus.SUCCEEDED.value:
            status = TaskRunStatus.RUNNING
        return self._save(replace(task, status=status))

    def _active_child(self, task: TaskRun):
        for node_id in reversed(tuple(task.node_runs)):
            child = self.runtime.runs.get(task.node_runs[node_id])
            if str(child.status) not in {
                RunStatus.SUCCEEDED.value,
                RunStatus.FAILED.value,
                RunStatus.CANCELLED.value,
            }:
                return child
        return None

    async def execute(self, task_run_id: str, plan: TaskPlan) -> TaskRun:
        task = self.get(task_run_id)
        plan.validate()
        if task.plan_id != plan.id:
            raise ValueError(
                f"task run plan mismatch: expected {task.plan_id}, received {plan.id}"
            )
        if self.resource_coordinator is not None and task.id not in self._resource_leases:
            owner_id = str(task.context.get("resource_owner_id") or task.id)
            self._resource_leases[task.id] = self.resource_coordinator.acquire(
                ResourceRequest("device", task.device_id, owner_id)
            )
        outputs = dict(task.outputs)
        node_runs = dict(task.node_runs)
        try:
            for node in plan._ordered_nodes():
                if node.id in node_runs:
                    child = self.runtime.runs.get(node_runs[node.id])
                    child_status = str(child.status)
                    if child_status in {RunStatus.RUNNING.value, RunStatus.RECOVERING.value}:
                        child = await self.runtime.run_until_blocked(child.id)
                        child_status = str(child.status)
                    if child_status != RunStatus.SUCCEEDED.value:
                        aggregate = self._aggregate_child_status(child_status)
                        if aggregate in {TaskRunStatus.FAILED, TaskRunStatus.CANCELLED, TaskRunStatus.UNKNOWN}:
                            return self._save(replace(
                                task,
                                status=aggregate,
                                outputs=outputs,
                                error=getattr(child, "error", None),
                            ))
                        return self._save(replace(task, status=aggregate, outputs=outputs))
                    outputs[node.id] = dict(child.outputs)
                    continue
                node_inputs = self._resolve_inputs(node.input_mapping, {**task.inputs, **outputs})
                definition = self.workflows.build(node.workflow_id, node_inputs)
                child = self.runtime.start(
                    definition,
                    device_id=task.device_id,
                    run_id=(
                        str(task.context.get("orchestrator.child_run_id") or "") or None
                        if len(plan.nodes) == 1 else None
                    ),
                    context={
                        **task.context,
                        "task_run_id": task.id,
                        "node_id": node.id,
                        "inputs": node_inputs,
                        "resource_owner_id": str(task.context.get("resource_owner_id") or task.id),
                    },
                )
                node_runs[node.id] = child.id
                task = self._save(replace(task, node_runs=dict(node_runs), status=TaskRunStatus.WAITING_CHILD))
                child = await self.runtime.run_until_blocked(child.id)
                child_status = str(child.status)
                if child_status != RunStatus.SUCCEEDED.value:
                    aggregate = self._aggregate_child_status(child_status)
                    return self._save(replace(
                        task,
                        status=aggregate,
                        outputs=outputs,
                        error=getattr(child, "error", None)
                        if aggregate in {TaskRunStatus.FAILED, TaskRunStatus.UNKNOWN}
                        else task.error,
                    ))
                outputs[node.id] = dict(child.outputs)
                task = self._save(replace(task, outputs=dict(outputs), status=TaskRunStatus.RUNNING))
            return self._save(replace(task, status=TaskRunStatus.SUCCEEDED, outputs=outputs))
        except Exception as exc:
            # A failed child creation/resolution can leave a runtime lease
            # behind before the child reaches a terminal state. Fence those
            # children so a failed Task cannot block later plans forever.
            for child_id in node_runs.values():
                try:
                    child = self.runtime.runs.get(child_id)
                except KeyError:
                    continue
                if str(child.status) not in {
                    RunStatus.SUCCEEDED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELLED.value,
                }:
                    self.runtime.cancel(child.id)
            return self._save(replace(task, status=TaskRunStatus.FAILED, outputs=outputs, error={"code": "task_orchestration_failed", "message": str(exc)}))

    @staticmethod
    def _aggregate_child_status(status: str) -> TaskRunStatus:
        """Preserve child recovery semantics at the Task boundary."""
        mapping = {
            RunStatus.WAITING_DECISION.value: TaskRunStatus.WAITING_DECISION,
            RunStatus.WAITING_RECONCILE.value: TaskRunStatus.WAITING_RECONCILE,
            RunStatus.RECOVERING.value: TaskRunStatus.WAITING_RECONCILE,
            RunStatus.PAUSED.value: TaskRunStatus.WAITING_RECONCILE,
            RunStatus.CANCELLED.value: TaskRunStatus.CANCELLED,
            "unknown": TaskRunStatus.UNKNOWN,
            RunStatus.FAILED.value: TaskRunStatus.FAILED,
        }
        return mapping.get(status, TaskRunStatus.WAITING_CHILD)

    @staticmethod
    def _resolve_inputs(mapping: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for name, expression in mapping.items():
            if not isinstance(expression, str) or not expression.startswith("${") or not expression.endswith("}"):
                resolved[name] = expression
                continue
            path = expression[2:-1].split(".")
            current: Any = values
            for segment in path:
                if isinstance(current, Mapping) and segment in current:
                    current = current[segment]
                else:
                    raise ValueError(f"unresolved task input: {expression}")
            resolved[name] = current
        return resolved

    def _save(self, run: TaskRun) -> TaskRun:
        self._runs[run.id] = run
        self.store.save(run)
        if run.status in {
            TaskRunStatus.SUCCEEDED,
            TaskRunStatus.FAILED,
            TaskRunStatus.CANCELLED,
        }:
            lease = self._resource_leases.pop(run.id, None)
            if lease is not None and self.resource_coordinator is not None:
                self.resource_coordinator.release(lease)
        return run


__all__ = [
    "MemoryTaskRunStore",
    "TaskOrchestrator",
    "TaskPlan",
    "TaskRun",
    "TaskRunStatus",
    "TaskRunStore",
    "WorkflowNode",
]
