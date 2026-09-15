"""Async terminal event consumers used by workflow activities."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol

from .matcher import TerminalMatcher


class EventHub(Protocol):
    def subscribe(self, session_id: str, *, after_sequence: int = 0) -> tuple[asyncio.Queue[Any], list[Any]]: ...
    def unsubscribe(self, session_id: str, queue: asyncio.Queue[Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class MatchResult:
    status: str
    output: str = ""
    sequence: int = 0
    reason: str = ""


async def wait_for_output(
    hub: EventHub,
    session_id: str,
    *,
    mode: str = "contains",
    pattern: str,
    case_sensitive: bool = False,
    timeout_seconds: float = 30.0,
    cancel_event: asyncio.Event | None = None,
    after_sequence: int = 0,
) -> MatchResult:
    """Wait for a match while consuming only output after the wait started."""
    matcher = TerminalMatcher(mode, pattern, case_sensitive=case_sensitive)
    timeout = max(0.01, float(timeout_seconds))
    queue, replay = hub.subscribe(session_id, after_sequence=after_sequence)
    output_parts: list[str] = []
    queue_task: asyncio.Task[Any] | None = None
    cancel_task: asyncio.Task[bool] | None = None

    async def process(event: TerminalEvent) -> MatchResult | None:
        if event.sequence and event.sequence <= after_sequence:
            return None
        if event.type == "terminal.output" and event.data:
            output_parts.append(event.data)
            if matcher.feed(event.data):
                return MatchResult("matched", "".join(output_parts), event.sequence)
        if event.type == "terminal.status" and event.status.lower() in {"disconnected", "failed", "closed"}:
            return MatchResult("disconnected", "".join(output_parts), event.sequence, event.status.lower())
        if event.type == "terminal.error":
            return MatchResult("error", "".join(output_parts), event.sequence, event.data)
        return None

    try:
        for event in replay:
            result = await process(event)
            if result is not None:
                return result

        deadline = monotonic() + timeout
        while True:
            remaining = deadline - monotonic()
            if remaining <= 0:
                return MatchResult("timeout", "".join(output_parts), reason="timeout")
            queue_task = asyncio.create_task(queue.get())
            waiters: set[asyncio.Task[Any]] = {queue_task}
            if cancel_event is not None:
                cancel_task = asyncio.create_task(cancel_event.wait())
                waiters.add(cancel_task)
            done, _ = await asyncio.wait(waiters, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
            if not done:
                return MatchResult("timeout", "".join(output_parts), reason="timeout")
            if cancel_task is not None and cancel_task in done and cancel_task.result():
                return MatchResult("cancelled", "".join(output_parts), reason="cancelled")
            if queue_task in done:
                result = await process(queue_task.result())
                if result is not None:
                    return result
            for pending in waiters - done:
                pending.cancel()
            await asyncio.gather(*(waiters - done), return_exceptions=True)
    finally:
        for task in (queue_task, cancel_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (queue_task, cancel_task) if task is not None), return_exceptions=True)
        hub.unsubscribe(session_id, queue)
