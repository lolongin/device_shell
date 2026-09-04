"""Public task lifecycle boundary.

New tasks enter through ``TaskService`` and execute via
``TaskOrchestrator``/``WorkflowRuntime``.  The injected legacy backend is
kept behind this boundary for historical ``TaskRecord`` data and old task
requests that have no Framework plan.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from dataclasses import replace
from typing import Any, Callable, Iterable, Mapping, Protocol, runtime_checkable
from uuid import uuid4

from device_tui.framework import (
    DecisionSubmission as FrameworkDecisionSubmission,
    RunStatus,
    TaskPlan,
    TaskRun,
    WorkflowNode,
    WorkflowRegistry,
)

from device_tui.application.errors import ApplicationConflictError, ApplicationError
from .models import DecisionContext, TaskCreate, TaskRecord
from .models import Action, Decision, DecisionActor, TaskStatus
from .projection import TaskRunProjector


logger = logging.getLogger(__name__)


class TaskLifecycle(Protocol):
    def create(self, request: TaskCreate) -> TaskRecord: ...
    def get(self, task_id: str) -> TaskRecord: ...
    def list(self, *, limit: int = 200) -> list[TaskRecord]: ...
    def get_decision(self, task_id: str) -> DecisionContext | None: ...
    def apply_decision(self, task_id: str, decision: Any) -> TaskRecord: ...
    def resume(self, task_id: str, *, context: dict[str, Any] | None = None, step_id: str = "") -> TaskRecord: ...
    def pause(self, task_id: str) -> TaskRecord: ...
    def cancel(self, task_id: str) -> TaskRecord: ...
    def delete_task(self, task_id: str) -> None: ...
    def delete_tasks(self, task_ids: Iterable[str]) -> tuple[str, ...]: ...
    async def close(self) -> None: ...


@runtime_checkable
class TaskPlanLifecycle(Protocol):
    """Port required by the generic TaskPlan API.

    Keeping this protocol separate from ``TaskLifecycle`` prevents the legacy
    TaskRecord manager from becoming a required dependency of the framework
    execution path.
    """

    def start(
        self,
        plan: TaskPlan,
        *,
        device_id: str,
        inputs: Mapping[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        task_run_id: str | None = None,
        child_run_id: str | None = None,
    ) -> TaskRun: ...

    async def execute(self, task_run_id: str, plan: TaskPlan) -> TaskRun: ...
    def get(self, task_run_id: str) -> TaskRun: ...
    def list(self, *, limit: int = 500) -> list[TaskRun]: ...
    def pause(self, task_run_id: str) -> TaskRun: ...
    def resume(self, task_run_id: str, *, context: Mapping[str, Any] | None = None) -> TaskRun: ...
    def cancel(self, task_run_id: str) -> TaskRun: ...


class TaskCompatibilityPersistence(Protocol):
    """Optional persistence port for legacy TaskRecord projections."""

    def persist_framework_task(self, task_id: str, request: TaskCreate, record: TaskRecord) -> None: ...
    def forget_framework_task(self, task_id: str) -> None: ...


class TaskService:
    """Stable application API for user-facing task lifecycle operations."""

    def __init__(
        self,
        backend: TaskLifecycle,
        orchestrator: TaskPlanLifecycle | None = None,
        projector: TaskRunProjector | None = None,
        operation_status: Callable[[str], str] | None = None,
        framework_workflows: WorkflowRegistry | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._backend = backend
        self._orchestrator = orchestrator
        self._projector = projector or TaskRunProjector()
        self._operation_status = operation_status
        self._framework_workflows = framework_workflows
        self._event_bus = event_bus
        self._plan_jobs: set[Any] = set()
        self._runner_loop: asyncio.AbstractEventLoop | None = None
        self._framework_requests: dict[str, TaskCreate] = {}
        self._framework_plans: dict[str, TaskPlan] = {}
        self._framework_records: dict[str, TaskRecord] = {}
        self._restore_framework_tasks()

    def _restore_framework_tasks(self) -> None:
        """Adopt persisted Framework TaskRuns without starting legacy jobs."""
        if self._orchestrator is None:
            return
        requests = getattr(self._backend, "_requests", {})
        persisted_plans = getattr(self._backend, "_framework_task_plans", {})
        if not isinstance(requests, Mapping):
            return
        for task_id, request in tuple(requests.items()):
            if not isinstance(request, TaskCreate):
                continue
            try:
                self._orchestrator.get(str(task_id))
            except (KeyError, ValueError):
                continue
            plan = persisted_plans.get(task_id) if isinstance(persisted_plans, Mapping) else None
            if not isinstance(plan, TaskPlan):
                resolved = self._framework_request_plan(request)
                plan = resolved[0] if resolved is not None else None
            if plan is None:
                continue
            self._framework_requests[str(task_id)] = request
            self._framework_plans[str(task_id)] = plan
            try:
                self._project_framework_task(str(task_id))
            except KeyError:
                self._framework_requests.pop(str(task_id), None)
                self._framework_plans.pop(str(task_id), None)

    def bind_runner_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Use the application's durable loop for detached TaskPlan work."""
        self._runner_loop = loop

    async def start_file_transfer(
        self,
        *,
        device_id: str,
        session_id: str,
        direction: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
        protocol: str = "auto",
        terminal_environment: str = "auto",
        command_mode: str = "vrp",
        interaction_profile: Mapping[str, str] | None = None,
        context: Mapping[str, Any] | None = None,
        startup_timeout_seconds: float = 10.0,
    ) -> tuple[TaskRun, str]:
        """Start ``file.transfer`` through the generic TaskPlan boundary.

        The transfer operation is returned once the Activity has dispatched
        it. Progress and history remain available through the Operation API;
        the TaskRun owns scheduling and recovery.
        """
        plan = TaskPlan(
            id="file-transfer:1",
            version="1",
            nodes=(WorkflowNode(
                id="transfer",
                workflow_id="file.transfer",
                input_mapping={
                    "direction": "${direction}",
                    "source_path": "${source_path}",
                    "destination_path": "${destination_path}",
                    "overwrite": "${overwrite}",
                    "terminal_environment": "${terminal_environment}",
                    "command_mode": "${command_mode}",
                    "interaction_profile": "${interaction_profile}",
                },
            ),),
        )
        inputs = {
            "direction": direction,
            "source_path": source_path,
            "destination_path": destination_path,
            "overwrite": overwrite,
            "terminal_environment": terminal_environment,
            "command_mode": command_mode,
            "interaction_profile": dict(interaction_profile or {}),
        }
        # ``ManagedTransferService`` marks its Operation completed before the
        # Activity has persisted its final verification result. Give that
        # narrow hand-off window a chance to release the Task device lease so
        # an immediately-following transfer does not falsely conflict.
        await self._settle_completed_file_transfer_tasks(device_id)
        run = self.start_plan(
            plan,
            device_id=device_id,
            inputs=inputs,
            context={
                **dict(context or {}),
                "source": str((context or {}).get("source") or "transfer"),
                "target": {
                    "device_id": device_id,
                    "session_id": session_id,
                    "protocol": protocol,
                },
            },
        )
        self._schedule_plan_execution(run.id, plan)
        operation_id = await self._wait_for_transfer_operation(run.id, startup_timeout_seconds)
        return self.get_plan(run.id), operation_id

    def _schedule_plan_execution(self, task_run_id: str, plan: TaskPlan) -> None:
        runner_loop = self._runner_loop
        current_loop = asyncio.get_running_loop()
        if runner_loop is not None and runner_loop.is_running() and runner_loop is not current_loop:
            job: Any = asyncio.run_coroutine_threadsafe(
                self.execute_plan(task_run_id, plan),
                runner_loop,
            )
        else:
            job = current_loop.create_task(
                self.execute_plan(task_run_id, plan),
                name=f"file-transfer-task-{task_run_id}",
            )
        self._plan_jobs.add(job)
        job.add_done_callback(lambda completed: self._plan_job_done(task_run_id, completed))

    def _plan_job_done(self, task_run_id: str, job: Any) -> None:
        self._plan_jobs.discard(job)
        try:
            error = job.exception()
        except (asyncio.CancelledError, concurrent.futures.CancelledError):
            return
        if error is not None:
            logger.error("background TaskPlan execution failed: %s: %s", task_run_id, error)

    async def _wait_for_transfer_operation(self, task_run_id: str, timeout_seconds: float) -> str:
        """Read the queued event without waiting for transfer completion."""
        deadline = time.monotonic() + max(0.1, float(timeout_seconds))
        while time.monotonic() < deadline:
            run = self.get_plan(task_run_id)
            child_id = run.node_runs.get("transfer")
            runtime = getattr(self._orchestrator, "runtime", None)
            events = getattr(runtime, "events", None)
            if child_id and events is not None:
                for event in events.list(child_id):
                    if event.type == "transfer.operation.queued":
                        operation_id = str(event.payload.get("operation_id") or "")
                        if operation_id:
                            return operation_id
            await asyncio.sleep(0.01)
        raise TimeoutError("file.transfer was not dispatched before the startup timeout")

    async def _settle_completed_file_transfer_tasks(self, device_id: str) -> None:
        """Allow completed transfer Activities to release their Task lease.

        A managed Operation can become ``completed`` just before the Activity
        monitor observes that revision and writes ``transfer.completed``.  The
        next request must not treat this brief projection lag as a conflicting
        live transfer.  In-progress Operations still return immediately and
        retain the normal resource-conflict behavior.
        """
        if self._operation_status is None:
            return
        for _ in range(50):
            runtime = getattr(self._orchestrator, "runtime", None)
            events = getattr(runtime, "events", None)
            if events is None:
                return
            settling = False
            for run in self.list_plans(limit=500):
                if run.plan_id != "file-transfer:1" or run.device_id != device_id:
                    continue
                if str(run.status) in {"succeeded", "failed", "cancelled"}:
                    continue
                child_id = run.node_runs.get("transfer")
                if not child_id:
                    continue
                operation_id = next((
                    str(event.payload.get("operation_id") or "")
                    for event in events.list(child_id)
                    if event.type == "transfer.operation.queued"
                ), "")
                if operation_id and self._is_completed_operation(operation_id):
                    settling = True
                    break
            if not settling:
                return
            await asyncio.sleep(0.01)

    def _is_completed_operation(self, operation_id: str) -> bool:
        try:
            return self._operation_status(operation_id) == "completed"  # type: ignore[misc]
        except (KeyError, LookupError):
            return False

    def project_run(
        self,
        run: TaskRun,
        *,
        workflow_id: str | None = None,
        session_id: str = "",
        source: str = "framework",
        created_at: str = "",
        updated_at: str = "",
        workflow_view: Mapping[str, Any] | None = None,
    ) -> TaskRecord:
        """Return a legacy DTO for presentation without changing run state."""
        return self._projector.project(
            run,
            workflow_id=workflow_id,
            session_id=session_id,
            source=source,
            created_at=created_at,
            updated_at=updated_at,
            workflow_view=workflow_view,
        )

    def _framework_request_plan(self, request: TaskCreate) -> tuple[TaskPlan, dict[str, Any]] | None:
        """Resolve the canonical Framework plan carried by a task request."""
        metadata = dict(request.workflow.metadata)
        raw_plan = request.framework_plan or metadata.get("framework_task_plan")
        if isinstance(raw_plan, TaskPlan):
            return raw_plan, dict(metadata.get("framework_inputs") or {})
        if isinstance(raw_plan, Mapping):
            plan = TaskPlan.from_dict(raw_plan)
            plan.validate()
            return plan, dict(metadata.get("framework_inputs") or {})
        canonical_id = str(metadata.get("canonical_workflow_id") or "").strip()
        raw_inputs = metadata.get("framework_inputs")
        if not canonical_id or not isinstance(raw_inputs, dict) or self._framework_workflows is None:
            # Catalog providers predating the Framework metadata contract may
            # still return a plain WorkflowDefinition.  Convert only the
            # small, stable set of generic actions exposed by the Framework;
            # unknown legacy actions must remain rejected by production.
            if self._framework_workflows is None:
                return None
            plan = self._legacy_workflow_task_plan(request.workflow)
            if plan is None:
                return None
            return plan, {}
        definition = self._framework_workflows.build(canonical_id, dict(raw_inputs))
        return TaskPlan(
            id=f"workflow-task:{definition.id}:{definition.version}",
            version=definition.version,
            nodes=(WorkflowNode(
                id="workflow",
                workflow_id=definition.id,
                input_mapping={key: f"${{{key}}}" for key in raw_inputs},
            ),),
        ), dict(raw_inputs)

    def _legacy_workflow_task_plan(self, workflow: Any) -> TaskPlan | None:
        """Translate a restricted legacy workflow into Framework nodes.

        This is deliberately an allow-list, rather than a generic adapter to
        the old engine.  It lets existing catalog providers migrate gradually
        while ensuring production execution still enters ActivityExecutor.
        """
        action_to_workflow = {
            "command": "terminal.command",
            "batch": "terminal.batch",
            "reboot": "device.reboot",
            "wait_online": "device.wait_online",
            "verify_version": "device.verify_version",
        }
        nodes: list[WorkflowNode] = []
        seen_ids: set[str] = set()
        for step in tuple(getattr(workflow, "steps", ()) or ()):
            step_id = str(getattr(step, "id", "") or "").strip()
            if not step_id or step_id in seen_ids:
                return None
            seen_ids.add(step_id)
            raw_action = getattr(step, "action", "")
            action_name = str(getattr(raw_action, "name", raw_action) or "").strip().casefold()
            framework_id = action_to_workflow.get(action_name)
            if framework_id is None:
                return None
            params = dict(getattr(step, "params", {}) or {})
            action_params = getattr(raw_action, "parameters", None)
            if isinstance(action_params, Mapping):
                params = {**dict(action_params), **params}
            if framework_id == "terminal.command":
                command = params.get("command")
                if not isinstance(command, str) or not command.strip():
                    return None
                params["command"] = command
            elif framework_id == "terminal.batch":
                commands = params.get("commands")
                if not isinstance(commands, (list, tuple)) or not commands:
                    return None
                params["commands"] = list(commands)
            nodes.append(WorkflowNode(
                id=step_id,
                workflow_id=framework_id,
                depends_on=tuple(str(item) for item in getattr(step, "depends_on", ()) if str(item)),
                input_mapping=params,
            ))
        if not nodes:
            return None
        plan = TaskPlan(
            id=f"legacy-workflow:{str(getattr(workflow, 'id', '') or 'workflow')}",
            version=str(getattr(workflow, "version", "1") or "1"),
            nodes=tuple(nodes),
        )
        try:
            plan.validate()
        except (TypeError, ValueError):
            return None
        return plan

    def _project_framework_task(self, task_id: str) -> TaskRecord:
        request = self._framework_requests[task_id]
        run = self._orchestrator.get(task_id)  # type: ignore[union-attr]
        metadata = dict(request.workflow.metadata)
        workflow_view = self._framework_workflow_view(
            metadata,
            workflow=request.workflow,
            plan=self._framework_plans.get(task_id),
        )
        record = self.project_run(
            run,
            workflow_id=request.workflow.id,
            session_id=request.target.session_id,
            source=request.source,
            workflow_view=workflow_view,
        )
        # Preserve agent-plan identity fields on the compatibility DTO. They
        # are read-only projections; execution remains owned by TaskRun.
        record = replace(
            record,
            plan_id=str(metadata.get("plan_id") or ""),
            plan_hash=str(metadata.get("plan_hash") or ""),
            parent_task_id=str(metadata.get("parent_task_id") or ""),
            plan_revision=max(0, int(metadata.get("revision") or run.context.get("plan_revision") or request.workflow.version or 0)),
        )
        previous = self._framework_records.get(task_id)
        self._framework_records[task_id] = record
        persist = getattr(self._backend, "persist_framework_task", None)
        if callable(persist):
            persist(task_id, request, record)
        if self._event_bus is not None and previous != record:
            event_type = "task.created" if previous is None else "task.updated"
            self._event_bus.publish(
                event_type,
                resource_id=record.id,
                data={
                    "task_id": record.id,
                    "status": record.status,
                    "workflow_id": record.workflow_id,
                    "device_id": record.device_id,
                    "progress_percent": record.progress_percent,
                    "current_step_id": record.current_step_id,
                    "error_code": record.error_code,
                    "message": record.message,
                    "plan_id": record.plan_id,
                    "parent_task_id": record.parent_task_id,
                    "plan_revision": record.plan_revision,
                },
            )
        return record

    def _framework_workflow_view(
        self,
        metadata: Mapping[str, Any],
        *,
        workflow: Any | None = None,
        plan: TaskPlan | None = None,
    ) -> dict[str, Any]:
        canonical_id = str(metadata.get("canonical_workflow_id") or "").strip()
        raw_inputs = metadata.get("framework_inputs")
        if canonical_id and isinstance(raw_inputs, dict) and self._framework_workflows is not None:
            try:
                definition = self._framework_workflows.build(canonical_id, dict(raw_inputs))
            except (KeyError, ValueError):
                definition = None
            if definition is not None:
                return {
                    "id": definition.id,
                    "version": definition.version,
                    "states": [
                        {
                            "id": state.id,
                            "label": state.label or state.id,
                            "description": state.description,
                            "terminal": state.terminal,
                            "action_id": state.action.id if state.action is not None else "",
                            "operation": state.action.operation if state.action is not None else "",
                            "expectations": [
                                {
                                    "event_type": expectation.event_type,
                                    "timeout_seconds": expectation.timeout_seconds,
                                    "idle_timeout_seconds": expectation.idle_timeout_seconds,
                                    "progress": expectation.progress,
                                }
                                for expectation in (state.action.expectations if state.action is not None else ())
                            ],
                        }
                        for state in definition.states
                    ],
                }

        # Generic TaskPlans carry a compiled WorkflowDefinition with ordinary
        # steps rather than a canonical Framework workflow. Expose only safe
        # labels and dependency-derived terminal flags to the renderer.
        steps = tuple(getattr(workflow, "steps", ()) or ())
        if not steps and plan is not None:
            return {
                "id": plan.id,
                "version": plan.version,
                "states": [
                    {"id": node.id, "label": node.workflow_id, "terminal": True, "action_id": node.workflow_id, "operation": node.workflow_id}
                    for node in plan.nodes
                ],
            }
        if not steps:
            return {}
        depended_on = {dependency for step in steps for dependency in getattr(step, "depends_on", ())}
        states: list[dict[str, Any]] = []
        for step in steps:
            action = getattr(step, "action", "")
            action_name = str(getattr(action, "name", action) or "").strip()
            states.append({
                "id": str(getattr(step, "id", "") or ""),
                "label": action_name or str(getattr(step, "id", "") or "step"),
                "terminal": str(getattr(step, "id", "")) not in depended_on,
                "action_id": action_name,
                "operation": action_name,
            })
        return {
            "id": str(getattr(workflow, "id", "") or (plan.id if plan is not None else "workflow")),
            "version": str(getattr(workflow, "version", "") or (plan.version if plan is not None else "1")),
            "states": states,
        }

    def _framework_child_run(self, task_id: str) -> Any | None:
        """Return the active WorkflowRun behind a composed TaskRun."""
        if self._orchestrator is None:
            return None
        runtime = getattr(self._orchestrator, "runtime", None)
        if runtime is None:
            return None
        try:
            task = self._orchestrator.get(task_id)
        except KeyError:
            return None
        runs = getattr(runtime, "runs", None)
        if runs is None:
            return None
        terminal = {
            RunStatus.SUCCEEDED.value,
            RunStatus.FAILED.value,
            RunStatus.CANCELLED.value,
        }
        for child_id in reversed(tuple(task.node_runs)):
            try:
                child = runs.get(task.node_runs[child_id])
            except KeyError:
                continue
            if str(child.status) not in terminal:
                return child
        return None

    @staticmethod
    def _decision_action(decision: Any) -> tuple[Action, DecisionActor, str, int | None, str]:
        """Normalize legacy decision inputs for the Framework boundary."""
        if isinstance(decision, Decision):
            return (
                decision.action,
                decision.actor,
                decision.reason,
                decision.expected_revision,
                decision.decision_id,
            )
        if isinstance(decision, Action):
            return decision, DecisionActor(type="user"), "", decision.expected_revision, ""
        if isinstance(decision, str):
            return Action(decision), DecisionActor(type="user"), "", None, ""
        raise ValueError("Decision action is required")

    def _schedule_framework_task(self, task_id: str, plan: TaskPlan) -> None:
        """Continue a Framework task after resume or decision application."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        try:
            job = asyncio.create_task(
                self._execute_framework_task(task_id, plan),
                name=f"framework-task-{task_id}",
            )
        except RuntimeError:
            return
        self._plan_jobs.add(job)
        job.add_done_callback(self._plan_jobs.discard)

    async def _execute_framework_task(self, task_id: str, plan: TaskPlan) -> None:
        try:
            await self.execute_plan(task_id, plan)
            self._project_framework_task(task_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # The Framework owns the durable run state.  Keep a projected
            # failure visible to compatibility clients when execution setup
            # itself fails before a child Workflow can be persisted.
            record = self._framework_records.get(task_id)
            if record is not None:
                self._framework_records[task_id] = replace(
                    record,
                    status="failed",
                    error_code="task_orchestration_failed",
                    message=str(exc),
                )

    def create(self, request: TaskCreate) -> TaskRecord:
        """Create a task through the Framework whenever a plan is available."""
        resolved = self._framework_request_plan(request)
        if resolved is None:
            # New requests must be represented by a Framework TaskPlan.  The
            # compatibility backend is history-only and must never become an
            # implicit execution fallback.
            raise ApplicationError(
                "Legacy task execution is disabled; submit a Framework TaskPlan."
            )
        if self._orchestrator is None:
            raise RuntimeError("generic TaskPlan orchestration is not configured")
        plan, inputs = resolved
        task_id = str(uuid4())
        device_id = str(request.target.device_id or "").strip()
        if not device_id:
            raise ValueError("device_id is required")
        self._framework_requests[task_id] = request
        self._framework_plans[task_id] = plan
        try:
            run = self.start_plan(
                plan,
                device_id=device_id,
                inputs=inputs,
                context={
                    **dict(request.context),
                    "source": request.source,
                    "target": {
                        "device_id": device_id,
                        "session_id": request.target.session_id,
                        "protocol": request.target.protocol,
                    },
                },
                task_run_id=task_id,
                child_run_id=task_id if len(plan.nodes) == 1 else None,
            )
        except Exception:
            self._framework_requests.pop(task_id, None)
            self._framework_plans.pop(task_id, None)
            raise
        record = self._project_framework_task(task_id)
        # Synchronous callers can explicitly invoke execute_plan; async API
        # callers get detached execution on the current application loop.
        self._schedule_framework_task(task_id, plan)
        return record

    def start_plan(
        self,
        plan: TaskPlan,
        *,
        device_id: str,
        inputs: dict[str, Any] | None = None,
        context: Mapping[str, Any] | None = None,
        task_run_id: str | None = None,
        child_run_id: str | None = None,
    ) -> TaskRun:
        if self._orchestrator is None:
            raise RuntimeError("generic TaskPlan orchestration is not configured")
        kwargs: dict[str, Any] = {
            "device_id": device_id,
            "inputs": inputs,
            "context": context,
            "task_run_id": task_run_id,
        }
        if child_run_id is not None:
            kwargs["child_run_id"] = child_run_id
        return self._orchestrator.start(
            plan,
            **kwargs,
        )

    async def execute_plan(self, task_run_id: str, plan: TaskPlan) -> TaskRun:
        if self._orchestrator is None:
            raise RuntimeError("generic TaskPlan orchestration is not configured")
        return await self._orchestrator.execute(task_run_id, plan)

    def get_plan(self, task_run_id: str) -> TaskRun:
        if self._orchestrator is None:
            raise RuntimeError("generic TaskPlan orchestration is not configured")
        return self._orchestrator.get(task_run_id)

    def list_plans(self, *, limit: int = 200) -> list[TaskRun]:
        if self._orchestrator is None:
            raise RuntimeError("generic TaskPlan orchestration is not configured")
        return self._orchestrator.list(limit=limit)

    def pause_plan(self, task_run_id: str) -> TaskRun:
        if self._orchestrator is None:
            raise RuntimeError("generic TaskPlan orchestration is not configured")
        return self._orchestrator.pause(task_run_id)

    def resume_plan(self, task_run_id: str, *, context: dict[str, Any] | None = None) -> TaskRun:
        if self._orchestrator is None:
            raise RuntimeError("generic TaskPlan orchestration is not configured")
        return self._orchestrator.resume(task_run_id, context=context)

    def cancel_plan(self, task_run_id: str) -> TaskRun:
        if self._orchestrator is None:
            raise RuntimeError("generic TaskPlan orchestration is not configured")
        return self._orchestrator.cancel(task_run_id)

    def get(self, task_id: str) -> TaskRecord:
        if task_id in self._framework_requests:
            return self._project_framework_task(task_id)
        return self._backend.get(task_id)

    def list(self, *, limit: int = 200) -> list[TaskRecord]:
        # Framework projections are persisted through the compatibility store
        # for restart recovery, but must appear only once in this facade.
        records = [
            item for item in self._backend.list(limit=limit)
            if item.id not in self._framework_requests
        ]
        for task_id in tuple(self._framework_requests):
            try:
                records.append(self._project_framework_task(task_id))
            except KeyError:
                continue
        return sorted(records, key=lambda item: (item.updated_at or item.created_at, item.id), reverse=True)[:max(0, limit)]

    def get_decision(self, task_id: str) -> DecisionContext | None:
        if task_id in self._framework_requests:
            child = self._framework_child_run(task_id)
            if child is None or child.decision_point is None:
                return None
            request = self._framework_requests[task_id]
            point = child.decision_point
            actions = tuple(
                Action(
                    item.id,
                    target_step=child.current_state,
                    risk=item.risk,
                    metadata={
                        "kind": item.kind,
                        "label": item.label,
                        "description": item.description,
                        "requires_reason": item.requires_reason,
                        "input_schema": dict(item.input_schema),
                    },
                )
                for item in point.options
            )
            return DecisionContext(
                task_id=task_id,
                workflow_id=request.workflow.id,
                current_step=child.current_state,
                error=child.error,
                context=dict(child.context),
                available_actions=actions,
                workflow_instance_id=f"framework-{task_id}",
                checkpoint_revision=child.revision,
            )
        return self._backend.get_decision(task_id)

    def apply_decision(self, task_id: str, decision: Any) -> TaskRecord:
        if task_id in self._framework_requests:
            child = self._framework_child_run(task_id)
            if child is None or child.decision_point is None:
                raise ValueError("Workflow is not waiting for a decision")
            action, actor, reason, expected_revision, decision_id = self._decision_action(decision)
            action_name = action.name.casefold()
            option = next(
                (
                    item for item in child.decision_point.options
                    if item.id.casefold() == action_name
                    or item.kind.casefold() == action_name
                    or (action_name == "cancel" and item.kind.casefold() == "abort")
                ),
                None,
            )
            if option is None:
                raise ValueError(f"Workflow decision action is not available: {action.name}")
            submission = FrameworkDecisionSubmission(
                decision_point_id=child.decision_point.id,
                expected_revision=expected_revision if expected_revision is not None else child.revision,
                option_id=option.id,
                actor_type="human" if actor.type == "user" else "agent",
                actor_id=actor.id,
                inputs=dict(action.parameters),
                reason=reason,
                idempotency_key=decision_id,
            )
            updated = self._orchestrator.apply_decision(task_id, submission)  # type: ignore[union-attr]
            if str(updated.status) == "running":
                if not any(
                    getattr(job, "get_name", lambda: "")() == f"framework-task-{task_id}"
                    for job in self._plan_jobs
                ):
                    self._schedule_framework_task(task_id, self._framework_plans[task_id])
            return self._project_framework_task(task_id)
        return self._backend.apply_decision(task_id, decision)

    def resume(
        self,
        task_id: str,
        *,
        context: dict[str, Any] | None = None,
        step_id: str = "",
    ) -> TaskRecord:
        if task_id in self._framework_requests:
            run = self.resume_plan(task_id, context=context)
            plan = self._framework_plans[task_id]
            if str(run.status) == "running" and not any(
                getattr(job, "get_name", lambda: "")() == f"framework-task-{task_id}"
                for job in self._plan_jobs
            ):
                self._schedule_framework_task(task_id, plan)
            return self._project_framework_task(task_id)
        return self._backend.resume(task_id, context=context, step_id=step_id)

    def pause(self, task_id: str) -> TaskRecord:
        if task_id in self._framework_requests:
            self.pause_plan(task_id)
            for job in tuple(self._plan_jobs):
                if getattr(job, "get_name", lambda: "")() == f"framework-task-{task_id}":
                    job.cancel()
            return self._project_framework_task(task_id)
        return self._backend.pause(task_id)

    def cancel(self, task_id: str) -> TaskRecord:
        if task_id in self._framework_requests:
            self.cancel_plan(task_id)
            return self._project_framework_task(task_id)
        return self._backend.cancel(task_id)

    def cancel_session(self, session_id: str) -> int:
        """Cancel tasks attached to a session before it is disconnected.

        Session lifecycle code should depend on this service rather than the
        compatibility task implementation.  The backend method remains
        private to the composition root while the public behavior is stable.
        """
        cancelled = 0
        for task_id, request in tuple(self._framework_requests.items()):
            if request.target.session_id != session_id:
                continue
            try:
                before = self.get_plan(task_id)
            except KeyError:
                continue
            if str(before.status) in {"succeeded", "failed", "cancelled"}:
                continue
            self.cancel(task_id)
            cancelled += 1
        cancel_session = getattr(self._backend, "cancel_session", None)
        if callable(cancel_session):
            cancelled += int(cancel_session(session_id))
        return cancelled

    def delete_task(self, task_id: str) -> None:
        if task_id in self._framework_requests:
            record = self.get(task_id)
            if str(record.status) not in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:
                raise ApplicationConflictError(
                    "只能删除已结束的任务记录。",
                    details={"task_id": task_id, "status": str(record.status)},
                )
            delete = getattr(self._orchestrator, "delete", None)
            if callable(delete):
                delete(task_id)
            forget = getattr(self._backend, "forget_framework_task", None)
            if callable(forget):
                forget(task_id)
            self._framework_requests.pop(task_id, None)
            self._framework_plans.pop(task_id, None)
            self._framework_records.pop(task_id, None)
            return
        self._backend.delete_task(task_id)

    def delete_tasks(self, task_ids: Iterable[str]) -> tuple[str, ...]:
        normalized = tuple(dict.fromkeys(str(task_id).strip() for task_id in task_ids if str(task_id).strip()))
        framework_ids = tuple(task_id for task_id in normalized if task_id in self._framework_requests)
        legacy_ids = tuple(task_id for task_id in normalized if task_id not in self._framework_requests)
        # Preserve the legacy backend's all-or-nothing validation when this
        # is a purely historical batch. Mixed batches validate both stores
        # before mutating either one.
        if not framework_ids:
            return self._backend.delete_tasks(normalized)
        terminal = {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }
        for task_id in framework_ids:
            record = self.get(task_id)
            if str(record.status) not in terminal:
                raise ApplicationConflictError(
                    "只能删除已结束的任务记录。",
                    details={"task_id": task_id, "status": str(record.status)},
                )
        for task_id in legacy_ids:
            record = self._backend.get(task_id)
            if str(record.status) not in terminal:
                raise ApplicationConflictError(
                    "只能删除已结束的任务记录。",
                    details={"task_id": task_id, "status": str(record.status)},
                )
        if legacy_ids:
            self._backend.delete_tasks(legacy_ids)
        for task_id in framework_ids:
            self.delete_task(task_id)
        return normalized

    async def close(self) -> None:
        for task_id in tuple(self._framework_requests):
            try:
                run = self.get_plan(task_id)
            except KeyError:
                continue
            if str(run.status) not in {"succeeded", "failed", "cancelled"}:
                try:
                    self.cancel_plan(task_id)
                except (KeyError, ValueError):
                    pass
        jobs = tuple(self._plan_jobs)
        for job in jobs:
            job.cancel()
        awaitables = []
        for job in jobs:
            if isinstance(job, concurrent.futures.Future):
                awaitables.append(asyncio.wrap_future(job))
            else:
                awaitables.append(job)
        if awaitables:
            await asyncio.gather(*awaitables, return_exceptions=True)
        self._plan_jobs.clear()
        await self._backend.close()

    def __getattr__(self, name: str) -> Any:
        """Expose read-only compatibility state during the API cutover.

        A small number of older integrations inspect ``_records`` and
        ``_requests`` directly when importing or deleting task history.  Keep
        those lookups working without making ``TaskManager`` the application
        dependency again.  New code must use the lifecycle methods above.
        """
        if name in {"_records", "_requests"}:
            return getattr(self._backend, name)
        raise AttributeError(name)


__all__ = ["TaskCompatibilityPersistence", "TaskLifecycle", "TaskPlanLifecycle", "TaskService"]
