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


def _setup_devices(window: DeviceDesktopApp, count: int = 2) -> list[object]:
    from src._sample_data import sample_devices

    devices = sample_devices()[:count]
    for index, device in enumerate(devices):
        device.id = f"vis-device-{index}"
        device.name = f"可见设备 {index + 1}"
    window.devices = devices
    window.rebuild_device_indexes()
    return devices


def _open_session(window: DeviceDesktopApp, device: object, title: str) -> None:
    window.ensure_session_tab(
        kind="simulated",
        device=device,
        host="10.0.0.1",
        port=22,
        username="admin",
        password="secret",
        title=title,
        suppress_initial_error=True,
    )


def _session_tabs_for(window: DeviceDesktopApp, device_id: str):
    device_tab = window.device_tabs_by_id[device_id]
    return window.session_tab_widgets_for_device(device_tab)[0]


def test_side_layout_shows_only_active_device_session_bars(app: QApplication) -> None:
    """In side layout the active device's session tab bar shows; inactive
    devices' bars and the device-level bar stay hidden."""
    _ = app
    window = DeviceDesktopApp()
    devices = _setup_devices(window, count=2)
    _open_session(window, devices[0], "会话 A")
    _open_session(window, devices[1], "会话 B")  # B becomes the active device
    window.session_tab_layout = "side"
    window.apply_session_layout_state()
    window.show()
    QApplication.processEvents()
    tabs_a = _session_tabs_for(window, devices[0].id)
    tabs_b = _session_tabs_for(window, devices[1].id)
    try:
        assert not window.session_tab_widget.tabBar().isVisible()
        assert tabs_b.tabBar().isVisible()
        assert not tabs_a.tabBar().isVisible()
    finally:
        window.close()


def test_side_layout_hides_inactive_device_without_sessions(app: QApplication) -> None:
    """A device tab with no sessions is inactive; its (empty) session bar stays
    hidden while the active device's bar shows."""
    _ = app
    window = DeviceDesktopApp()
    devices = _setup_devices(window, count=2)
    window.ensure_device_tab(devices[0])  # open device tab, no sessions
    window.ensure_device_tab(devices[1])  # active device
    _open_session(window, devices[1], "会话 B")
    window.session_tab_layout = "side"
    window.apply_session_layout_state()
    window.show()
    QApplication.processEvents()
    tabs_a = _session_tabs_for(window, devices[0].id)
    tabs_b = _session_tabs_for(window, devices[1].id)
    try:
        assert not window.session_tab_widget.tabBar().isVisible()
        assert tabs_b.tabBar().isVisible()
        assert not tabs_a.tabBar().isVisible()
    finally:
        window.close()
