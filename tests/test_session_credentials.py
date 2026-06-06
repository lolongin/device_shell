"""Tests for manual terminal credential overrides."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from src._sample_data import STATUS_OCCUPIED, sample_devices
from src.app_state import SessionTabState
from src.app.main_window import DeviceDesktopApp
from src.app.temporary_device_ops import TemporaryDeviceDialog


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_selected_device_connection_panel_overrides_session_credentials(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]
    window.devices = [device]
    window.selected_device_id = device.id
    window.rebuild_device_indexes()
    window.sync_auth_fields_from_selected()

    window.device_username_input.setText("manual-telnet")
    window.device_password_input.setText("manual-telnet-pass")
    window.linux_username_input.setText("manual-ssh")
    window.linux_password_input.setText("manual-ssh-pass")
    window.serial_username_input.setText("manual-serial")
    window.serial_password_input.setText("manual-serial-pass")

    assert window.session_telnet_credentials(device) == ("manual-telnet", "manual-telnet-pass")
    assert window.session_ssh_credentials(device) == ("manual-ssh", "manual-ssh-pass")
    assert window.session_serial_credentials(device) == ("manual-serial", "manual-serial-pass")


def test_reconnect_refreshes_credentials_from_connection_panel(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]
    window.devices = [device]
    window.selected_device_id = device.id
    window.rebuild_device_indexes()
    window.sync_auth_fields_from_selected()
    window.linux_username_input.setText("retry-user")
    window.linux_password_input.setText("retry-pass")

    state = SimpleNamespace(
        kind="linux",
        device_id=device.id,
        username="old-user",
        password="old-pass",
    )

    window.refresh_session_credentials_from_panel(state)

    assert state.username == "retry-user"
    assert state.password == "retry-pass"
    assert window.local_credential_overrides[device.id]["linux"] == {
        "username": "retry-user",
        "password": "retry-pass",
    }


def test_sync_auth_fields_prefers_local_credential_overrides(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]
    window.devices = [device]
    window.selected_device_id = device.id
    window.rebuild_device_indexes()
    window.local_credential_overrides = {
        device.id: {
            "linux": {"username": "local-linux", "password": "root"},
            "device": {"username": "local-telnet", "password": "huawei"},
            "serial": {"username": "local-serial", "password": "serial-root"},
        }
    }

    window.sync_auth_fields_from_selected()
    window.refresh_device_context()

    assert window.linux_username_input.text() == "local-linux"
    assert window.linux_password_input.text() == "root"
    assert window.device_username_input.text() == "local-telnet"
    assert window.device_password_input.text() == "huawei"
    assert window.serial_username_input.text() == "local-serial"
    assert window.serial_password_input.text() == "serial-root"


def test_switching_selected_device_refreshes_connection_panel_even_with_active_session(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    first = replace(sample_devices()[0], id="first-device", username="first-user", password="first-pass")
    second = replace(
        sample_devices()[1],
        id="second-device",
        username="second-user",
        password="second-pass",
        ssh_username="second-ssh",
        ssh_password="second-ssh-pass",
    )
    window.devices = [first, second]
    window.selected_device_id = second.id
    window.rebuild_device_indexes()
    monkeypatch.setattr(
        window,
        "current_session_state",
        lambda: SimpleNamespace(device_id=first.id),
    )

    window.sync_auth_fields_from_selected()

    assert window.device_username_input.text() == "second-user"
    assert window.device_password_input.text() == "second-pass"
    assert window.linux_username_input.text() == "second-ssh"
    assert window.linux_password_input.text() == "second-ssh-pass"


def test_matching_credentials_clear_local_override(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]
    window.local_credential_overrides = {
        device.id: {"linux": {"username": "local-linux", "password": "root"}}
    }

    window.remember_session_credentials_override(
        device,
        "linux",
        window.device_ssh_username(device),
        window.device_ssh_password(device),
    )

    assert device.id not in window.local_credential_overrides


def test_linux_ssh_first_connect_uses_default_root_candidates(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]

    candidates = window.linux_ssh_credential_candidates(device, "api-user", "api-pass")

    assert candidates[:2] == [("root", "root"), ("root", "huawei")]
    assert ("api-user", "api-pass") in candidates


def test_linux_ssh_local_override_uses_confirmed_credentials_only(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]
    window.local_credential_overrides = {
        device.id: {"linux": {"username": "root", "password": "confirmed-pass"}}
    }

    assert window.linux_ssh_credential_candidates(device, "root", "confirmed-pass") == [
        ("root", "confirmed-pass")
    ]


def test_connection_parameter_buttons_exist(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    assert window.connection_telnet_button.text() == "连接 Telnet"
    assert window.connection_ssh_button.text() == "连接 SSH"
    assert window.connection_serial_button.text() == "连接串口"


def test_collapsed_connection_panel_keeps_natural_height(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    window.connection_params_collapsed = True
    window.apply_connection_params_state()

    assert not window.connection_params_body.isVisible()
    assert window.connection_params_group.maximumHeight() == 16777215


def test_device_navigation_button_collapses_left_sidebar(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    window.toggle_left_sidebar()

    assert window.left_sidebar_collapsed
    assert not window.left_sidebar_content.isVisible()
    assert window.left_sidebar_shell.maximumWidth() == 46
    assert window.connection_telnet_button.width() >= 92


def test_activity_device_button_toggles_left_sidebar(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.left_sidebar_active_panel = "devices"
    window.left_sidebar_collapsed = False

    window.toggle_device_sidebar_panel()

    assert window.left_sidebar_collapsed
    assert not window.left_sidebar_content.isVisible()

    window.toggle_device_sidebar_panel()

    assert not window.left_sidebar_collapsed
    assert window.left_sidebar_stack.currentIndex() == 0


def test_local_credential_overrides_round_trip_desktop_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()
    device = sample_devices()[0]
    first.local_credential_overrides = {
        device.id: {"linux": {"username": "local-linux", "password": "root"}}
    }

    first.save_desktop_state()
    second = DeviceDesktopApp()

    assert second.local_credential_overrides[device.id]["linux"] == {
        "username": "local-linux",
        "password": "root",
    }


def test_always_on_top_round_trips_desktop_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()

    first.toggle_always_on_top(True)
    first.save_desktop_state()
    second = DeviceDesktopApp()

    assert second.always_on_top
    assert second.always_on_top_button.isChecked()
    if os.name != "nt":
        assert bool(second.windowFlags() & Qt.WindowStaysOnTopHint)


def test_always_on_top_keeps_visible_window_visible(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.show()

    window.toggle_always_on_top(True)

    assert window.always_on_top
    assert window.isVisible()


def test_create_session_log_rotates_current_session_log(app: QApplication, tmp_path) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]
    window.log_directory = tmp_path
    window.devices = [device]
    window.rebuild_device_indexes()
    old_path = tmp_path / "old.log"
    state = SessionTabState(
        tab_id="test:device:1",
        kind="device",
        device_id=device.id,
        title="Telnet #1",
        host=device.telnet_ip,
        port=device.telnet_port,
        username=device.username,
        password=device.password,
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=old_path,
    )

    window.write_session_log_line(state, "SYS", "before rotation")
    new_path = window.create_session_log(state)

    assert new_path != old_path
    assert state.log_path == new_path
    assert old_path.exists()
    assert new_path.exists()
    assert "before rotation" in old_path.read_text(encoding="utf-8")
    assert "New log created; previous log:" in new_path.read_text(encoding="utf-8")


def assert_password_visibility_toggle(field: QLineEdit) -> None:
    assert field.echoMode() == QLineEdit.Password
    actions = [action for action in field.actions() if action.isCheckable()]
    assert actions

    action = actions[-1]
    action.trigger()
    assert field.echoMode() == QLineEdit.Normal
    assert action.toolTip() == "隐藏密码"

    action.trigger()
    assert field.echoMode() == QLineEdit.Password
    assert action.toolTip() == "显示密码"


def test_connection_password_fields_can_toggle_visibility(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    for field in (
        window.device_password_input,
        window.linux_password_input,
        window.serial_password_input,
        window.temporary_telnet_password_input,
        window.temporary_ssh_password_input,
        window.temporary_serial_password_input,
    ):
        assert_password_visibility_toggle(field)


def test_temporary_device_dialog_password_can_toggle_visibility(app: QApplication) -> None:
    _ = app
    dialog = TemporaryDeviceDialog()

    assert_password_visibility_toggle(dialog.password_input)


def test_device_table_shows_board_type_cpu_and_slot_without_ip(app: QApplication, sample_device) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.devices = [sample_device]
    window.rebuild_device_indexes()
    window.apply_filters()

    assert window.device_table.horizontalHeaderItem(0).text() == "序号"
    assert window.device_table.horizontalHeaderItem(1).text() == "设备"
    assert window.device_table.horizontalHeaderItem(2).text() == "板类型"
    assert window.device_table.horizontalHeaderItem(3).text() == "CPU"
    assert window.device_table.horizontalHeaderItem(4).text() == "Slot"
    assert window.device_table.horizontalHeaderItem(5).text() == "状态"
    assert window.device_table.item(0, 1).text() == sample_device.name
    assert window.device_table.item(0, 2).text() == sample_device.device_type
    assert window.device_table.item(0, 3).text() == sample_device.cpu
    assert window.device_table.item(0, 4).text() == sample_device.rack
    assert window.device_table.item(0, 5).text() == sample_device.status
    assert sample_device.ssh_ip not in window.device_row_copy_text(sample_device)
    assert sample_device.telnet_ip not in window.device_row_copy_text(sample_device)


def test_device_table_shows_occupied_status_with_duration(app: QApplication, sample_device) -> None:
    _ = app
    occupied = replace(
        sample_device,
        status=STATUS_OCCUPIED,
        owner="li.wei",
        extra={
            **sample_device.extra,
            "occupancy_started_at": (datetime.now(timezone.utc) - timedelta(hours=2, minutes=5)).isoformat(),
        },
    )
    window = DeviceDesktopApp()
    window.devices = [occupied]
    window.rebuild_device_indexes()
    window.apply_filters()

    status_item = window.device_table.item(0, 5)

    assert status_item is not None
    assert STATUS_OCCUPIED in status_item.text()
    assert "小时" in status_item.text() or "分" in status_item.text()
    assert "li.wei" in status_item.toolTip()
    assert "占用时长" in status_item.toolTip()


def test_device_table_groups_duplicate_device_names(app: QApplication, sample_device) -> None:
    _ = app
    first = replace(
        sample_device,
        id="TEST-001-A",
        board_id="0001",
        device_type="Main Board",
        cpu="ARM-1",
        rack="Slot-1",
    )
    second = replace(
        sample_device,
        id="TEST-001-B",
        board_id="0002",
        device_type="Line Board",
        cpu="ARM-2",
        rack="Slot-2",
    )
    standalone = replace(
        sample_device,
        id="TEST-002",
        name="Standalone",
        board_id="0003",
        device_type="Single Board",
        cpu="ARM-3",
        rack="Slot-3",
    )
    window = DeviceDesktopApp()
    window.devices = [first, second, standalone]
    window.rebuild_device_indexes()
    window.apply_filters()

    assert window.device_table.rowCount() == 5
    assert window.device_table.item(0, 0).text() == sample_device.name
    assert window.device_table.columnSpan(0, 0) == 2
    assert window.device_table.item(0, 2).text() == "2 块板"
    assert window.device_table.item(1, 0).text() == "0001"
    assert window.device_table.item(1, 1).text() == "Main Board"
    assert window.device_table.item(1, 0).toolTip() == "0001"
    assert window.device_table.item(1, 1).toolTip() == sample_device.name
    assert window.device_table.item(1, 2).text() == "Main Board"
    assert window.device_table.item(2, 0).text() == "0002"
    assert window.device_table.item(2, 2).text() == "Line Board"
    assert window.device_table.item(3, 1).text() == "Standalone"
    assert window.device_table.item(4, 1).text() == "模拟终端"
    assert window.device_table_rows == {
        first.id: 1,
        second.id: 2,
        standalone.id: 3,
        "SIM-TERMINAL": 4,
    }
