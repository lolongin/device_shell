"""Tests for manual terminal credential overrides."""

from __future__ import annotations

import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit

from src._sample_data import sample_devices
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
