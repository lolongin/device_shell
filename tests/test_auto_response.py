"""Tests for generic terminal auto-response rules."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp
from src.app_state import SessionTabState
from src.auto_response import AutoResponseRule, TerminalQuickButton, decode_response_text


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
    assert "清空规则 (1)" in action_texts
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

    assert window.connection_telnet_button.text() == "打开模拟终端"
    assert not window.connection_ssh_button.isEnabled()
    assert not window.connection_serial_button.isEnabled()


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
