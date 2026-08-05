# tests/test_ai_gateway_service.py
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.ai_gateway.service import (
    GatewayService,
    GatewayUnavailableError,
)


def _fake_executor(plan: dict[str, dict[str, str]] | None = None):
    """Return a command executor driven by an ordered dict of command→(status, output)."""
    plan = plan or {}
    calls: list[str] = []

    def execute_command(command: str, session_id: str, timeout_seconds: int) -> dict[str, str]:
        calls.append(command)
        status, output = plan.get(command, ("success", f"output of {command}"))
        return {"status": status, "output": output, "exit_code": 0 if status == "success" else 1}

    return execute_command, calls


def test_execute_command_returns_result_and_summary() -> None:
    executor, calls = _fake_executor()
    service = GatewayService()
    result = service.execute_command("display version", "sess-1", executor=executor)
    assert result["result_id"].startswith("R")
    assert result["summary"]["status"] == "success"
    assert calls == ["display version"]


def test_execute_batch_runs_all_commands() -> None:
    executor, calls = _fake_executor()
    service = GatewayService()
    result = service.execute_batch(["display version", "display cpu"], "sess-1", executor=executor)
    assert calls == ["display version", "display cpu"]
    assert result["summary"]["command_count"] == 2


def test_execute_script_linux_injects_whole_block() -> None:
    executor, calls = _fake_executor()
    service = GatewayService()
    script = "export FOO=bar\nls $FOO\n"
    result = service.execute_script(script, "sess-1", is_network_device=False, executor=executor)
    # Linux: the whole block goes in one command (multi-line).
    assert len(calls) == 1
    assert calls[0] == script
    assert result["summary"]["status"] == "success"


def test_execute_script_network_device_splits_lines() -> None:
    executor, calls = _fake_executor()
    service = GatewayService()
    script = "display version\ndisplay cpu\n"
    result = service.execute_script(script, "sess-1", is_network_device=True, executor=executor)
    assert calls == ["display version", "display cpu"]
    assert result["summary"]["command_count"] == 2


def test_get_result_round_trip() -> None:
    service = GatewayService()
    created = service.execute_command("display version", "sess-1", executor=_fake_executor()[0])
    fetched = service.get_result(created["result_id"])
    assert fetched is not None
    assert fetched["result"]["summary"]["status"] == "success"
    raw = service.get_result(created["result_id"], include_raw=True)
    assert raw is not None
    assert "raw_output" in raw


def test_run_skill_instantiates_flow() -> None:
    executor, _ = _fake_executor()
    service = GatewayService()
    result = service.run_skill(
        "driver_reload",
        {"device_id": "dev-1"},
        session_id="sess-1",
        executor=executor,
    )
    assert result["result_id"].startswith("R")
    assert result["summary"]["command_count"] == 2  # both steps ran


def test_skill_flow_returns_substituted_dict() -> None:
    service = GatewayService()
    flow = service.skill_flow("driver_reload", {"device_id": "dev-1"})
    assert isinstance(flow, dict)
    assert flow["steps"][0]["command"] == "display version"


def test_gateway_unavailable_without_executor() -> None:
    service = GatewayService()
    with pytest.raises(GatewayUnavailableError):
        service.execute_command("display version", "sess-1")
