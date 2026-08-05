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


def _device_tabs(window: DeviceDesktopApp):
    devices = sample_devices()[:2]
    for index, device in enumerate(devices):
        device.id = f"menu-device-{index}"
        device.name = f"菜单设备 {index + 1}"
    window.devices = devices
    window.rebuild_device_indexes()
    return [window.ensure_device_tab(device) for device in devices]


def test_apply_font_size_to_terminal_calls_set_font_size(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    calls: list[int] = []
    terminal = type("T", (), {"set_font_size": lambda self, n: calls.append(n)})()
    window.apply_font_size_to_terminal(terminal, 18)
    assert calls == [18]
    window.close()


def test_session_manager_context_menu_builds_workspace_menu(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window)
    window.session_manager_custom_context_menu(None)  # no crash with no item
    window.close()
