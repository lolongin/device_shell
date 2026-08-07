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


def test_breadcrumb_device_label_click_activates_device(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ = app
    window = DeviceDesktopApp()
    calls: list[str] = []
    monkeypatch.setattr(window, "activate_device", lambda device_id: calls.append(device_id))
    window.session_breadcrumb_device_label.setProperty("deviceId", "crumb-device-0")
    window.session_breadcrumb_device_label.mousePressEvent(None)
    assert calls == ["crumb-device-0"]
    window.close()


def test_breadcrumb_device_label_has_clickable_cursor(app: QApplication) -> None:
    """The breadcrumb shows only the device name, which must be clickable."""
    _ = app
    window = DeviceDesktopApp()
    from PySide6.QtCore import Qt

    assert window.session_breadcrumb_device_label.cursor().shape() == Qt.PointingHandCursor
    assert not hasattr(window, "session_breadcrumb_session_label")
    window.close()


def _device_tabs(window: DeviceDesktopApp):
    devices = sample_devices()[:2]
    for index, device in enumerate(devices):
        device.id = f"switch-device-{index}"
        device.name = f"切换设备 {index + 1}"
    window.devices = devices
    window.rebuild_device_indexes()
    return [window.ensure_device_tab(device) for device in devices]


def test_apply_layout_state_side_hides_tab_bars_shows_panel(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window)

    window.session_tab_layout = "side"
    window.apply_session_layout_state()

    window.show()
    QApplication.processEvents()

    assert not window.session_tab_widget.tabBar().isVisible()
    assert window.session_manager_panel.isVisible()
    assert window.session_breadcrumb.isVisible()
    window.close()


def test_apply_layout_state_top_restores_tab_bars(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window)

    window.session_tab_layout = "top"
    window.apply_session_layout_state()

    window.show()
    QApplication.processEvents()

    assert window.session_tab_widget.tabBar().isVisible()
    assert not window.session_manager_panel.isVisible()
    assert not window.session_breadcrumb.isVisible()
    window.close()
