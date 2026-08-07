from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp


class _FakeMenu:
    """A plain-Python menu stand-in: its exec() returns the action we inject,
    so we never hit Qt's native popup (which cannot run offscreen)."""

    def __init__(self, result: object) -> None:
        self._result = result

    def exec(self, pos: object = None) -> object:  # noqa: N802 (Qt naming)
        return self._result


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _setup(window: DeviceDesktopApp, monkeypatch: pytest.MonkeyPatch):
    devices = sample_devices()[:1]
    device = devices[0]
    device.id = "ctx-menu-device-0"
    device.name = "右键设备"
    window.devices = devices
    window.rebuild_device_indexes()
    tab = window.ensure_device_tab(device)
    monkeypatch.setattr(window, "connect_session_tab", lambda tab_id: None)
    # Open a session so the device parent appears in the session-manager tree.
    window.ensure_session_tab(
        kind="simulated",
        device=device,
        host=device.ssh_ip or "10.0.0.1",
        port=device.ssh_port or 22,
        username="admin",
        password="secret",
        title="右键会话",
        suppress_initial_error=True,
    )
    window.refresh_session_manager_tree()
    return window, device, tab


def _drive_tree_menu(
    window: DeviceDesktopApp,
    monkeypatch: pytest.MonkeyPatch,
    close_actions: dict[str, object],
    device_actions: dict[str, object],
    device: object,
    fake_result: object,
) -> None:
    """Make session_manager_custom_context_menu hit the device parent row and
    exec a fake menu returning ``fake_result``, reusing the caller's REAL
    close_actions / device_actions / device so dispatch matches genuine QActions."""
    tree = window.session_manager_tree
    parent = tree.topLevelItem(0)
    assert parent is not None
    monkeypatch.setattr(tree, "itemAt", lambda _pos: parent)
    monkeypatch.setattr(
        window,
        "build_device_tab_context_menu",
        lambda state, parent_widget: (
            _FakeMenu(fake_result),
            close_actions,
            device_actions,
            device,
        ),
    )


def _build_actions(window: DeviceDesktopApp, tab: object):
    """Build the device context menu once and return (close_actions, device_actions, device)."""
    _menu, close_actions, device_actions, device = window.build_device_tab_context_menu(
        tab, window.session_manager_tree
    )
    return close_actions, device_actions, device


def test_session_manager_device_context_menu_dispatches_device_action(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Choosing a device action (复制 SSH IP) from the session-manager tree menu
    must dispatch to the device quick-action handler. Regression: the tree path
    dropped device_actions and only handled close_actions."""
    _ = app
    window, device, tab = _setup(window := DeviceDesktopApp(), monkeypatch)
    close_actions, device_actions, _device = _build_actions(window, tab)
    copy_ssh = device_actions["copy_ssh_ip"]
    calls: list[str] = []
    monkeypatch.setattr(window, "copy_device_field", lambda device, field: calls.append(field))
    _drive_tree_menu(window, monkeypatch, close_actions, device_actions, _device, copy_ssh)

    window.session_manager_custom_context_menu(QPoint(0, 0))

    assert calls == ["ssh_ip"]
    window.close()


def test_session_manager_device_context_menu_close_actions_still_work(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The close-tab actions in the session-manager tree path must keep working."""
    _ = app
    window, device, tab = _setup(window := DeviceDesktopApp(), monkeypatch)
    close_actions, device_actions, _device = _build_actions(window, tab)
    closed: list[str] = []
    monkeypatch.setattr(
        window,
        "close_device_tabs_relative",
        lambda reference, mode: closed.append(mode),
    )
    _drive_tree_menu(window, monkeypatch, close_actions, device_actions, _device, close_actions["current"])

    window.session_manager_custom_context_menu(QPoint(0, 0))

    assert closed == ["current"]
    window.close()
