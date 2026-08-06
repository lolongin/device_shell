from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_split_tab_bar_hidden_in_side_layout(app: QApplication) -> None:
    """In the side (right) layout, a newly created split tab widget's tab bar
    must be hidden — the top tab bar is replaced by the right session manager."""
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_layout = "side"
    window.apply_session_layout_state()
    window.show()
    QApplication.processEvents()
    parent = QWidget()
    tabs = window.create_session_tab_widget("layout-visibility-device", parent)
    parent.show()
    QApplication.processEvents()
    try:
        assert not tabs.tabBar().isVisible()
    finally:
        window.close()


def test_split_tab_bar_visible_in_top_layout(app: QApplication) -> None:
    """In the top layout, a newly created split tab widget's tab bar stays
    visible so sessions are switchable from the top."""
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_layout = "top"
    window.apply_session_layout_state()
    window.show()
    QApplication.processEvents()
    parent = QWidget()
    tabs = window.create_session_tab_widget("layout-visibility-device", parent)
    parent.show()
    QApplication.processEvents()
    try:
        assert tabs.tabBar().isVisible()
    finally:
        window.close()
