from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _state_path(window: DeviceDesktopApp) -> Path:
    return Path(window.state_path)


def test_session_layout_defaults(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.session_tab_layout == "top"
    assert window.terminal_font_size == 14
    assert window.session_manager_default_collapsed is False
    assert window.session_manager_width == 260
    assert window.session_manager_collapsed is False
    assert window.collapsed_device_groups == []
    window.close()


def test_session_layout_round_trip(app: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_layout = "side"
    window.terminal_font_size = 18
    window.session_manager_width = 340
    window.session_manager_collapsed = True
    window.collapsed_device_groups = ["R1-核心"]
    window.save_desktop_state()

    saved = json.loads(_state_path(window).read_text(encoding="utf-8"))
    assert saved["version"] == 14
    assert saved["session_layout"]["session_tab_layout"] == "side"
    assert saved["session_layout"]["terminal_font_size"] == 18
    assert saved["session_layout"]["session_manager_width"] == 340
    assert saved["session_layout"]["session_manager_collapsed"] is True
    assert saved["session_layout"]["collapsed_device_groups"] == ["R1-核心"]

    window.close()
