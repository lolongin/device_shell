"""Execution boundary for staged Activities.

The executor owns lifecycle bookkeeping and postcondition dispatch. Concrete
handlers remain responsible for transport interaction and may emit semantic
progress events while they run.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Callable, Mapping

from .activity import (
    ActivityContext,
    ActivityDefinition,
    ActivityHandler,
    ActivityInvocation,
    ActivityProbe,
    ActivityResult,
    ActivityStatus,
    ActivityVerifier,
    ProgressReporter,
)
from .events import Event
from .models import ActionResult, ActionSpec, ActionStatus


class ActivityExecutionError(RuntimeError):
    """Raised when an Activity cannot be resolved or violates its contract."""


class ActivityExecutor:
    """Run one Activity invocation while emitting durable lifecycle events."""

    def __init__(
        self,
        *,
        definitions: Mapping[str, ActivityDefinition] | None = None,
        handlers: Mapping[str, ActivityHandler] | None = None,
        verifiers: Mapping[str, ActivityVerifier] | None = None,
        probes: Mapping[str, ActivityProbe] | None = None,
    ) -> None:
        self._definitions = dict(definitions or {})
        self._handlers = dict(handlers or {})
        self._verifiers = dict(verifiers or {})
        self._probes = dict(probes or {})

    def register_definition(self, definition: ActivityDefinition) -> None:
        definition.validate()
        key = f"{definition.id}:{definition.version}"
        if key in self._definitions:
            raise ValueError(f"activity definition already registered: {key}")
        self._definitions[key] = definition

    def register_handler(self, handler: ActivityHandler, *, activity_id: str | None = None) -> None:
        key = activity_id or handler.activity_id
        if key in self._handlers:
            raise ValueError(f"activity handler already registered: {key}")
        self._handlers[key] = handler

    def register_verifier(self, verifier: ActivityVerifier, *, verifier_id: str | None = None) -> None:
        key = verifier_id or verifier.verifier_id
        if key in self._verifiers:
            raise ValueError(f"activity verifier already registered: {key}")
        self._verifiers[key] = verifier

    def register_probe(self, probe: ActivityProbe, *, probe_id: str | None = None) -> None:
        key = probe_id or probe.probe_id
        if key in self._probes:
            raise ValueError(f"activity probe already registered: {key}")
        self._probes[key] = probe

    async def execute(
        self,
        invocation: ActivityInvocation,
        context: ActivityContext,
        report: ProgressReporter,
        *,
        version: str = "1",
        _preparation_depth: int = 0,
    ) -> ActivityResult:
        definition = self._definitions.get(f"{invocation.activity_id}:{version}")
        if definition is None:
            raise ActivityExecutionError(
                f"activity definition not found: {invocation.activity_id}:{version}"
            )
        handler = self._handlers.get(invocation.activity_id)
        if handler is None:
            raise ActivityExecutionError(f"activity handler not found: {invocation.activity_id}")

        self._emit(report, "activity.started", invocation, {"activity_id": invocation.activity_id})
        self._emit(report, "activity.preconditions.checking", invocation, {
            "count": len(definition.preconditions),
        })
        precondition_error = await self._check_preconditions(
            definition,
            invocation,
            context,
            report,
            version=version,
            preparation_depth=_preparation_depth,
        )
        if precondition_error is not None:
            self._emit(report, "activity.preconditions.failed", invocation, precondition_error)
            return ActivityResult(
                status=ActivityStatus.FAILED,
                error=precondition_error,
            )
        self._emit(report, "activity.preconditions.checked", invocation, {
            "count": len(definition.preconditions),
        })
        if definition.preparation:
            self._emit(report, "activity.preparation.started", invocation, {
                "activities": list(definition.preparation),
            })
        if definition.exchanges:
            self._emit(report, "activity.interaction.started", invocation, {
                "exchanges": [item.id for item in definition.exchanges],
            })
        if definition.monitor is not None:
            self._emit(report, "activity.monitoring.ready", invocation, {
                "monitor_id": definition.monitor.id,
            })

        try:
            result = await handler.execute(invocation, context, report)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return ActivityResult(
                status=ActivityStatus.FAILED,
                error={
                    "code": getattr(exc, "code", "activity_failed"),
                    "message": str(exc),
                    "class": getattr(exc, "error_class", "unknown"),
                },
            )
        if not isinstance(result, ActivityResult):
            raise ActivityExecutionError("activity handler returned an invalid result")

        if result.status == ActivityStatus.SUCCEEDED and definition.verification is not None:
            verifier = self._verifiers.get(definition.verification.verifier)
            if verifier is None:
                raise ActivityExecutionError(
                    f"activity verifier not found: {definition.verification.verifier}"
                )
            self._emit(report, "activity.verification.started", invocation, {
                "verifier": definition.verification.verifier,
            })
            result = await verifier.verify(definition.verification, result, context)
            if not isinstance(result, ActivityResult):
                raise ActivityExecutionError("activity verifier returned an invalid result")

        terminal_event = {
            ActivityStatus.SUCCEEDED: "activity.succeeded",
            ActivityStatus.FAILED: "activity.failed",
            ActivityStatus.UNKNOWN: "activity.unknown",
            ActivityStatus.CANCELLED: "activity.cancelled",
        }.get(str(result.status))
        if terminal_event:
            self._emit(report, terminal_event, invocation, {
                "operation_id": result.operation_id,
                "error": result.error or {},
            })
        return result

    async def _check_preconditions(
        self,
        definition: ActivityDefinition,
        invocation: ActivityInvocation,
        context: ActivityContext,
        report: ProgressReporter,
        *,
        version: str,
        preparation_depth: int,
    ) -> dict[str, Any] | None:
        for guard in definition.preconditions:
            probe = self._probes.get(guard.probe)
            # Missing probes are allowed for compatibility adapters. They
            # still receive lifecycle events and can perform the check inside
            # their transport implementation.
            if probe is None:
                continue
            try:
                observed = await probe.probe(guard, context)
            except Exception as exc:
                return {
                    "code": "precondition_probe_failed",
                    "guard_id": guard.id,
                    "probe": guard.probe,
                    "message": str(exc),
                    "class": "transient",
                }
            if self._predicate_matches(guard.predicate, observed):
                self._emit(report, "activity.precondition.satisfied", invocation, {
                    "guard_id": guard.id,
                    "probe": guard.probe,
                })
                continue
            if guard.on_failure == "prepare" and guard.preparation_activity:
                if preparation_depth >= 3:
                    return {
                        "code": "precondition_preparation_depth_exceeded",
                        "guard_id": guard.id,
                        "probe": guard.probe,
                    }
                self._emit(report, "activity.preparation.required", invocation, {
                    "guard_id": guard.id,
                    "activity_id": guard.preparation_activity,
                })
                preparation = ActivityInvocation(
                    activity_id=guard.preparation_activity,
                    invocation_id=f"{invocation.invocation_id}:prepare:{guard.id}",
                    workflow_run_id=invocation.workflow_run_id,
                    attempt=1,
                    inputs=dict(invocation.inputs),
                    context=dict(invocation.context),
                )
                prepared = await self.execute(
                    preparation,
                    ActivityContext(workflow_run=context.workflow_run, invocation=preparation),
                    report,
                    version=version,
                    _preparation_depth=preparation_depth + 1,
                )
                if prepared.status != ActivityStatus.SUCCEEDED:
                    return {
                        "code": "precondition_preparation_failed",
                        "guard_id": guard.id,
                        "preparation_activity": guard.preparation_activity,
                        "cause": prepared.error or {},
                    }
                observed = await probe.probe(guard, context)
                if self._predicate_matches(guard.predicate, observed):
                    continue
            return {
                "code": "precondition_failed" if guard.on_failure != "decision" else "precondition_decision_required",
                "guard_id": guard.id,
                "probe": guard.probe,
                "observed": observed,
                "predicate": dict(guard.predicate),
            }
        return None

    @staticmethod
    def _predicate_matches(predicate: Mapping[str, Any], observed: Any) -> bool:
        if not predicate:
            return bool(observed)
        if isinstance(observed, Mapping):
            value = observed.get("value", observed.get("status", observed))
        else:
            value = observed
        if "equals" in predicate and value != predicate["equals"]:
            return False
        if "in" in predicate and value not in predicate["in"]:
            return False
        if "exists" in predicate and bool(value is not None) != bool(predicate["exists"]):
            return False
        for key, expected in predicate.items():
            if key in {"equals", "in", "exists"}:
                continue
            if not isinstance(observed, Mapping) or observed.get(key) != expected:
                return False
        return True

    async def cancel(self, invocation: ActivityInvocation, context: ActivityContext, *, version: str = "1") -> None:
        """Forward cancellation to the concrete handler when supported."""
        del version
        handler = self._handlers.get(invocation.activity_id)
        if handler is None:
            return
        cancel = getattr(handler, "cancel", None)
        if callable(cancel):
            await cancel(invocation, context)

    @staticmethod
    def _emit(
        report: ProgressReporter,
        event_type: str,
        invocation: ActivityInvocation,
        payload: dict[str, Any],
    ) -> Event:
        event = Event(
            type=event_type,
            run_id=invocation.workflow_run_id,
            action_id=invocation.activity_id,
            source="activity.executor",
            payload=payload,
        )
        reported = report(event)
        if inspect.isawaitable(reported):
            raise ActivityExecutionError("activity progress reporter must be synchronous")
        return reported


class ActivityActionHandler:
    """Compatibility adapter from legacy ``ActionHandler`` to Activities.

    This lets the existing WorkflowRuntime drive new Activity handlers while
    the TaskManager and older plugins are migrated incrementally.
    """

    def __init__(self, executor: ActivityExecutor, activity_id: str, *, version: str = "1") -> None:
        self._executor = executor
        self.operation = activity_id
        self.activity_id = activity_id
        self._version = version
        self._active: dict[str, tuple[ActivityInvocation, ActivityContext]] = {}

    async def execute(self, action: ActionSpec, run: Any, emit: ProgressReporter) -> ActionResult:
        attempts = [item for item in getattr(run, "attempts", ()) if item.action_id == action.id]
        attempt = max((int(item.attempt) for item in attempts), default=1)
        invocation = ActivityInvocation(
            activity_id=self.activity_id,
            invocation_id=f"{run.id}:{action.id}:{attempt}",
            workflow_run_id=run.id,
            attempt=attempt,
            inputs={
                **dict(action.params),
                # Preserve the legacy Action deadline as an Activity input so
                # adapters can apply it to long-running monitors.
                "activity_timeout_seconds": float(action.timeout_seconds),
            },
            context={
                **dict(getattr(run, "context", {}) or {}),
                # Device-control adapters use task_id as the fencing owner.
                # Older Workflow callers did not put it in context, but the
                # WorkflowRun id is the stable owner identity at this boundary.
                "task_id": str(getattr(run, "id", "") or ""),
            },
        )
        context = ActivityContext(workflow_run=run, invocation=invocation)
        self._active[invocation.invocation_id] = (invocation, context)
        try:
            result = await self._executor.execute(invocation, context, emit, version=self._version)
        finally:
            self._active.pop(invocation.invocation_id, None)
        facts = dict(result.outputs)
        if result.operation_id:
            facts["operation_id"] = result.operation_id
        if result.evidence:
            facts["evidence"] = list(result.evidence)
        status = {
            ActivityStatus.SUCCEEDED: ActionStatus.SUCCEEDED,
            ActivityStatus.FAILED: ActionStatus.FAILED,
            ActivityStatus.UNKNOWN: ActionStatus.UNKNOWN,
            ActivityStatus.CANCELLED: ActionStatus.CANCELLED,
        }.get(str(result.status), ActionStatus.FAILED)
        return ActionResult(status=status, facts=facts, error=result.error)

    async def cancel(self, action: ActionSpec, run: Any) -> None:
        attempts = [item for item in getattr(run, "attempts", ()) if item.action_id == action.id]
        attempt = max((int(item.attempt) for item in attempts), default=1)
        invocation_id = f"{run.id}:{action.id}:{attempt}"
        active = self._active.get(invocation_id)
        if active is not None:
            await self._executor.cancel(active[0], active[1], version=self._version)


__all__ = ["ActivityActionHandler", "ActivityExecutionError", "ActivityExecutor"]
