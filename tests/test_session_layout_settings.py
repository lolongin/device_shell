from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_settings_button_sits_at_activity_rail_bottom(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.settings_button is not None
    assert window.settings_button.objectName() == "activityRailButton"
    assert window.settings_button.parent() is window.activity_rail
    assert not window.settings_button.isCheckable()
    window.close()


def test_settings_layout_combo_changes_session_layout(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.settings_layout_combo.setCurrentText("右侧")
    assert window.session_tab_layout == "side"
    window.settings_layout_combo.setCurrentText("顶部")
    assert window.session_tab_layout == "top"
    window.close()


def test_settings_font_spin_applies_font_size(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.settings_font_spin.setValue(18)
    assert window.terminal_font_size == 18
    window.close()
