"""Tests for generic terminal auto-response rules."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QDialogButtonBox, QLineEdit, QWidget

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp
from src.app.session_ops import (
    AutoResponseRuleDialog,
    AutoResponseRulePreviewDialog,
    AutoResponseRuleWebDialog,
    QuickSendButtonDialog,
)
from src.app_state import SessionTabState
from src.auto_response import (
    AutoResponseAction,
    AutoResponseRule,
    AutoResponseStep,
    TerminalQuickButton,
    decode_response_text,
    deserialize_auto_response_rule,
    serialize_auto_response_rule,
)
from src.auto_response_parser import parse_simple_auto_response_rule
from src.command_suggestions import CommandHistoryItem


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _allow_auto_response(state: SessionTabState) -> SessionTabState:
    state.user_input_seen = True
    state.suppress_auto_response_until_input = False
    return state


def test_decode_response_text_supports_control_keys_and_escapes() -> None:
    assert decode_response_text("Ctrl+B") == "\x02"
    assert decode_response_text("Ctrl+Z") == "\x1a"
    assert decode_response_text(r"\x02") == "\x02"
    assert decode_response_text("admin", append_enter=True) == "admin\r"


def test_simple_auto_response_parser_handles_capture_rule() -> None:
    result = parse_simple_auto_response_rule('看到 "Password:" => admin')

    assert result.ok
    assert result.rule is not None
    assert result.rule.kind == "capture"
    assert result.rule.trigger_type == "match"
    assert result.rule.pattern == "Password:"
    assert result.rule.response_text == "admin"


def test_simple_auto_response_parser_handles_connected_and_delay_rules() -> None:
    connected = parse_simple_auto_response_rule("连接后 => system-view")
    delayed = parse_simple_auto_response_rule("延时 1500ms => display version")

    assert connected.rule is not None
    assert connected.rule.trigger_type == "connected"
    assert connected.rule.pattern == ""
    assert delayed.rule is not None
    assert delayed.rule.trigger_type == "delay"
    assert delayed.rule.trigger_delay_ms == 1500


def test_simple_auto_response_parser_handles_manual_loop_rule() -> None:
    result = parse_simple_auto_response_rule("手动循环 5 次，每 1000ms => display clock")

    assert result.rule is not None
    assert result.rule.kind == "manual_loop"
    assert result.rule.trigger_type == "manual"
    assert result.rule.loop_count == 5
    assert result.rule.step_delay_ms == 1000
    assert not result.rule.once


def test_simple_auto_response_parser_handles_quick_send_rule() -> None:
    result = parse_simple_auto_response_rule('按钮 "Ctrl+B" => Ctrl+B')

    assert result.rule is not None
    assert result.rule.kind == "quick_send"
    assert result.rule.name == "Ctrl+B"
    assert result.rule.response_text == "Ctrl+B"


def test_simple_auto_response_parser_reports_useful_errors() -> None:
    missing_arrow = parse_simple_auto_response_rule("看到 Password:")
    empty_response = parse_simple_auto_response_rule("看到 Password: => ")

    assert missing_arrow.error is not None
    assert "=>" in missing_arrow.error.message
    assert empty_response.error is not None
    assert "发送内容" in empty_response.error.message


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
        step_delays=[0, 1200, 0],
        step_append_enters=[False, True, False],
        once=True,
    )

    assert rule is not None
    assert rule.pattern == "Ctrl+B"
    assert rule.response == "\x02"
    assert len(rule.steps) == 2
    assert rule.steps[0].pattern == "Ctrl+B"
    assert rule.steps[0].responses == ["\x02", "display version\r"]
    assert rule.steps[0].response_texts == ["Ctrl+B", "display version"]
    assert rule.steps[0].response_targets == ["current", "current"]
    assert rule.steps[0].response_delays == [0, 1200]
    assert rule.steps[0].response_append_enters == [False, True]
    assert rule.steps[1].pattern == "ADMIN"
    assert rule.steps[1].responses == ["\x01"]
    assert rule.steps[1].response_delays == [0]
    assert rule.steps[1].response_append_enters == [False]


def test_create_auto_response_rule_supports_unconditional_automation_steps(
    app: QApplication,
) -> None:
    _ = app
    window = DeviceDesktopApp()

    rule = window.create_auto_response_rule(
        name="Init",
        pattern="",
        response_text="",
        steps_text="=> system-view\n=> display version",
        step_append_enters=[True, True],
        trigger_type="connected",
        loop_count=2,
        once=True,
    )

    assert rule is not None
    assert rule.pattern == ""
    assert rule.trigger_type == "connected"
    assert rule.loop_count == 2
    assert len(rule.steps) == 1
    assert rule.steps[0].pattern == ""
    assert rule.steps[0].responses == ["system-view\r", "display version\r"]


def test_create_auto_response_rule_accepts_simple_capture_text(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    rule = window.create_auto_response_rule(
        name="",
        pattern="",
        response_text="",
        simple_rule_text='看到 "Password:" => admin',
    )

    assert rule is not None
    assert rule.kind == "capture"
    assert rule.pattern == "Password:"
    assert rule.response == "admin\r"
    assert rule.steps[0].pattern == "Password:"


def test_create_auto_response_rule_accepts_simple_manual_loop_text(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    rule = window.create_auto_response_rule(
        name="",
        pattern="",
        response_text="",
        kind="manual_loop",
        simple_rule_text="手动循环 3 次，每 500ms => display clock",
    )

    assert rule is not None
    assert rule.kind == "manual_loop"
    assert rule.trigger_type == "manual"
    assert rule.loop_count == 3
    assert not rule.once
    assert rule.steps[0].pattern == ""
    assert rule.steps[0].response_delays == [500]


def test_create_auto_response_rule_requires_manual_name(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    monkeypatch.setattr(window, "show_warning", lambda message: None)

    rule = window.create_auto_response_rule(
        name="",
        pattern="start",
        response_text="Ctrl+B",
    )

    assert rule is None


def test_auto_response_rule_kind_round_trips() -> None:
    rule = AutoResponseRule(
        name="Manual patrol",
        pattern="",
        response="display clock\r",
        trigger_type="manual",
        loop_count=3,
        kind="manual_loop",
    )

    loaded = deserialize_auto_response_rule(serialize_auto_response_rule(rule))

    assert loaded is not None
    assert loaded.kind == "manual_loop"


def test_legacy_auto_response_rule_kind_is_inferred() -> None:
    loaded = deserialize_auto_response_rule(
        {
            "name": "Manual patrol",
            "pattern": "",
            "response": "display clock\r",
            "trigger_type": "manual",
            "loop_count": 3,
        }
    )

    assert loaded is not None
    assert loaded.kind == "manual_loop"


def test_create_auto_response_rule_supports_regex_and_trigger_limits(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    rule = window.create_auto_response_rule(
        name="Prompt",
        pattern=r"Password:\s*$",
        response_text="admin",
        append_enter=True,
        match_type="regex",
        delay_ms=250,
        max_triggers=2,
        once=False,
    )

    assert rule is not None
    assert rule.match_type == "regex"
    assert rule.delay_ms == 250
    assert rule.max_triggers == 2
    assert rule.matches("Password: ")
    assert not rule.matches("Password needed later")


def test_auto_response_rule_dialog_builds_steps_with_buttons(app: QApplication) -> None:
    _ = app
    dialog = AutoResponseRuleDialog()

    assert dialog.objectName() == "workspaceDialog"
    assert dialog.findChild(QDialogButtonBox, "workspaceDialogButtons") is not None

    dialog.condition_blocks[0]["pattern_input"].setText("Ctrl+B")
    dialog.condition_blocks[0]["response_rows"][0]["response_input"].setText("Ctrl+B")
    dialog.add_send_row("display version")
    second_delay_input = dialog.condition_blocks[0]["response_rows"][1]["delay_input"]
    assert isinstance(second_delay_input, QLineEdit)
    second_delay_input.setText("1200")
    dialog.add_wait_row("ADMIN", "Ctrl+A")
    values = dialog.values()

    assert values["steps_text"] == "Ctrl+B => Ctrl+B\n=> display version\nADMIN => Ctrl+A"
    assert values["step_targets"] == ["current", "current", "current"]
    assert values["step_delays"] == [0, 1200, 0]
    assert values["case_sensitive"] is True
    assert not hasattr(dialog, "steps_input")


def test_new_auto_response_rule_dialog_starts_blank(app: QApplication) -> None:
    _ = app
    dialog = AutoResponseRuleDialog()

    values = dialog.values()

    assert dialog.name_input.text() == ""
    assert values["pattern"] == ""
    assert values["response_text"] == ""


def test_quick_send_button_dialog_uses_workspace_surfaces(app: QApplication) -> None:
    _ = app
    dialog = QuickSendButtonDialog()

    assert dialog.objectName() == "workspaceDialog"
    assert dialog.findChild(QDialogButtonBox, "workspaceDialogButtons") is not None


def test_auto_response_web_dialog_uses_workspace_button_surface(app: QApplication) -> None:
    _ = app
    try:
        dialog = AutoResponseRuleWebDialog()
    except RuntimeError:
        pytest.skip("QWebEngineView is not available")

    assert dialog.objectName() == "workspaceDialog"
    assert dialog.findChild(QDialogButtonBox, "workspaceDialogButtons") is not None
    assert not dialog.isModal()
    assert dialog.minimumWidth() >= 1180
    assert dialog.minimumHeight() >= 760


def test_new_auto_response_web_dialog_payload_starts_blank(app: QApplication) -> None:
    _ = app

    payload = AutoResponseRuleWebDialog.payload_from_rule(None)

    assert payload["name"] == ""
    assert payload["simpleRuleText"] == ""
    assert payload["steps"][0]["pattern"] == ""
    assert payload["steps"][0]["responses"][0]["text"] == ""
    assert payload["actions"][0]["text"] == ""


def test_auto_response_preview_dialog_renders_nested_flow(app: QApplication) -> None:
    _ = app
    payload = {
        "name": "TEST",
        "triggerType": "manual",
        "once": True,
        "actions": [
            {
                "kind": "loop",
                "repeatCount": 3,
                "intervalMs": 1000,
                "actions": [
                    {
                        "kind": "send",
                        "text": "disp version",
                        "target": "current",
                        "appendEnter": True,
                    }
                ],
            }
        ],
        "targets": [{"label": "当前选中终端", "value": "current"}],
    }

    html = AutoResponseRulePreviewDialog.preview_html(payload)

    assert "开始：点击按钮 TEST" in html
    assert "循环 3 次" in html
    assert "发送 disp version" in html
    assert "执行后停用本规则" in html


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
    target_state = _allow_auto_response(SessionTabState(
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
    ))

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


def test_auto_response_web_dialog_values_match_workflow_payload(app: QApplication) -> None:
    _ = app
    payload = {
        "name": "Boot workflow",
        "matchType": "contains",
        "appendEnter": False,
        "caseSensitive": True,
        "once": True,
        "allowStartupTrigger": True,
        "delayMs": 100,
        "maxTriggers": 2,
        "triggerType": "delay",
        "triggerDelayMs": 800,
        "loopCount": 3,
        "kind": "advanced",
        "simpleRuleText": "",
        "steps": [
            {
                "pattern": "Ctrl+B",
                "responses": [
                    {"text": "Ctrl+B", "target": "current", "delay": 0, "appendEnter": False},
                    {
                        "text": "display version",
                        "target": "session:device:linux:SSH #1",
                        "delay": 1200,
                        "appendEnter": True,
                    },
                ],
            },
            {
                "pattern": "ADMIN",
                "responses": [{"text": "Ctrl+A", "target": "current", "delay": 0, "appendEnter": False}],
            },
        ],
    }

    values = AutoResponseRuleWebDialog.values_from_payload(payload)

    assert values["steps_text"] == "Ctrl+B => Ctrl+B\n=> display version\nADMIN => Ctrl+A"
    assert values["step_targets"] == ["current", "session:device:linux:SSH #1", "current"]
    assert values["step_delays"] == [0, 1200, 0]
    assert values["step_append_enters"] == [False, True, False]
    assert values["trigger_type"] == "delay"
    assert values["trigger_delay_ms"] == 800
    assert values["loop_count"] == 3
    assert values["kind"] == "advanced"
    assert values["simple_rule_text"] == ""
    assert values["append_enter"] is True
    assert values["allow_startup_trigger"] is True
    assert values["delay_ms"] == 100
    assert values["max_triggers"] == 2


def test_auto_response_web_dialog_values_include_simple_authoring_payload(app: QApplication) -> None:
    _ = app
    payload = {
        "name": "",
        "kind": "manual_loop",
        "simpleRuleText": "手动循环 3 次，每 500ms => display clock",
        "steps": [{"pattern": "", "responses": [{"text": "", "target": "current", "delay": 0}]}],
    }

    values = AutoResponseRuleWebDialog.values_from_payload(payload)

    assert values["kind"] == "manual_loop"
    assert values["simple_rule_text"] == "手动循环 3 次，每 500ms => display clock"


def test_auto_response_web_dialog_values_include_action_flow_payload(app: QApplication) -> None:
    _ = app
    payload = {
        "name": "Start flow",
        "triggerType": "match",
        "triggerPattern": "start",
        "matchType": "contains",
        "once": True,
        "actions": [
            {"kind": "send", "text": "Ctrl+B", "target": "current", "appendEnter": False},
            {
                "kind": "loop",
                "repeatCount": 3,
                "intervalMs": 500,
                "actions": [
                    {"kind": "send", "text": "display clock", "target": "current", "appendEnter": True},
                    {"kind": "exit", "exitPattern": "done", "exitScope": "loop"},
                ],
            },
        ],
    }

    values = AutoResponseRuleWebDialog.values_from_payload(payload)

    assert values["pattern"] == "start"
    assert values["response_text"] == "Ctrl+B"
    assert values["trigger_type"] == "match"
    assert values["steps_text"] == ""
    assert values["actions"] == payload["actions"]


def test_auto_response_action_flow_round_trips() -> None:
    rule = AutoResponseRule(
        name="Loop flow",
        pattern="start",
        response="\x02",
        response_text="Ctrl+B",
        actions=[
            AutoResponseAction(kind="send", text="Ctrl+B"),
            AutoResponseAction(
                kind="loop",
                repeat_count=2,
                interval_ms=1000,
                actions=[AutoResponseAction(kind="send", text="display clock", append_enter=True)],
            ),
        ],
    )

    loaded = deserialize_auto_response_rule(serialize_auto_response_rule(rule))

    assert loaded is not None
    assert len(loaded.actions) == 2
    assert loaded.actions[1].kind == "loop"
    assert loaded.actions[1].actions[0].text == "display clock"


def test_auto_response_infinite_loop_action_round_trips() -> None:
    rule = AutoResponseRule(
        name="Infinite patrol",
        pattern="start",
        response="display clock\r",
        response_text="display clock",
        actions=[
            AutoResponseAction(
                kind="loop",
                repeat_count=0,
                interval_ms=1000,
                actions=[AutoResponseAction(kind="send", text="display clock", append_enter=True)],
            )
        ],
    )

    loaded = deserialize_auto_response_rule(serialize_auto_response_rule(rule))

    assert loaded is not None
    assert loaded.actions[0].kind == "loop"
    assert loaded.actions[0].repeat_count == 0


def test_auto_response_condition_action_round_trips() -> None:
    rule = AutoResponseRule(
        name="Conditional patrol",
        pattern="start",
        response="display clock\r",
        response_text="display clock",
        actions=[
            AutoResponseAction(
                kind="condition",
                condition_pattern=r">\s*$",
                condition_match_type="regex",
                actions=[AutoResponseAction(kind="send", text="display clock", append_enter=True)],
            )
        ],
    )

    loaded = deserialize_auto_response_rule(serialize_auto_response_rule(rule))

    assert loaded is not None
    assert loaded.actions[0].kind == "condition"
    assert loaded.actions[0].condition_pattern == r">\s*$"
    assert loaded.actions[0].condition_match_type == "regex"
    assert loaded.actions[0].actions[0].text == "display clock"


def test_auto_response_variable_action_round_trips() -> None:
    rule = AutoResponseRule(
        name="Incrementing ports",
        pattern="",
        response="",
        trigger_type="manual",
        actions=[
            AutoResponseAction(
                kind="set",
                variable_name="port",
                variable_value="2000",
                variable_operation="set",
            ),
            AutoResponseAction(
                kind="set",
                variable_name="port",
                variable_value="1",
                variable_operation="add",
            ),
        ],
    )

    loaded = deserialize_auto_response_rule(serialize_auto_response_rule(rule))

    assert loaded is not None
    assert loaded.actions[0].kind == "set"
    assert loaded.actions[0].variable_name == "port"
    assert loaded.actions[0].variable_value == "2000"
    assert loaded.actions[1].variable_operation == "add"


def test_create_auto_response_rule_accepts_infinite_loop_action(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    rule = window.create_auto_response_rule(
        name="Infinite patrol",
        pattern="",
        response_text="",
        trigger_type="manual",
        actions=[
            {
                "kind": "loop",
                "repeatCount": 0,
                "intervalMs": 1000,
                "actions": [
                    {
                        "kind": "send",
                        "text": "display clock",
                        "target": "current",
                        "appendEnter": True,
                    }
                ],
            }
        ],
    )

    assert rule is not None
    assert rule.actions[0].kind == "loop"
    assert rule.actions[0].repeat_count == 0


def test_add_auto_response_rule_quick_send_kind_creates_quick_button(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    original_count = len(window.remembered_quick_send_buttons)

    class Dialog:
        def __init__(self, parent: QWidget | None = None) -> None:
            self.parent = parent

        def exec(self) -> int:
            return QDialog.Accepted

        def values(self) -> dict[str, object]:
            return {
                "kind": "quick_send",
                "simple_rule_text": '按钮 "Ctrl+B" => Ctrl+B',
                "name": "",
                "response_text": "",
                "append_enter": False,
            }

    monkeypatch.setattr(window, "auto_response_rule_dialog_class", lambda: Dialog)

    window.add_auto_response_rule_for_session()

    assert len(window.remembered_quick_send_buttons) == original_count + 1
    button = window.remembered_quick_send_buttons[-1]
    assert button.name == "Ctrl+B"
    assert button.response == "\x02"


def test_deserialize_legacy_workflow_append_enter_backfills_actions() -> None:
    rule = deserialize_auto_response_rule(
        {
            "name": "Legacy login",
            "pattern": "login:",
            "response": "admin\r",
            "response_text": "admin",
            "append_enter": True,
            "steps": [
                {
                    "pattern": "login:",
                    "responses": ["admin\r", "display version\r"],
                    "response_texts": ["admin", "display version"],
                }
            ],
        }
    )

    assert rule is not None
    assert rule.steps[0].response_append_enters == [True, True]


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
            match_type="regex",
            delay_ms=150,
            max_triggers=3,
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
    assert loaded_rule.match_type == "regex"
    assert loaded_rule.delay_ms == 150
    assert loaded_rule.max_triggers == 3
    assert loaded_rule.trigger_count == 3


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
                    response_delays=[0, 1200],
                    response_append_enters=[False, True],
                    timeout_ms=15_000,
                ),
                AutoResponseStep(
                    pattern="ADMIN",
                    responses=["\x01"],
                    response_texts=["Ctrl+A"],
                    response_delays=[250],
                    response_append_enters=[False],
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
    assert loaded_rule.steps[0].response_delays == [0, 1200]
    assert loaded_rule.steps[0].response_append_enters == [False, True]
    assert loaded_rule.steps[0].timeout_ms == 15_000
    assert loaded_rule.steps[1].pattern == "ADMIN"
    assert loaded_rule.steps[1].response_delays == [250]
    assert loaded_rule.steps[1].response_append_enters == [False]
    assert loaded_rule.steps[1].timeout_ms == 0


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
    assert window.remembered_auto_response_rules[0].allow_startup_trigger


def test_old_boot_ctrl_b_rule_is_migrated_to_startup_trigger() -> None:
    rule = deserialize_auto_response_rule(
        {
            "name": "启动菜单 Ctrl+B",
            "pattern": "Ctrl+B",
            "response": "\x02",
            "response_text": "Ctrl+B",
            "enabled": True,
        }
    )

    assert rule is not None
    assert rule.allow_startup_trigger


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
    buttons = [
        window.auto_response_rule_bar_layout.itemAt(index).widget()
        for index in range(window.auto_response_rule_bar_layout.count())
    ]
    button = next(button for button in buttons if button is not None and button.isCheckable())
    assert not button.isChecked()
    assert button.property("waitingForInput") == "true"


def test_terminal_web_actions_include_quick_buttons_and_rule_state(app: QApplication, tmp_path) -> None:
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
    window.remembered_quick_send_buttons = [
        TerminalQuickButton(name="Send Ctrl+B", response="\x02", response_text="Ctrl+B")
    ]
    window.remembered_auto_response_rules = [
        AutoResponseRule(name="Password", pattern="Password:", response="admin\r")
    ]

    actions = window.terminal_web_actions(state)

    assert actions[0]["kind"] == "quick"
    assert actions[0]["label"]
    assert actions[1]["kind"] == "rule"
    assert actions[1]["status"] == "waiting"
    assert actions[1]["checked"] is False


def test_terminal_web_quick_action_sends_to_action_tab(app: QApplication, tmp_path) -> None:
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
    window.session_tabs_by_id[state.tab_id] = state
    button = TerminalQuickButton(name="Send Ctrl+B", response="\x02", response_text="Ctrl+B")
    window.remembered_quick_send_buttons = [button]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.handle_terminal_web_action(state.tab_id, {"kind": "quick", "index": 0})

    assert sent == [(state.tab_id, "\x02")]
    assert button.trigger_count == 1


def test_startup_auto_response_rule_stays_active_without_session(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.current_session_state = lambda: None  # type: ignore[method-assign]
    window.remembered_auto_response_rules = [
        AutoResponseRule(
            name="启动菜单 Ctrl+B",
            pattern="Ctrl+B",
            response="\x02",
            allow_startup_trigger=True,
        )
    ]

    window.refresh_auto_response_rule_buttons()

    buttons = [
        window.auto_response_rule_bar_layout.itemAt(index).widget()
        for index in range(window.auto_response_rule_bar_layout.count())
    ]
    button = next(button for button in buttons if button is not None and button.isCheckable())
    assert button.isChecked()
    assert button.property("waitingForInput") == "false"


def test_auto_response_rule_bar_renders_all_items_without_overflow_label(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.current_session_state = lambda: None  # type: ignore[method-assign]
    window.remembered_quick_send_buttons = [
        TerminalQuickButton(name=f"Send {index}", response=f"cmd{index}\r", response_text=f"cmd{index}")
        for index in range(4)
    ]
    window.remembered_auto_response_rules = [
        AutoResponseRule(name=f"Rule {index}", pattern=f"P{index}", response=f"r{index}\r")
        for index in range(5)
    ]

    window.refresh_auto_response_rule_buttons()

    widgets = [
        window.auto_response_rule_bar_layout.itemAt(index).widget()
        for index in range(window.auto_response_rule_bar_layout.count())
    ]
    action_buttons = [
        widget
        for widget in widgets
        if widget is not None and widget.objectName() == "autoResponseRuleButton"
    ]
    overflow_labels = [
        widget
        for widget in widgets
        if widget is not None and widget.objectName() == "autoResponseOverflowLabel"
    ]
    assert len(action_buttons) == 9
    assert overflow_labels == []
    assert not window.auto_response_rule_bar.isHidden()


def test_auto_response_rule_button_shows_waiting_state_before_user_input(
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
    window.remembered_auto_response_rules = [
        AutoResponseRule(name="Admin", pattern="ADMIN", response="\x01")
    ]

    window.refresh_auto_response_rule_buttons()

    buttons = [
        window.auto_response_rule_bar_layout.itemAt(index).widget()
        for index in range(window.auto_response_rule_bar_layout.count())
    ]
    button = next(button for button in buttons if button is not None and button.isCheckable())
    assert button is not None
    assert not button.isChecked()
    assert button.property("waitingForInput") == "true"

    state.user_input_seen = True
    state.suppress_auto_response_until_input = False
    window.refresh_auto_response_rule_buttons()

    buttons = [
        window.auto_response_rule_bar_layout.itemAt(index).widget()
        for index in range(window.auto_response_rule_bar_layout.count())
    ]
    button = next(button for button in buttons if button is not None and button.isCheckable())
    assert button is not None
    assert button.isChecked()
    assert button.property("waitingForInput") == "false"


def test_send_ctrl_b_is_direct_button_for_current_session(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
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


def test_command_record_suggestions_fill_current_line(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.command_history = [
        CommandHistoryItem(command="display version", count=2, last_used_at=100),
    ]

    window.command_record_input.setPlainText("dis")
    window.refresh_command_suggestions()

    assert window.current_command_suggestions[0] == "display version"
    assert window.command_suggestion_bar.isHidden()
    assert window.accept_first_command_suggestion()
    assert window.command_record_input.current_command_line() == "display version"


def test_command_record_suggestions_include_saved_command_lines(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.command_record_groups[window.current_command_group_index()]["content"] = "star\nlay versionadmin\nsta"
    window._load_current_command_content(move_cursor_to_end=True)

    window.refresh_command_suggestions()

    assert window.current_command_suggestions[0] == "star"
    assert window.command_suggestion_bar.isHidden()


def test_terminal_command_suggestion_uses_history_and_defaults(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SimpleNamespace(device_id="sim-terminal", kind="simulated")

    assert window.terminal_command_suggestion(state, "re") == "reboot"

    window.remember_command_history("reset board", state=state)

    assert window.terminal_command_suggestion(state, "res") == "reset board"


def test_terminal_command_suggestions_return_ranked_candidates(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = SimpleNamespace(device_id="sim-terminal", kind="simulated")
    window.remember_command_history("reset board", state=state)
    window.remember_command_history("reboot", state=state)

    suggestions = window.terminal_command_suggestions(state, "re", limit=3)

    assert suggestions[:2] == ["reboot", "reset board"]
    assert len(suggestions) <= 3


def test_auto_response_rule_sends_when_split_output_matches(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(name="Boot Ctrl+B", pattern="Ctrl+B", response="\x02")
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "Press Ctrl+")
    window.apply_auto_response_rules(state, "B to enter menu")

    assert sent == [("device:device:1", "\x02")]
    assert not rule.enabled
    assert window.auto_response_rule_signature(rule) in state.auto_response_triggered_rules
    assert "Auto response sent: Boot Ctrl+B" in state.log_path.read_text(encoding="utf-8")


def test_auto_response_rule_ignores_initial_session_output_until_user_input(
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
    rule = AutoResponseRule(name="Manual Ctrl+B", pattern="Ctrl+B", response="\x02")
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "Press Ctrl+B to enter menu")

    assert sent == []
    assert state.auto_response_buffer == ""


def test_auto_response_rule_can_match_initial_output_when_allowed(
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
        name="Boot Ctrl+B",
        pattern="Ctrl+B",
        response="\x02",
        allow_startup_trigger=True,
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "Press Ctrl+B to enter menu")

    assert sent == [("device:device:1", "\x02")]


def test_auto_response_workflow_sends_multiple_actions_then_waits_for_next_match(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
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


def test_auto_response_action_flow_runs_loop_actions(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="动作流",
        pattern="start",
        response="\x02",
        response_text="Ctrl+B",
        actions=[
            AutoResponseAction(kind="send", text="Ctrl+B", target="current"),
            AutoResponseAction(
                kind="loop",
                repeat_count=3,
                interval_ms=0,
                actions=[
                    AutoResponseAction(
                        kind="send",
                        text="display clock",
                        target="current",
                        append_enter=True,
                    )
                ],
            ),
        ],
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "start")

    assert sent == [
        ("device:device:1", "\x02"),
        ("device:device:1", "display clock\r"),
        ("device:device:1", "display clock\r"),
        ("device:device:1", "display clock\r"),
    ]


def test_auto_response_loop_can_run_conditional_actions(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="Conditional loop",
        pattern="start",
        response="display clock\r",
        response_text="display clock",
        actions=[
            AutoResponseAction(
                kind="loop",
                repeat_count=2,
                interval_ms=0,
                actions=[
                    AutoResponseAction(
                        kind="condition",
                        condition_pattern=">",
                        condition_match_type="contains",
                        actions=[
                            AutoResponseAction(
                                kind="send",
                                text="display clock",
                                target="current",
                                append_enter=True,
                            )
                        ],
                    )
                ],
            ),
        ],
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "start>")

    assert sent == [
        ("device:device:1", "display clock\r"),
        ("device:device:1", "display clock\r"),
    ]


def test_running_auto_response_button_stop_cancels_queued_actions(
    app: QApplication,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="Manual delayed",
        pattern="",
        response="display clock\r",
        response_text="display clock",
        trigger_type="manual",
        actions=[
            AutoResponseAction(
                kind="send",
                text="display clock",
                target="current",
                append_enter=True,
                delay_ms=1000,
            )
        ],
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    scheduled: list[tuple[int, object]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]
    monkeypatch.setattr(
        "src.app.session_ops.QTimer",
        SimpleNamespace(singleShot=lambda delay, callback: scheduled.append((delay, callback))),
    )

    window.toggle_auto_response_rule_from_button(rule, True)

    signature = window.auto_response_rule_signature(rule)
    assert signature in state.auto_response_running_rules
    assert window.auto_response_rule_effective_status(rule, state)["status"] == "running"

    window.toggle_auto_response_rule_from_button(rule, False)

    assert signature not in state.auto_response_running_rules
    for _delay, callback in scheduled:
        callback()
    assert sent == []


def test_auto_response_workflow_respects_case_sensitive_matching(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
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
    source_state = _allow_auto_response(SessionTabState(
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
    ))
    target_state = _allow_auto_response(SessionTabState(
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
    ))
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
    state = _allow_auto_response(SessionTabState(
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
    ))
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
    state = _allow_auto_response(SessionTabState(
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
    ))
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
    state = _allow_auto_response(SessionTabState(
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
    ))
    window.remembered_auto_response_rules = [
        AutoResponseRule(name="Admin Ctrl+A", pattern="ADMIN", response="\x01")
    ]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "")

    assert sent == [("device:device:1", "\x01")]


def test_immediate_auto_response_runs_without_output_match(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="Init",
        pattern="",
        response="display version\r",
        response_text="display version",
        trigger_type="immediate",
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "", trigger_event="immediate")

    assert sent == [("device:device:1", "display version\r")]
    assert window.auto_response_rule_signature(rule) in state.auto_response_triggered_rules


def test_connected_auto_response_runs_action_only_workflow(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="Connected init",
        pattern="",
        response="system-view\r",
        response_text="system-view",
        trigger_type="connected",
        steps=[
            AutoResponseStep(
                pattern="",
                responses=["system-view\r", "display clock\r"],
                response_texts=["system-view", "display clock"],
                response_targets=["current", "current"],
                response_delays=[0, 0],
                response_append_enters=[True, True],
            )
        ],
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "", trigger_event="connected")

    assert sent == [
        ("device:device:1", "system-view\r"),
        ("device:device:1", "display clock\r"),
    ]


def test_auto_response_workflow_can_loop_without_output_match(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="Loop",
        pattern="",
        response="display clock\r",
        response_text="display clock",
        trigger_type="immediate",
        loop_count=3,
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "", trigger_event="immediate")

    assert sent == [
        ("device:device:1", "display clock\r"),
        ("device:device:1", "display clock\r"),
        ("device:device:1", "display clock\r"),
    ]
    assert rule.trigger_count == 3


def test_manual_auto_response_button_runs_even_when_unchecked(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="Manual patrol",
        pattern="",
        response="display clock\r",
        response_text="display clock",
        trigger_type="manual",
        kind="manual_loop",
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.toggle_auto_response_rule_from_button(rule, False)

    assert sent == [("device:device:1", "display clock\r")]


def test_delay_trigger_schedules_automation_start(
    app: QApplication,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="Delayed",
        pattern="",
        response="display version\r",
        response_text="display version",
        trigger_type="delay",
        trigger_delay_ms=1500,
    )
    window.remembered_auto_response_rules = [rule]
    window.session_tabs_by_id = {state.tab_id: state}
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    scheduled: list[tuple[int, object]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]
    monkeypatch.setattr(
        "src.app.session_ops.QTimer",
        SimpleNamespace(singleShot=lambda delay, callback: scheduled.append((delay, callback))),
    )

    window.apply_auto_response_rules(state, "", trigger_event="connected")

    assert sent == []
    assert len(scheduled) == 1
    delay, callback = scheduled[0]
    assert delay == 1500
    callback()
    assert sent == [("device:device:1", "display version\r")]


def test_auto_response_trigger_and_loop_fields_round_trip() -> None:
    rule = AutoResponseRule(
        name="Init",
        pattern="",
        response="display version\r",
        trigger_type="connected",
        trigger_delay_ms=300,
        loop_count=4,
    )

    loaded = deserialize_auto_response_rule(serialize_auto_response_rule(rule))

    assert loaded is not None
    assert loaded.trigger_type == "connected"
    assert loaded.trigger_delay_ms == 300
    assert loaded.loop_count == 4


def test_auto_response_regex_rule_matches_terminal_output(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    window.remembered_auto_response_rules = [
        AutoResponseRule(
            name="Password",
            pattern=r"Password:\s*$",
            response="admin\r",
            match_type="regex",
        )
    ]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, "Password: ")

    assert sent == [("device:device:1", "admin\r")]


def test_auto_response_rule_honors_max_triggers(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="Prompt",
        pattern=">",
        response="display version\r",
        once=False,
        max_triggers=2,
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(state, ">")
    window.apply_auto_response_rules(state, ">")
    window.apply_auto_response_rules(state, ">")

    assert sent == [
        ("device:device:1", "display version\r"),
        ("device:device:1", "display version\r"),
    ]
    assert rule.trigger_count == 2
    assert not rule.enabled


def test_auto_response_rule_can_delay_sending(
    app: QApplication,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(name="Prompt", pattern=">", response="display clock\r", delay_ms=300)
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    scheduled: list[tuple[int, object]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]
    monkeypatch.setattr(
        "src.app.session_ops.QTimer",
        SimpleNamespace(singleShot=lambda delay, callback: scheduled.append((delay, callback))),
    )

    window.apply_auto_response_rules(state, ">")

    assert sent == []
    assert len(scheduled) == 1
    delay, callback = scheduled[0]
    assert delay == 300
    callback()
    assert sent == [("device:device:1", "display clock\r")]


def test_auto_response_workflow_can_delay_between_responses(
    app: QApplication,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
    rule = AutoResponseRule(
        name="Boot sequence",
        pattern="Ctrl+B",
        response="\x02",
        steps=[
            AutoResponseStep(
                pattern="Ctrl+B",
                responses=["\x02", "display version\r"],
                response_texts=["Ctrl+B", "display version"],
                response_targets=["source", "source"],
                response_delays=[0, 1000],
            )
        ],
    )
    window.remembered_auto_response_rules = [rule]
    window.current_session_state = lambda: state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    scheduled: list[tuple[int, object]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]
    monkeypatch.setattr(
        "src.app.session_ops.QTimer",
        SimpleNamespace(singleShot=lambda delay, callback: scheduled.append((delay, callback))),
    )

    window.apply_auto_response_rules(state, "Press Ctrl+B to enter menu")

    assert sent == [("device:device:1", "\x02")]
    assert len(scheduled) == 1
    delay, callback = scheduled[0]
    assert delay == 1000
    callback()
    assert sent == [("device:device:1", "\x02"), ("device:device:1", "display version\r")]


def test_auto_response_rule_ignores_stale_buffer_on_new_output(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state = _allow_auto_response(SessionTabState(
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
    ))
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
    selected_state = _allow_auto_response(SessionTabState(
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
    ))
    background_state = _allow_auto_response(SessionTabState(
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
    ))
    window.remembered_auto_response_rules = [
        AutoResponseRule(name="Boot Ctrl+B", pattern="Ctrl+B", response="\x02")
    ]
    window.current_session_state = lambda: selected_state  # type: ignore[method-assign]
    sent: list[tuple[str, str]] = []
    window.send_session_text = lambda tab_id, text: sent.append((tab_id, text))  # type: ignore[method-assign]

    window.apply_auto_response_rules(background_state, "Press Ctrl+B to enter menu")
    window.apply_auto_response_rules(selected_state, "Press Ctrl+B to enter menu")

    assert sent == [("device:device:1", "\x02")]

