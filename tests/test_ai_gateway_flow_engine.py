from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.ai_gateway.flow_engine import (
    FlowEngine,
    FlowPlanError,
    parse_flow,
)


def _run(
    plan_data: dict,
    *,
    executor=None,
    waiter=None,
) -> list:
    plan = parse_flow(plan_data)
    engine = FlowEngine()
    executed = []

    base_executor = executor or (
        lambda command, session_id, timeout: ("success", f"output of {command}")
    )
    base_waiter = waiter or (lambda condition, session_id, device_id: ("success", "condition met"))

    def record_executor(command: str, session_id: str, timeout: int) -> tuple[str, str]:
        executed.append(command)
        return base_executor(command, session_id, timeout)

    return engine.run(
        plan,
        session_id="sess-1",
        device_id="dev-1",
        execute_step=record_executor,
        wait_for_condition=base_waiter,
    ), executed


def test_flow_runs_steps_in_order() -> None:
    results, executed = _run(
        {
            "steps": [
                {"id": "s1", "command": "display version"},
                {"id": "s2", "command": "display cpu"},
            ]
        }
    )
    assert executed == ["display version", "display cpu"]
    assert all(result.status == "success" for result in results)


def test_flow_dependency_gates_second_step() -> None:
    # s2 depends on s1; s1 fails → s2 must not run.
    def executor(command: str, session_id: str, timeout: int) -> tuple[str, str]:
        if command == "display version":
            return "failed", "Error: nope"
        return "success", "ok"

    results, executed = _run(
        {
            "steps": [
                {"id": "s1", "command": "display version"},
                {"id": "s2", "command": "display cpu", "depends_on": ["s1"]},
            ]
        },
        executor=executor,
    )
    assert executed == ["display version"]
    assert results[0].status == "failed"
    assert results[1].status == "skipped"


def test_flow_retry_on_failure() -> None:
    calls = {"n": 0}

    def executor(command: str, session_id: str, timeout: int) -> tuple[str, str]:
        calls["n"] += 1
        if calls["n"] < 3:
            return "failed", "Error: transient"
        return "success", "ok"

    plan = parse_flow(
        {
            "steps": [
                {
                    "id": "s1",
                    "command": "save",
                    "retry": {"max": 3, "interval_ms": 1, "on_status": "failed"},
                }
            ]
        }
    )
    engine = FlowEngine()
    results = engine.run(
        plan,
        session_id="sess-1",
        device_id="dev-1",
        execute_step=executor,
        wait_for_condition=lambda c, s, d: ("success", "ok"),
    )
    assert calls["n"] == 3
    assert results[0].status == "success"
    assert results[0].attempt_count == 3


def test_flow_wait_condition_polls_until_met() -> None:
    polls = {"n": 0}

    def waiter(condition: dict, session_id: str, device_id: str) -> tuple[str, str]:
        polls["n"] += 1
        if polls["n"] < 3:
            return "not_ready", "still booting"
        return "success", "ready"

    plan = parse_flow(
        {
            "steps": [
                {"id": "s1", "command": "save"},
                {
                    "id": "s2",
                    "command": "display version",
                    "wait_condition": {
                        "type": "command_output_contains",
                        "command": "display version",
                        "expected": "VRP",
                        "interval_ms": 1,
                        "max_attempts": 5,
                    },
                },
            ]
        }
    )
    engine = FlowEngine()
    results = engine.run(
        plan,
        session_id="sess-1",
        device_id="dev-1",
        execute_step=lambda c, s, t: ("success", "ok"),
        wait_for_condition=waiter,
    )
    assert polls["n"] == 3
    assert results[1].status == "success"


def test_flow_wait_condition_times_out() -> None:
    plan = parse_flow(
        {
            "steps": [
                {
                    "id": "s1",
                    "command": "save",
                    "wait_condition": {
                        "type": "command_output_contains",
                        "command": "display version",
                        "expected": "VRP",
                        "interval_ms": 1,
                        "max_attempts": 2,
                    },
                }
            ]
        }
    )
    engine = FlowEngine()
    results = engine.run(
        plan,
        session_id="sess-1",
        device_id="dev-1",
        execute_step=lambda c, s, t: ("success", "ok"),
        wait_for_condition=lambda c, s, d: ("not_ready", "booting"),
    )
    assert results[0].status == "failed"
    assert results[0].error_code == "condition_timeout"


def test_flow_too_many_steps_rejected() -> None:
    with pytest.raises(FlowPlanError) as exc_info:
        parse_flow({"steps": [{"id": f"s{i}", "command": "x"} for i in range(21)]})
    assert exc_info.value.code == "too_many_steps"


def test_flow_dependency_unknown_rejected() -> None:
    with pytest.raises(FlowPlanError) as exc_info:
        parse_flow(
            {
                "steps": [
                    {"id": "s1", "command": "a", "depends_on": ["ghost"]}
                ]
            }
        )
    assert exc_info.value.code == "unknown_dependency"
