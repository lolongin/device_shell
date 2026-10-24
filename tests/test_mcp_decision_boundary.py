from __future__ import annotations

import asyncio
from dataclasses import replace
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from device_tui.application.tasking.models import TaskRecord
from device_tui.application.tasking.observation import TaskObserver
from device_tui.application.tasking.protocol import DecisionContext
from device_tui.interfaces.desktop_api.mcp_service import DesktopMcpService


def _service() -> tuple[DesktopMcpService, Mock]:
    tasks = Mock()
    tasks.get.return_value = TaskRecord(id="task", status="running", workflow_id="check", device_id="device")
    tasks.get_decision.return_value = DecisionContext(
        task_id="task", workflow_id="check", current_step="verify", checkpoint_revision=3,
    )
    tasks.apply_decision.return_value = tasks.get.return_value
    service = DesktopMcpService.__new__(DesktopMcpService)
    service.desktop = SimpleNamespace(task_service=tasks)
    service.ai = Mock()
    service._lock = threading.RLock()
    service._idempotency = {}
    service._task_observer = TaskObserver(tasks)
    return service, tasks


@pytest.mark.parametrize("tool", ["task.get", "task.wait", "decision.get"])
def test_observation_with_reused_key_remains_live(tool: str) -> None:
    service, tasks = _service()
    params = {"task_id": "task", "task_ids": ["task"], "timeout_seconds": 0, "idempotency_key": "same"}
    first = asyncio.run(service.invoke(tool, params))
    tasks.get.return_value = replace(tasks.get.return_value, progress_percent=60)
    tasks.get_decision.return_value = replace(tasks.get_decision.return_value, checkpoint_revision=4)
    second = asyncio.run(service.invoke(tool, params))
    assert first[0] == second[0] == 200
    assert first[1] != second[1]


@pytest.mark.parametrize("tool", ["decision.apply", "task_decision"])
@pytest.mark.parametrize("scenario,status", [("user_only", 400), ("stale", 409), ("missing", 400), ("conflicting", 409)])
def test_decisions_reject_unauthorized_or_stale_submissions(tool: str, scenario: str, status: int) -> None:
    service, tasks = _service()
    params = {"task_id": "task", "actor_type": "user", "action": {"name": "retry", "expected_revision": 3}}
    if scenario == "user_only":
        tasks.get_decision.return_value = replace(tasks.get_decision.return_value, decision_modes=("user",))
    elif scenario == "missing":
        tasks.get_decision.return_value = None
    elif scenario == "stale":
        params["action"]["expected_revision"] = 2
    else:
        params["expected_revision"] = 2
    result = asyncio.run(service.invoke(tool, params))
    assert result[0] == status
    tasks.apply_decision.assert_not_called()


@pytest.mark.parametrize("explicit_revision", [True, False])
def test_decision_forwards_current_revision_and_agent_identity(explicit_revision: bool) -> None:
    service, tasks = _service()
    action = {"name": "retry"}
    if explicit_revision:
        action["expected_revision"] = 3
    result = asyncio.run(service.invoke("decision.apply", {"task_id": "task", "action": action}))
    assert result[0] == 200
    decision = tasks.apply_decision.call_args.args[1]
    assert decision.expected_revision == 3
    assert decision.actor.type == "agent"
