"""Task manager and workflow engine for human and agent operations."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from device_tui.application.device_control import ControlContext, DeviceLeaseService, DeviceTarget
from device_tui.application.errors import ApplicationError, ResourceNotFoundError
from device_tui.application.events import EventBus
from device_tui.application.workflows.decisions import DecisionSubmission as FrameworkDecisionSubmission
from device_tui.application.workflows.models import (
    ActionStatus as FrameworkActionStatus,
    RunStatus as FrameworkRunStatus,
    WorkflowDefinition as FrameworkWorkflowDefinition,
    WorkflowRun as FrameworkWorkflowRun,
)
from device_tui.application.workflows.plugins import WorkflowRegistry
from device_tui.application.workflows.runtime import WorkflowRuntime

from .decision import DecisionEngine, RuleDecisionEngine
from .execution import DeviceExecutionTool, ExecutionTool
from .models import (
    Action,
    Checkpoint,
    Decision,
    DecisionActor,
    DecisionContext,
    DecisionRequest,
    StepStatus,
    Task,
    TaskStatus,
    TaskCreate,
    TaskRecord,
    ToolError,
    ToolResult,
    ToolStatus,
    WorkflowDefinition,
    WorkflowCheckpoint,
    WorkflowInstance,
    WorkflowResult,
    WorkflowStep,
    WorkflowStepResult,
    WorkflowStepState,
)
from .store import TaskStore


class WorkflowEngine:
    """A resumable workflow state machine.

    The older :meth:`run` entry point remains for compatibility with the
    background ``TaskManager``.  The lifecycle methods below operate on one
    persisted :class:`Task` at a time and never infer a restart from step one.
    """

    def __init__(
        self,
        workflow: WorkflowDefinition | None = None,
        execution: ExecutionTool | Any | None = None,
        *,
        decision: DecisionEngine | None = None,
        target: DeviceTarget | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        self._workflow = workflow
        self._execution = execution
        self._decision = decision
        self._target = target or DeviceTarget()
        self._context = dict(context or {})
        self._task: Task | None = None
        self._states: dict[str, WorkflowStepState] = {}
        self._outputs: dict[str, Any] = {}
        self._attempts: dict[str, int] = {}
        self._decisions: list[Decision] = []
        self._pending_context: DecisionContext | None = None
        self._pending_decision_id = ""
        self._approved_steps: set[str] = set()
        self._revision = 0

    @property
    def task(self) -> Task:
        if self._task is None:
            raise RuntimeError("Workflow has not been started")
        return self._task

    @property
    def pending_decision(self) -> DecisionContext | None:
        return self._pending_context

    def start(
        self,
        task: Task | TaskCreate,
        workflow: WorkflowDefinition | None = None,
        *,
        execution: ExecutionTool | Any | None = None,
        target: DeviceTarget | None = None,
        context: dict[str, Any] | None = None,
    ) -> Task:
        """Attach the engine to a task and restore its checkpoint.

        ``TaskCreate`` is accepted as a convenience for callers that have not
        persisted a Task yet.  A running task restored after a crash becomes
        running again, while all completed step states and outputs are kept.
        """
        if isinstance(task, TaskCreate):
            request = task
            now = self._now()
            task = Task(
                id=str(uuid4()),
                workflow_instance_id=str(uuid4()),
                device_id=task.target.device_id,
                source=task.source,
                created_at=now,
                updated_at=now,
                context=dict(request.context),
            )
            workflow = workflow or request.workflow
            self._target = request.target
            self._context = {**request.context, **dict(context or {})}
        self._task = task
        self._workflow = workflow or self._workflow or self._workflow_from_task(task)
        if self._workflow is None:
            raise ValueError("A WorkflowDefinition is required to start a task")
        if execution is not None:
            self._execution = execution
        if target is not None:
            self._target = target
        elif task.device_id:
            self._target = DeviceTarget(device_id=task.device_id)
        self._context = {**dict(task.context), **self._context, **dict(context or {})}
        self._validate_workflow(self._workflow)
        instance = task.workflow if isinstance(task.workflow, WorkflowInstance) else None
        checkpoint = task.checkpoint or (instance.checkpoint if instance else None)
        self._revision = checkpoint.revision if checkpoint else 0
        self._outputs = dict(checkpoint.outputs if checkpoint else (instance.outputs if instance else {}))
        self._restore_recovery_target()
        self._attempts = dict(checkpoint.attempts if checkpoint else {})
        self._decisions = list(checkpoint.decisions if checkpoint else getattr(task, "decisions", ()))
        self._pending_decision_id = checkpoint.pending_decision_id if checkpoint else ""
        approval_context = checkpoint.context if checkpoint is not None else task.context
        raw_approved = approval_context.get("approved_steps", ()) if isinstance(approval_context, dict) else ()
        self._approved_steps = {str(item) for item in raw_approved} if isinstance(raw_approved, (list, tuple, set)) else set()
        self._states = {step.id: WorkflowStepState(step.id) for step in self._workflow.steps}
        if checkpoint:
            self._states.update({state.step_id: state for state in checkpoint.step_states})
            for step_id in checkpoint.completed_steps:
                state = self._states.get(step_id)
                if state is not None and state.status not in {StepStatus.COMPLETED, StepStatus.SUCCESS}:
                    self._states[step_id] = replace(state, status=StepStatus.COMPLETED)
        completed = self._completed_ids()
        current = (checkpoint.current_step if checkpoint else (instance.current_step if instance else ""))
        if not current or current in completed:
            current = self._next_ready(current)
        status = str(task.status)
        if status not in {
            TaskStatus.CANCELLED.value, TaskStatus.COMPLETED.value,
            TaskStatus.WAITING_FOR_DECISION.value, TaskStatus.PAUSED.value,
            TaskStatus.WAITING_FOR_USER.value,
        }:
            status = TaskStatus.RUNNING.value
        if status in {TaskStatus.WAITING_FOR_DECISION.value, TaskStatus.WAITING_FOR_USER.value}:
            failed_id = checkpoint.failed_step_id if checkpoint else current
            failed_state = self._states.get(failed_id)
            actions = self._decision_actions(failed_id, user_confirmation=status == TaskStatus.WAITING_FOR_USER.value)
            self._pending_context = DecisionContext(
                task_id=task.id, workflow_id=self._workflow.id, current_step=failed_id,
                error=failed_state.error if failed_state else None,
                result=failed_state.result if failed_state else None,
                context={**self._checkpoint_context(), "outputs": dict(self._outputs)},
                available_actions=actions,
                workflow_instance_id=task.workflow_instance_id, checkpoint_revision=self._revision + 1,
            )
        else:
            self._pending_context = None
        return self._save(status=status, current_step=current)

    async def execute_step(self) -> Task:
        """Execute exactly the current step (including deterministic retries)."""
        task = self.task
        if task.status in {TaskStatus.PAUSED.value, TaskStatus.CANCELLED.value, TaskStatus.COMPLETED.value}:
            return task
        if task.status in {TaskStatus.WAITING_FOR_DECISION.value, TaskStatus.WAITING_FOR_USER.value}:
            return task
        workflow = self._require_workflow()
        step_id = self._current_step()
        if not step_id:
            return self._save(status=TaskStatus.COMPLETED.value, current_step="")
        step = next(item for item in workflow.steps if item.id == step_id)
        if step.kind.casefold() == "decision":
            self.create_decision(current_step=step.id)
            return self.task
        if step.action and isinstance(step.action, Action) and step.action.confirmation_required and step.id not in self._approved_steps:
            self.create_decision(current_step=step.id, waiting_status=TaskStatus.WAITING_FOR_USER.value)
            return self.task
        state = self._states[step.id]
        max_attempts = max(1, int(step.retry_policy.get("max_attempts", 1) or 1))
        while True:
            attempt = self._attempts.get(step.id, state.attempt) + 1
            self._attempts[step.id] = attempt
            self._states[step.id] = replace(state, status=StepStatus.RUNNING, attempt=attempt)
            self._save(status=TaskStatus.RUNNING.value, current_step=step.id)
            try:
                data = await self._invoke(step)
                result = data if isinstance(data, ToolResult) else ToolResult(
                    tool=str(step.action or step.kind), status=ToolStatus.SUCCEEDED,
                    facts=dict(data) if isinstance(data, dict) else {"value": data},
                    output=str(data.get("output") or "") if isinstance(data, dict) else str(data), attempt=attempt,
                    operation_id=str(data.get("operation_id") or "") if isinstance(data, dict) else "",
                    execution_id=str(data.get("execution_id") or "") if isinstance(data, dict) else "",
                    evidence=tuple(dict(item) for item in data.get("evidence", ()) if isinstance(item, dict)) if isinstance(data, dict) else (),
                )
                if not result.evidence:
                    result = replace(
                        result,
                        evidence=(
                            {
                                "kind": "workflow_step",
                                "step_id": step.id,
                                "status": str(result.status),
                                "facts": dict(result.facts),
                            },
                        ),
                    )
                self._outputs[step.id] = result.facts or {"output": result.output}
                self._remember_recovery_target(step, result.facts)
                self._states[step.id] = replace(self._states[step.id], status=StepStatus.COMPLETED, result=result, error=None)
                next_step = self._next_ready(step.id)
                status = TaskStatus.COMPLETED.value if not next_step else TaskStatus.RUNNING.value
                return self._save(status=status, current_step=next_step)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error = self._error_from_exception(exc)
                failed_result = ToolResult(
                    tool=str(step.action or step.kind),
                    status=ToolStatus.FAILED,
                    error=error,
                    attempt=attempt,
                    evidence=(
                        {
                            "kind": "workflow_step",
                            "step_id": step.id,
                            "status": "failed",
                            "error_code": error.code,
                        },
                    ),
                )
                self._states[step.id] = replace(self._states[step.id], status=StepStatus.FAILED, result=failed_result, error=error)
                requires_judgment = bool(getattr(exc, "requires_decision", False)) or error.error_class.casefold() in {"human", "agent", "ambiguous"}
                # Human-reviewable device responses (for example, an
                # unrecognised command) must reach a Decision Point even when
                # the step normally has a terminal policy.
                terminal = not requires_judgment and (
                    bool(step.retry_policy.get("terminal", False))
                    or error.error_class.casefold() in {"terminal", "fatal"}
                    or error.code == "unsupported_operation"
                )
                if terminal:
                    return self._save(status=TaskStatus.FAILED.value, current_step=step.id)
                # An explicit max_attempts policy is the declaration that this
                # failure mode is deterministic.  Exceptions can opt out via
                # requires_decision/error_class when the operator must judge it.
                deterministic = not requires_judgment and (
                    error.error_class.casefold() == "deterministic"
                    or bool(step.retry_policy.get("deterministic", False))
                    or "max_attempts" in step.retry_policy
                )
                retryable = error.retryable or bool(step.retry_policy.get("retryable", False)) or deterministic
                if deterministic and retryable and attempt < max_attempts:
                    state = self._states[step.id]
                    continue
                self.create_decision(current_step=step.id, error=error, result=failed_result)
                return self.task

    def pause(self) -> Task:
        if self.task.status in {TaskStatus.RUNNING.value, TaskStatus.RESUMED.value}:
            return self._save(status=TaskStatus.PAUSED.value, current_step=self._current_step())
        return self.task

    def resume(self) -> Task:
        if self.task.status not in {TaskStatus.PAUSED.value, TaskStatus.WAITING_FOR_USER.value, TaskStatus.RESUMED.value}:
            return self.task
        return self._save(status=TaskStatus.RUNNING.value, current_step=self._current_step())

    def cancel(self) -> Task:
        if self.task.status not in {TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value}:
            self._pending_context = None
            self._pending_decision_id = ""
            return self._save(status=TaskStatus.CANCELLED.value, current_step=self._current_step())
        return self.task

    def retry_step(self, step_id: str | None = None) -> Task:
        step_id = step_id or self._current_step()
        if step_id not in self._states:
            raise ValueError(f"Unknown workflow step: {step_id}")
        state = self._states[step_id]
        self._states[step_id] = replace(state, status=StepStatus.PENDING, result=None, error=None)
        self._attempts[step_id] = 0
        self._pending_context = None
        self._pending_decision_id = ""
        return self._save(status=TaskStatus.RUNNING.value, current_step=step_id)

    def resume_from(self, step_id: str) -> Task:
        workflow = self._require_workflow()
        if step_id not in self._states:
            raise ValueError(f"Unknown workflow step: {step_id}")
        reset = {step_id}
        changed = True
        while changed:
            changed = False
            for step in workflow.steps:
                if step.id not in reset and set(step.depends_on) & reset:
                    reset.add(step.id)
                    changed = True
        for item in reset:
            self._states[item] = replace(self._states[item], status=StepStatus.PENDING, result=None, error=None)
            self._attempts[item] = 0
            self._outputs.pop(item, None)
        self._pending_context = None
        self._pending_decision_id = ""
        return self._save(status=TaskStatus.RUNNING.value, current_step=step_id)

    def accept_failed_step(self, step_id: str | None = None) -> Task:
        """Record human acceptance of an ambiguous failed device step.

        This is intentionally different from retrying: the failed command is
        not sent again. The checkpoint records that an operator accepted the
        observed error and advances to the next dependency-ready step.
        """
        step_id = step_id or self._current_step()
        state = self._states.get(step_id)
        if state is None:
            raise ValueError(f"Unknown workflow step: {step_id}")
        original_error = state.error.to_dict() if state.error is not None else {}
        accepted = ToolResult(
            tool=str(state.result.tool if state.result else step_id),
            status=ToolStatus.SUCCEEDED,
            facts={"human_confirmed": True, "accepted_error": original_error},
            output=state.result.output if state.result else "",
            attempt=state.attempt,
            metadata={"human_confirmed": True},
        )
        self._states[step_id] = replace(state, status=StepStatus.COMPLETED, result=accepted, error=None)
        self._outputs[step_id] = dict(accepted.facts)
        next_step = self._next_ready(step_id)
        status = TaskStatus.COMPLETED.value if not next_step else TaskStatus.RUNNING.value
        self._pending_context = None
        self._pending_decision_id = ""
        return self._save(status=status, current_step=next_step)

    def create_decision(
        self,
        *,
        current_step: str | None = None,
        error: ToolError | None = None,
        result: ToolResult | None = None,
        waiting_status: str = TaskStatus.WAITING_FOR_DECISION.value,
    ) -> DecisionContext:
        step_id = current_step or self._current_step()
        workflow = self._require_workflow()
        available_actions = self._decision_actions(step_id, user_confirmation=waiting_status == TaskStatus.WAITING_FOR_USER.value)
        context = DecisionContext(
            task_id=self.task.id, workflow_id=workflow.id, current_step=step_id,
            error=error, result=result, context={**self._checkpoint_context(), "outputs": dict(self._outputs)},
            available_actions=available_actions,
            workflow_instance_id=self.task.workflow_instance_id, checkpoint_revision=self._revision + 1,
        )
        self._pending_context = context
        self._pending_decision_id = str(uuid4())
        self._save(status=waiting_status, current_step=step_id, pending_decision_id=self._pending_decision_id)
        return context

    def apply_decision(self, decision: Decision | Action | str) -> Task:
        if self._pending_context is None or self.task.status not in {TaskStatus.WAITING_FOR_DECISION.value, TaskStatus.WAITING_FOR_USER.value}:
            raise ValueError("Workflow is not waiting for a decision")
        if isinstance(decision, str):
            decision = Action(decision)
        if isinstance(decision, Action):
            decision = Decision(
                decision_id=str(uuid4()), actor=DecisionActor(type="user"), action=decision,
                task_id=self.task.id, workflow_id=self._require_workflow().id,
                expected_revision=self._revision,
            )
        if decision.expected_revision is not None and decision.expected_revision != self._revision:
            raise ValueError("Decision checkpoint revision does not match the workflow")
        if decision.task_id and decision.task_id != self.task.id:
            raise ValueError("Decision belongs to another task")
        action = decision.action
        name = action.name.casefold()
        if name not in {"retry", "retry_step", "resume_from", "resume-from", "cancel", "pause", "resume", "continue", "accept", "accept_failure", "accept-failure", "approve"}:
            raise ValueError(f"Unsupported workflow decision action: {action.name}")
        allowed_names = {
            item.name.casefold()
            for item in self._pending_context.available_actions
        }
        if name not in allowed_names:
            raise ValueError(f"Workflow decision action is not available: {action.name}")
        self._decisions.append(decision)
        self._pending_context = None
        self._pending_decision_id = ""
        target_step = action.target_step or str(action.parameters.get("step_id") or action.parameters.get("target_step") or "")
        if name in {"retry", "retry_step"}:
            return self.retry_step(target_step or self._current_step())
        if name in {"resume_from", "resume-from"}:
            return self.resume_from(target_step or self._current_step())
        if name in {"continue", "accept", "accept_failure", "accept-failure"}:
            return self.accept_failed_step(target_step or self._current_step())
        if name == "cancel":
            return self.cancel()
        if name == "pause":
            return self.pause()
        if name in {"resume", "approve"}:
            if name == "approve":
                self._approved_steps.add(target_step or self._current_step())
            return self.resume()
        raise AssertionError("validated decision action was not handled")

    def checkpoint(self) -> Checkpoint:
        self._save()
        return self.task.checkpoint or Checkpoint()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _require_workflow(self) -> WorkflowDefinition:
        if self._workflow is None:
            raise RuntimeError("Workflow has not been started")
        return self._workflow

    def _decision_actions(self, step_id: str, *, user_confirmation: bool) -> tuple[Action, ...]:
        if user_confirmation:
            return (Action("approve", target_step=step_id), Action("cancel"))
        steps = self._require_workflow().steps
        try:
            index = next(index for index, step in enumerate(steps) if step.id == step_id)
        except StopIteration:
            return (Action("retry", target_step=step_id), Action("cancel"))
        actions = [Action("retry", target_step=step_id)]
        state = self._states.get(step_id)
        if state is not None and state.error is not None and state.error.code not in {
            "unsupported_operation",
            "package_upgrade_error",
        }:
            actions.append(Action("continue", target_step=step_id))
        if index > 0:
            actions.append(Action("resume_from", target_step=steps[index - 1].id))
        actions.append(Action("cancel"))
        return tuple(actions)

    @staticmethod
    def _workflow_from_task(task: Task) -> WorkflowDefinition | None:
        if isinstance(task.workflow, WorkflowDefinition):  # type: ignore[unreachable]
            return task.workflow
        raw = task.metadata.get("workflow_definition")
        return WorkflowDefinition.from_dict(raw) if isinstance(raw, dict) else None

    @staticmethod
    def _validate_workflow(workflow: WorkflowDefinition) -> None:
        if not workflow.steps or len(workflow.steps) > workflow.max_steps:
            raise ValueError("Workflow step count is invalid")
        ids = {step.id for step in workflow.steps}
        if len(ids) != len(workflow.steps) or any(dep not in ids for step in workflow.steps for dep in step.depends_on):
            raise ValueError("Workflow dependencies are invalid")
        resolved: set[str] = set()
        while True:
            newly_resolved = {step.id for step in workflow.steps if step.id not in resolved and set(step.depends_on) <= resolved}
            if not newly_resolved:
                break
            resolved.update(newly_resolved)
        if len(resolved) != len(workflow.steps):
            raise ValueError("Workflow contains a dependency cycle")

    def _completed_ids(self) -> set[str]:
        return {step_id for step_id, state in self._states.items() if state.status in {StepStatus.COMPLETED, StepStatus.SUCCESS}}

    def _next_ready(self, after: str = "") -> str:
        completed = self._completed_ids()
        for step in self._require_workflow().steps:
            if step.id not in completed and set(step.depends_on) <= completed:
                return step.id
        return ""

    def _current_step(self) -> str:
        return self.task.workflow.current_step if isinstance(self.task.workflow, WorkflowInstance) else ""

    async def _invoke(self, step: WorkflowStep) -> Any:
        if self._execution is None:
            raise RuntimeError("Workflow execution tool is not configured")
        context = ControlContext(
            source=str(self._context.get("source") or "task"),
            task_id=self.task.id,
            step_id=step.id,
            lease_token=str(self._context.get("lease_token") or ""),
            operation_callback=self._context.get("operation_callback"),
        )
        if hasattr(self._execution, "execute"):
            value = self._execution.execute(self._target, step, context=context)
        else:
            value = self._execution(self._target, step, context=context)
        return await value if hasattr(value, "__await__") else value

    @staticmethod
    def _error_from_exception(exc: Exception) -> ToolError:
        return ToolError(
            code=str(getattr(exc, "code", "execution_failed")), message=str(exc),
            error_class=str(getattr(exc, "error_class", "unknown")),
            retryable=bool(getattr(exc, "retryable", False)),
            details=dict(getattr(exc, "details", {}) or {}),
        )

    def _save(self, *, status: str | None = None, current_step: str | None = None, pending_decision_id: str | None = None) -> Task:
        if self._task is None:
            raise RuntimeError("Workflow has not been started")
        self._revision += 1
        current = self._current_step() if current_step is None else current_step
        cp = Checkpoint(
            id=f"cp-{self._revision}", task_id=self.task.id, workflow_instance_id=self.task.workflow_instance_id,
            revision=self._revision, current_step=current,
            completed_steps=tuple(step.id for step in self._require_workflow().steps if step.id in self._completed_ids()),
            step_states=tuple(self._states.values()), outputs=dict(self._outputs),
            context={**self._checkpoint_context(), "approved_steps": tuple(sorted(self._approved_steps))},
            failed_step_id=next((sid for sid, state in self._states.items() if state.status == StepStatus.FAILED), ""),
            attempts=dict(self._attempts),
            operation_ids=tuple(str(item) for item in self._context.get("operation_ids", ()) if str(item)),
            pending_decision_id=self._pending_decision_id if pending_decision_id is None else pending_decision_id,
            error_code=next((state.error.code for state in self._states.values() if state.error), ""),
            error_message=next((state.error.message for state in self._states.values() if state.error), ""),
            decisions=tuple(self._decisions), created_at=self._now(),
        )
        old_instance = self.task.workflow if isinstance(self.task.workflow, WorkflowInstance) else WorkflowInstance(
            id=self.task.workflow_instance_id, task_id=self.task.id, workflow_id=self._require_workflow().id,
        )
        instance = replace(old_instance, status=status or str(self.task.status), current_step=current, outputs=dict(self._outputs),
                           step_states=tuple(self._states.values()), checkpoint=cp, updated_at=self._now(), decisions=tuple(self._decisions))
        self._task = replace(self.task, status=status or self.task.status, updated_at=self._now(), workflow=instance, checkpoint=cp, decisions=tuple(self._decisions))
        return self._task

    def _checkpoint_context(self) -> dict[str, Any]:
        """Return context that is safe to persist and expose through APIs."""
        internal_keys = {"lease_token", "operation_callback", "operation_ids"}
        return {key: value for key, value in self._context.items() if key not in internal_keys}

    def _remember_recovery_target(self, step: WorkflowStep, facts: dict[str, Any]) -> None:
        if str(step.action or step.kind).casefold() != "wait_online":
            return
        session_id = str(facts.get("session_id") or "").strip()
        if not session_id:
            return
        self._target = DeviceTarget(
            device_id=str(facts.get("device_id") or self._target.device_id),
            session_id=session_id,
            protocol=str(facts.get("recovery_protocol") or self._target.protocol or "auto"),
        )

    def _restore_recovery_target(self) -> None:
        for step_id, facts in self._outputs.items():
            if not isinstance(facts, dict) or not step_id.casefold().endswith("wait_online"):
                continue
            self._remember_recovery_target(
                WorkflowStep(step_id, kind="device", action="wait_online"),
                facts,
            )

    async def run(
        self,
        workflow: WorkflowDefinition,
        *,
        task_id: str,
        target: DeviceTarget,
        context: dict[str, Any],
        decision: DecisionEngine,
        execution: ExecutionTool,
        cancel_event: asyncio.Event,
        on_step: Any = None,
        checkpoint: WorkflowCheckpoint | None = None,
        pause_on_error: bool = False,
    ) -> WorkflowResult:
        if not workflow.steps or len(workflow.steps) > workflow.max_steps:
            return WorkflowResult("failed", (), error_code="invalid_workflow", message="Workflow step count is invalid.")
        by_id = {step.id: step for step in workflow.steps}
        if len(by_id) != len(workflow.steps) or any(dep not in by_id for step in workflow.steps for dep in step.depends_on):
            return WorkflowResult("failed", (), error_code="invalid_workflow", message="Workflow dependencies are invalid.")
        completed: set[str] = set(checkpoint.completed_steps if checkpoint else ())
        failed: set[str] = set()
        resolved: set[str] = set(completed)
        results: list[WorkflowStepResult] = []
        outputs: dict[str, Any] = dict(checkpoint.outputs if checkpoint else {})
        remaining = [step for step in workflow.steps if step.id not in completed]
        while remaining:
            if cancel_event.is_set():
                return WorkflowResult("cancelled", tuple(results), outputs, "task_cancelled", "Task cancelled.")
            ready = next((step for step in remaining if set(step.depends_on) <= resolved), None)
            if ready is None:
                return WorkflowResult("failed", tuple(results), outputs, "workflow_cycle", "Workflow contains a dependency cycle.")
            remaining.remove(ready)
            if set(ready.depends_on) & failed:
                result = WorkflowStepResult(ready.id, "skipped", ready.action, message="Dependency failed.")
                results.append(result)
                resolved.add(ready.id)
                failed.add(ready.id)
                if on_step:
                    on_step(result)
                continue
            try:
                if ready.kind.casefold() == "decision":
                    decision_result = await decision.decide(DecisionRequest(task_id, ready, context, dict(outputs)))
                    data = {"approved": decision_result.approved, "action": decision_result.action, **decision_result.data}
                    result = WorkflowStepResult(ready.id, "completed" if decision_result.approved else "failed", ready.action, decision_result.reason, data=data)
                else:
                    execution_context = {**context, "outputs": dict(outputs)}
                    data = await execution.execute(
                        target,
                        ready,
                        context=ControlContext(
                            source=str(execution_context.get("source") or "task"),
                            task_id=task_id,
                            step_id=ready.id,
                            lease_token=str(execution_context.get("lease_token") or ""),
                            operation_callback=execution_context.get("operation_callback"),
                        ),
                    )
                    output = str(data.get("output") or "")
                    result = WorkflowStepResult(
                        ready.id,
                        "completed",
                        ready.action,
                        output,
                        data=data,
                        operation_id=str(data.get("operation_id") or ""),
                        execution_id=str(data.get("execution_id") or ""),
                        evidence=tuple(dict(item) for item in data.get("evidence", ()) if isinstance(item, dict)),
                    )
                results.append(result)
                outputs[ready.id] = result.data
                if result.status == "completed":
                    completed.add(ready.id)
                else:
                    failed.add(ready.id)
                resolved.add(ready.id)
            except asyncio.CancelledError:
                raise
            except (ApplicationError, ValueError) as exc:
                result = WorkflowStepResult(
                    ready.id,
                    "failed",
                    ready.action,
                    error_code=getattr(exc, "code", "execution_failed"),
                    message=str(exc),
                    evidence=({"kind": "error", "step_id": ready.id, "error_code": getattr(exc, "code", "execution_failed"), "message": str(exc)},),
                )
                results.append(result)
                failed.add(ready.id)
                resolved.add(ready.id)
                if pause_on_error:
                    return WorkflowResult("paused", tuple(results), outputs, result.error_code, result.message)
            if on_step:
                on_step(result)
        status = "failed" if failed else "completed"
        return WorkflowResult(status, tuple(results), outputs, "workflow_failed" if failed else "", "Workflow completed." if not failed else "Workflow failed.")


class TaskManager:
    """Own task lifecycle and delegate every device action to workflow ports."""

    def __init__(
        self,
        execution: DeviceExecutionTool,
        events: EventBus,
        *,
        workflow_engine: WorkflowEngine | None = None,
        decision_engine: DecisionEngine | None = None,
        store: TaskStore | None = None,
        leases: DeviceLeaseService | None = None,
        framework_runtime: WorkflowRuntime | None = None,
        framework_workflows: WorkflowRegistry | None = None,
    ) -> None:
        self._execution = execution
        self._events = events
        self._engine = workflow_engine or WorkflowEngine()
        self._decision = decision_engine or RuleDecisionEngine()
        self._records: dict[str, TaskRecord] = {}
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self._cancel: dict[str, asyncio.Event] = {}
        self._completed_steps: dict[str, int] = {}
        self._requests: dict[str, TaskCreate] = {}
        self._stateful_engines: dict[str, WorkflowEngine] = {}
        self._leases = leases
        self._lease_tokens: dict[str, tuple[str, str]] = {}
        self._resources: dict[str, set[tuple[str, str]]] = {}
        self._store = store
        self._framework_runtime = framework_runtime
        self._framework_workflows = framework_workflows
        self._framework_definitions: dict[str, FrameworkWorkflowDefinition] = {}
        if store is not None:
            for record, request in store.list_tasks():
                interrupted = self._interrupted_operation(record)
                if record.status in {"running", "pending"}:
                    record = replace(
                        record,
                        status="paused",
                        message=(
                            "应用重启，关联设备操作已中断；请从断点恢复或重新规划。"
                            if interrupted else "应用重启后任务等待恢复。"
                        ),
                        error_code="operation_interrupted" if interrupted else "app_restarted",
                    )
                self._records[record.id] = record
                self._requests[record.id] = request
                if record.checkpoint is not None:
                    self._resources[record.id] = {("operation", item) for item in record.checkpoint.operation_ids}
                store.upsert_task(record, request)

    def create(self, request: TaskCreate) -> TaskRecord:
        task_id = str(uuid4())
        device_id = str(request.target.device_id or "").strip()
        framework_definition = self._framework_definition(request.workflow)
        if request.workflow.id == "device_upgrade" and framework_definition is None:
            raise ApplicationError("The device_upgrade workflow requires the Workflow Framework.")
        if framework_definition is None and self._leases is not None and device_id:
            lease = self._leases.acquire(device_id, task_id)
            self._lease_tokens[task_id] = (device_id, lease.token)
        now = self._now()
        metadata = dict(request.workflow.metadata)
        record = TaskRecord(
            task_id,
            "pending",
            request.workflow.id,
            request.target.device_id,
            request.target.session_id,
            request.source,
            now,
            now,
            message="Task queued.",
            plan_id=str(metadata.get("plan_id") or ""),
            plan_hash=str(metadata.get("plan_hash") or ""),
            parent_task_id=str(metadata.get("parent_task_id") or ""),
            plan_revision=max(0, int(request.workflow.version or 0)) if str(request.workflow.version).isdigit() else 0,
        )
        self._records[task_id] = record
        self._requests[task_id] = request
        cancel_event = asyncio.Event()
        self._cancel[task_id] = cancel_event
        self._resources[task_id] = set()
        self._completed_steps[task_id] = 0
        if framework_definition is not None:
            run = self._framework_runtime.start(
                framework_definition,
                device_id=device_id,
                run_id=task_id,
                context={
                    **dict(request.context),
                    "source": request.source,
                    "target": {
                        "device_id": device_id,
                        "session_id": request.target.session_id,
                        "protocol": request.target.protocol,
                    },
                },
            )
            self._framework_definitions[task_id] = framework_definition
            self._update_framework_record(task_id, request, run)
            self._jobs[task_id] = asyncio.create_task(
                self._run_framework(task_id, request),
                name=f"framework-task-{task_id}",
            )
            self._publish("task.created", self.get(task_id))
            self._persist(self.get(task_id), request)
            return self.get(task_id)
        # Agent-authored plans still use the resumable legacy engine until the
        # generic plan compiler is migrated to Framework definitions.
        runner = self._run_stateful if request.source in {"agent", "mcp-agent"} else self._run
        self._jobs[task_id] = asyncio.create_task(runner(task_id, request), name=f"device-task-{task_id}")
        self._publish("task.created", record)
        self._persist(record, request)
        return record

    async def _run_framework(self, task_id: str, request: TaskCreate) -> None:
        try:
            await self._framework_runtime.run_until_blocked(
                task_id,
                on_update=lambda run: self._update_framework_record(task_id, request, run),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._update(task_id, status=TaskStatus.FAILED.value, message=str(exc), error_code="framework_task_failed")
        finally:
            self._jobs.pop(task_id, None)
            run = self._framework_runtime.runs.get(task_id)
            if str(run.status) not in {FrameworkRunStatus.WAITING_DECISION.value, FrameworkRunStatus.PAUSED.value}:
                self._release_task_resources(task_id)

    def _framework_definition_for_task(self, task_id: str) -> FrameworkWorkflowDefinition | None:
        definition = self._framework_definitions.get(task_id)
        if definition is not None:
            return definition
        request = self._requests.get(task_id)
        if request is None:
            return None
        definition = self._framework_definition(request.workflow)
        if definition is not None:
            self._framework_definitions[task_id] = definition
            self._framework_runtime.register_definition(definition)
        return definition

    def _framework_definition(self, workflow: WorkflowDefinition) -> FrameworkWorkflowDefinition | None:
        if self._framework_runtime is None or self._framework_workflows is None:
            return None
        metadata = dict(workflow.metadata)
        canonical_id = str(metadata.get("canonical_workflow_id") or "").strip()
        if not canonical_id:
            return None
        raw_inputs = metadata.get("framework_inputs")
        if not isinstance(raw_inputs, dict):
            return None
        return self._framework_workflows.build(canonical_id, dict(raw_inputs))

    @staticmethod
    def _framework_workflow_view(definition: FrameworkWorkflowDefinition) -> dict[str, Any]:
        """Build the non-executable workflow metadata consumed by generic UIs."""
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

    @staticmethod
    def _framework_step_states(
        definition: FrameworkWorkflowDefinition,
        run: FrameworkWorkflowRun,
    ) -> tuple[WorkflowStepState, ...]:
        """Project attempts onto every declared state, including unstarted states."""
        latest_attempts = {attempt.action_id: attempt for attempt in run.attempts}
        states: list[WorkflowStepState] = []
        for state in definition.states:
            attempt = latest_attempts.get(state.action.id) if state.action is not None else None
            if state.id == run.current_state:
                if state.terminal and str(run.status) == FrameworkRunStatus.SUCCEEDED.value:
                    status = StepStatus.COMPLETED.value
                elif str(run.status) == FrameworkRunStatus.WAITING_DECISION.value:
                    status = StepStatus.WAITING_FOR_DECISION.value
                elif str(run.status) == FrameworkRunStatus.CANCELLED.value:
                    status = StepStatus.CANCELLED.value
                else:
                    status = StepStatus.RUNNING.value
            elif attempt is not None:
                status = StepStatus.COMPLETED.value if str(attempt.status) == FrameworkActionStatus.SUCCEEDED.value else str(attempt.status)
            else:
                status = StepStatus.PENDING.value
            facts = dict(attempt.result) if attempt is not None else {}
            error = dict(attempt.error) if attempt is not None and attempt.error else {}
            result = None
            if attempt is not None:
                result = ToolResult(
                    tool=state.action.operation if state.action is not None else state.id,
                    status=status,
                    facts=facts,
                    output=str(facts.get("output") or ""),
                    error=ToolError(
                        code=str(error.get("code") or ""),
                        message=str(error.get("message") or ""),
                        error_class=str(error.get("class") or error.get("error_class") or "unknown"),
                    ) if error else None,
                    operation_id=str(facts.get("operation_id") or ""),
                    execution_id=str(facts.get("execution_id") or ""),
                    evidence=tuple(dict(item) for item in facts.get("evidence", ()) if isinstance(item, dict)),
                    attempt=attempt.attempt,
                )
            states.append(WorkflowStepState(
                step_id=state.id,
                status=status,
                attempt=attempt.attempt if attempt is not None else 0,
                result=result,
                error=result.error if result is not None else None,
                started_at=attempt.started_at if attempt is not None else "",
            ))
        return tuple(states)

    def _update_framework_record(self, task_id: str, request: TaskCreate, run: FrameworkWorkflowRun) -> None:
        definition = self._framework_definitions.get(task_id)
        if definition is None:
            return
        state_by_id = {item.id: item for item in definition.states}
        completed = {attempt.action_id for attempt in run.attempts if str(attempt.status) == FrameworkActionStatus.SUCCEEDED.value}
        total = max(1, len(definition.states) - 1)
        completed_count = len(completed & set(state_by_id))
        status_map = {
            FrameworkRunStatus.PENDING.value: TaskStatus.PENDING.value,
            FrameworkRunStatus.RUNNING.value: TaskStatus.RUNNING.value,
            FrameworkRunStatus.RECOVERING.value: TaskStatus.RUNNING.value,
            FrameworkRunStatus.WAITING_RECONCILE.value: TaskStatus.RUNNING.value,
            FrameworkRunStatus.WAITING_DECISION.value: TaskStatus.WAITING_FOR_DECISION.value,
            FrameworkRunStatus.SUCCEEDED.value: TaskStatus.COMPLETED.value,
            FrameworkRunStatus.FAILED.value: TaskStatus.FAILED.value,
            FrameworkRunStatus.CANCELLED.value: TaskStatus.CANCELLED.value,
        }
        status = status_map.get(str(run.status), str(run.status))
        attempts = []
        for attempt in run.attempts:
            facts = dict(attempt.result or {})
            error = dict(attempt.error or {})
            # Preserve the legacy TaskResult shape for callers that still
            # read package-upgrade evidence from data.operation. The Framework
            # facts remain the source of truth; this is only a projection.
            if facts.get("operation_id") and isinstance(facts.get("data"), dict) and "operation" not in facts:
                facts["operation"] = {
                    "operation_id": facts["operation_id"],
                    "status": facts.get("status", "completed"),
                    "data": dict(facts["data"]),
                }
            attempts.append(WorkflowStepResult(
                attempt.action_id,
                "completed" if str(attempt.status) == FrameworkActionStatus.SUCCEEDED.value else str(attempt.status),
                state_by_id.get(attempt.action_id).action.operation if state_by_id.get(attempt.action_id) and state_by_id.get(attempt.action_id).action else attempt.action_id,
                output=str(facts.get("output") or ""),
                error_code=str(error.get("code") or ""),
                message=str(error.get("message") or ""),
                data=facts,
                operation_id=str(facts.get("operation_id") or ""),
                evidence=tuple(dict(item) for item in facts.get("evidence", ()) if isinstance(item, dict)),
            ))
        result_status = "completed" if status == TaskStatus.COMPLETED.value else status
        result = WorkflowResult(
            status=result_status,
            steps=tuple(attempts),
            outputs=dict(run.context),
            error_code=str((run.error or {}).get("code") or ""),
            message=("Workflow completed." if status == TaskStatus.COMPLETED.value else "Workflow waiting." if status == TaskStatus.WAITING_FOR_DECISION.value else "Workflow running." if status == TaskStatus.RUNNING.value else "Workflow failed."),
        )
        checkpoint = Checkpoint(
            task_id=task_id,
            workflow_instance_id=f"framework-{task_id}",
            revision=run.revision,
            current_step=run.current_state,
            completed_steps=tuple(sorted(completed & set(state_by_id))),
            outputs=dict(run.context),
            context={key: value for key, value in run.context.items() if key != "lease_token"},
            attempts={attempt.action_id: sum(1 for item in run.attempts if item.action_id == attempt.action_id) for attempt in run.attempts},
            error_code=str((run.error or {}).get("code") or ""),
            error_message=str((run.error or {}).get("message") or ""),
            step_states=self._framework_step_states(definition, run),
        )
        self._update(
            task_id,
            status=status,
            current_step_id=run.current_state,
            progress_percent=100 if status == TaskStatus.COMPLETED.value else min(99, int(completed_count * 100 / total)),
            result=result,
            checkpoint=checkpoint,
            message=result.message,
            error_code=result.error_code,
            workflow_view=self._framework_workflow_view(definition),
        )

    async def _run_stateful(self, task_id: str, request: TaskCreate) -> None:
        record = self.get(task_id)
        task = Task(
            id=task_id, workflow_instance_id=f"workflow-{task_id}", status=record.status,
            device_id=request.target.device_id, source=request.source,
            created_at=record.created_at, updated_at=record.updated_at, checkpoint=record.checkpoint, context=dict(request.context),
        )
        engine = WorkflowEngine(request.workflow, self._execution, target=request.target, context=self._execution_context(task_id, request))
        self._stateful_engines[task_id] = engine
        try:
            engine.start(task, execution=self._execution, target=request.target)
            self._update_from_engine(task_id, request.workflow, engine.task)
            while engine.task.status in {TaskStatus.RUNNING.value, TaskStatus.RESUMED.value}:
                await engine.execute_step()
                self._update_from_engine(task_id, request.workflow, engine.task)
            self._update_from_engine(task_id, request.workflow, engine.task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._update(task_id, status=TaskStatus.FAILED.value, message=str(exc), error_code="task_failed")
        finally:
            self._jobs.pop(task_id, None)
            if self.get(task_id).status not in {TaskStatus.WAITING_FOR_DECISION.value, TaskStatus.WAITING_FOR_USER.value, TaskStatus.PAUSED.value}:
                self._release_task_resources(task_id)

    def apply_decision(self, task_id: str, decision: Any) -> TaskRecord:
        request = self._requests.get(task_id)
        if request is None:
            raise ResourceNotFoundError("Task workflow definition is no longer available.", details={"task_id": task_id})
        if self._framework_definition_for_task(task_id) is not None:
            run = self._framework_runtime.runs.get(task_id)
            action = decision.action if isinstance(decision, Decision) else decision
            if isinstance(action, Action):
                action_name = action.name.casefold()
                point = run.decision_point
                if point is None:
                    raise ValueError("Workflow is not waiting for a decision")
                option = next(
                    (
                        item for item in point.options
                        if item.id.casefold() == action_name
                        or item.kind.casefold() == action_name
                        or (action_name == "cancel" and item.kind.casefold() == "abort")
                    ),
                    None,
                )
                if option is None:
                    raise ValueError(f"Workflow decision action is not available: {action.name}")
                actor = decision.actor if isinstance(decision, Decision) else DecisionActor(type="user")
                actor_type = "human" if actor.type == "user" else "agent"
                submission = FrameworkDecisionSubmission(
                    decision_point_id=point.id,
                    expected_revision=(decision.expected_revision if isinstance(decision, Decision) and decision.expected_revision is not None else run.revision),
                    option_id=option.id,
                    actor_type=actor_type,
                    actor_id=actor.id,
                    inputs=dict(action.parameters),
                    reason=str(decision.reason if isinstance(decision, Decision) else ""),
                    idempotency_key=str(decision.decision_id if isinstance(decision, Decision) else ""),
                )
                updated = self._framework_runtime.apply_decision(task_id, submission)
                self._update_framework_record(task_id, request, updated)
                if str(updated.status) == FrameworkRunStatus.RUNNING.value and task_id not in self._jobs:
                    self._jobs[task_id] = asyncio.create_task(self._run_framework(task_id, request), name=f"framework-task-{task_id}-decision")
                return self.get(task_id)
        self._ensure_lease(task_id, request.target.device_id)
        engine = self._stateful_engines.get(task_id)
        if engine is None:
            record = self.get(task_id)
            task = Task(id=task_id, workflow_instance_id=f"workflow-{task_id}", status=record.status, device_id=request.target.device_id, source=request.source, checkpoint=record.checkpoint, context=dict(request.context))
            engine = WorkflowEngine(request.workflow, self._execution, target=request.target, context=self._execution_context(task_id, request))
            engine.start(task, execution=self._execution, target=request.target)
            self._stateful_engines[task_id] = engine
        engine.apply_decision(decision)
        if task_id not in self._jobs:
            self._jobs[task_id] = asyncio.create_task(self._run_stateful(task_id, request), name=f"device-task-{task_id}-decision")
        self._update_from_engine(task_id, request.workflow, engine.task)
        return self.get(task_id)

    def _update_from_engine(self, task_id: str, workflow: WorkflowDefinition, task: Task) -> None:
        done = len(task.checkpoint.completed_steps) if task.checkpoint else 0
        total = max(1, len(workflow.steps))
        status = str(task.status)
        if status == TaskStatus.COMPLETED.value:
            workflow_message = "Workflow completed."
        elif status == TaskStatus.FAILED.value:
            workflow_message = "Workflow failed."
        elif status == TaskStatus.CANCELLED.value:
            workflow_message = "Workflow cancelled."
        elif status == TaskStatus.PAUSED.value:
            workflow_message = "Workflow paused."
        elif status.startswith("waiting"):
            workflow_message = "Workflow waiting."
        else:
            workflow_message = "Workflow running."
        result = WorkflowResult(
            status=status,
            steps=tuple(
                WorkflowStepResult(
                    state.step_id,
                    state.status,
                    workflow.steps[index].action if index < len(workflow.steps) else "",
                    output=state.result.output if state.result else "",
                    error_code=state.error.code if state.error else "",
                    message=state.error.message if state.error else "",
                    data=state.result.facts if state.result else {},
                    operation_id=state.result.operation_id if state.result else "",
                    execution_id=state.result.execution_id if state.result else "",
                    evidence=state.result.evidence if state.result else (),
                )
                for index, state in enumerate(task.workflow.step_states if task.workflow else ())
            ),
            outputs=dict(task.workflow.outputs if task.workflow else {}),
            error_code=(task.checkpoint.error_code if task.checkpoint else ""),
            message=workflow_message,
        )
        self._update(task_id, status=status, current_step_id=task.workflow.current_step if task.workflow else "", progress_percent=100 if status == TaskStatus.COMPLETED.value else min(99, int(done * 100 / total)), checkpoint=task.checkpoint, result=result, message=result.message, error_code=result.error_code)

    async def _run(self, task_id: str, request: TaskCreate) -> None:
        self._update(task_id, status="running", message="Task running.")
        try:
            result = await self._engine.run(
                request.workflow,
                task_id=task_id,
                target=request.target,
                context=self._execution_context(task_id, request),
                decision=self._decision,
                execution=self._execution,
                cancel_event=self._cancel[task_id],
                on_step=lambda step: self._step_update(task_id, request.workflow, step),
                checkpoint=self.get(task_id).checkpoint,
                pause_on_error=True,
            )
            checkpoint = self._checkpoint_from_result(result, self.get(task_id).checkpoint)
            self._update(task_id, status=result.status, result=result, checkpoint=checkpoint, progress_percent=100 if result.status == "completed" else self.get(task_id).progress_percent, message=result.message, error_code=result.error_code)
        except asyncio.CancelledError:
            result = WorkflowResult("cancelled", (), error_code="task_cancelled", message="Task cancelled.")
            self._update(task_id, status="cancelled", result=result, message=result.message, error_code=result.error_code)
        except Exception as exc:
            self._update(task_id, status="failed", message=str(exc), error_code="task_failed")
        finally:
            self._jobs.pop(task_id, None)
            self._completed_steps.pop(task_id, None)
            self._release_task_resources(task_id)

    def resume(self, task_id: str, *, context: dict[str, Any] | None = None, step_id: str = "") -> TaskRecord:
        """Resume a paused task after an operator or agent has repaired the device."""
        record = self.get(task_id)
        if record.status not in {"paused", "failed"}:
            raise ApplicationError("Only paused or failed tasks can be resumed.", details={"task_id": task_id, "status": record.status})
        request = self._requests.get(task_id)
        if request is None:
            raise ResourceNotFoundError("Task workflow definition is no longer available.", details={"task_id": task_id})
        if self._framework_definition_for_task(task_id) is not None:
            run = self._framework_runtime.resume(task_id, context=dict(context or {}))
            self._update_framework_record(task_id, request, run)
            if str(run.status) == FrameworkRunStatus.RUNNING.value and task_id not in self._jobs:
                self._jobs[task_id] = asyncio.create_task(self._run_framework(task_id, request), name=f"framework-task-{task_id}-resume")
            return self.get(task_id)
        self._ensure_lease(task_id, request.target.device_id)
        if request.source in {"agent", "mcp-agent"}:
            engine = self._stateful_engines.get(task_id)
            if engine is None:
                record = self.get(task_id)
                restored = Task(id=task_id, workflow_instance_id=f"workflow-{task_id}", status=record.status, device_id=request.target.device_id, source=request.source, checkpoint=record.checkpoint, context=dict(request.context))
                engine = WorkflowEngine(request.workflow, self._execution, target=request.target, context=self._execution_context(task_id, request))
                engine.start(restored, execution=self._execution, target=request.target)
                self._stateful_engines[task_id] = engine
            if step_id:
                engine.resume_from(step_id)
            else:
                engine.resume()
            self._update_from_engine(task_id, request.workflow, engine.task)
            if task_id not in self._jobs:
                self._jobs[task_id] = asyncio.create_task(self._run_stateful(task_id, request), name=f"device-task-{task_id}-resume")
            return self.get(task_id)
        checkpoint = record.checkpoint or WorkflowCheckpoint()
        if step_id:
            if step_id not in {item.id for item in request.workflow.steps}:
                raise ApplicationError("Unknown workflow step.", details={"task_id": task_id, "step_id": step_id})
            completed = tuple(item for item in checkpoint.completed_steps if item != step_id)
            checkpoint = replace(checkpoint, completed_steps=completed, failed_step_id=step_id)
        updated_request = replace(request, context={**request.context, **dict(context or {})})
        self._requests[task_id] = updated_request
        self._cancel[task_id] = asyncio.Event()
        self._completed_steps[task_id] = len(checkpoint.completed_steps)
        self._update(task_id, status="running", checkpoint=checkpoint, result=None, error_code="", message="Task resumed.")
        self._jobs[task_id] = asyncio.create_task(self._run(task_id, updated_request), name=f"device-task-{task_id}-resume")
        return self.get(task_id)

    def pause(self, task_id: str) -> TaskRecord:
        record = self.get(task_id)
        if record.status in {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELLED.value}:
            return record
        request = self._requests.get(task_id)
        if request is not None and self._framework_definition_for_task(task_id) is not None:
            run = self._framework_runtime.pause(task_id)
            job = self._jobs.get(task_id)
            if job is not None:
                job.cancel()
            self._update_framework_record(task_id, request, run)
            return self.get(task_id)
        if request is not None and request.source in {"agent", "mcp-agent"}:
            engine = self._stateful_engines.get(task_id)
            if engine is not None:
                engine.pause()
            self._cancel_underlying(task_id)
            job = self._jobs.get(task_id)
            if job is not None:
                job.cancel()
            self._update(task_id, status=TaskStatus.PAUSED.value, checkpoint=engine.task.checkpoint if engine else record.checkpoint, message="Task paused.")
            return self.get(task_id)
        self._update(task_id, status=TaskStatus.PAUSED.value, message="Task paused.")
        self._cancel_underlying(task_id)
        job = self._jobs.get(task_id)
        if job is not None:
            job.cancel()
        return self.get(task_id)

    def get_decision(self, task_id: str) -> DecisionContext | None:
        record = self.get(task_id)
        request = self._requests.get(task_id)
        if request is not None and self._framework_definition_for_task(task_id) is not None:
            run = self._framework_runtime.runs.get(task_id)
            point = run.decision_point
            if point is None:
                return None
            actions = tuple(
                Action(
                    item.id,
                    target_step=run.current_state,
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
                workflow_id=record.workflow_id,
                current_step=run.current_state,
                error=run.error,
                context=dict(run.context),
                available_actions=actions,
                workflow_instance_id=f"framework-{task_id}",
                checkpoint_revision=run.revision,
            )
        if request is None or request.source not in {"agent", "mcp-agent"}:
            return None
        engine = self._stateful_engines.get(task_id)
        if engine is None:
            task = Task(id=task_id, workflow_instance_id=f"workflow-{task_id}", status=record.status, device_id=request.target.device_id, source=request.source, checkpoint=record.checkpoint, context=dict(request.context))
            engine = WorkflowEngine(request.workflow, self._execution, target=request.target, context=self._execution_context(task_id, request))
            engine.start(task, execution=self._execution, target=request.target)
            self._stateful_engines[task_id] = engine
        return engine.pending_decision

    def get(self, task_id: str) -> TaskRecord:
        try:
            return self._records[task_id]
        except KeyError as exc:
            raise ResourceNotFoundError(f"Unknown task: {task_id}", details={"task_id": task_id}) from exc

    def list(self, *, limit: int = 200) -> list[TaskRecord]:
        return sorted(
            self._records.values(),
            key=lambda item: (item.updated_at or item.created_at, item.id),
            reverse=True,
        )[: max(0, limit)]

    def cancel(self, task_id: str) -> TaskRecord:
        record = self.get(task_id)
        if record.status in {"completed", "failed", "cancelled"}:
            return record
        request = self._requests.get(task_id)
        if request is not None and self._framework_definition_for_task(task_id) is not None:
            self._framework_runtime.cancel(task_id)
            job = self._jobs.get(task_id)
            if job is not None:
                job.cancel()
            self._update_framework_record(task_id, request, self._framework_runtime.runs.get(task_id))
            self._release_task_resources(task_id)
            return self.get(task_id)
        self._cancel.setdefault(task_id, asyncio.Event()).set()
        self._cancel_underlying(task_id)
        job = self._jobs.get(task_id)
        if job is not None:
            job.cancel()
        self._update(task_id, status="cancelled", message="Task cancelled.", error_code="task_cancelled")
        self._release_task_resources(task_id)
        return self.get(task_id)

    def cancel_session(self, session_id: str) -> int:
        """Cancel active tasks bound to a session before it is disconnected."""
        cancelled = 0
        for task_id, request in tuple(self._requests.items()):
            if request.target.session_id != session_id:
                continue
            if self.get(task_id).status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            }:
                continue
            self.cancel(task_id)
            cancelled += 1
        return cancelled

    async def close(self) -> None:
        for task_id in tuple(self._jobs):
            self._cancel_underlying(task_id)
        for task in list(self._jobs.values()):
            task.cancel()
        if self._jobs:
            await asyncio.gather(*self._jobs.values(), return_exceptions=True)
        self._jobs.clear()
        self._stateful_engines.clear()
        for task_id in tuple(self._lease_tokens):
            self._release_task_resources(task_id)

    def _execution_context(self, task_id: str, request: TaskCreate) -> dict[str, Any]:
        lease_token = self._lease_tokens.get(task_id, ("", ""))[1]
        record = self._records.get(task_id)
        operation_ids = list(record.checkpoint.operation_ids if record is not None and record.checkpoint is not None else ())
        return {
            **request.context,
            "source": request.source,
            "task_id": task_id,
            "lease_token": lease_token,
            "operation_ids": operation_ids,
            "operation_callback": lambda kind, resource_id: self._register_resource(task_id, kind, resource_id, operation_ids),
        }

    def _register_resource(self, task_id: str, kind: str, resource_id: str, operation_ids: list[str] | None = None) -> None:
        resource = (str(kind), str(resource_id))
        self._resources.setdefault(task_id, set()).add(resource)
        if operation_ids is not None and resource_id not in operation_ids:
            operation_ids.append(str(resource_id))
        record = self._records.get(task_id)
        request = self._requests.get(task_id)
        if record is None or request is None:
            return
        checkpoint = record.checkpoint or Checkpoint(task_id=task_id, current_step=record.current_step_id)
        if resource_id in checkpoint.operation_ids:
            return
        checkpoint = replace(checkpoint, operation_ids=(*checkpoint.operation_ids, str(resource_id)))
        updated = replace(record, checkpoint=checkpoint, updated_at=self._now())
        self._records[task_id] = updated
        self._persist(updated, request)

    def _cancel_underlying(self, task_id: str) -> None:
        cancel = getattr(self._execution, "cancel_resource", None)
        if callable(cancel):
            for kind, resource_id in tuple(self._resources.get(task_id, ())):
                try:
                    cancel(kind, resource_id)
                except Exception:
                    continue
        request = self._requests.get(task_id)
        cancel_target = getattr(self._execution, "cancel_target", None)
        if request is not None and callable(cancel_target):
            try:
                cancel_target(request.target)
            except Exception:
                pass

    def _release_task_resources(self, task_id: str) -> None:
        self._resources.pop(task_id, None)
        lease = self._lease_tokens.pop(task_id, None)
        if lease is not None and self._leases is not None:
            self._leases.release(lease[0], lease[1])

    def _ensure_lease(self, task_id: str, device_id: str) -> None:
        if self._leases is None or not str(device_id).strip() or task_id in self._lease_tokens:
            return
        lease = self._leases.acquire(device_id, task_id)
        self._lease_tokens[task_id] = (device_id, lease.token)
        self._resources.setdefault(task_id, set())

    def _interrupted_operation(self, record: TaskRecord) -> bool:
        get_resource = getattr(self._execution, "get_resource", None)
        if record.checkpoint is None or not callable(get_resource):
            return False
        for operation_id in record.checkpoint.operation_ids:
            try:
                snapshot = get_resource("operation", operation_id)
            except Exception:
                continue
            if str(snapshot.get("status") or "").casefold() == "interrupted":
                return True
        return False

    def _step_update(self, task_id: str, workflow: WorkflowDefinition, step: WorkflowStepResult) -> None:
        total = max(1, len(workflow.steps))
        done = self._completed_steps.get(task_id, 0) + 1
        self._completed_steps[task_id] = done
        self._update(task_id, current_step_id=step.step_id, progress_percent=min(99, int(done * 100 / total)), message=step.message or f"Step {step.step_id} completed.")

    @staticmethod
    def _checkpoint_from_result(result: WorkflowResult, previous: WorkflowCheckpoint | None) -> WorkflowCheckpoint | None:
        if result.status not in {"paused", "failed"}:
            return None
        completed = list(previous.completed_steps if previous else ())
        failed_step_id = ""
        for step in result.steps:
            if step.status == "completed" and step.step_id not in completed:
                completed.append(step.step_id)
            elif step.status == "failed":
                failed_step_id = step.step_id
        return WorkflowCheckpoint(
            completed_steps=tuple(completed),
            outputs=dict(result.outputs),
            failed_step_id=failed_step_id or (previous.failed_step_id if previous else ""),
            attempts=dict(previous.attempts if previous else {}),
            error_code=result.error_code,
            error_message=result.message,
        )

    def _update(self, task_id: str, **changes: Any) -> None:
        record = self.get(task_id)
        updated = replace(record, updated_at=self._now(), **changes)
        self._records[task_id] = updated
        request = self._requests.get(task_id)
        if request is not None:
            self._persist(updated, request)
        self._publish("task.updated", updated)

    def _persist(self, record: TaskRecord, request: TaskCreate) -> None:
        if self._store is not None:
            self._store.upsert_task(record, request)

    def _publish(self, event_type: str, record: TaskRecord) -> None:
        self._events.publish(
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

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
