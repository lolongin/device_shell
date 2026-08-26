"""Small event-driven workflow runtime suitable for a single-device worker."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Protocol
from uuid import uuid4

from .decisions import DecisionEngine, DecisionSubmission
from .events import Event, MemoryWorkflowEventStore, WorkflowEventStore
from .models import (
    ActionAttempt,
    ActionResult,
    ActionStatus,
    DecisionPoint,
    DeviceStateSnapshot,
    ProgressSnapshot,
    ReconcileClassification,
    RunStatus,
    WorkflowDefinition,
    WorkflowRun,
)
from .plugins import ActionHandler, ActionRegistry, ReconcileRegistry
from .watchdog import Watchdog


class WorkflowRunStore(Protocol):
    def save(self, run: WorkflowRun) -> WorkflowRun: ...
    def get(self, run_id: str) -> WorkflowRun: ...


class WorkflowLeaseService(Protocol):
    def acquire(self, device_id: str, owner_id: str) -> Any: ...
    def release(self, device_id: str, token: str) -> bool: ...


class MemoryWorkflowRunStore:
    def __init__(self) -> None:
        self._runs: dict[str, WorkflowRun] = {}

    def save(self, run: WorkflowRun) -> WorkflowRun:
        self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> WorkflowRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise KeyError(f"workflow run not found: {run_id}") from exc


class WorkflowRuntime:
    def __init__(
        self,
        *,
        actions: ActionRegistry | None = None,
        reconciliations: ReconcileRegistry | None = None,
        runs: WorkflowRunStore | None = None,
        events: WorkflowEventStore | None = None,
        watchdog: Watchdog | None = None,
        decisions: DecisionEngine | None = None,
        leases: WorkflowLeaseService | None = None,
    ) -> None:
        self.actions = actions or ActionRegistry()
        self.reconciliations = reconciliations or ReconcileRegistry()
        self.runs = runs or MemoryWorkflowRunStore()
        self.events = events or MemoryWorkflowEventStore()
        self.watchdog = watchdog or Watchdog()
        self.decisions = decisions or DecisionEngine()
        self.leases = leases
        self._lease_tokens: dict[str, tuple[str, str]] = {}
        self._definitions: dict[str, WorkflowDefinition] = {}

    def register_definition(self, definition: WorkflowDefinition) -> None:
        definition.validate()
        self._definitions[f"{definition.id}:{definition.version}"] = definition

    def start(self, definition: WorkflowDefinition, *, device_id: str, context: dict[str, Any] | None = None, run_id: str | None = None) -> WorkflowRun:
        definition.validate()
        self.register_definition(definition)
        resolved_run_id = run_id or str(uuid4())
        run_context = dict(context or {})
        if self.leases is not None:
            lease = self.leases.acquire(device_id, resolved_run_id)
            token = str(getattr(lease, "token", ""))
            self._lease_tokens[resolved_run_id] = (device_id, token)
        run = WorkflowRun(
            id=resolved_run_id,
            workflow_id=definition.id,
            workflow_version=definition.version,
            device_id=device_id,
            status=RunStatus.RUNNING,
            current_state=definition.start_state,
            context=run_context,
            progress=ProgressSnapshot(stage=definition.start_state),
        )
        self.runs.save(run)
        self._emit(run, "workflow.started", payload={"state": run.current_state})
        return run

    async def tick(self, run_id: str) -> WorkflowRun:
        run = self.runs.get(run_id)
        if run.status not in {RunStatus.RUNNING, RunStatus.RECOVERING}:
            return run
        definition = self._definitions.get(f"{run.workflow_id}:{run.workflow_version}")
        if definition is None:
            raise KeyError(f"workflow definition not registered: {run.workflow_id}:{run.workflow_version}")
        state = next(item for item in definition.states if item.id == run.current_state)
        if state.terminal:
            return self._save(replace(run, status=RunStatus.SUCCEEDED, revision=run.revision + 1))
        if state.action is None and state.decision_options:
            return self._create_decision(run, state, "decision_required", None)
        if state.action is None:
            return self._advance(run, state.next_state or "", trigger="state.completed")
        attempt_no = sum(1 for item in run.attempts if item.action_id == state.action.id) + 1
        attempt = ActionAttempt(
            id=str(uuid4()), action_id=state.action.id, attempt=attempt_no,
            status=ActionStatus.RUNNING, started_at=_now(), last_progress_at=_now(),
        )
        run = self._save(replace(run, attempts=run.attempts + (attempt,), revision=run.revision + 1))
        handler: ActionHandler = self.actions.resolve(state.action.operation)

        emitted: list[Event] = []

        def emit(event: Event) -> Event:
            return self._append_action_event(event, run.id, state.action.id, emitted)

        try:
            result = await asyncio.wait_for(
                handler.execute(state.action, self._execution_run(run), emit),
                timeout=state.action.timeout_seconds,
            )
        except asyncio.TimeoutError:
            result = ActionResult(
                status=ActionStatus.TIMED_OUT,
                error={
                    "code": "action_timeout",
                    "message": f"Action {state.action.id} exceeded its timeout.",
                    "class": "timeout",
                },
            )
        except Exception as exc:
            result = ActionResult(
                status=ActionStatus.FAILED,
                error={"code": getattr(exc, "code", "action_failed"), "message": str(exc), "class": getattr(exc, "error_class", "unknown")},
            )
        for event in result.events:
            emit(event if isinstance(event, Event) else Event(type=str(event), run_id=run.id, action_id=state.action.id))
        observed = {event.type for event in emitted}
        expected = {item.event_type for item in state.action.expectations if item.terminal}
        run = self._with_action_facts(run, state.action.id, result.facts)
        last_event = emitted[-1] if emitted else None
        updated_attempt = replace(
            attempt,
            last_event_type=last_event.type if last_event is not None else attempt.last_event_type,
            last_progress_at=(last_event.observed_at if last_event is not None and last_event.progress else attempt.last_progress_at),
        )
        if result.status == ActionStatus.SUCCEEDED and expected <= observed:
            last = replace(updated_attempt, status=ActionStatus.SUCCEEDED, result=dict(result.facts))
            run = self._replace_attempt(run, last)
            return self._advance(run, self._next_state(state, observed), trigger=next(iter(observed), "state.completed"))
        incident = self.watchdog.evaluate(
            state.action,
            updated_attempt,
            satisfied_events=observed,
            device_state=run.device_state,
        )
        reason = (result.error or {}).get("code") or (incident.code if incident else "expectation_not_met")
        run = self._replace_attempt(run, replace(updated_attempt, status=ActionStatus.UNKNOWN, result=dict(result.facts), error=result.error))
        if state.action.reconcile.provider:
            run = self._save(replace(run, status=RunStatus.WAITING_RECONCILE, revision=run.revision + 1))
            provider = self.reconciliations.resolve(state.action.reconcile.provider)
            outcome = await provider.reconcile(state.action, self._execution_run(run), str(reason), emit)
            return self._apply_reconcile(run, state.id, outcome.classification, state.action.reconcile.on_classification, outcome.facts, outcome.evidence)
        return self._create_decision(run, state, str(reason), result.error)

    async def run_until_blocked(
        self,
        run_id: str,
        *,
        on_update: Callable[[WorkflowRun], None] | None = None,
    ) -> WorkflowRun:
        """Drive a run until it reaches a terminal or externally resumable state.

        The runtime owns the tick loop so compatibility surfaces only project
        Framework state; they do not implement a second execution scheduler.
        """
        while True:
            run = self.runs.get(run_id)
            if on_update is not None:
                on_update(run)
            if run.status not in {RunStatus.RUNNING, RunStatus.RECOVERING}:
                return run
            run = await self.tick(run_id)
            if on_update is not None:
                on_update(run)
            if run.status not in {RunStatus.RUNNING, RunStatus.RECOVERING}:
                return run
            await asyncio.sleep(0)

    async def reconcile(self, run_id: str, reason: str = "watchdog") -> WorkflowRun:
        run = self.runs.get(run_id)
        definition = self._definitions[f"{run.workflow_id}:{run.workflow_version}"]
        state = next(item for item in definition.states if item.id == run.current_state)
        if state.action is None or not state.action.reconcile.provider:
            return self._create_decision(run, state, reason, None)
        provider = self.reconciliations.resolve(state.action.reconcile.provider)
        emitted: list[Event] = []

        def emit(event: Event) -> Event:
            return self._append_action_event(event, run.id, state.action.id, emitted)

        outcome = await provider.reconcile(state.action, self._execution_run(run), reason, emit)
        return self._apply_reconcile(run, state.id, outcome.classification, state.action.reconcile.on_classification, outcome.facts, outcome.evidence)

    def pause(self, run_id: str) -> WorkflowRun:
        run = self.runs.get(run_id)
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run
        return self._save(replace(run, status=RunStatus.PAUSED, revision=run.revision + 1))

    def resume(self, run_id: str, *, context: dict[str, Any] | None = None) -> WorkflowRun:
        run = self.runs.get(run_id)
        if run.status not in {RunStatus.PAUSED, RunStatus.WAITING_DECISION}:
            return run
        return self._save(replace(
            run,
            status=RunStatus.RUNNING,
            context={**run.context, **dict(context or {})},
            decision_point=None,
            revision=run.revision + 1,
        ))

    def cancel(self, run_id: str) -> WorkflowRun:
        run = self.runs.get(run_id)
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run
        return self._save(replace(run, status=RunStatus.CANCELLED, decision_point=None, revision=run.revision + 1))

    def apply_decision(self, run_id: str, submission: DecisionSubmission) -> WorkflowRun:
        run = self.runs.get(run_id)
        option = self.decisions.validate(run, submission)
        target = option.next_state
        self._emit(run, "decision.applied", payload={"option_id": option.id, "actor_type": submission.actor_type})
        if option.kind in {"abort", "cancel"}:
            return self._save(replace(run, status=RunStatus.CANCELLED, decision_point=None, revision=run.revision + 1))
        if option.kind == "retry":
            return self._save(replace(run, status=RunStatus.RUNNING, decision_point=None, revision=run.revision + 1))
        if target and any(state.id == target for state in self._definitions[f"{run.workflow_id}:{run.workflow_version}"].states):
            return self._advance(replace(run, decision_point=None), target, trigger="decision.applied")
        return self._save(replace(run, status=RunStatus.RUNNING, decision_point=None, revision=run.revision + 1))

    def _apply_reconcile(self, run: WorkflowRun, state_id: str, classification: str, mapping: dict[str, str], facts: dict[str, Any], evidence: tuple[dict[str, Any], ...]) -> WorkflowRun:
        outcome = str(classification)
        directive = mapping.get(outcome, "decision")
        run = self._save(replace(run, context={**run.context, f"reconcile.{state_id}": {"classification": outcome, "facts": facts, "evidence": list(evidence)}}, status=RunStatus.RECOVERING, revision=run.revision + 1))
        if directive == "continue":
            definition = self._definitions[f"{run.workflow_id}:{run.workflow_version}"]
            state = next(item for item in definition.states if item.id == state_id)
            return self._advance(run, self._next_state(state, set()), trigger="reconcile.success")
        if directive == "retry":
            definition = self._definitions[f"{run.workflow_id}:{run.workflow_version}"]
            state = next(item for item in definition.states if item.id == state_id)
            attempts = sum(1 for item in run.attempts if item.action_id == state_id)
            if state.action is not None and attempts < state.action.retry_policy.max_attempts:
                return self._save(replace(run, status=RunStatus.RUNNING, revision=run.revision + 1))
            return self._create_decision(run, state, f"retry.exhausted.{outcome}", {"evidence": list(evidence)})
        definition = self._definitions[f"{run.workflow_id}:{run.workflow_version}"]
        state = next(item for item in definition.states if item.id == state_id)
        return self._create_decision(run, state, f"reconcile.{outcome}", {"evidence": list(evidence)})

    def _create_decision(self, run: WorkflowRun, state: Any, reason: str, error: dict[str, Any] | None) -> WorkflowRun:
        if not state.decision_options:
            return self._save(replace(run, status=RunStatus.FAILED, error=error or {"code": reason}, revision=run.revision + 1))
        point = DecisionPoint(
            id=str(uuid4()), run_id=run.id, revision=run.revision + 1,
            reason_code=reason, summary=f"Workflow state {state.id} requires a constrained decision.",
            options=state.decision_options, evidence=tuple([error] if error else []),
        )
        return self._save(replace(run, status=RunStatus.WAITING_DECISION, decision_point=point, revision=run.revision + 1))

    def _advance(self, run: WorkflowRun, next_state: str, *, trigger: str) -> WorkflowRun:
        definition = self._definitions[f"{run.workflow_id}:{run.workflow_version}"]
        if not next_state:
            return self._save(replace(run, status=RunStatus.SUCCEEDED, current_state="", revision=run.revision + 1))
        state = next(item for item in definition.states if item.id == next_state)
        return self._save(replace(run, status=RunStatus.SUCCEEDED if state.terminal else RunStatus.RUNNING, current_state=next_state, progress=replace(run.progress, stage=next_state, last_event_type=trigger), decision_point=None, revision=run.revision + 1))

    @staticmethod
    def _next_state(state: Any, observed: set[str]) -> str:
        for event_type, target in state.transitions.items():
            if event_type in observed:
                return target
        return state.next_state

    def _replace_attempt(self, run: WorkflowRun, attempt: ActionAttempt) -> WorkflowRun:
        return self._save(replace(run, attempts=tuple(attempt if item.id == attempt.id else item for item in run.attempts), revision=run.revision + 1))

    def _emit(self, run: WorkflowRun, event_type: str, *, payload: dict[str, Any]) -> Event:
        return self.events.append(Event(type=event_type, run_id=run.id, payload=payload))

    def _append_action_event(
        self,
        event: Event,
        run_id: str,
        action_id: str,
        emitted: list[Event],
    ) -> Event:
        if event.run_id != run_id or event.action_id != action_id:
            event = replace(event, run_id=run_id, action_id=action_id)
        stored = self.events.append(event)
        emitted.append(stored)
        return stored

    @staticmethod
    def _with_action_facts(run: WorkflowRun, action_id: str, facts: dict[str, Any]) -> WorkflowRun:
        if not facts:
            return run
        return replace(
            run,
            context={
                **run.context,
                f"action.{action_id}.facts": dict(facts),
            },
        )

    def _save(self, run: WorkflowRun) -> WorkflowRun:
        saved = self.runs.save(run)
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            lease = self._lease_tokens.pop(run.id, None)
            if lease is not None and self.leases is not None:
                self.leases.release(lease[0], lease[1])
        return saved

    def _execution_run(self, run: WorkflowRun) -> WorkflowRun:
        """Expose the fencing token only to backend handlers, never to run state."""
        if self.leases is None:
            return run
        lease = self._lease_tokens.get(run.id)
        if lease is None:
            acquired = self.leases.acquire(run.device_id, run.id)
            token = str(getattr(acquired, "token", ""))
            lease = (run.device_id, token)
            self._lease_tokens[run.id] = lease
        return replace(run, context={**run.context, "lease_token": lease[1]})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
