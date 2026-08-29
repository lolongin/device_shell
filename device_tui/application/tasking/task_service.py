"""Public task lifecycle boundary.

The compatibility ``TaskManager`` still contains the old and new execution
paths.  ``TaskService`` is deliberately small: callers depend on this API,
while the manager can later be replaced by ``TaskOrchestrator`` plus a
projection without changing desktop/MCP adapters.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from typing import Any, Callable, Iterable, Mapping, Protocol, runtime_checkable

from device_tui.application.workflows import TaskPlan, TaskRun, WorkflowNode

from .models import DecisionContext, TaskCreate, TaskRecord
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


class TaskService:
    """Stable application API for user-facing task lifecycle operations."""

    def __init__(
        self,
        backend: TaskLifecycle,
        orchestrator: TaskPlanLifecycle | None = None,
        projector: TaskRunProjector | None = None,
        operation_status: Callable[[str], str] | None = None,
    ) -> None:
        self._backend = backend
        self._orchestrator = orchestrator
        self._projector = projector or TaskRunProjector()
        self._operation_status = operation_status
        self._plan_jobs: set[Any] = set()
        self._runner_loop: asyncio.AbstractEventLoop | None = None

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

    def create(self, request: TaskCreate) -> TaskRecord:
        return self._backend.create(request)

    def get(self, task_id: str) -> TaskRecord:
        return self._backend.get(task_id)

    def list(self, *, limit: int = 200) -> list[TaskRecord]:
        return self._backend.list(limit=limit)

    def get_decision(self, task_id: str) -> DecisionContext | None:
        return self._backend.get_decision(task_id)

    def apply_decision(self, task_id: str, decision: Any) -> TaskRecord:
        return self._backend.apply_decision(task_id, decision)

    def resume(
        self,
        task_id: str,
        *,
        context: dict[str, Any] | None = None,
        step_id: str = "",
    ) -> TaskRecord:
        return self._backend.resume(task_id, context=context, step_id=step_id)

    def pause(self, task_id: str) -> TaskRecord:
        return self._backend.pause(task_id)

    def cancel(self, task_id: str) -> TaskRecord:
        return self._backend.cancel(task_id)

    def delete_task(self, task_id: str) -> None:
        self._backend.delete_task(task_id)

    def delete_tasks(self, task_ids: Iterable[str]) -> tuple[str, ...]:
        return self._backend.delete_tasks(task_ids)

    async def close(self) -> None:
        await self._backend.close()


__all__ = ["TaskLifecycle", "TaskPlanLifecycle", "TaskService"]
