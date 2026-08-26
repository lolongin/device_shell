"""Progress-aware action watchdog."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .models import ActionAttempt, ActionSpec, DeviceStateSnapshot


@dataclass(frozen=True, slots=True)
class WatchdogIncident:
    code: str
    action_id: str
    message: str
    expected_events: tuple[str, ...] = ()
    idle_seconds: float = 0.0
    elapsed_seconds: float = 0.0


class Watchdog:
    """Checks action deadline, semantic progress, expectations, and device state."""

    def evaluate(
        self,
        action: ActionSpec,
        attempt: ActionAttempt,
        *,
        satisfied_events: set[str],
        device_state: DeviceStateSnapshot,
        now: datetime | None = None,
    ) -> WatchdogIncident | None:
        now = now or datetime.now(timezone.utc)
        started = _parse(attempt.started_at, now)
        elapsed = max(0.0, (now - started).total_seconds())
        expected = {item.event_type for item in action.expectations if item.terminal} - satisfied_events
        if elapsed >= action.timeout_seconds:
            return WatchdogIncident(
                "action_timeout", action.id, "action deadline exceeded", tuple(sorted(expected)), elapsed_seconds=elapsed,
            )
        progress_at = _parse(attempt.last_progress_at or attempt.started_at, now)
        idle = max(0.0, (now - progress_at).total_seconds())
        idle_limits = [item.idle_timeout_seconds for item in action.expectations if item.idle_timeout_seconds > 0]
        if idle_limits and idle >= min(idle_limits):
            return WatchdogIncident(
                "progress_timeout", action.id, "semantic progress stopped", tuple(sorted(expected)), idle_seconds=idle, elapsed_seconds=elapsed,
            )
        if device_state.reachability == "unreachable" and elapsed > 0:
            return WatchdogIncident(
                "device_unreachable", action.id, "device became unreachable", tuple(sorted(expected)), idle_seconds=idle, elapsed_seconds=elapsed,
            )
        return None


def _parse(value: str, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return fallback
