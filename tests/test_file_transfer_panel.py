"""Tests for the local file transfer service panel."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_file_transfer_panel_exists_in_left_sidebar(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    window.show_left_sidebar_panel("transfer")

    assert window.left_sidebar_active_panel == "transfer"
    assert window.left_sidebar_stack.currentIndex() == 2
    assert window.transfer_protocol_combo.currentText() in {"FTP", "SFTP"}
    assert window.transfer_start_button.text() == "启动服务"


def test_file_transfer_default_port_tracks_protocol(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    window.transfer_port_input.setText("21")
    window.update_transfer_default_port("SFTP")

    assert window.transfer_port_input.text() == "2222"

    window.transfer_port_input.setText("2222")
    window.update_transfer_default_port("FTP")

    assert window.transfer_port_input.text() == "2121"


def test_file_transfer_config_round_trips_desktop_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    root = tmp_path / "share"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()
    first.transfer_protocol = "sftp"
    first.transfer_host = "127.0.0.1"
    first.transfer_port = 2022
    first.transfer_root_directory = root
    first.transfer_username = "uploader"
    first.transfer_password = "secret"
    first.transfer_writable = False

    first.save_desktop_state()
    second = DeviceDesktopApp()

    assert second.transfer_protocol == "sftp"
    assert second.transfer_host == "127.0.0.1"
    assert second.transfer_port == 2022
    assert second.transfer_root_directory == root
    assert second.transfer_username == "uploader"
    assert second.transfer_password == "secret"
    assert not second.transfer_writable
