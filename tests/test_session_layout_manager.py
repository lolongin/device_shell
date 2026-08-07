from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QHeaderView, QTreeWidget

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


def test_tree_columns_stretch_proportionally(app: QApplication) -> None:
    """Both session-manager tree columns use Stretch mode so the metadata column
    (count / protocol·host:port) shares width with the name column instead of the
    last column absorbing all leftover space."""
    _ = app
    window = DeviceDesktopApp()
    tree: QTreeWidget = window.session_manager_tree
    header = tree.header()
    assert header.stretchLastSection() is False
    assert header.sectionResizeMode(0) == QHeaderView.Stretch
    assert header.sectionResizeMode(1) == QHeaderView.Stretch
    window.close()


def test_tree_has_two_columns_with_session_metadata(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
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
        title="SSH 双列",
        suppress_initial_error=True,
    )
    window.refresh_session_manager_tree()
    tree: QTreeWidget = window.session_manager_tree

    assert tree.columnCount() == 2
    child = tree.topLevelItem(0).child(0)
    assert child is not None
    assert not child.icon(0).isNull()
    assert "SSH 双列" in child.text(0)
    assert "模拟" in child.text(1)
    assert (device.ssh_ip or "10.0.0.1") in child.text(1)
    assert str(device.ssh_port or 22) in child.text(1)
    window.close()


def test_device_parent_column1_shows_session_count(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
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
        title="SSH 计数",
        suppress_initial_error=True,
    )
    window.ensure_session_tab(
        kind="simulated",
        device=device,
        host=device.ssh_ip or "10.0.0.1",
        port=device.ssh_port or 23,
        username="admin",
        password="secret",
        title="SSH 计数 2",
        suppress_initial_error=True,
    )
    window.refresh_session_manager_tree()
    tree: QTreeWidget = window.session_manager_tree

    parent = tree.topLevelItem(0)
    assert parent is not None
    assert parent.text(0) == device.name
    assert not parent.icon(0).isNull()
    assert parent.text(1) == "2"
    assert parent.childCount() == 2
    window.close()


def test_new_terminal_button_removed(app: QApplication) -> None:
    """The '＋ 新建终端' footer button was removed from the session-manager
    panel (sessions are opened from the device pool / terminal, not here)."""
    _ = app
    window = DeviceDesktopApp()
    assert not hasattr(window, "_session_manager_new_terminal")
    # No footer "新建终端" button should exist under the panel.
    from PySide6.QtWidgets import QPushButton

    buttons = window.session_manager_panel.findChildren(QPushButton)
    labels = [b.text() for b in buttons]
    assert not any("新建终端" in t for t in labels), f"new-terminal button still present: {labels}"
    window.close()


def test_toggle_all_session_groups_expands_and_collapses(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The expand/collapse-all button toggles every device group in the tree."""
    _ = app
    window = DeviceDesktopApp()
    monkeypatch.setattr(window, "connect_session_tab", lambda tab_id: None)
    devices = sample_devices()[:2]
    for index, device in enumerate(devices):
        device.id = f"expand-all-{index}"
        device.name = f"展开设备 {index + 1}"
    window.devices = devices
    window.rebuild_device_indexes()
    for index, device in enumerate(devices):
        window.ensure_session_tab(
            kind="simulated", device=device, host="10.0.0.1", port=22,
            username="admin", password="secret", title=f"会话 {index}",
            suppress_initial_error=True,
        )
    window.refresh_session_manager_tree()
    tree = window.session_manager_tree
    assert tree.topLevelItemCount() == 2
    # Collapse all.
    window.session_manager_expand_all_button.setChecked(True)
    window.toggle_all_session_groups_expanded()
    assert all(not tree.topLevelItem(i).isExpanded() for i in range(2))
    assert window.collapsed_device_groups == sorted(device.id for device in devices)
    # Expand all.
    window.session_manager_expand_all_button.setChecked(False)
    window.toggle_all_session_groups_expanded()
    assert all(tree.topLevelItem(i).isExpanded() for i in range(2))
    assert window.collapsed_device_groups == []
    window.close()
