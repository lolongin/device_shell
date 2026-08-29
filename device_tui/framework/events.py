"""Append-only workflow events and replay storage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class Event:
    type: str
    run_id: str
    action_id: str = ""
    sequence: int = 0
    event_id: str = field(default_factory=lambda: str(uuid4()))
    source: str = "engine"
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str = ""
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    progress: bool = False
    evidence_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "run_id": self.run_id,
            "action_id": self.action_id,
            "sequence": self.sequence,
            "source": self.source,
            "payload": dict(self.payload),
            "correlation_id": self.correlation_id,
            "observed_at": self.observed_at,
            "progress": self.progress,
            "evidence_ref": self.evidence_ref,
        }


class WorkflowEventStore(Protocol):
    def append(self, event: Event) -> Event: ...
    def list(self, run_id: str, *, after_sequence: int = 0) -> list[Event]: ...


class MemoryWorkflowEventStore:
    def __init__(self) -> None:
        self._events: dict[str, list[Event]] = {}
        self._ids: set[str] = set()
        self._lock = RLock()

    def append(self, event: Event) -> Event:
        with self._lock:
            if event.event_id in self._ids:
                return next(item for item in self._events.get(event.run_id, ()) if item.event_id == event.event_id)
            items = self._events.setdefault(event.run_id, [])
            stored = Event(
                type=event.type,
                run_id=event.run_id,
                action_id=event.action_id,
                sequence=len(items) + 1,
                event_id=event.event_id,
                source=event.source,
                payload=dict(event.payload),
                correlation_id=event.correlation_id,
                observed_at=event.observed_at,
                progress=event.progress,
                evidence_ref=event.evidence_ref,
            )
            items.append(stored)
            self._ids.add(stored.event_id)
            return stored

    def list(self, run_id: str, *, after_sequence: int = 0) -> list[Event]:
        with self._lock:
            return [item for item in self._events.get(run_id, ()) if item.sequence > after_sequence]
