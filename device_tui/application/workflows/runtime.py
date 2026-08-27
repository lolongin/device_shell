"""Small event-driven workflow runtime suitable for a single-device worker."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
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
from .supervisor import ActionSupervisor
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
        supervisor: ActionSupervisor | None = None,
        recovery_poll_seconds: float = 5.0,
        decisions: DecisionEngine | None = None,
        leases: WorkflowLeaseService | None = None,
    ) -> None:
        self.actions = actions or ActionRegistry()
        self.reconciliations = reconciliations or ReconcileRegistry()
        self.runs = runs or MemoryWorkflowRunStore()
        self.events = events or MemoryWorkflowEventStore()
        self.watchdog = watchdog or Watchdog()
        self.supervisor = supervisor or ActionSupervisor(self.watchdog)
        self.recovery_poll_seconds = max(0.01, recovery_poll_seconds)
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
        if run.status == RunStatus.RECOVERING:
            return await self._recover(run, state)
        if state.terminal:
            return self._save(replace(run, status=RunStatus.SUCCEEDED, revision=run.revision + 1))
        if state.action is None and state.decision_options:
            return self._create_decision(run, state, "decision_required", None)
        if state.action is None:
            return self._advance(run, state.next_state or "", trigger="state.completed")
        attempt_no = sum(1 for item in run.attempts if item.action_id == state.action.id) + 1
        attempt = ActionAttempt(
            id=str(uuid4()), action_id=state.action.id, attempt=attempt_no,
            status=ActionStatus.RUNNING, started_at=_now(),
            deadline_at=(_utcnow() + timedelta(seconds=state.action.timeout_seconds)).isoformat(),
            last_progress_at=_now(),
        )
        run = self._save(replace(run, attempts=run.attempts + (attempt,), revision=run.revision + 1))
        handler: ActionHandler = self.actions.resolve(state.action.operation)

        emitted: list[Event] = []

        def emit(event: Event) -> Event:
            return self._append_action_event(event, run.id, state.action.id, emitted)

        supervised = await self.supervisor.execute(
            handler,
            state.action,
            self._execution_run(run),
            attempt,
            emit,
        )
        result = supervised.result
        attempt = supervised.attempt
        for event in result.events:
            emit(event if isinstance(event, Event) else Event(type=str(event), run_id=run.id, action_id=state.action.id))
        observed = {event.type for event in emitted}
        expected = {item.event_type for item in state.action.expectations if item.terminal}
        last_event = emitted[-1] if emitted else None
        # Event emission can checkpoint progress while a handler is running.
        # Reload that checkpoint before applying its final outcome.
        run = self.runs.get(run.id)
        run = self._save(self._with_action_facts(run, state.action.id, result.facts))
        persisted_attempt = next((item for item in run.attempts if item.id == attempt.id), attempt)
        updated_attempt = replace(
            persisted_attempt,
            last_event_type=last_event.type if last_event is not None else attempt.last_event_type,
            last_progress_at=(last_event.observed_at if last_event is not None and last_event.progress else persisted_attempt.last_progress_at),
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
            if run.status == RunStatus.RECOVERING:
                recovery = run.context.get("framework.recovery")
                retry_at = recovery.get("retry_at") if isinstance(recovery, dict) else ""
                if retry_at:
                    delay = max(0.0, (_parse_time(str(retry_at)) - _utcnow()).total_seconds())
                    if delay:
                        await asyncio.sleep(min(delay, self.recovery_poll_seconds))
                        continue
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

    def mark_interrupted(self, run_id: str, *, reason: str = "process_restart") -> WorkflowRun:
        """Durably fence an in-flight run until its current Action is reconciled."""
        run = self.runs.get(run_id)
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED, RunStatus.WAITING_DECISION}:
            return run
        self._emit(run, "workflow.interrupted", payload={"reason": reason, "state": run.current_state})
        return self._save(replace(
            run,
            status=RunStatus.PAUSED,
            context={**run.context, "framework.recovery": {"required": True, "reason": reason, "observed_at": _now()}},
            revision=run.revision + 1,
        ))

    def pause(self, run_id: str) -> WorkflowRun:
        run = self.runs.get(run_id)
        if run.status in {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}:
            return run
        return self._save(replace(
            run,
            status=RunStatus.PAUSED,
            # Cancellation is cooperative at the transport boundary.  A
            # later resume therefore treats the last Action as uncertain.
            context={**run.context, "framework.recovery": {"required": True, "reason": "paused", "observed_at": _now()}},
            revision=run.revision + 1,
        ))

    def resume(self, run_id: str, *, context: dict[str, Any] | None = None) -> WorkflowRun:
        run = self.runs.get(run_id)
        if run.status not in {RunStatus.PAUSED, RunStatus.WAITING_DECISION, RunStatus.RECOVERING}:
            return run
        recovery = run.context.get("framework.recovery")
        requires_reconcile = isinstance(recovery, dict) and bool(recovery.get("required"))
        return self._save(replace(
            run,
            status=RunStatus.RECOVERING if requires_reconcile else RunStatus.RUNNING,
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
        if option.kind == "reconnect":
            # Reconnect is a constrained framework directive, not a bare
            # retry. A compatible Action consumes it at the device boundary.
            return self._save(replace(
                run,
                status=RunStatus.RUNNING,
                decision_point=None,
                context={
                    **run.context,
                    "framework.reconnect": {
                        "state": run.current_state,
                        "requested_at": _now(),
                    },
                },
                revision=run.revision + 1,
            ))
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

    async def _recover(self, run: WorkflowRun, state: Any) -> WorkflowRun:
        """Resume only after observing the real device state for the last Action."""
        recovery = run.context.get("framework.recovery")
        if not isinstance(recovery, dict) or not recovery.get("required"):
            return self._save(replace(run, status=RunStatus.RUNNING, revision=run.revision + 1))
        retry_at = str(recovery.get("retry_at") or "")
        if retry_at and _parse_time(retry_at) > _utcnow():
            return run
        if state.action is None or not state.action.reconcile.provider:
            return self._create_decision(run, state, "recovery.reconcile_unavailable", None)
        emitted: list[Event] = []

        def emit(event: Event) -> Event:
            return self._append_action_event(event, run.id, state.action.id, emitted)

        self._emit(run, "workflow.recovery.reconcile_started", payload={"state": state.id, "reason": recovery.get("reason", "restart")})
        outcome = await self.reconciliations.resolve(state.action.reconcile.provider).reconcile(
            state.action,
            self._execution_run(run),
            str(recovery.get("reason") or "restart"),
            emit,
        )
        classification = str(outcome.classification)
        evidence = tuple(outcome.evidence)
        context = {
            **run.context,
            f"reconcile.{state.id}": {"classification": classification, "facts": outcome.facts, "evidence": list(evidence)},
        }
        if classification == ReconcileClassification.SUCCESS.value:
            recovered = self._save(replace(run, context={**context, "framework.recovery": {"required": False}}, revision=run.revision + 1))
            self._emit(recovered, "workflow.recovery.confirmed_success", payload={"state": state.id})
            return self._advance(recovered, self._next_state(state, set()), trigger="recovery.confirmed_success")
        if classification == ReconcileClassification.NOT_STARTED.value:
            recovered = self._save(replace(run, context={**context, "framework.recovery": {"required": False}}, status=RunStatus.RUNNING, revision=run.revision + 1))
            self._emit(recovered, "workflow.recovery.confirmed_not_started", payload={"state": state.id})
            return recovered
        if classification == ReconcileClassification.IN_PROGRESS.value:
            next_probe = (_utcnow() + timedelta(seconds=self.recovery_poll_seconds)).isoformat()
            recovered = self._save(replace(
                run,
                context={**context, "framework.recovery": {"required": True, "reason": recovery.get("reason", "restart"), "retry_at": next_probe}},
                status=RunStatus.RECOVERING,
                revision=run.revision + 1,
            ))
            self._emit(recovered, "workflow.recovery.in_progress", payload={"state": state.id, "retry_at": next_probe})
            return recovered
        return self._create_decision(
            self._save(replace(run, context=context, revision=run.revision + 1)),
            state,
            f"recovery.{classification}",
            {"evidence": list(evidence)},
        )

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
        if stored.progress:
            run = self.runs.get(run_id)
            active_attempt = next((item for item in reversed(run.attempts) if item.action_id == action_id and str(item.status) == ActionStatus.RUNNING.value), None)
            if active_attempt is not None:
                progressed = replace(active_attempt, last_progress_at=stored.observed_at, last_event_type=stored.type)
                self._replace_attempt(run, progressed)
                run = self.runs.get(run_id)
                self._save(replace(
                    run,
                    progress=replace(run.progress, last_event_type=stored.type, last_progress_at=stored.observed_at),
                    revision=run.revision + 1,
                ))
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
    return _utcnow().isoformat()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return _utcnow()
