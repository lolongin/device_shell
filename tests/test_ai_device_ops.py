from __future__ import annotations

from device_tui.application.ai.operations import (
    DeviceSnapshot,
    RiskLevel,
    SimpleAiDevicePlanner,
    classify_command_risk,
)


def test_ai_command_risk_classification() -> None:
    assert classify_command_risk("display version") == RiskLevel.LOW
    assert classify_command_risk("dir flash:/") == RiskLevel.LOW
    assert classify_command_risk("ftp 192.0.2.10 2121") == RiskLevel.MEDIUM
    assert classify_command_risk("startup system-software flash:/target.cc all") == RiskLevel.HIGH
    assert classify_command_risk("reboot") == RiskLevel.HIGH


def test_ai_planner_builds_simulated_package_upgrade_plan() -> None:
    planner = SimpleAiDevicePlanner()
    plan = planner.build_plan(
        "给模拟终端执行自动换包",
        [DeviceSnapshot(id="SIM-TERMINAL", name="模拟终端", kind="simulated")],
    )

    assert plan.requires_confirmation
    assert [action.kind for action in plan.actions] == [
        "select_device",
        "open_session",
        "run_package_upgrade",
    ]
    assert plan.actions[-1].risk == RiskLevel.FLOW
    assert plan.actions[-1].device_id == "SIM-TERMINAL"
    assert plan.actions[1].params["protocol"] == "telnet"
    assert plan.actions[2].params["protocol"] == "telnet"


def test_ai_planner_can_prepare_simulated_failure_toggle() -> None:
    planner = SimpleAiDevicePlanner()
    plan = planner.build_plan(
        "模拟终端空间不足后执行换包",
        [DeviceSnapshot(id="SIM-TERMINAL", name="模拟终端", kind="simulated")],
    )

    assert plan.actions[0].command == "sim upgrade fail-space on"
    assert plan.actions[0].risk == RiskLevel.LOW
