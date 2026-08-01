from __future__ import annotations

import os
from dataclasses import replace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src._sample_data import sample_devices
from src.app.main_window import DeviceDesktopApp
from src.styles import APP_STYLE


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _device_tabs(window: DeviceDesktopApp, count: int = 3):
    devices = [
        replace(
            sample_devices()[index],
            id=f"context-device-{index}",
            name=f"设备页签 {index + 1}",
        )
        for index in range(count)
    ]
    window.devices = devices
    window.rebuild_device_indexes()
    return [window.ensure_device_tab(device) for device in devices]


def test_top_device_tab_bar_uses_custom_context_menu(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    assert window.session_tab_widget.tabBar().contextMenuPolicy() == Qt.CustomContextMenu

    window.close()


def test_device_tab_context_menu_has_close_groups_and_preserves_device_actions(
    app: QApplication,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    states = _device_tabs(window)

    menu, actions, device_actions, device = window.build_device_tab_context_menu(states[1], window)
    menu_actions = menu.actions()

    assert menu.objectName() == "workspaceContextMenu"
    assert menu.property("menuKind") == "device-tab-menu"
    assert menu_actions[0].text() == "设备页签 2"
    assert not menu_actions[0].isEnabled()
    assert [actions[key].text() for key in ("current", "left", "right", "others", "all")] == [
        "关闭当前页签",
        "关闭左侧页签",
        "关闭右侧页签",
        "关闭其他页签",
        "关闭所有页签",
    ]
    assert actions["left"].isEnabled()
    assert actions["right"].isEnabled()
    assert actions["others"].isEnabled()
    assert not actions["all"].icon().isNull()
    assert device is not None
    assert device_actions
    assert any(action.menu() is not None and action.text() == "设备操作" for action in menu_actions)

    window.close()


@pytest.mark.parametrize(
    ("reference_index", "mode", "expected_indexes"),
    [
        (1, "current", [1]),
        (1, "left", [0]),
        (1, "right", [2, 3]),
        (1, "others", [0, 2, 3]),
        (1, "all", [0, 1, 2, 3]),
    ],
)
def test_device_tab_close_targets_follow_visible_tab_order(
    app: QApplication,
    reference_index: int,
    mode: str,
    expected_indexes: list[int],
) -> None:
    _ = app
    window = DeviceDesktopApp()
    states = _device_tabs(window, 4)

    targets = window.device_tab_close_targets(states[reference_index], mode)

    assert targets == [states[index] for index in expected_indexes]

    window.close()


def test_device_tab_context_menu_disables_unavailable_boundaries(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    states = _device_tabs(window)

    _first_menu, first_actions, _device_actions, _device = window.build_device_tab_context_menu(
        states[0],
        window,
    )
    _last_menu, last_actions, _device_actions, _device = window.build_device_tab_context_menu(
        states[-1],
        window,
    )

    assert not first_actions["left"].isEnabled()
    assert first_actions["right"].isEnabled()
    assert last_actions["left"].isEnabled()
    assert not last_actions["right"].isEnabled()

    window.close()

    single_window = DeviceDesktopApp()
    single_state = _device_tabs(single_window, 1)[0]
    _menu, single_actions, _device_actions, _device = single_window.build_device_tab_context_menu(
        single_state,
        single_window,
    )

    assert not single_actions["left"].isEnabled()
    assert not single_actions["right"].isEnabled()
    assert not single_actions["others"].isEnabled()

    single_window.close()


def test_bulk_device_tab_close_uses_snapshot_and_keeps_reference_selected(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    states = _device_tabs(window, 4)
    closed = []
    monkeypatch.setattr(window, "close_device_tab_state", closed.append)

    window.close_device_tabs_relative(states[1], "right")

    assert closed == states[2:]
    assert window.session_tab_widget.currentWidget() is states[1].page

    window.close()


def test_workspace_context_menu_uses_neutral_compact_selection_style() -> None:
    workspace_menu_style = APP_STYLE[APP_STYLE.index("QMenu#workspaceContextMenu") :]

    assert "background: #24324a" in workspace_menu_style
    assert "color: #718096" in workspace_menu_style
    assert "padding: 6px" in workspace_menu_style
    assert "padding: 7px 30px 7px 12px" in workspace_menu_style
