from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from device_tui.application.tasking.models import TaskRecord
from device_tui.application.tasking.observation import TaskObserver
from device_tui.application.tasking.protocol import Action, DecisionContext


class MemoryTasks:
    def __init__(self) -> None:
        self.records = {
            key: TaskRecord(id=key, status="running", workflow_id="check", device_id=key)
            for key in ("a", "b")
        }
        self.decisions: dict[str, DecisionContext] = {}

    def get(self, task_id: str) -> TaskRecord:
        return self.records[task_id]

    def get_decision(self, task_id: str) -> DecisionContext | None:
        return self.decisions.get(task_id)


def test_fleet_wait_tracks_progress_without_status_or_revision_change() -> None:
    async def scenario() -> None:
        tasks = MemoryTasks()
        observer = TaskObserver(tasks)
        first = await observer.wait(["a", "b", "a"])
        assert first["reason"] == "snapshot"
        assert len(first["observations"]) == 2
        cursors = {item["task"]["id"]: item["cursor"] for item in first["observations"]}
        unchanged = await observer.wait(["a", "b"], cursors, 0)
        assert unchanged["reason"] == "timeout"
        assert unchanged["changed_task_ids"] == []

        async def update() -> None:
            await asyncio.sleep(0)
            tasks.records["b"] = replace(tasks.records["b"], progress_percent=50)

        updater = asyncio.create_task(update())
        changed = await observer.wait(["a", "b"], cursors, 1)
        await updater
        assert changed["reason"] == "changed"
        assert changed["changed_task_ids"] == ["b"]

    asyncio.run(scenario())


def test_decision_guidance_tracks_revision_and_agent_authority() -> None:
    tasks = MemoryTasks()
    tasks.records["a"] = replace(tasks.records["a"], status="waiting_for_decision")
    tasks.decisions["a"] = DecisionContext(
        task_id="a", workflow_id="check", current_step="verify",
        checkpoint_revision=3, available_actions=(Action(name="retry"),),
    )
    observer = TaskObserver(tasks)
    first = observer.observe("a")
    assert first["next_action"]["expected_revision"] == 3
    assert first["next_action"]["available_actions"][0]["name"] == "retry"
    tasks.decisions["a"] = replace(tasks.decisions["a"], checkpoint_revision=4, decision_modes=("user",))
    second = observer.observe("a")
    assert second["cursor"] != first["cursor"]
    assert second["next_action"] == {"kind": "user_input"}
    result = asyncio.run(observer.wait(["a"], {"a": second["cursor"]}, 20))
    assert result["reason"] == "attention"


@pytest.mark.parametrize("status,kind,reason", [
    ("completed", "complete", "terminal"),
    ("cancelled", "stopped", "terminal"),
    ("failed", "inspect_failure", "attention"),
    ("paused", "resume", "attention"),
])
def test_terminal_and_attention_wake_even_with_current_cursor(status: str, kind: str, reason: str) -> None:
    tasks = MemoryTasks()
    tasks.records["a"] = replace(tasks.records["a"], status=status)
    observer = TaskObserver(tasks)
    snapshot = observer.observe("a")
    assert snapshot["next_action"]["kind"] == kind
    result = asyncio.run(observer.wait(["a"], {"a": snapshot["cursor"]}, 20))
    assert result["reason"] == reason


@pytest.mark.parametrize("ids,cursors,timeout", [
    ([], None, 0), (["a"] * 33, None, 0), ([""], None, 0),
    (["a"], [], 0), (["a"], {"b": "cursor"}, 0),
    (["a"], {"a": 1}, 0), (["a"], None, float("nan")),
    (["a"], None, 21), (["a"], None, -1),
])
def test_wait_rejects_invalid_bounds(ids, cursors, timeout) -> None:
    with pytest.raises(ValueError):
        asyncio.run(TaskObserver(MemoryTasks()).wait(ids, cursors, timeout))


def test_wait_propagates_missing_task_and_cancellation() -> None:
    observer = TaskObserver(MemoryTasks())
    with pytest.raises(KeyError):
        asyncio.run(observer.wait(["missing"]))

    async def scenario() -> None:
        cursor = observer.observe("a")["cursor"]
        waiter = asyncio.create_task(observer.wait(["a"], {"a": cursor}))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    asyncio.run(scenario())
