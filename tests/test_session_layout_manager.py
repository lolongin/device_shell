from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTreeWidget

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _device_tabs(window: DeviceDesktopApp, count: int = 2):
    devices = sample_devices()[:count]
    for index, device in enumerate(devices):
        device.id = f"layout-device-{index}"
        device.name = f"设备 {index + 1}"
    window.devices = devices
    window.rebuild_device_indexes()
    return [window.ensure_device_tab(device) for device in devices]


def test_manager_panel_built_as_third_splitter_child(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.main_splitter.count() == 3
    assert window.session_manager_panel is not None
    assert window.session_manager_tree is not None
    # The default "top" layout keeps the right manager hidden.
    window.show()
    QApplication.processEvents()
    assert not window.session_manager_panel.isVisible()
    window.close()


def test_tree_populates_with_device_and_session_items(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    states = _device_tabs(window)
    # Avoid real terminal connections while opening the simulated sessions.
    monkeypatch.setattr(window, "connect_session_tab", lambda tab_id: None)
    for index, device in enumerate(window.devices):
        window.ensure_session_tab(
            kind="simulated",
            device=device,
            host=device.ssh_ip or "10.0.0.1",
            port=device.ssh_port or 22,
            username="admin",
            password="secret",
            title=f"SSH {index + 1}",
            suppress_initial_error=True,
        )
    tree: QTreeWidget = window.session_manager_tree

    window.refresh_session_manager_tree()

    assert tree.topLevelItemCount() == len(states)
    assert window.session_manager_count_label.text().startswith("共")
    window.close()


def test_tree_items_have_status_dot_icons(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window, count=1)
    monkeypatch.setattr(window, "connect_session_tab", lambda tab_id: None)
    device = window.devices[0]
    window.ensure_session_tab(
        kind="simulated",
        device=device,
        host=device.ssh_ip or "10.0.0.1",
        port=device.ssh_port or 22,
        username="admin",
        password="secret",
        title="SSH 状态点",
        suppress_initial_error=True,
    )
    window.refresh_session_manager_tree()
    tree: QTreeWidget = window.session_manager_tree

    assert tree.topLevelItemCount() == 1
    parent = tree.topLevelItem(0)
    assert parent is not None
    assert not parent.icon(0).isNull()
    child = parent.child(0)
    assert child is not None
    assert not child.icon(0).isNull()
    window.close()


def test_collapsed_device_groups_pruned_to_existing_tabs(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    _device_tabs(window, count=1)
    window.collapsed_device_groups = ["layout-device-0", "stale-device-9"]

    window.refresh_session_manager_tree()

    assert window.collapsed_device_groups == ["layout-device-0"]
    window.close()
