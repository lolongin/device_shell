"""Task-level orchestration for composing independent Workflow runs."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import asyncio
import re
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from .models import FrameworkModel, RunStatus, WorkflowDefinition, WorkflowRun
from .conditions import evaluate_rules
from .expression import evaluate_expression
from .resources import ResourceCoordinator, ResourceLease, ResourceRequest
from .runtime import WorkflowRuntime


class TaskInputResolutionError(ValueError):
    """Raised when a TaskPlan input reference cannot be resolved."""

    def __init__(
        self,
        expression: str,
        *,
        missing_segment: str,
        available_keys: tuple[str, ...] = (),
        resolved_path: str = "",
    ) -> None:
        available = ", ".join(available_keys) if available_keys else "none"
        location = resolved_path or "<root>"
        super().__init__(
            f"unresolved task input: {expression}; missing segment: {missing_segment}; "
            f"available keys at {location}: {available}"
        )
        self.expression = expression
        self.missing_segment = missing_segment
        self.available_keys = available_keys
        self.resolved_path = resolved_path

    def to_error(self) -> dict[str, Any]:
        return {
            "code": "unresolved_task_input",
            "message": str(self),
            "class": "deterministic",
            "expression": self.expression,
            "missing_segment": self.missing_segment,
            "available_keys": list(self.available_keys),
            "resolved_path": self.resolved_path,
        }


class TaskInputDependencyError(ValueError):
    """Raised when a node references an output outside its dependency chain."""

    def __init__(self, node_id: str, reference: str, required_dependency: str) -> None:
        self.node_id = node_id
        self.reference = reference
        self.required_dependency = required_dependency
        super().__init__(
            f"task input reference requires dependency: node {node_id} references "
            f"{reference}, but {required_dependency} is not an upstream dependency"
        )

    def to_error(self) -> dict[str, Any]:
        return {
            "code": "task_input_dependency_missing",
            "message": str(self),
            "class": "deterministic",
            "node_id": self.node_id,
            "reference": self.reference,
            "required_dependency": self.required_dependency,
        }


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
    # Optional business rule produced by the Workflow Studio branch compiler.
    # It remains JSON-compatible so plans can be persisted and resumed.
    run_if: dict[str, Any] | None = None
    retry_policy: dict[str, Any] = field(default_factory=dict)
    repeat_policy: dict[str, Any] = field(default_factory=dict)
    parallel_group: str | None = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowNode":
        return cls(
            id=str(payload.get("id") or ""),
            workflow_id=str(payload.get("workflow_id") or payload.get("workflow") or ""),
            depends_on=tuple(str(item) for item in payload.get("depends_on", ()) if str(item)),
            input_mapping={str(key): value for key, value in dict(payload.get("input_mapping") or payload.get("inputs") or {}).items()},
            version=str(payload.get("version") or "1"),
            run_if=dict(payload.get("run_if") or {}) or None,
            retry_policy=dict(payload.get("retry_policy") or {}),
            repeat_policy=dict(payload.get("repeat_policy") or payload.get("repeat") or {}),
            parallel_group=str(payload.get("parallel_group") or "").strip() or None,
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
        groups: dict[str, set[str]] = {}
        for node in self.nodes:
            if node.parallel_group:
                groups.setdefault(node.parallel_group, set()).add(node.id)
        for group, members in groups.items():
            for node in self.nodes:
                if node.id in members and set(node.depends_on) & members:
                    raise ValueError(f"parallel group {group} contains dependent nodes")
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

    def execution_batches(self) -> tuple[tuple[WorkflowNode, ...], ...]:
        """Return dependency-safe batches for schedulers.

        Nodes without a parallel group remain singleton batches. Nodes sharing
        a group are batched only when all of their dependencies are complete;
        validation guarantees that group members do not depend on one another.
        This keeps persistence and resume boundaries deterministic.
        """
        ordered = self._ordered_nodes()
        batches: list[tuple[WorkflowNode, ...]] = []
        pending = {node.id: node for node in ordered}
        completed: set[str] = set()
        while pending:
            ready = [node for node in ordered if node.id in pending and set(node.depends_on) <= completed]
            if not ready:
                raise ValueError("task plan contains a dependency cycle")
            first = ready[0]
            if first.parallel_group:
                batch = tuple(node for node in ready if node.parallel_group == first.parallel_group)
            else:
                batch = (first,)
            batches.append(batch)
            for node in batch:
                pending.pop(node.id, None)
                completed.add(node.id)
        return tuple(batches)


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
        sleep: Callable[[float], Any] | None = None,
    ) -> None:
        self.runtime = runtime
        self.workflows = workflows
        self.store = store or MemoryTaskRunStore()
        self.resource_coordinator = resource_coordinator
        self._sleep = sleep or asyncio.sleep
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

    def resume(self, task_run_id: str, *, context: Mapping[str, Any] | None = None, step_id: str = "", plan: TaskPlan | None = None) -> TaskRun:
        """Resume a task; child recovery remains owned by ``WorkflowRuntime``."""
        task = self.get(task_run_id)
        if step_id:
            if plan is None or step_id not in {node.id for node in plan.nodes}:
                raise ValueError(f"unknown workflow step: {step_id}")
            return self._resume_from_step(task, plan, step_id, context=context, cancel_active=True)
        child = self._active_child(task)
        if child is not None:
            self.runtime.resume(child.id, context=dict(context or {}))
        elif plan is not None and str(task.status) in {TaskRunStatus.FAILED.value, TaskRunStatus.UNKNOWN.value}:
            failed_step = self._failed_child_step(task, plan)
            if failed_step:
                return self._resume_from_step(task, plan, failed_step, context=context)
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
        outputs = dict(task.outputs)
        projected = self._project_node_outputs(updated_child.outputs)
        if projected:
            node_id = str(child.context.get("node_id") or "").strip()
            if node_id:
                outputs[node_id] = projected
        if str(updated_child.status) == RunStatus.RUNNING.value:
            status = TaskRunStatus.RUNNING
        elif str(updated_child.status) == RunStatus.SUCCEEDED.value:
            status = TaskRunStatus.RUNNING
        return self._save(replace(task, status=status, outputs=outputs))

    async def _execute_parallel_node(
        self,
        task: TaskRun,
        node: WorkflowNode,
        values: Mapping[str, Any],
        on_child_started: Callable[[str, str], None] | None = None,
    ) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None, str | None]:
        """Execute one independent node for a parallel batch."""
        if node.run_if is not None and not self._matches_run_if(node.run_if, task.inputs, values):
            return node.id, "skipped", {"status": "skipped", "reason": "condition_false"}, None, None
        node_inputs = self._resolve_node_inputs(node, task.inputs, values, context=task.context)
        definition = self.workflows.build(node.workflow_id, node_inputs)
        max_attempts = max(1, min(5, int(node.retry_policy.get("max_attempts", 1) or 1)))
        max_iterations = max(1, min(20, int(node.repeat_policy.get("max_iterations", 1) or 1)))
        backoff_seconds = max(0.0, min(60.0, float(node.retry_policy.get("backoff_seconds", 0) or 0)))
        child = None
        for iteration in range(max_iterations):
            for attempt in range(max_attempts):
                if attempt > 0:
                    await self._sleep(backoff_seconds)
                child = self.runtime.start(
                    definition,
                    device_id=task.device_id,
                    context={
                        **task.context,
                        "task_run_id": task.id,
                        "node_id": node.id,
                        "inputs": node_inputs,
                        "retry_attempt": attempt + 1,
                        "retry_limit": max_attempts,
                        "repeat_iteration": iteration + 1,
                        "repeat_limit": max_iterations,
                        "resource_owner_id": str(task.context.get("resource_owner_id") or task.id),
                    },
                )
                if on_child_started is not None:
                    on_child_started(node.id, child.id)
                child = await self.runtime.run_until_blocked(child.id)
                status = str(child.status)
                if status == RunStatus.SUCCEEDED.value:
                    break
                if status not in {RunStatus.FAILED.value, "unknown"} or attempt + 1 >= max_attempts:
                    return node.id, status, self._project_node_outputs(child.outputs), getattr(child, "error", None), child.id
        assert child is not None
        output = self._project_node_outputs(child.outputs)
        if max_iterations > 1:
            output["repeat_iterations"] = max_iterations
        return node.id, RunStatus.SUCCEEDED.value, output, None, child.id

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

    def _resume_from_step(
        self,
        task: TaskRun,
        plan: TaskPlan,
        step_id: str,
        *,
        context: Mapping[str, Any] | None = None,
        cancel_active: bool = False,
    ) -> TaskRun:
        downstream = self._downstream_node_ids(plan, step_id)
        if cancel_active:
            child = self._active_child(task)
            if child is not None:
                cancel = getattr(self.runtime, "cancel", None)
                if callable(cancel):
                    cancel(child.id)
        return self._save(replace(
            task,
            status=TaskRunStatus.RUNNING,
            node_runs={key: value for key, value in task.node_runs.items() if key not in downstream},
            outputs={key: value for key, value in task.outputs.items() if key not in downstream},
            error=None,
            context={**task.context, **dict(context or {}), "resume_from_step": step_id},
        ))

    @staticmethod
    def _downstream_node_ids(plan: TaskPlan, step_id: str) -> set[str]:
        downstream = {step_id}
        changed = True
        while changed:
            changed = False
            for node in plan.nodes:
                if node.id not in downstream and set(node.depends_on) & downstream:
                    downstream.add(node.id)
                    changed = True
        return downstream

    def _failed_child_step(self, task: TaskRun, plan: TaskPlan) -> str:
        restartable = {RunStatus.FAILED.value, RunStatus.CANCELLED.value, "unknown"}
        for node in plan._ordered_nodes():
            child_id = task.node_runs.get(node.id)
            if not child_id:
                continue
            try:
                child = self.runtime.runs.get(child_id)
            except KeyError:
                continue
            if str(child.status) in restartable:
                return node.id
        return ""

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
            self._validate_input_dependencies(plan)
            parallel_batches = {batch[0].id: batch for batch in plan.execution_batches() if len(batch) > 1}
            parallel_completed: set[str] = set()
            for node in plan._ordered_nodes():
                if node.id in parallel_completed:
                    continue
                batch = parallel_batches.get(node.id)
                if batch and not any(item.id in node_runs for item in batch):
                    group_name = batch[0].parallel_group or "parallel"
                    task = self._save(replace(
                        task,
                        status=TaskRunStatus.WAITING_CHILD,
                        context={**task.context, "parallel_batch": {"group": group_name, "node_ids": [item.id for item in batch]}},
                    ))
                    def record_child(node_id: str, child_id: str) -> None:
                        node_runs[node_id] = child_id
                        self._save(replace(task, node_runs=dict(node_runs), status=TaskRunStatus.WAITING_CHILD))
                    results = await asyncio.gather(*(
                        self._execute_parallel_node(task, item, outputs, record_child) for item in batch
                    ))
                    failures = [result for result in results if result[1] not in {RunStatus.SUCCEEDED.value, "skipped"}]
                    if failures:
                        for node_id, _status, output, _error, _child_id in results:
                            if output:
                                outputs[node_id] = dict(output)
                        cancel = getattr(self.runtime, "cancel", None)
                        if callable(cancel):
                            for _node_id, _status, _output, _error, child_id in results:
                                if child_id:
                                    try:
                                        child = self.runtime.runs.get(child_id)
                                        if str(child.status) not in {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}:
                                            cancel(child_id)
                                    except (KeyError, AttributeError):
                                        continue
                        first = failures[0]
                        return self._save(replace(task, status=self._aggregate_child_status(first[1]), outputs=outputs, error=first[3], context={key: value for key, value in task.context.items() if key != "parallel_batch"}))
                    for node_id, _status, output, _error, child_id in results:
                        if child_id:
                            node_runs[node_id] = child_id
                        outputs[node_id] = output or {"status": "skipped", "reason": "condition_false"}
                        self._record_variable_output(outputs, next(item for item in batch if item.id == node_id), outputs[node_id])
                        task = replace(
                            task,
                            context=self._context_with_target_output(task.context, outputs[node_id]),
                        )
                        parallel_completed.add(node_id)
                    task = self._save(replace(task, node_runs=dict(node_runs), outputs=dict(outputs), status=TaskRunStatus.RUNNING, context={key: value for key, value in task.context.items() if key != "parallel_batch"}))
                    continue
                if node.id in node_runs:
                    child = self.runtime.runs.get(node_runs[node.id])
                    child_status = str(child.status)
                    if child_status in {RunStatus.RUNNING.value, RunStatus.RECOVERING.value}:
                        child = await self.runtime.run_until_blocked(child.id)
                        child_status = str(child.status)
                    if child_status != RunStatus.SUCCEEDED.value:
                        aggregate = self._aggregate_child_status(child_status)
                        projected = self._project_node_outputs(child.outputs)
                        if projected:
                            outputs[node.id] = projected
                        if aggregate in {TaskRunStatus.FAILED, TaskRunStatus.CANCELLED, TaskRunStatus.UNKNOWN}:
                            return self._save(replace(
                                task,
                                status=aggregate,
                                outputs=dict(outputs),
                                error=getattr(child, "error", None),
                            ))
                        return self._save(replace(task, status=aggregate, outputs=dict(outputs)))
                    projected = self._project_node_outputs(child.outputs)
                    outputs[node.id] = projected
                    self._record_variable_output(outputs, node, projected)
                    task = replace(task, context=self._context_with_target_output(task.context, projected))
                    continue
                if node.run_if is not None and not self._matches_run_if(node.run_if, task.inputs, outputs):
                    outputs[node.id] = {
                        "status": "skipped",
                        "reason": "condition_false",
                    }
                    task = self._save(replace(task, outputs=dict(outputs), status=TaskRunStatus.RUNNING))
                    continue
                node_inputs = self._resolve_node_inputs(node, task.inputs, outputs, context=task.context)
                definition = self.workflows.build(node.workflow_id, node_inputs)
                max_attempts = max(1, min(5, int(node.retry_policy.get("max_attempts", 1) or 1)))
                max_iterations = max(1, min(20, int(node.repeat_policy.get("max_iterations", 1) or 1)))
                backoff_seconds = max(0.0, min(60.0, float(node.retry_policy.get("backoff_seconds", 0) or 0)))
                child = None
                for _iteration in range(max_iterations):
                    for _attempt in range(max_attempts):
                        if _attempt > 0:
                            await self._sleep(backoff_seconds)
                        child = self.runtime.start(
                            definition,
                            device_id=task.device_id,
                            run_id=(
                                str(task.context.get("orchestrator.child_run_id") or "") or None
                                if len(plan.nodes) == 1 and _attempt == 0 and _iteration == 0 else None
                            ),
                            context={
                                **task.context,
                                "task_run_id": task.id,
                                "node_id": node.id,
                                "inputs": node_inputs,
                                "retry_attempt": _attempt + 1,
                                "retry_limit": max_attempts,
                                "repeat_iteration": _iteration + 1,
                                "repeat_limit": max_iterations,
                                "resource_owner_id": str(task.context.get("resource_owner_id") or task.id),
                            },
                        )
                        node_runs[node.id] = child.id
                        task = self._save(replace(task, node_runs=dict(node_runs), status=TaskRunStatus.WAITING_CHILD))
                        child = await self.runtime.run_until_blocked(child.id)
                        child_status = str(child.status)
                        if child_status == RunStatus.SUCCEEDED.value:
                            break
                        if child_status not in {RunStatus.FAILED.value, "unknown"} or _attempt + 1 >= max_attempts:
                            aggregate = self._aggregate_child_status(child_status)
                            projected = self._project_node_outputs(child.outputs)
                            if projected:
                                outputs[node.id] = projected
                            return self._save(replace(
                                task,
                                status=aggregate,
                                outputs=dict(outputs),
                                error=getattr(child, "error", None)
                                if aggregate in {TaskRunStatus.FAILED, TaskRunStatus.UNKNOWN}
                                else task.error,
                            ))
                    assert child is not None
                    projected = self._project_node_outputs(child.outputs)
                    outputs[node.id] = projected
                    self._record_variable_output(outputs, node, projected)
                    if max_iterations > 1:
                        outputs[node.id]["repeat_iterations"] = _iteration + 1
                    task = self._save(replace(
                        task,
                        outputs=dict(outputs),
                        status=TaskRunStatus.RUNNING,
                        context=self._context_with_target_output(task.context, projected),
                    ))
            return self._save(replace(task, status=TaskRunStatus.SUCCEEDED, outputs=outputs))
        except (TaskInputResolutionError, TaskInputDependencyError) as exc:
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
            return self._save(replace(task, status=TaskRunStatus.FAILED, outputs=outputs, error=exc.to_error()))
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
    def _validate_input_dependencies(plan: TaskPlan) -> None:
        """Ensure node output references have an explicit upstream edge."""
        node_ids = {node.id for node in plan.nodes}
        ancestors: dict[str, set[str]] = {node.id: set() for node in plan.nodes}
        by_id = {node.id: node for node in plan.nodes}
        for node in plan._ordered_nodes():
            for dependency in node.depends_on:
                ancestors[node.id].add(dependency)
                ancestors[node.id].update(ancestors[dependency])

        pattern = re.compile(r"\$\{([^}]+)\}")

        def references(value: Any):
            if isinstance(value, Mapping):
                for nested in value.values():
                    yield from references(nested)
            elif isinstance(value, (list, tuple)):
                for nested in value:
                    yield from references(nested)
            elif isinstance(value, str):
                yield from pattern.findall(value)

        for node in plan.nodes:
            for reference in references(node.input_mapping):
                parts = reference.split(".")
                root = parts[0] if parts else ""
                if root in {"inputs", "context", "device"}:
                    continue
                source = parts[1] if root == "outputs" and len(parts) > 1 else root
                if source in {"item", "index", "iteration", "result"}:
                    continue
                if source in node_ids and source not in ancestors[node.id]:
                    raise TaskInputDependencyError(node.id, reference, source)
                if root == "outputs" and source not in node_ids:
                    continue
                if root not in node_ids and root != "outputs":
                    # Top-level aliases remain valid for generic task inputs;
                    # the Studio validator checks their producer visibility.
                    continue

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

    @classmethod
    def _resolve_node_inputs(
        cls,
        node: WorkflowNode,
        inputs: Mapping[str, Any],
        outputs: Mapping[str, Any],
        *,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        context_values = dict(context or {})
        device_values = (
            {"device": context_values["device"]}
            if isinstance(context_values.get("device"), Mapping)
            else {}
        )
        return cls._resolve_inputs(
            node.input_mapping,
            {
                **inputs,
                **outputs,
                **device_values,
                "inputs": dict(inputs),
                "outputs": dict(outputs),
                "context": context_values,
            },
            deferred_reference_roots=cls._deferred_reference_roots(node),
            deferred_reference_keys=("action_inputs",),
        )

    @staticmethod
    def _deferred_reference_roots(node: WorkflowNode) -> frozenset[str]:
        if node.workflow_id == "loop.for_each":
            return frozenset({"item", "index"})
        if node.workflow_id == "loop.until":
            return frozenset({"iteration", "result", "outputs"})
        return frozenset()

    @staticmethod
    def _project_node_outputs(outputs: Mapping[str, Any]) -> dict[str, Any]:
        """Expose one-step Workflow outputs in one stable, flat shape."""
        projected = dict(outputs)
        run_output = projected.get("run")
        if isinstance(run_output, Mapping):
            for key, value in run_output.items():
                projected.setdefault(str(key), value)
        return projected

    @staticmethod
    def _record_variable_output(
        outputs: dict[str, Any],
        node: WorkflowNode,
        projected: Mapping[str, Any],
    ) -> None:
        if node.workflow_id != "variable.set":
            return
        variable_name = str(projected.get("name") or "").strip()
        if variable_name:
            outputs[variable_name] = projected.get("value")

    @staticmethod
    def _context_with_target_output(
        context: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Carry connection identity from one node to later device actions."""
        target_value = context.get("target")
        target = dict(target_value) if isinstance(target_value, Mapping) else {}
        changed = False
        for key in ("device_id", "session_id", "protocol", "host", "port"):
            value = output.get(key)
            if key == "protocol" and not value:
                value = output.get("recovery_protocol")
            if value not in (None, "") and target.get(key) != value:
                target[key] = value
                changed = True
        if not changed:
            return dict(context)
        return {**context, "target": target}

    @staticmethod
    def _resolve_inputs(
        mapping: Mapping[str, Any],
        values: Mapping[str, Any],
        *,
        deferred_reference_roots: frozenset[str] = frozenset(),
        deferred_reference_keys: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        reference_pattern = re.compile(r"\$\{([^}]+)\}")

        def resolve_reference(
            expression: str,
            container_path: tuple[str, ...],
        ) -> Any:
            path = expression[2:-1].split(".")
            root = path[0] if path else ""
            if root in deferred_reference_roots and (
                not deferred_reference_keys
                or any(key in container_path for key in deferred_reference_keys)
            ):
                return expression
            current: Any = values
            resolved: list[str] = []
            for segment in path:
                if isinstance(current, Mapping) and segment in current:
                    current = current[segment]
                    resolved.append(segment)
                elif (
                    isinstance(current, Mapping)
                    and isinstance(current.get("run"), Mapping)
                    and segment in current["run"]
                ):
                    current = current["run"][segment]
                    resolved.extend(("run", segment))
                else:
                    available = tuple(str(key) for key in current.keys()) if isinstance(current, Mapping) else ()
                    raise TaskInputResolutionError(
                        expression,
                        missing_segment=segment,
                        available_keys=available,
                        resolved_path=".".join(resolved),
                    )
            return current

        def resolve(expression: Any, container_path: tuple[str, ...] = ()) -> Any:
            if isinstance(expression, Mapping):
                return {
                    str(key): resolve(value, container_path + (str(key),))
                    for key, value in expression.items()
                }
            if isinstance(expression, list):
                return [resolve(item, container_path) for item in expression]
            if isinstance(expression, tuple):
                return tuple(resolve(item, container_path) for item in expression)
            if not isinstance(expression, str):
                return expression
            if expression.startswith("${") and expression.endswith("}"):
                return resolve_reference(expression, container_path)
            if container_path and container_path[-1] == "command" and reference_pattern.search(expression):
                return reference_pattern.sub(
                    lambda match: str(resolve_reference("${" + match.group(1) + "}", container_path)),
                    expression,
                )
            return expression
        return {str(name): resolve(expression, (str(name),)) for name, expression in mapping.items()}

    @staticmethod
    def _matches_run_if(
        run_if: Mapping[str, Any],
        inputs: Mapping[str, Any],
        outputs: Mapping[str, Any],
    ) -> bool:
        source_id = str(run_if.get("values_from") or "").strip()
        values: Mapping[str, Any] = outputs.get(source_id, {}) if source_id else {**inputs, **outputs}
        expression = str(run_if.get("expression") or "").strip()
        if expression:
            expression_values = {"inputs": inputs, "outputs": outputs, **inputs, **outputs}
            if source_id:
                expression_values.update(values)
            matched = bool(evaluate_expression(expression, expression_values))
        else:
            matched = evaluate_rules(
                [item for item in run_if.get("rules", ()) if isinstance(item, Mapping)],
                values,
                logical_operator=str(run_if.get("logical_operator") or "AND"),
            )
        return matched is bool(run_if.get("expected", True))

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
