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


def test_new_session_terminal_gets_persisted_font_size(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.terminal_font_size = 18
    _device_tabs(window)
    monkeypatch.setattr(window, "connect_session_tab", lambda tab_id: None)
    device = window.devices[0]
    state = window.ensure_session_tab(
        kind="simulated",
        device=device,
        host=device.ssh_ip or "10.0.0.1",
        port=device.ssh_port or 22,
        username="admin",
        password="secret",
        title="SSH 字体",
        suppress_initial_error=True,
    )
    # The newly created terminal carries the configured font size, not the xterm
    # default of 14.
    assert state.terminal._font_size == 18
    window.close()


def test_refresh_workspace_context_applies_font_to_all_terminals(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = app
    window = DeviceDesktopApp()
    calls: list[int] = []
    monkeypatch.setattr(
        window,
        "apply_font_size_to_all_terminals",
        lambda: calls.append(1),
    )
    window.refresh_workspace_context()
    assert calls == [1]
    window.close()


def test_session_manager_context_menu_builds_workspace_menu(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window)
    window.session_manager_custom_context_menu(None)  # no crash with no item
    window.close()
