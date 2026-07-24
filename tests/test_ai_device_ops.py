from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.ai_device_ops import (
    AiDeviceAction,
    DeviceSnapshot,
    RiskLevel,
    SimpleAiDevicePlanner,
    classify_command_risk,
)
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


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


def test_ai_planner_can_prepare_simulated_failure_toggle() -> None:
    planner = SimpleAiDevicePlanner()
    plan = planner.build_plan(
        "模拟终端空间不足后执行换包",
        [DeviceSnapshot(id="SIM-TERMINAL", name="模拟终端", kind="simulated")],
    )

    assert plan.actions[0].command == "sim upgrade fail-space on"
    assert plan.actions[0].risk == RiskLevel.LOW


def test_app_ai_bridge_lists_and_selects_simulated_device(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    snapshots = window.ai_device_snapshots()

    assert any(snapshot.id == "SIM-TERMINAL" for snapshot in snapshots)

    result = window.execute_ai_device_action(
        AiDeviceAction(
            "select_device",
            "选择模拟终端",
            RiskLevel.OBSERVE,
            device_id="SIM-TERMINAL",
        )
    )

    assert result.ok
    assert window.selected_device_id == "SIM-TERMINAL"


def test_app_ai_bridge_requires_approval_for_high_risk_command(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    action = AiDeviceAction(
        "send_command",
        "重启设备",
        RiskLevel.LOW,
        device_id="SIM-TERMINAL",
        command="reboot",
    )

    result = window.execute_ai_device_action(action)

    assert not result.ok
    assert result.approval_required
    assert result.action.risk == RiskLevel.HIGH


def test_ai_device_get_excludes_credentials(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    result = window.execute_ai_device_action(
        AiDeviceAction(
            "device_get",
            "读取模拟设备详情",
            RiskLevel.OBSERVE,
            device_id="SIM-TERMINAL",
        )
    )

    payload = json.dumps(result.data, ensure_ascii=False)
    assert result.ok
    assert result.data["device"]["protocols"] == ["simulated"]
    assert "password" not in payload.casefold()
    assert "username" not in payload.casefold()


def test_ai_session_resolution_rejects_ambiguous_device(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    def state(tab_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            tab_id=tab_id,
            kind="simulated",
            device_id="SIM-TERMINAL",
            title=tab_id,
            host="localhost",
            port=0,
            session=SimpleNamespace(is_connected=True),
            connecting=False,
            recent_output_buffer="",
            output_cursor=0,
            status_text="Connected",
        )

    window.session_tabs_by_id = {
        "sim:1": state("sim:1"),
        "sim:2": state("sim:2"),
    }
    result = window.execute_ai_device_action(
        AiDeviceAction(
            "terminal_execute_start",
            "执行命令",
            RiskLevel.LOW,
            device_id="SIM-TERMINAL",
            command="display version",
            params={"session_id": ""},
        )
    )

    assert not result.ok
    assert result.error_code == "ambiguous_session"
    assert [item["session_id"] for item in result.data["sessions"]] == [
        "sim:1",
        "sim:2",
    ]


def test_ai_device_panel_generates_plan(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    window.show_left_sidebar_panel("ai_device")
    window.ai_device_prompt_input.setPlainText("给模拟终端执行自动换包")
    window.generate_ai_device_plan()

    assert window.left_sidebar_active_panel == "ai_device"
    assert window.left_sidebar_stack.currentIndex() == 5
    assert window.activity_ai_device_button.isChecked()
    assert window.current_ai_device_plan is not None
    assert window.ai_device_execute_button.isEnabled()
    assert "执行受控自动换包流程" in window.ai_device_plan_output.toPlainText()
