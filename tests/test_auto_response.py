"""Tests for generic terminal auto-response rules."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp
from src.app.session_ops import AutoResponseRuleDialog
from src.app_state import SessionTabState
from src.auto_response import AutoResponseRule, AutoResponseStep, TerminalQuickButton, decode_response_text


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_decode_response_text_supports_control_keys_and_escapes() -> None:
    assert decode_response_text("Ctrl+B") == "\x02"
    assert decode_response_text("Ctrl+Z") == "\x1a"
    assert decode_response_text(r"\x02") == "\x02"
    assert decode_response_text("admin", append_enter=True) == "admin\r"


def test_create_auto_response_rule_keeps_editable_metadata(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    rule = window.create_auto_response_rule(
        name="Login",
        pattern="login:",
        response_text="admin",
        append_enter=True,
        once=False,
    )

    assert rule is not None
    assert rule.response == "admin\r"
    assert rule.response_text == "admin"
    assert rule.append_enter
    assert not rule.once


def test_create_auto_response_rule_supports_workflow_steps(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    rule = window.create_auto_response_rule(
        name="启动流程",
        pattern="",
        response_text="",
        steps_text="Ctrl+B => Ctrl+B\n=> display version\nADMIN => Ctrl+A",
        once=True,
    )

    assert rule is not None
    assert rule.pattern == "Ctrl+B"
    assert rule.response == "\x02"
    assert len(rule.steps) == 2
    assert rule.steps[0].pattern == "Ctrl+B"
    assert rule.steps[0].responses == ["\x02", "display version"]
    assert rule.steps[0].response_texts == ["Ctrl+B", "display version"]
    assert rule.steps[0].response_targets == ["current", "current"]
    assert rule.steps[1].pattern == "ADMIN"
    assert rule.steps[1].responses == ["\x01"]


def test_auto_response_rule_dialog_builds_steps_with_buttons(app: QApplication) -> None:
    _ = app
    dialog = AutoResponseRuleDialog()

    dialog.add_send_row("display version")
    dialog.add_wait_row("ADMIN", "Ctrl+A")
    values = dialog.values()

    assert values["steps_text"] == "Ctrl+B => Ctrl+B\n=> display version\nADMIN => Ctrl+A"
    assert values["step_targets"] == ["current", "current", "current"]
    assert values["case_sensitive"] is True
    assert not hasattr(dialog, "steps_input")


def test_auto_response_rule_dialog_preserves_case_sensitive_setting(app: QApplication) -> None:
    _ = app
    rule = AutoResponseRule(
        name="登录",
        pattern="ADMIN",
        response="admin\r",
        response_text="admin",
        case_sensitive=False,
    )

    dialog = AutoResponseRuleDialog(rule=rule)

    assert dialog.values()["case_sensitive"] is False


def test_auto_response_rule_dialog_lists_open_terminal_targets(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    target_state = SessionTabState(
        tab_id="device:linux:2",
        kind="linux",
        device_id="device",
        title="SSH #1",
        host="127.0.0.1",
        port=22,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "target.log",
    )

    class Parent(QWidget):
        def ordered_session_states(self) -> list[SessionTabState]:
            return [target_state]

        def session_jump_text(self, state: SessionTabState) -> str:
            return f"设备A · {state.title} · 已连接"

    parent = Parent()
    dialog = AutoResponseRuleDialog(parent)
    combo = dialog.condition_blocks[0]["response_rows"][0]["target_combo"]

    assert isinstance(combo, QComboBox)
    assert combo.itemText(0) == "当前选中终端"
    assert combo.findData("source") < 0
    assert combo.findData("next") < 0
    index = combo.findData("session:device:linux:SSH #1")
    assert index >= 0
    assert combo.itemData(index, Qt.ItemDataRole.ToolTipRole) == "已打开：设备A · SSH #1 · 已连接"
    assert combo.view().minimumWidth() > combo.width()


def test_open_simulated_session_does_not_copy_rule_objects(
    app: QApplication,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.remembered_auto_response_rules = [
        AutoResponseRule(name="Boot", pattern="Ctrl+B", response="\x02")
    ]
    captured: dict[str, object] = {}
    window.ensure_session_tab = lambda **kwargs: captured.update(kwargs) or None  # type: ignore[method-assign]

    window.open_simulated_session()

    assert captured["kind"] == "simulated"
    assert "auto_response_rules" not in captured


def test_remembered_auto_response_rules_round_trip_desktop_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()
    first.remembered_auto_response_rules = [
        AutoResponseRule(
            name="Admin",
            pattern="ADMIN",
            response="\x01",
            response_text="Ctrl+A",
            once=True,
            trigger_count=3,
        )
    ]

    first.save_desktop_state()
    second = DeviceDesktopApp()

    assert len(second.remembered_auto_response_rules) == 1
    loaded_rule = second.remembered_auto_response_rules[0]
    assert loaded_rule.name == "Admin"
    assert loaded_rule.pattern == "ADMIN"
    assert loaded_rule.response == "\x01"
    assert loaded_rule.response_text == "Ctrl+A"
    assert loaded_rule.once
    assert loaded_rule.trigger_count == 0


def test_auto_response_workflow_steps_round_trip_desktop_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()
    first.remembered_auto_response_rules = [
        AutoResponseRule(
            name="启动流程",
            pattern="Ctrl+B",
            response="\x02",
            response_text="Ctrl+B",
            steps=[
                AutoResponseStep(
                    pattern="Ctrl+B",
                    responses=["\x02", "display version"],
                    response_texts=["Ctrl+B", "display version"],
                    response_targets=["source", "title:SSH #1"],
                ),
                AutoResponseStep(
                    pattern="ADMIN",
                    responses=["\x01"],
                    response_texts=["Ctrl+A"],
                ),
            ],
        )
    ]

    first.save_desktop_state()
    second = DeviceDesktopApp()

    loaded_rule = second.remembered_auto_response_rules[0]
    assert len(loaded_rule.steps) == 2
    assert loaded_rule.steps[0].responses == ["\x02", "display version"]
    assert loaded_rule.steps[0].response_targets == ["source", "title:SSH #1"]
    assert loaded_rule.steps[1].pattern == "ADMIN"


def test_quick_send_buttons_round_trip_desktop_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()
    first.remembered_quick_send_buttons = [
        TerminalQuickButton(
            name="发送 Ctrl+A",
            response="\x01",
            response_text="Ctrl+A",
            trigger_count=3,
        )
    ]

    first.save_desktop_state()
    second = DeviceDesktopApp()

    assert len(second.remembered_quick_send_buttons) == 1
    loaded_button = second.remembered_quick_send_buttons[0]
    assert loaded_button.name == "发送 Ctrl+A"
    assert loaded_button.response == "\x01"
    assert loaded_button.response_text == "Ctrl+A"
    assert loaded_button.trigger_count == 0


def test_auto_response_button_stays_enabled_without_session(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.current_session_state = lambda: None  # type: ignore[method-assign]

    window.update_controls()

    assert window.quick_auto_response_button.isEnabled()
    assert not hasattr(window, "quick_simulated_terminal_button")


def test_auto_response_template_can_be_remembered_without_session(
    app: QApplication,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.remembered_auto_response_rules = []

    window.add_boot_ctrl_b_auto_response_rule()

    assert len(window.remembered_auto_response_rules) == 1
    assert window.remembered_auto_response_rules[0].pattern == "Ctrl+B"
    assert window.remembered_auto_response_rules[0].response == "\x02"


def test_auto_response_menu_uses_remembered_rules_without_session(
    app: QApplication,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.current_session_state = lambda: None  # type: ignore[method-assign]
    window.remembered_auto_response_rules = [
        AutoResponseRule(name="Admin", pattern="ADMIN", response="\x01")
    ]

    window.refresh_quick_auto_response_menu()

    action_texts = [action.text() for action in window.quick_auto_response_menu.actions()]
    assert "未打开终端，将编辑默认规则" not in action_texts
    assert "新增规则..." in action_texts
    assert "清空规则 (1)" not in action_texts
    assert "发送 Ctrl+B" not in action_texts
    assert "打开模拟终端（测试）" not in action_texts
    assert any(action.menu() and action.text() == "Admin" for action in window.quick_auto_response_menu.actions())


def test_simulated_terminal_appears_in_device_navigation(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.devices = [sample_devices()[0]]
    window.rebuild_device_indexes()
    window.refresh_domain_options()
    window.apply_filters()

    assert any(device.id == "SIM-TERMINAL" for device in window.visible_devices)
    assert window.get_device_by_id("SIM-TERMINAL") is not None


def test_simulated_terminal_selection_updates_connection_controls(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    simulated = window.simulated_device()
    window.devices = [sample_devices()[0]]
    window.rebuild_device_indexes()
    window.refresh_domain_options()
    window.apply_filters()

    window.activate_device(simulated.id)
    window.update_controls()

    assert window.connection_telnet_button.text() == "连接 Telnet"
    assert not window.connection_ssh_button.isEnabled()
    assert not window.connection_serial_button.isEnabled()


def test_simulated_terminal_uses_normal_device_display_name(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    simulated = window.simulated_device()

    assert window.temporary_device_display_name(simulated) == "模拟终端"
    assert not window.temporary_device_display_name(simulated).startswith("[模拟]")
    assert simulated.board_id == "0000"
    assert simulated.domain == "测试"


def test_selected_simulated_device_opens_simulated_session(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    simulated = window.simulated_device()
    window.device_by_id[simulated.id] = simulated
    window.selected_device_id = simulated.id
    captured: dict[str, object] = {}
    window.ensure_session_tab = lambda **kwargs: captured.update(kwargs) or None  # type: ignore[method-assign]

    window.open_selected_device_session()

    assert captured["kind"] == "simulated"
    assert captured["device"] == simulated
    assert "auto_response_rules" not in captured


def test_auto_response_rule_buttons_use_remembered_rules_without_session(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.current_session_state = lambda: None  # type: ignore[method-assign]
    window.remembered_auto_response_rules = [
        AutoResponseRule(name="Admin", pattern="ADMIN", response="\x01")
    ]

    window.refresh_auto_response_rule_buttons()

    assert not window.auto_response_rule_bar.isHidden()


def test_send_ctrl_b_is_direct_button_for_current_session(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "session.log",
    )
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    window.session_tabs_by_id = {state.tab_id: state}
    window.remembered_quick_send_buttons = [
        TerminalQuickButton(name="发送 Ctrl+B", response="\x02", response_text="Ctrl+B")
    ]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.refresh_auto_response_rule_buttons()

    buttons = [
        window.auto_response_rule_bar_layout.itemAt(index).widget()
        for index in range(window.auto_response_rule_bar_layout.count())
    ]
    send_buttons = [button for button in buttons if button is not None and button.text() == "发送 Ctrl+B"]
    assert len(send_buttons) == 1

    send_buttons[0].click()

    assert sent == [(state.tab_id, "\x02")]


def test_auto_response_rule_sends_when_split_output_matches(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "session.log",
    )
    rule = AutoResponseRule(name="Boot Ctrl+B", pattern="Ctrl+B", response="\x02")
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "Press Ctrl+")
    window.apply_auto_response_rules(state, "B to enter menu")

    assert sent == [("device:device:1", "\x02")]
    assert rule.enabled
    assert window.auto_response_rule_signature(rule) in state.auto_response_triggered_rules
    assert "Auto response sent: Boot Ctrl+B" in state.log_path.read_text(encoding="utf-8")


def test_auto_response_workflow_sends_multiple_actions_then_waits_for_next_match(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "session.log",
    )
    rule = AutoResponseRule(
        name="启动流程",
        pattern="Ctrl+B",
        response="\x02",
        response_text="Ctrl+B",
        steps=[
            AutoResponseStep(
                pattern="Ctrl+B",
                responses=["\x02", "display version\r"],
                response_texts=["Ctrl+B", "display version"],
            ),
            AutoResponseStep(
                pattern="ADMIN",
                responses=["\x01"],
                response_texts=["Ctrl+A"],
            ),
        ],
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "Press Ctrl+B to enter menu")

    signature = window.auto_response_rule_signature(rule)
    assert sent == [("device:device:1", "\x02"), ("device:device:1", "display version\r")]
    assert state.auto_response_rule_steps[signature] == 1
    assert signature not in state.auto_response_triggered_rules

    window.apply_auto_response_rules(state, "Welcome ADMIN menu")

    assert sent == [
        ("device:device:1", "\x02"),
        ("device:device:1", "display version\r"),
        ("device:device:1", "\x01"),
    ]
    assert signature in state.auto_response_triggered_rules
    assert signature not in state.auto_response_rule_steps


def test_auto_response_workflow_respects_case_sensitive_matching(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "session.log",
    )
    rule = AutoResponseRule(
        name="大小写测试",
        pattern="Ctrl+B",
        response="\x02",
        response_text="Ctrl+B",
        case_sensitive=True,
        steps=[
            AutoResponseStep(
                pattern="Ctrl+B",
                responses=["\x02"],
                response_texts=["Ctrl+B"],
            )
        ],
    )
    window.remembered_auto_response_rules = [rule]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "Press Ctrl+b")
    window.apply_auto_response_rules(state, "Press Ctrl+B")

    assert sent == [("device:device:1", "\x02")]


def test_auto_response_can_send_to_another_terminal_by_title(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    source_state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "source.log",
    )
    target_state = SessionTabState(
        tab_id="device:linux:2",
        kind="linux",
        device_id="device",
        title="SSH #1",
        host="127.0.0.1",
        port=22,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "target.log",
    )
    rule = AutoResponseRule(
        name="跨终端流程",
        pattern="READY",
        response="run\r",
        response_text="run",
        steps=[
            AutoResponseStep(
                pattern="READY",
                responses=["run\r"],
                response_texts=["run"],
                response_targets=["title:SSH #1"],
            )
        ],
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: source_state  # type: ignore[method-assign]
    window.ordered_session_states = lambda: [source_state, target_state]  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(source_state, "READY")

    assert sent == [("device:linux:2", "run\r")]


def test_auto_response_reenable_resets_hit_count_and_rearms_once_rule(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "session.log",
    )
    rule = AutoResponseRule(name="Boot Ctrl+B", pattern="Ctrl+B", response="\x02")
    window.remembered_auto_response_rules = [rule]
    window.session_tabs_by_id = {state.tab_id: state}
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "Press Ctrl+B to enter menu")
    assert rule.trigger_count == 1
    assert window.auto_response_rule_button_text(rule) == "Boot Ct..."

    window.set_auto_response_rule_enabled(rule, False)
    assert rule.trigger_count == 1
    window.set_auto_response_rule_enabled(rule, True)

    assert rule.trigger_count == 0
    assert window.auto_response_rule_signature(rule) not in state.auto_response_triggered_rules

    window.apply_auto_response_rules(state, "Press Ctrl+B to enter menu")

    assert sent == [("device:device:1", "\x02"), ("device:device:1", "\x02")]
    assert rule.trigger_count == 1


def test_once_auto_response_button_turns_inactive_after_current_session_hit(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "session.log",
    )
    rule = AutoResponseRule(name="登录B菜单", pattern="ADMIN", response="\x01", response_text="Ctrl+A")
    state.auto_response_triggered_rules.add(window.auto_response_rule_signature(rule))
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]

    window.refresh_auto_response_rule_buttons()

    buttons = [
        window.auto_response_rule_bar_layout.itemAt(index).widget()
        for index in range(window.auto_response_rule_bar_layout.count())
    ]
    rule_buttons = [button for button in buttons if button is not None and button.text() == "登录B菜单"]
    assert len(rule_buttons) == 1
    assert not rule_buttons[0].isChecked()
    assert "已执行" in rule_buttons[0].toolTip()


def test_auto_response_rule_can_match_existing_recent_buffer(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "session.log",
        auto_response_buffer="Press Ctrl+A to enter ADMIN menu:",
    )
    window.remembered_auto_response_rules = [
        AutoResponseRule(name="Admin Ctrl+A", pattern="ADMIN", response="\x01")
    ]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "")

    assert sent == [("device:device:1", "\x01")]


def test_auto_response_rule_ignores_stale_buffer_on_new_output(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "session.log",
        auto_response_buffer="Press Ctrl+A to enter ADMIN menu: ",
    )
    rule = AutoResponseRule(name="Admin Ctrl+A", pattern="ADMIN", response="\x01")
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "<sim> a")

    assert sent == []
    assert rule.enabled


def test_auto_response_rule_only_applies_to_selected_session(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    selected_state = SessionTabState(
        tab_id="device:device:1",
        kind="device",
        device_id="device",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "selected.log",
    )
    background_state = SessionTabState(
        tab_id="device:device:2",
        kind="device",
        device_id="device",
        title="Telnet #2",
        host="127.0.0.1",
        port=23,
        username="admin",
        password="admin",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=tmp_path / "background.log",
    )
    window.remembered_auto_response_rules = [
        AutoResponseRule(name="Boot Ctrl+B", pattern="Ctrl+B", response="\x02")
    ]
    window.current_session_state = lambda: selected_state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(background_state, "Press Ctrl+B to enter menu")
    window.apply_auto_response_rules(selected_state, "Press Ctrl+B to enter menu")

    assert sent == [("device:device:1", "\x02")]
