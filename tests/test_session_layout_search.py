from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _device_with_session(window: DeviceDesktopApp):
    device = sample_devices()[0]
    device.id = "search-device-0"
    device.name = "搜索路由器"
    window.devices = [device]
    window.rebuild_device_indexes()
    state = window.ensure_session_tab(
        kind="simulated",
        device=device,
        host=device.ssh_ip or "10.0.0.1",
        port=device.ssh_port or 22,
        username="admin",
        password="secret",
        title="SSH 搜索会话",
        suppress_initial_error=True,
    )
    return state


def test_search_filters_tree_by_session_title(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_with_session(window)
    window.refresh_session_manager_tree()
    tree = window.session_manager_tree

    window.session_manager_search.setText("搜索会话")
    window.refresh_session_manager_tree()

    # matching child remains, top-level count preserved
    assert tree.topLevelItemCount() == 1
    window.session_manager_search.clear()
    window.close()
