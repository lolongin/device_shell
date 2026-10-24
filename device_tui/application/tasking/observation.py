"""Read-only task observation and bounded, cancellation-friendly fleet waits."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
from typing import Any, Protocol

from .models import TaskRecord
from .protocol import DecisionContext


class TaskReader(Protocol):
    def get(self, task_id: str) -> TaskRecord: ...

    def get_decision(self, task_id: str) -> DecisionContext | None: ...


class TaskObserver:
    MAX_TASKS = 32
    MAX_WAIT_SECONDS = 20
    TERMINAL = frozenset({"completed", "success", "failed", "cancelled"})
    ATTENTION = frozenset({"waiting_for_decision", "waiting_for_user", "paused", "failed"})

    def __init__(self, tasks: TaskReader) -> None:
        self._tasks = tasks

    def observe(self, task_id: str) -> dict[str, Any]:
        task = self._tasks.get(task_id).to_dict()
        context = self._tasks.get_decision(task_id)
        decision = context.to_dict() if context is not None else None
        status = str(task["status"])
        state = {"task": task, "decision": decision}
        cursor = hashlib.sha256(json.dumps(
            state, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        next_action: dict[str, Any] = {"kind": "wait", "tool": "task.wait"}
        if status in {"completed", "success", "cancelled"}:
            next_action = {"kind": "complete" if status != "cancelled" else "stopped"}
        elif status == "failed":
            next_action = {"kind": "inspect_failure", "tool": "task.get"}
        elif status == "paused":
            next_action = {"kind": "resume", "tool": "task.resume"}
        elif status in {"waiting_for_user", "waiting_for_decision"}:
            if status == "waiting_for_decision" and decision and "agent" in decision["decision_modes"]:
                next_action = {
                    "kind": "choose_action", "tool": "decision.apply",
                    "expected_revision": decision["checkpoint_revision"],
                    "available_actions": decision["available_actions"],
                }
            else:
                next_action = {"kind": "user_input"}
        return {
            **state, "cursor": cursor, "terminal": status in self.TERMINAL,
            "requires_attention": status in self.ATTENTION, "next_action": next_action,
        }

    async def wait(
        self,
        task_ids: list[str],
        after_cursors: dict[str, str] | None = None,
        timeout_seconds: float = 20,
    ) -> dict[str, Any]:
        if not isinstance(task_ids, list) or not 1 <= len(task_ids) <= self.MAX_TASKS:
            raise ValueError("task_ids must contain 1 to 32 task IDs")
        if any(not isinstance(item, str) or not item.strip() for item in task_ids):
            raise ValueError("task IDs must be non-empty strings")
        if not math.isfinite(timeout_seconds) or not 0 <= timeout_seconds <= self.MAX_WAIT_SECONDS:
            raise ValueError("timeout_seconds must be between 0 and 20")
        cursors = {} if after_cursors is None else after_cursors
        if not isinstance(cursors, dict) or any(
            key not in task_ids or not isinstance(value, str) for key, value in cursors.items()
        ):
            raise ValueError("after_cursors must map requested task IDs to cursor strings")
        ids = list(dict.fromkeys(task_ids))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        while True:
            observations = [self.observe(task_id) for task_id in ids]
            changed = [item["task"]["id"] for item in observations
                       if cursors.get(item["task"]["id"]) != item["cursor"]]
            if any(item["requires_attention"] for item in observations):
                reason = "attention"
            elif any(item["terminal"] for item in observations):
                reason = "terminal"
            elif changed:
                reason = "snapshot" if any(task_id not in cursors for task_id in ids) else "changed"
            elif loop.time() >= deadline:
                reason = "timeout"
            else:
                await asyncio.sleep(min(0.2, max(0, deadline - loop.time())))
                continue
            return {"observations": observations, "changed_task_ids": changed, "reason": reason}
