"""Replayable application lifecycle events."""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass(frozen=True, slots=True)
class ApplicationEvent:
    type: str
    sequence: int
    resource_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    version: int = 1

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "version": self.version,
            "type": self.type,
            "sequence": self.sequence,
            "data": dict(self.data),
        }
        if self.resource_id:
            payload["resourceId"] = self.resource_id
        return payload


class EventBus:
    """Small in-process bus used by realtime transport adapters."""

    def __init__(self, replay_limit: int = 1_000) -> None:
        self._sequence = 0
        self._replay: deque[ApplicationEvent] = deque(maxlen=replay_limit)
        self._subscribers: set[asyncio.Queue[ApplicationEvent]] = set()
        self._lock = Lock()

    def publish(
        self,
        event_type: str,
        *,
        resource_id: str = "",
        data: dict[str, Any] | None = None,
    ) -> ApplicationEvent:
        with self._lock:
            self._sequence += 1
            event = ApplicationEvent(
                type=event_type,
                sequence=self._sequence,
                resource_id=resource_id,
                data=dict(data or {}),
            )
            self._replay.append(event)
            subscribers = tuple(self._subscribers)

        stale: list[asyncio.Queue[ApplicationEvent]] = []
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                stale.append(queue)
        if stale:
            with self._lock:
                for queue in stale:
                    self._subscribers.discard(queue)
        return event

    def subscribe(
        self,
        *,
        after_sequence: int = 0,
    ) -> tuple[asyncio.Queue[ApplicationEvent], list[ApplicationEvent]]:
        queue: asyncio.Queue[ApplicationEvent] = asyncio.Queue(maxsize=1_000)
        with self._lock:
            self._subscribers.add(queue)
            replay = [event for event in self._replay if event.sequence > after_sequence]
        return queue, replay

    def unsubscribe(self, queue: asyncio.Queue[ApplicationEvent]) -> None:
        with self._lock:
            self._subscribers.discard(queue)
