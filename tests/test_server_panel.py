"""Tests for the saved SSH server panel."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from src.app import server_ops as server_ops_module
from src.app.main_window import DeviceDesktopApp
from src.data import SavedServer


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_server_panel_distinguishes_empty_search(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.saved_servers = [
        SavedServer(
            id="srv-prod",
            name="生产跳板机",
            host="10.0.0.8",
            username="ops",
            group="生产",
        )
    ]
    window._refresh_server_panel()

    window.server_search_input.setText("missing")

    assert not window.server_empty_label.isHidden()
    assert "没有匹配" in window.server_empty_label.text()

    window.server_search_input.setText("")

    assert window.server_empty_label.isHidden()


def test_server_card_left_click_opens_session(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = app
    window = DeviceDesktopApp()
    server = SavedServer(id="srv-click", name="点击连接", host="10.0.0.9")
    opened: list[str] = []
    monkeypatch.setattr(window, "_open_server_session", lambda selected: opened.append(selected.id))

    card = window._server_card(server)
    event = SimpleNamespace(button=lambda: Qt.LeftButton)

    window._handle_server_card_press(event, server)

    assert card.objectName() == "serverCard"
    assert opened == ["srv-click"]


def test_server_card_omits_redundant_group_pill(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    card = window._server_card(
        SavedServer(id="srv-grouped", name="分组服务器", host="10.0.0.7", group="实验室")
    )

    assert card.findChildren(QLabel, "serverCardPill") == []


def test_create_server_group_keeps_empty_group_visible(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    monkeypatch.setattr(
        server_ops_module.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("实验室", True),
    )

    group_name = window._create_server_group()

    titles = [label.text() for label in window.server_list_container.findChildren(QLabel, "serverGroupTitle")]
    assert group_name == "实验室"
    assert window.saved_server_groups == ["实验室"]
    assert "实验室  (0)" in titles


def test_move_server_to_group_updates_server_and_groups(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    server = SavedServer(id="srv-move", name="可移动服务器", host="10.0.0.14", group="A")
    window.saved_server_groups = ["A", "B"]
    window.saved_servers = [server]

    window._move_server_to_group(server, "B")

    assert window.saved_servers[0].group == "B"
    assert window.saved_server_groups == ["A", "B"]


def test_duplicate_server_detection_ignores_current_edit_target(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    existing = SavedServer(id="srv-existing", name="已有服务器", host="10.0.0.13", port=22)
    window.saved_servers = [existing]

    assert window._find_duplicate_server("10.0.0.13", 22) == existing
    assert window._find_duplicate_server("10.0.0.13", 22, ignore_id="srv-existing") is None


def test_saved_server_groups_round_trip_desktop_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()
    first.saved_server_groups = ["实验室", "生产"]

    first.save_desktop_state()
    second = DeviceDesktopApp()

    assert second.saved_server_groups == ["实验室", "生产"]


def test_saved_server_can_be_resolved_for_session_restore(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.saved_servers = [
        SavedServer(
            id="srv-restore",
            name="恢复服务器",
            host="10.0.0.10",
            port=2222,
            username="root",
            password="secret",
        )
    ]
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(window, "ordered_session_states", lambda: [])
    monkeypatch.setattr(
        window,
        "ensure_session_tab",
        lambda **kwargs: calls.append(kwargs) or SimpleNamespace(tab_id="restored"),
    )

    result = window.restore_remembered_terminal_session(
        {
            "device_id": "srv-restore",
            "kind": "linux",
            "title": "恢复服务器",
            "host": "10.0.0.10",
            "port": 2222,
        }
    )

    assert result is not None
    assert calls[0]["device"].name == "恢复服务器"
    assert calls[0]["username"] == "root"
    assert calls[0]["password"] == "secret"


def test_saved_server_session_keeps_only_ssh_quick_action_enabled(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.saved_servers = [
        SavedServer(id="srv-actions", name="快捷动作服务器", host="10.0.0.11", username="root")
    ]
    monkeypatch.setattr(
        window,
        "current_session_state",
        lambda: SimpleNamespace(
            device_id="srv-actions",
            connecting=False,
            session=SimpleNamespace(is_connected=False),
        ),
    )

    window.update_controls()

    assert not window.connection_telnet_button.isEnabled()
    assert window.connection_ssh_button.isEnabled()
    assert not window.connection_serial_button.isEnabled()
