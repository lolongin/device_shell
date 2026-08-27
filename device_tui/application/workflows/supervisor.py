"""Continuous Action supervision for the single-device workflow runtime."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Callable

from .events import Event
from .models import ActionAttempt, ActionResult, ActionSpec, ActionStatus
from .watchdog import Watchdog, WatchdogIncident


@dataclass(frozen=True, slots=True)
class SupervisedActionResult:
    result: ActionResult
    attempt: ActionAttempt
    events: tuple[Event, ...]
    incident: WatchdogIncident | None = None


class ActionSupervisor:
    """Run one Action while enforcing semantic and absolute deadlines.

    Handlers keep ownership of device interactions.  The supervisor only
    observes their structured events and requests cancellation when a policy
    deadline expires.
    """

    def __init__(self, watchdog: Watchdog, *, poll_seconds: float = 0.25) -> None:
        self._watchdog = watchdog
        self._poll_seconds = max(0.01, poll_seconds)

    async def execute(
        self,
        handler: Any,
        action: ActionSpec,
        run: Any,
        attempt: ActionAttempt,
        emit: Callable[[Event], Event],
    ) -> SupervisedActionResult:
        observed: set[str] = set()
        events: list[Event] = []
        active_attempt = attempt

        def supervised_emit(event: Event) -> Event:
            nonlocal active_attempt
            stored = emit(event)
            events.append(stored)
            observed.add(stored.type)
            if stored.progress:
                active_attempt = replace(
                    active_attempt,
                    last_progress_at=stored.observed_at,
                    last_event_type=stored.type,
                )
            elif not active_attempt.last_event_type:
                active_attempt = replace(active_attempt, last_event_type=stored.type)
            return stored

        task = asyncio.create_task(handler.execute(action, run, supervised_emit))
        while not task.done():
            timeout = min(self._poll_seconds, self._seconds_until_watchdog(action, active_attempt, observed))
            done, _ = await asyncio.wait({task}, timeout=max(0.0, timeout))
            if done:
                break
            incident = self._watchdog.evaluate(
                action,
                active_attempt,
                satisfied_events=observed,
                device_state=run.device_state,
            )
            if incident is not None:
                await self._cancel(handler, action, run, task)
                return SupervisedActionResult(
                    ActionResult(
                        ActionStatus.TIMED_OUT,
                        facts={},
                        error={
                            "code": incident.code,
                            "message": incident.message,
                            "class": "timeout",
                            "expected_events": list(incident.expected_events),
                        },
                    ),
                    active_attempt,
                    tuple(events),
                    incident,
                )
        try:
            result = task.result()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            details = getattr(exc, "details", {})
            result = ActionResult(
                ActionStatus.FAILED,
                error={
                    "code": getattr(exc, "code", "action_failed"),
                    "message": str(exc),
                    "class": getattr(exc, "error_class", "unknown"),
                    "details": dict(details) if isinstance(details, dict) else {},
                },
            )
        if not isinstance(result, ActionResult):
            result = ActionResult(
                ActionStatus.FAILED,
                error={
                    "code": "invalid_action_result",
                    "message": "Action handler did not return an ActionResult.",
                    "class": "deterministic",
                },
            )
        return SupervisedActionResult(result, active_attempt, tuple(events))

    @staticmethod
    def _seconds_until_watchdog(
        action: ActionSpec,
        attempt: ActionAttempt,
        satisfied_events: set[str],
    ) -> float:
        now = datetime.now(timezone.utc)
        try:
            started = datetime.fromisoformat(attempt.started_at.replace("Z", "+00:00"))
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            started = now
        elapsed = max(0.0, (now - started).total_seconds())
        remaining = [action.timeout_seconds - elapsed]
        remaining.extend(
            item.timeout_seconds - elapsed
            for item in action.expectations
            if item.terminal and item.event_type not in satisfied_events
        )
        idle_limits = [item.idle_timeout_seconds for item in action.expectations if item.idle_timeout_seconds > 0]
        if idle_limits:
            try:
                progress_at = datetime.fromisoformat((attempt.last_progress_at or attempt.started_at).replace("Z", "+00:00"))
                if progress_at.tzinfo is None:
                    progress_at = progress_at.replace(tzinfo=timezone.utc)
                idle_elapsed = max(0.0, (now - progress_at).total_seconds())
            except (TypeError, ValueError):
                idle_elapsed = 0.0
            remaining.extend(limit - idle_elapsed for limit in idle_limits)
        return max(0.0, min(remaining))

    @staticmethod
    async def _cancel(handler: Any, action: ActionSpec, run: Any, task: asyncio.Task[Any]) -> None:
        cancel = getattr(handler, "cancel", None)
        if callable(cancel):
            try:
                result = cancel(action, run)
                if hasattr(result, "__await__"):
                    await result
            except Exception:
                # Reconciliation, rather than an unverified cancellation,
                # determines the subsequent device state.
                pass
        task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
        except asyncio.CancelledError:
            pass
        except Exception:
            # A handler that cannot be cancelled may still finish in the
            # background.  The Runtime will not advance without Reconcile.
            pass


__all__ = ["ActionSupervisor", "SupervisedActionResult"]
