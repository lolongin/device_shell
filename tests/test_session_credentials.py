"""Tests for manual terminal credential overrides."""

from __future__ import annotations

import os
import re
import json
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QFrame, QLabel, QLineEdit, QPushButton, QSizePolicy, QWidget

from src._sample_data import STATUS_IDLE, STATUS_OCCUPIED, STATUS_OTHER, STATUS_PIPELINE, sample_devices
from src.app_state import SessionTabState
from src.app.main_window import DeviceDesktopApp
from src.app.temporary_device_ops import TemporaryDeviceDialog
from src.styles import APP_STYLE, STATUS_COLORS


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


def test_connection_parameters_use_web_protocol_cards(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    rows = window.connection_params_body.findChildren(QFrame, "connectionCompactRow")

    assert len(rows) == 3
    assert {row.property("surface") for row in rows} == {"connectionProtocolCard"}
    assert all(row.toolTip() for row in rows)
    assert window.device_telnet_ip_value.property("connectionField") == "host"
    assert window.device_username_input.property("connectionField") == "username"
    assert window.device_password_input.property("connectionField") == "password"
    assert window.connection_telnet_button.property("connectionAction") == "primary"


def test_left_drawer_uses_workspace_style_overrides() -> None:
    assert "/* Left drawer native surfaces */" in APP_STYLE
    assert 'QFrame#connectionCompactRow[surface="connectionProtocolCard"]' in APP_STYLE
    assert 'QFrame#connectionCompactRow QLineEdit[connectionField="host"]' in APP_STYLE
    assert "QPushButton#primaryButton" in APP_STYLE
    assert "background: #15803d" in APP_STYLE


def test_status_stat_chips_use_workspace_palette(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    table_ops = (Path(__file__).resolve().parents[1] / "src" / "app" / "table_ops.py").read_text(
        encoding="utf-8"
    )

    assert STATUS_COLORS[STATUS_IDLE] in window.stat_chip_html("idle", 1, STATUS_COLORS[STATUS_IDLE])
    assert "stat-chip-text" in window.stat_chip_html("idle", 1, STATUS_COLORS[STATUS_IDLE])
    assert "html_status_text(" in table_ops
    assert "html_device_summary(" in table_ops
    assert "font-weight:800'>{html.escape(label)} {value}" not in table_ops
    assert STATUS_COLORS[STATUS_PIPELINE] in window.stat_chip_html(
        "pipeline", 1, STATUS_COLORS[STATUS_PIPELINE]
    )
    assert STATUS_COLORS[STATUS_OTHER] in window.stat_chip_html("other", 1, STATUS_COLORS[STATUS_OTHER])
    assert "#3cc98e" not in table_ops
    assert "#f5a623" not in table_ops
    assert "#5b6ef5" not in table_ops
    assert "#808080" not in table_ops
    assert table_ops.count("temporary_device_detail_badge(device)") == 1
    assert "html.escape(self.temporary_device_display_name(device))" not in table_ops


def test_filter_and_device_summary_html_use_workspace_palette(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]
    window.devices = [device]
    window.selected_device_id = device.id
    window.rebuild_device_indexes()

    chip = window.filter_chip_html("CPU", "ARM")
    window.refresh_device_context()
    summary = window.device_summary_card.text()

    assert "#08101d" in chip
    assert "#243244" in chip
    assert "#a7b4c7" in chip
    assert "#f8fafc" in summary
    assert "#a7b4c7" in summary
    assert "#22c55e" in summary
    assert "#181818" not in chip
    assert "#c0c0c0" not in summary


def test_device_navigation_button_collapses_terminal_sidebar(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_widget.addTab(QWidget(), "Session")
    window.show_terminal_workspace()
    window.show()
    QApplication.processEvents()

    assert not window.left_sidebar_collapsed
    assert not window.left_sidebar_content.isHidden()

    window.toggle_left_sidebar()

    assert window.left_sidebar_collapsed
    assert window.left_sidebar_content.isHidden()
    assert window.left_sidebar_shell.maximumWidth() == 46
    assert window.connection_telnet_button.width() >= 92

    window.show_web_home()
    window.toggle_left_sidebar()

    assert window.left_sidebar_content.isHidden()
    assert window.left_sidebar_shell.maximumWidth() == 46


def test_transfer_log_uses_workspace_context_menu(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    assert window.transfer_log_output.contextMenuPolicy() == Qt.CustomContextMenu
    assert hasattr(window, "show_transfer_log_context_menu")


def test_activity_terminal_button_opens_terminal_workspace(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    assert not window.activity_terminal_button.isEnabled()

    window.session_tab_widget.addTab(QWidget(), "Session")
    window.update_center_stage_state()

    assert window.activity_terminal_button.isEnabled()
    assert not window.web_shell.isHidden()

    window.activity_terminal_button.click()

    assert not window.session_tab_widget.isHidden()
    assert window.activity_terminal_button.isChecked()

    window.toggle_left_sidebar()

    assert window.left_sidebar_collapsed

    window.activity_terminal_button.click()

    assert not window.left_sidebar_collapsed


def test_activity_rail_tools_toggle_and_home_restores_full_dashboard(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    window.activity_temporary_button.click()

    assert window.center_stage_mode == "home"
    assert window.left_sidebar_active_panel == "temporary"
    assert not window.left_sidebar_collapsed
    assert window.activity_temporary_button.isChecked()
    assert not window.activity_home_button.isChecked()

    window.activity_home_button.click()

    assert window.center_stage_mode == "home"
    assert window.left_sidebar_active_panel == "devices"
    assert window.left_sidebar_collapsed
    assert window.left_sidebar_content.isHidden()
    assert window.left_sidebar_shell.maximumWidth() == 46
    assert window.activity_home_button.isChecked()
    assert not window.activity_temporary_button.isChecked()

    window.activity_transfer_button.click()

    assert window.left_sidebar_active_panel == "transfer"
    assert not window.left_sidebar_collapsed
    assert window.activity_transfer_button.isChecked()
    assert not window.activity_home_button.isChecked()

    window.activity_transfer_button.click()

    assert window.left_sidebar_collapsed
    assert window.activity_home_button.isChecked()
    assert not window.activity_transfer_button.isChecked()


def test_terminal_button_closes_tool_drawer_and_restores_session_navigation(
    app: QApplication,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_widget.addTab(QWidget(), "Session")
    window.update_center_stage_state()
    window.activity_terminal_button.click()

    assert window.center_stage_mode == "sessions"
    assert window.left_sidebar_active_panel == "devices"
    assert not window.left_sidebar_collapsed
    assert window.activity_terminal_button.isChecked()

    window.activity_temporary_button.click()

    assert window.left_sidebar_active_panel == "temporary"
    assert window.activity_temporary_button.isChecked()
    assert not window.activity_terminal_button.isChecked()

    window.activity_terminal_button.click()

    assert window.center_stage_mode == "sessions"
    assert window.left_sidebar_active_panel == "devices"
    assert not window.left_sidebar_collapsed
    assert window.activity_terminal_button.isChecked()
    assert not window.activity_temporary_button.isChecked()


def test_terminal_sidebar_stops_stale_width_animation(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_widget.addTab(QWidget(), "Session")

    window.show_terminal_workspace()
    QApplication.processEvents()

    assert window.left_sidebar_animation is None
    assert window.left_sidebar_shell.minimumWidth() == window.TERMINAL_SIDEBAR_MIN_WIDTH
    assert window.left_sidebar_shell.maximumWidth() == window.TERMINAL_SIDEBAR_MAX_WIDTH


def test_terminal_workspace_keeps_native_control_surfaces(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()

    assert window.session_tab_widget.objectName() == "sessionTabs"
    assert window.session_quick_action_bar.objectName() == "sessionQuickBar"
    assert window.terminal_ops_label.objectName() == "terminalOpsLabel"
    assert window.terminal_ops_label.text() == "TERMINAL OPS"
    assert window.session_count_label.objectName() == "terminalSessionCountPill"
    assert window.terminal_ops_label.isHidden()
    assert window.session_jump_combo.isHidden()
    assert window.session_jump_resize_handle.isHidden()
    assert window.session_count_label.isHidden()
    assert window.quick_reconnect_button.objectName() == "quickActionIconButton"
    assert window.quick_auto_response_button.objectName() == "autoResponseMenuButton"
    assert window.command_record_frame.objectName() == "commandRecordDock"
    assert window.command_record_input.objectName() == "commandRecordEditor"
    assert window.command_record_toggle_button.objectName() == "commandCollapseButton"
    assert window.command_enter_mode_button.objectName() == "commandEnterModeButton"
    assert window.quick_auto_response_menu.objectName() == "workspaceContextMenu"
    assert window.quick_auto_response_menu.property("menuKind") == "auto-response-menu"
    assert window.quick_log_menu.objectName() == "workspaceContextMenu"
    assert window.quick_log_menu.property("menuKind") == "log-menu"
    assert window.quick_close_button.objectName() == "quickDangerIconButton"
    assert window.quick_close_menu.objectName() == "workspaceContextMenu"
    assert window.quick_close_menu.property("menuKind") == "close-session-menu"
    assert window.quick_close_current_action.text() == "关闭当前会话"
    assert window.quick_close_other_action.text() == "关闭其他会话"
    assert window.quick_close_all_action.text() == "关闭全部会话"
    assert window.session_jump_resize_handle.objectName() == "sessionJumpResizeHandle"
    assert window.session_quick_bar_toggle_button.objectName() == "quickActionIconButton"
    assert window.session_quick_restore_bar.objectName() == "sessionQuickRestoreBar"
    assert window.session_quick_restore_button.objectName() == "sessionQuickRestoreButton"

    state = SessionTabState(
        tab_id="test:device:1",
        kind="device",
        device_id="D1",
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="user",
        password="pass",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=Path("session.log"),
    )
    monkeypatch.setattr(window, "ordered_session_states", lambda: [state])
    monkeypatch.setattr(window, "current_session_key", lambda: state.tab_id)
    monkeypatch.setattr(window, "session_jump_text", lambda _state: "Mock / Telnet #1")
    window.refresh_session_jump_combo()
    assert window.session_count_label.text() == "1 会话"


def test_session_quick_bar_can_resize_and_hide(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.session_tab_widget.addTab(QWidget(), "Session")
    window.show_terminal_workspace()
    window.show()
    QApplication.processEvents()

    assert window.session_quick_action_bar.isVisible()
    assert not window.session_quick_restore_bar.isVisible()

    window.resize_session_jump_combo(470)
    assert window.session_jump_combo.width() == 470
    window.resize_session_jump_combo(40)
    assert window.session_jump_combo.width() == 180
    window.resize_session_jump_combo(900)
    assert window.session_jump_combo.width() == 520

    window.set_session_quick_bar_collapsed(True)
    assert not window.session_quick_action_bar.isVisible()
    assert window.session_quick_restore_bar.isVisible()

    window.session_quick_restore_button.click()
    assert window.session_quick_action_bar.isVisible()
    assert not window.session_quick_restore_bar.isVisible()

    window.close()


def test_terminal_workspace_uses_workspace_style_overrides() -> None:
    assert "/* Terminal workspace shell */" in APP_STYLE
    assert "QTabWidget#sessionTabs::pane" in APP_STYLE
    assert "QTabWidget#deviceSessionTabs QTabBar::tab:selected" in APP_STYLE
    assert "QFrame#sessionQuickBar" in APP_STYLE
    assert "QFrame#sessionQuickRestoreBar" in APP_STYLE
    assert "QFrame#sessionJumpResizeHandle" in APP_STYLE
    assert "QToolButton#sessionQuickRestoreButton" in APP_STYLE
    assert "QLabel#terminalOpsLabel" in APP_STYLE
    assert "QLabel#terminalSessionCountPill" in APP_STYLE
    assert "QFrame#commandRecordDock" in APP_STYLE
    assert "border-color: #22c55e" in APP_STYLE


def test_workspace_dialog_style_overrides() -> None:
    assert "/* Workspace dialogs */" in APP_STYLE
    assert "QDialog#workspaceDialog" in APP_STYLE
    assert "QFrame#dialogFormCard" in APP_STYLE
    assert "QDialogButtonBox#workspaceDialogButtons" in APP_STYLE
    assert "QMessageBox" in APP_STYLE


def test_data_table_style_overrides() -> None:
    assert "/* Data tables and scrollbars */" in APP_STYLE
    assert "QTableWidget" in APP_STYLE
    assert "selection-background-color: #24324a" in APP_STYLE
    assert "QHeaderView::section" in APP_STYLE
    assert "QScrollBar::handle:vertical" in APP_STYLE
    assert "background: #334155" in APP_STYLE


def test_native_workspace_foundation_style_overrides() -> None:
    assert "/* Native workspace foundation */" in APP_STYLE
    assert "QMainWindow,\nQWidget#centerStage" in APP_STYLE
    assert "QComboBox QAbstractItemView" in APP_STYLE
    assert 'QPushButton[connectionAction="primary"]' in APP_STYLE
    assert "QToolTip" in APP_STYLE
    assert "QMenu::item:selected" in APP_STYLE
    assert "QSplitter::handle:hover" in APP_STYLE
    assert "selection-background-color: #24324a" in APP_STYLE
    assert "color: #718096;" in APP_STYLE


def test_oled_final_cascade_overrides_legacy_native_palette() -> None:
    legacy_index = APP_STYLE.index("/* Linear / Vercel dark minimal redesign overrides */")
    final_index = APP_STYLE.index("/* OLED workspace final cascade */")

    assert final_index > legacy_index
    final = APP_STYLE[final_index:]
    assert 'font-family: "Fira Sans"' in final
    assert "QFrame#activityRail" in final
    assert "QPlainTextEdit#commandRecordEditor" in final
    assert "QLineEdit#detailValueInput" in final
    assert 'font-family: "Fira Code"' in final
    assert "QLabel#tabStatusDot[connectionState=\"connected\"]" in final
    assert "background: #020617" in final
    assert "background: #0f172a" in final
    assert "background: #22c55e" in final
    assert "border-color: #60a5fa" in final
    assert "#5b6ef5" not in final
    assert "#ededed" not in final
    assert "#080808" not in final


def test_workspace_context_menu_factory_uses_native_theme(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    menu = window.new_workspace_menu(window, "设备操作", "device")

    assert menu.objectName() == "workspaceContextMenu"
    assert menu.property("menuKind") == "device"
    assert menu.actions()[0].text() == "设备操作"
    assert not menu.actions()[0].isEnabled()
    assert "QMenu#workspaceContextMenu" in APP_STYLE
    assert "QMenu#workspaceContextMenu::item:selected" in APP_STYLE


def test_core_context_menus_use_workspace_factory() -> None:
    root = Path(__file__).resolve().parents[1]

    for path in (
        root / "src" / "app" / "table_ops.py",
        root / "src" / "app" / "session_ops.py",
        root / "src" / "app" / "temporary_device_ops.py",
        root / "src" / "app" / "file_transfer_ops.py",
        root / "src" / "app" / "command_record_ops.py",
    ):
        source = path.read_text(encoding="utf-8")
        assert "new_workspace_menu(" in source
        assert "QMenu(" not in source

    main_window = (root / "src" / "app" / "main_window.py").read_text(encoding="utf-8")
    assert main_window.count("QMenu(") == 1
    assert "menu = QMenu(parent)" in main_window


def test_native_icon_painters_use_workspace_palette() -> None:
    root = Path(__file__).resolve().parents[1]
    main_window = (root / "src" / "app" / "main_window.py").read_text(encoding="utf-8")
    password_field = (root / "src" / "widgets" / "password_field.py").read_text(encoding="utf-8")

    assert "#f8fafc" in main_window
    assert "#718096" in main_window
    assert "#f87171" in main_window
    assert "#a0a0a0" not in main_window
    assert "#d0d0d0" not in password_field
    assert "#808080" not in password_field


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


def test_terminal_navigation_height_round_trips_desktop_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()

    first.resize_terminal_navigation_web(720)
    first.save_desktop_state()
    second = DeviceDesktopApp()

    assert first.device_navigation_web.minimumHeight() == 720
    assert first.device_navigation_web.maximumHeight() == 720
    assert second.terminal_navigation_web_height == 720
    assert second.device_navigation_web.minimumHeight() == 720
    assert second.device_navigation_web.maximumHeight() == 720


def test_terminal_sessions_round_trip_and_restore_without_credentials_in_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()
    device = sample_devices()[0]
    first.devices = [device]
    first.rebuild_device_indexes()
    opened: list[str] = []
    monkeypatch.setattr(first, "connect_session_tab", lambda tab_id: opened.append(tab_id))

    username, password = first.session_ssh_credentials(device)
    state = first.ensure_session_tab(
        kind="linux",
        device=device,
        host=device.ssh_ip.strip(),
        port=device.ssh_port,
        username=username,
        password=password,
        credential_candidates=first.linux_ssh_credential_candidates(device, username, password),
        title="SSH #4",
    )
    assert state is not None
    first.save_desktop_state()

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    remembered = payload["terminal_sessions"]
    assert opened == [state.tab_id]
    assert remembered == [{
        "device_id": device.id,
        "kind": "linux",
        "title": "SSH #4",
        "host": device.ssh_ip.strip(),
        "port": device.ssh_port,
        "active": True,
    }]
    assert "username" not in remembered[0]
    assert "password" not in remembered[0]

    second = DeviceDesktopApp()
    second.devices = [device]
    second.rebuild_device_indexes()
    restored: list[str] = []
    monkeypatch.setattr(second, "connect_session_tab", lambda tab_id: restored.append(tab_id))

    second.restore_remembered_terminal_sessions_once()

    restored_states = second.ordered_session_states()
    assert len(restored_states) == 1
    restored_state = restored_states[0]
    assert restored == [restored_state.tab_id]
    assert restored_state.kind == "linux"
    assert restored_state.title == "SSH #4"
    assert restored_state.host == device.ssh_ip.strip()
    assert restored_state.port == device.ssh_port
    assert restored_state.username == username
    assert restored_state.password == password
    assert restored_state.suppress_next_connection_error
    assert second.terminal_sessions_restored

    next_state = second.ensure_session_tab(
        kind="linux",
        device=device,
        host=device.ssh_ip.strip(),
        port=device.ssh_port,
        username=username,
        password=password,
        credential_candidates=second.linux_ssh_credential_candidates(device, username, password),
    )
    assert next_state is not None
    assert next_state.title == "SSH #5"


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
    assert new_path.parent == tmp_path / f"{device.id}_{device.name}"
    assert "before rotation" in old_path.read_text(encoding="utf-8")
    assert "New log created; previous log:" in new_path.read_text(encoding="utf-8")


def test_session_log_path_uses_device_directory(app: QApplication, tmp_path) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]
    window.log_directory = tmp_path

    log_path = window.session_log_path(device, "Telnet #1", "device")

    assert log_path.parent == tmp_path / f"{device.id}_{device.name}"
    assert log_path.suffix == ".log"


def test_session_log_rotates_automatically_at_size_limit(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = sample_devices()[0]
    window.log_directory = tmp_path
    window.log_rotate_size_bytes = 120
    window.devices = [device]
    window.rebuild_device_indexes()
    old_path = window.session_log_path(device, "Telnet #1", "device")
    state = SessionTabState(
        tab_id="test:device:auto-rotate",
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

    window.write_session_log_line(state, "OUT", "A" * 80)
    window.write_session_log_line(state, "OUT", "B" * 80)

    assert old_path.exists()
    assert state.log_path != old_path
    assert state.log_path.parent == old_path.parent
    assert "A" * 80 in old_path.read_text(encoding="utf-8")
    rotated_text = state.log_path.read_text(encoding="utf-8")
    assert "Log rotated automatically; previous log:" in rotated_text
    assert "B" * 80 in rotated_text


def test_log_rotate_size_round_trips_desktop_state(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _ = app
    state_path = tmp_path / "desktop_state.json"
    monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
    first = DeviceDesktopApp()
    first.log_rotate_size_bytes = 24 * 1024 * 1024

    first.save_desktop_state()
    second = DeviceDesktopApp()

    assert second.log_rotate_size_bytes == 24 * 1024 * 1024


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


def test_temporary_device_dialog_uses_workspace_surfaces(app: QApplication) -> None:
    _ = app
    dialog = TemporaryDeviceDialog()

    assert dialog.objectName() == "workspaceDialog"
    assert dialog.findChild(QFrame, "dialogFormCard") is not None
    assert dialog.findChild(QDialogButtonBox, "workspaceDialogButtons") is not None


def test_temporary_panel_uses_workspace_cards(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    device = replace(
        sample_devices()[1],
        id="TEMP-UI",
        name="Temp UI",
        telnet_ip="10.0.0.9",
        ssh_ip="10.0.0.10",
        serial_ip="10.0.0.11",
        notes="temporary card",
        extra={**sample_devices()[1].extra, "temporary": True},
    )
    window.temporary_devices = [device]
    window.refresh_temporary_panel()

    cards = window.temporary_list_container.findChildren(QFrame, "temporaryDeviceCard")
    protocol_cards = window.temporary_name_input.parent().findChildren(QFrame, "temporaryProtocolCard")
    protocol_pills = cards[0].findChildren(QLabel, "temporaryProtocolPill") if cards else []
    main_window_source = (Path(__file__).resolve().parents[1] / "src" / "app" / "main_window.py").read_text(
        encoding="utf-8"
    )

    assert window.temporary_name_input.parent().objectName() == "temporaryFormCard"
    assert {card.property("protocol") for card in protocol_cards} == {"telnet", "ssh", "serial"}
    assert len(cards) == 1
    assert cards[0].contextMenuPolicy() == Qt.CustomContextMenu
    assert cards[0].toolTip()
    assert {pill.text() for pill in protocol_pills} == {"Telnet", "SSH", "Serial"}
    assert {pill.property("protocol") for pill in protocol_pills} == {"telnet", "ssh", "serial"}
    assert "display:inline-block" not in main_window_source
    assert cards[0].findChild(QPushButton, "dangerButton") is not None

    window.selected_device_id = device.id
    window.rebuild_device_indexes()
    window.refresh_device_context()
    summary = window.device_summary_card.text()
    temporary_ops_source = (
        Path(__file__).resolve().parents[1] / "src" / "app" / "temporary_device_ops.py"
    ).read_text(encoding="utf-8")

    assert "temporary-detail-badge" in summary
    assert "仅保存在本机" in summary
    assert "#f8e7a1" in summary
    assert "rgba(251, 191, 36, 0.13)" in summary
    assert "#fbbf24" not in temporary_ops_source
    assert "style=" not in temporary_ops_source


def test_device_table_shows_board_type_cpu_and_slot_without_ip(app: QApplication, sample_device) -> None:
    _ = app
    device = replace(sample_device, extra={**sample_device.extra, "slot_id": "SLOT-9"})
    window = DeviceDesktopApp()
    window.devices = [device]
    window.rebuild_device_indexes()
    window.apply_filters()

    assert window.device_table.horizontalHeaderItem(0).text() == "序号"
    assert window.device_table.horizontalHeaderItem(1).text() == "设备"
    assert window.device_table.horizontalHeaderItem(2).text() == "板类型"
    assert window.device_table.horizontalHeaderItem(3).text() == "CPU"
    assert window.device_table.horizontalHeaderItem(4).text() == "Slot"
    assert window.device_table.horizontalHeaderItem(5).text() == "状态"
    assert window.device_table.item(0, 1).text() == device.name
    assert window.device_table.item(0, 2).text() == device.device_type
    assert window.device_table.item(0, 3).text() == device.cpu
    assert window.device_table.item(0, 4).text() == "SLOT-9"
    assert window.device_table.item(0, 5).text() == device.status
    assert "SLOT-9" in window.device_row_copy_text(device)
    assert device.rack not in window.device_row_copy_text(device)
    assert device.ssh_ip not in window.device_row_copy_text(device)
    assert device.telnet_ip not in window.device_row_copy_text(device)


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


def test_device_navigation_payload_includes_web_rows(app: QApplication, sample_device) -> None:
    _ = app
    occupied = replace(
        sample_device,
        status=STATUS_OCCUPIED,
        owner="li.wei",
        extra={
            **sample_device.extra,
            "slot_id": "SLOT-10",
            "occupancy_started_at": (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat(),
        },
    )
    window = DeviceDesktopApp()
    window.devices = [occupied]
    window.rebuild_device_indexes()
    window.apply_filters()

    payload = window.device_navigation_payload()
    rows = payload["rows"]

    assert payload["stats"]["occupied"] == 1
    assert isinstance(rows, list)
    assert rows[0]["kind"] == "device"
    assert rows[0]["id"] == occupied.id
    assert rows[0]["boardType"] == occupied.device_type
    assert rows[0]["slot"] == "SLOT-10"
    assert STATUS_OCCUPIED in rows[0]["statusText"]
    assert rows[0]["selected"] is True


def test_session_navigation_payload_is_terminal_focused(
    app: QApplication,
    sample_device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    device = replace(sample_device, extra={**sample_device.extra, "slot_id": "SLOT-11"})
    window = DeviceDesktopApp()
    window.devices = [device]
    window.rebuild_device_indexes()
    window.apply_filters()
    state = SessionTabState(
        tab_id="nav:device:1",
        kind="device",
        device_id=device.id,
        title="Telnet #1",
        host="127.0.0.1",
        port=23,
        username="user",
        password="pass",
        page=QWidget(),
        terminal=SimpleNamespace(),
        session=SimpleNamespace(),
        log_path=Path("session.log"),
        status_text="Connected",
    )
    monkeypatch.setattr(window, "ordered_session_states", lambda: [state])
    monkeypatch.setattr(window, "current_session_key", lambda: state.tab_id)

    payload = window.session_navigation_payload()

    assert payload["stats"]["total"] == 1
    assert payload["stats"]["connected"] == 1
    assert payload["rows"]
    assert payload["rows"][0]["id"] == device.id
    assert payload["rows"][0]["slot"] == "SLOT-11"
    assert payload["rows"][0]["telnet"] == f"{device.telnet_ip}:{device.telnet_port}"
    assert "filters" not in payload
    assert payload["sessions"][0]["tabId"] == state.tab_id
    assert payload["sessions"][0]["active"] is True
    assert payload["selectedDevice"]["id"] == device.id
    assert payload["selectedDevice"]["slot"] == "SLOT-11"


def test_web_shell_payload_includes_selected_device(app: QApplication, sample_device) -> None:
    _ = app
    device = replace(sample_device, extra={**sample_device.extra, "slot_id": "SLOT-12"})
    window = DeviceDesktopApp()
    window.devices = [device]
    window.rebuild_device_indexes()
    window.apply_filters()

    payload = window.web_shell_payload()
    selected = payload["selectedDevice"]

    assert selected["id"] == device.id
    assert selected["name"] == device.name
    assert selected["boardType"] == device.device_type
    assert selected["slot"] == "SLOT-12"
    assert selected["statusKind"] == window.device_status_kind(device)
    assert selected["telnet"] == f"{device.telnet_ip}:{device.telnet_port}"
    assert payload["stats"]["total"] == 2
    assert payload["sessions"] == []


def test_web_home_preserves_device_context_and_terminal_nav_actions(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    shell_requests: list[tuple[str, int, int]] = []
    shell_session_requests: list[str] = []
    shell_session_context_requests: list[tuple[str, int, int]] = []
    session_requests: list[str] = []
    session_close_requests: list[str] = []
    device_connect_requests: list[tuple[str, str]] = []
    session_context_requests: list[tuple[str, int, int]] = []
    home_requests: list[bool] = []
    window.web_shell.device_context_requested.connect(
        lambda device_id, x, y: shell_requests.append((device_id, x, y))
    )
    window.web_shell.session_selected.connect(shell_session_requests.append)
    window.web_shell.session_context_requested.connect(
        lambda tab_id, x, y: shell_session_context_requests.append((tab_id, x, y))
    )
    window.device_navigation_web.session_selected.connect(session_requests.append)
    window.device_navigation_web.session_close_requested.connect(session_close_requests.append)
    window.device_navigation_web.device_connect_requested.disconnect(window.open_navigation_device_session)
    window.device_navigation_web.device_connect_requested.connect(
        lambda device_id, kind: device_connect_requests.append((device_id, kind))
    )
    window.device_navigation_web.session_context_requested.connect(
        lambda tab_id, x, y: session_context_requests.append((tab_id, x, y))
    )
    window.device_navigation_web.home_requested.connect(lambda: home_requests.append(True))

    window.web_shell.bridge.requestDeviceContextMenu("WEB-001", 12, 18)
    window.web_shell.bridge.selectSession("SHELL-TAB-001")
    window.web_shell.bridge.requestSessionContextMenu("SHELL-TAB-001", 3, 4)
    window.device_navigation_web.bridge.selectSession("TAB-001")
    window.device_navigation_web.bridge.closeSession("TAB-001")
    window.device_navigation_web.bridge.requestDeviceConnect("WEB-001", "ssh")
    window.device_navigation_web.bridge.requestSessionContextMenu("TAB-001", 7, 9)
    window.device_navigation_web.bridge.requestHome()

    assert shell_requests and shell_requests[0][0] == "WEB-001"
    assert shell_session_requests == ["SHELL-TAB-001"]
    assert shell_session_context_requests and shell_session_context_requests[0][0] == "SHELL-TAB-001"
    assert session_requests == ["TAB-001"]
    assert session_close_requests == ["TAB-001"]
    assert device_connect_requests == [("WEB-001", "ssh")]
    assert session_context_requests and session_context_requests[0][0] == "TAB-001"
    assert home_requests == [True]
    window.close()


def test_terminal_navigation_device_connect_actions_select_device(
    app: QApplication,
    sample_device,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.devices = [sample_device]
    window.rebuild_device_indexes()
    opened: list[str] = []
    monkeypatch.setattr(window, "open_selected_device_session", lambda: opened.append("telnet"))
    monkeypatch.setattr(window, "open_selected_linux_session", lambda: opened.append("ssh"))
    monkeypatch.setattr(window, "open_selected_serial_session", lambda: opened.append("serial"))

    window.open_navigation_device_session(sample_device.id, "telnet")
    window.open_navigation_device_session(sample_device.id, "ssh")
    window.open_navigation_device_session(sample_device.id, "serial")

    assert window.selected_device_id == sample_device.id
    assert opened == ["telnet", "ssh", "serial"]


def test_terminal_navigation_web_can_shrink_to_compact_sidebar(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    assert window.device_navigation_web.minimumWidth() == 0
    assert window.device_navigation_web.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
    assert window.device_navigation_web.view.minimumWidth() == 0
    assert window.device_navigation_web.view.sizePolicy().horizontalPolicy() == QSizePolicy.Ignored


def test_terminal_sidebar_stack_does_not_clip_compact_navigation(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.resize(1366, 768)
    window.session_tab_widget.addTab(QWidget(), "Session")

    window.show_terminal_workspace()
    window.show()
    QApplication.processEvents()

    viewport_width = window.left_sidebar_content.viewport().width()

    assert window.left_sidebar_compact
    assert window.left_sidebar_content.widget().sizePolicy().horizontalPolicy() == QSizePolicy.Ignored
    assert window.left_sidebar_content.widget().width() <= viewport_width
    assert window.device_sidebar_panel.width() <= viewport_width
    assert window.device_navigation_web.width() <= viewport_width

    window.close()


def test_web_pages_share_workspace_theme() -> None:
    web_root = Path(__file__).resolve().parents[1] / "src" / "web"
    widget_root = Path(__file__).resolve().parents[1] / "src" / "widgets"

    for page_name in (
        "web_shell.html",
        "device_navigation.html",
        "auto_response_editor.html",
        "xterm_terminal.html",
        "xterm_prewarm.html",
    ):
        page = (web_root / page_name).read_text(encoding="utf-8")
        assert 'href="assets/workspace-theme.css"' in page
        assert ":root {" not in page
        assert "#34d399" not in page
        assert "#090d13" not in page
        assert "#06090d" not in page
        assert "rgba(16, 185, 129" not in page

    theme = (web_root / "assets" / "workspace-theme.css").read_text(encoding="utf-8")
    auto_response_page = (web_root / "auto_response_editor.html").read_text(encoding="utf-8")
    assert "--accent: #22c55e" in theme
    assert "--accent-2: #60a5fa" in theme
    assert "--input: #08101d" in theme
    assert "--input-quiet: #050b14" in theme
    assert "--focus: rgba(96, 165, 250, 0.35)" in theme
    assert "prefers-reduced-motion" in theme
    assert "--success-soft: rgba(34, 197, 94, 0.14)" in theme
    assert "--success-text: #d8fff0" in theme
    assert "--danger-text: #fecaca" in theme
    assert "--warn-text: #f8e7a1" in theme
    assert "--scroll-hover: #475569" in theme
    assert "--terminal-suggestion: rgba(167, 180, 199, 0.68)" in theme
    assert "--terminal-ansi-magenta: #c4b5fd" in theme
    assert "--terminal-ansi-cyan: #91d7e3" in theme
    assert "--terminal-ansi-bright-red: #fca5a5" in theme
    assert "--terminal-ansi-bright-green: #86efac" in theme
    assert "--terminal-ansi-bright-yellow: #f5d99a" in theme
    assert "--terminal-ansi-bright-blue: #b7c8ff" in theme
    assert "--terminal-ansi-bright-magenta: #ddd6fe" in theme
    assert "--terminal-ansi-bright-cyan: #b5eff7" in theme
    assert "--terminal-ansi-bright-white: #f6f8fb" in theme
    assert "--overlay: rgba(2, 6, 23, 0.72)" in theme
    assert "--shadow-strong: rgba(0, 0, 0, 0.5)" in theme
    assert "--status-idle-soft: var(--success-soft)" in theme
    assert "--status-idle-line: rgba(34, 197, 94, 0.42)" in theme
    assert "--status-occupied-soft: rgba(251, 191, 36, 0.13)" in theme
    assert "--status-occupied-line: rgba(251, 191, 36, 0.42)" in theme
    assert "--status-pipeline-soft: rgba(96, 165, 250, 0.13)" in theme
    assert "--status-pipeline-line: rgba(96, 165, 250, 0.42)" in theme
    assert "--status-other-soft: rgba(113, 128, 150, 0.14)" in theme
    assert "--status-other-line: rgba(113, 128, 150, 0.36)" in theme
    assert "--empty-bg: rgba(8, 16, 29, 0.55)" in theme
    empty_rules = theme[theme.index(".empty") : theme.index(".status {")]
    assert "background: var(--empty-bg)" in empty_rules
    assert "rgba(8, 16, 29, 0.55)" not in empty_rules
    status_rules = theme[theme.index(".status.idle") : theme.index("::-webkit-scrollbar")]
    assert "var(--status-idle-soft)" in status_rules
    assert "var(--status-occupied-soft)" in status_rules
    assert "var(--status-pipeline-soft)" in status_rules
    assert "var(--status-other-soft)" in status_rules
    assert "rgba(34, 197, 94, 0.42)" not in status_rules
    assert "rgba(251, 191, 36, 0.13)" not in status_rules
    assert "rgba(96, 165, 250, 0.13)" not in status_rules
    assert "rgba(113, 128, 150, 0.14)" not in status_rules
    assert "background: var(--panel)" in auto_response_page
    assert "var(--success-text)" in auto_response_page
    assert "button.danger" in theme
    assert 'class="danger remove-step"' in auto_response_page
    assert "var(--warn-text)" in auto_response_page
    assert "var(--overlay)" in auto_response_page
    assert "var(--shadow-strong)" in auto_response_page
    assert "#ffd7d7" not in auto_response_page
    assert "#f8e7a1" not in auto_response_page
    assert "rgba(2, 6, 23, 0.72)" not in auto_response_page
    assert "#090c10" not in auto_response_page
    assert "rgba(16, 185, 129" not in auto_response_page
    assert ".row.contextable" in theme
    assert ".status.idle" in theme
    assert ".status.occupied" in theme
    assert ".status.pipeline" in theme
    assert ".status.other" in theme
    assert "--focus-ring" in theme
    assert "--row-line" in theme
    assert "--home-glow-accent: rgba(34, 197, 94, 0.08)" in theme
    assert "--home-glow-blue: rgba(96, 165, 250, 0.10)" in theme
    assert "--surface-top: rgba(9, 12, 16, 0.86)" in theme
    assert "--surface-filter: rgba(8, 12, 17, 0.92)" in theme
    assert "--surface-card: rgba(13, 17, 23, 0.94)" in theme
    assert "button.primary" in theme
    assert "button:disabled" in theme
    assert "body.workspace-page" in theme
    assert "body.workspace-compact-page" in theme
    assert "body.workspace-terminal-page" in theme
    assert ".workspace-field" in theme
    assert ".workspace-panel" in theme
    assert ".workspace-button-row" in theme
    assert ".workspace-step-actions" in theme
    assert ".workspace-context-menu" in theme
    assert ".workspace-context-menu.open" in theme
    assert ".workspace-context-menu-separator" in theme
    assert ".workspace-contextable" in theme
    assert ".workspace-contextable:focus-visible" in theme
    assert "button:hover:not(:disabled)" in theme
    assert "background: var(--panel-2)" in theme
    assert 'class="workspace-field"' in auto_response_page
    assert 'class="workspace-panel"' in auto_response_page
    assert 'class="workspace-button-row workspace-step-actions"' in auto_response_page
    assert 'id="editorContextMenu"' in auto_response_page
    assert 'role="menu"' in auto_response_page
    assert 'class="step workspace-contextable"' in auto_response_page
    assert 'class="action workspace-contextable"' in auto_response_page
    assert 'tabindex="0"' in auto_response_page
    assert 'role="group"' in auto_response_page
    assert "stepsEl.addEventListener(\"contextmenu\", showEditorContextMenu)" in auto_response_page
    assert "function showEditorContextMenu(event)" in auto_response_page
    assert "function handleEditorContextMenuKey(event)" in auto_response_page
    assert 'event.key === "ContextMenu"' in auto_response_page
    assert 'event.shiftKey && event.key === "F10"' in auto_response_page
    assert 'stepEl.addEventListener("keydown", handleEditorContextMenuKey)' in auto_response_page
    assert 'actionEl.addEventListener("keydown", handleEditorContextMenuKey)' in auto_response_page
    assert "function contextMenuPoint(event, anchor)" in auto_response_page
    assert "复制动作" in auto_response_page
    assert "删除动作" in auto_response_page
    assert "复制步骤" in auto_response_page
    assert 'class="field"' not in auto_response_page
    assert 'class="panel"' not in auto_response_page
    assert "btn-row" not in auto_response_page
    assert "style=" not in auto_response_page
    xterm_page = (web_root / "xterm_terminal.html").read_text(encoding="utf-8")
    assert "var(--terminal-suggestion)" in xterm_page
    assert "var(--scroll-hover)" in xterm_page
    assert "cssVar('--terminal-ansi-magenta')" in xterm_page
    assert "cssVar('--terminal-ansi-bright-white')" in xterm_page
    assert "rgba(167, 180, 199, 0.68)" not in xterm_page
    for local_terminal_color in (
        "#c4b5fd",
        "#91d7e3",
        "#fca5a5",
        "#86efac",
        "#f5d99a",
        "#b7c8ff",
        "#ddd6fe",
        "#b5eff7",
        "#f6f8fb",
    ):
        assert local_terminal_color not in xterm_page
    web_shell_page = (web_root / "web_shell.html").read_text(encoding="utf-8")
    navigation_page = (web_root / "device_navigation.html").read_text(encoding="utf-8")
    assert "appendMetaChip(meta, device.statusText" in web_shell_page
    assert 'body class="workspace-page"' in web_shell_page
    assert 'body class="workspace-compact-page"' in navigation_page
    assert 'body class="workspace-page"' in auto_response_page
    assert "var(--home-glow-accent)" in web_shell_page
    assert "var(--home-glow-blue)" in web_shell_page
    assert "var(--surface-top)" in web_shell_page
    assert "var(--surface-filter)" in web_shell_page
    assert "var(--surface-card)" in web_shell_page
    assert "rgba(34, 197, 94, 0.08)" not in web_shell_page
    assert "rgba(96, 165, 250, 0.10)" not in web_shell_page
    assert "rgba(9, 12, 16, 0.86)" not in web_shell_page
    assert "rgba(8, 12, 17, 0.92)" not in web_shell_page
    assert "rgba(13, 17, 23, 0.94)" not in web_shell_page
    assert "function chipClass" not in web_shell_page
    assert ".chip.good" not in web_shell_page
    assert ".chip.warn" not in web_shell_page
    assert ".chip.blue" not in web_shell_page
    assert "row contextable" in web_shell_page
    assert 'row.setAttribute("role", "button")' in web_shell_page
    assert 'row.setAttribute("aria-selected", item.selected ? "true" : "false")' in web_shell_page
    assert 'event.key === "Enter" || event.key === " "' in web_shell_page
    assert 'event.key === "ContextMenu"' in web_shell_page
    assert 'event.shiftKey && event.key === "F10"' in web_shell_page
    assert "requestDeviceRowContext(row, item, event)" in web_shell_page
    assert "bridge.selectSession(session.tabId)" in web_shell_page
    assert "bridge.requestSessionContextMenu(session.tabId, point.x, point.y)" in web_shell_page
    assert "Terminal Workspace" in navigation_page
    assert 'id="devices"' in navigation_page
    assert "function renderDevices(rows)" in navigation_page
    assert "bridge.requestDeviceConnect(deviceId, kind)" in navigation_page
    assert 'actions.className = "device-actions"' in navigation_page
    assert 'item.setAttribute("role", "button")' in navigation_page
    assert 'item.setAttribute("aria-current", session.active ? "true" : "false")' in navigation_page
    assert "bridge.selectSession(session.tabId)" in navigation_page
    assert "bridge.closeSession(session.tabId)" in navigation_page
    assert "bridge.requestSessionContextMenu(session.tabId, point.x, point.y)" in navigation_page
    assert 'main.className = "session-main"' in navigation_page
    assert 'meta.className = "session-meta"' in navigation_page
    assert 'close.className = "session-close"' in navigation_page
    assert 'event.stopPropagation()' in navigation_page
    assert 'item.addEventListener("contextmenu", (event) => requestSessionContext(item, session, event))' in navigation_page
    assert 'event.key === "ContextMenu"' in navigation_page
    assert 'event.shiftKey && event.key === "F10"' in navigation_page
    assert "bridge.requestHome()" in navigation_page
    assert "@media (max-width: 420px)" in navigation_page
    assert ".counts {\n        grid-template-columns: repeat(2, minmax(0, 1fr));" in navigation_page
    assert ".metric:last-child {\n        grid-column: 1 / -1;" in navigation_page
    assert "text-overflow: ellipsis;" in navigation_page
    assert ".actions button" in navigation_page
    assert "grid-template-columns: minmax(0, 1fr) auto;" in navigation_page
    for page_name in ("web_shell.html", "device_navigation.html"):
        page = (web_root / page_name).read_text(encoding="utf-8")
        assert "#d6deeb" not in page
        assert "#0b0f14" not in page
        assert "#05080c" not in page
        assert "#080c11" not in page
        assert "#202733" not in page
        assert "#0a0d12" not in page
        assert "rgba(36, 43, 54" not in page
        assert ".status { font-weight: 800; }" not in page
        assert "button,\n    input,\n    select" not in page
        assert "input,\n    select {" not in page
        assert "button:hover {" not in page
        assert "button:focus-visible" not in page
        assert "html,\n    body" not in page
        assert "* { box-sizing: border-box; }" not in page
    assert 'body class="workspace-terminal-page"' in xterm_page
    assert 'body class="workspace-terminal-page"' in (
        web_root / "xterm_prewarm.html"
    ).read_text(encoding="utf-8")
    assert 'id="homeWorkspace"' not in (
        web_root / "web_shell.html"
    ).read_text(encoding="utf-8")
    token_source = (Path(__file__).resolve().parents[1] / "src" / "theme_tokens.py").read_text(encoding="utf-8")
    assert 'WORKSPACE_BG = "#020617"' in token_source
    assert "qwebengine_background_stylesheet(" in (
        widget_root / "web_shell_widget.py"
    ).read_text(encoding="utf-8")
    assert "qwebengine_background_stylesheet(" in (
        widget_root / "device_navigation_web_widget.py"
    ).read_text(encoding="utf-8")
    assert "WORKSPACE_BG" in (widget_root / "xterm_web_widget.py").read_text(encoding="utf-8")
    assert "#07090c" not in (widget_root / "web_shell_widget.py").read_text(encoding="utf-8")
    assert "#07090c" not in (widget_root / "device_navigation_web_widget.py").read_text(encoding="utf-8")
    assert "#06090d" not in (widget_root / "xterm_web_widget.py").read_text(encoding="utf-8")


def test_design_system_documents_workspace_ui_invariants() -> None:
    root = Path(__file__).resolve().parents[1]
    design_system = (root / "design-system" / "MASTER.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    theme = (root / "src" / "web" / "assets" / "workspace-theme.css").read_text(encoding="utf-8")

    for token in (
        "#020617",
        "#0f172a",
        "#08101d",
        "#22c55e",
        "#60a5fa",
        "#f8fafc",
        "#d8fff0",
        "#fecaca",
        "#f8e7a1",
        "#475569",
        "rgba(2, 6, 23, 0.72)",
        "rgba(34, 197, 94, 0.42)",
        "rgba(251, 191, 36, 0.13)",
        "rgba(96, 165, 250, 0.13)",
        "rgba(113, 128, 150, 0.14)",
        "rgba(8, 16, 29, 0.55)",
        "#c4b5fd",
        "#91d7e3",
        "#fca5a5",
        "#86efac",
        "#f5d99a",
        "#b7c8ff",
        "#ddd6fe",
        "#b5eff7",
        "#f6f8fb",
    ):
        assert token in design_system
    assert "workspace-theme.css" in design_system
    assert "src/theme_tokens.py" in design_system
    assert "workspace-page" in design_system
    assert "workspace-compact-page" in design_system
    assert "workspace-terminal-page" in design_system
    assert "shared `button`, `input`, `select`" in design_system
    assert "workspace-field" in design_system
    assert "workspace-panel" in design_system
    assert "workspace-button-row" in design_system
    assert "workspace-step-actions" in design_system
    assert "style=" in design_system
    assert "new_workspace_menu()" in design_system
    assert "xterm WebView" in design_system
    assert "xterm ANSI theme colors" in design_system
    assert "ContextMenu" in design_system
    assert "Shift+F10" in design_system
    assert "page-local context menus" in design_system
    assert "aria-selected" in design_system
    assert "Do not show the left device pool on the home screen" in design_system
    assert "design-system/MASTER.md" in readme
    assert "Web-style OLED design system" in readme
    theme_vars = sorted(set(re.findall(r"^\s*(--[a-z0-9-]+):", theme, flags=re.MULTILINE)))
    assert theme_vars
    assert all(f"`{name}`" in design_system for name in theme_vars)


def test_terminal_render_surfaces_share_workspace_palette() -> None:
    root = Path(__file__).resolve().parents[1]
    canvas = (root / "src" / "widgets" / "terminal_canvas.py").read_text(encoding="utf-8")
    legacy = (root / "src" / "widgets" / "terminal_widget.py").read_text(encoding="utf-8")

    assert "DEFAULT_BG = QColor(\"#020617\")" in canvas
    assert "DEFAULT_FG = QColor(\"#f8fafc\")" in canvas
    assert "CURSOR_BG = QColor(\"#22c55e\")" in canvas
    assert '"white": QColor("#f8fafc")' in canvas
    assert '"white": "#f8fafc"' in legacy
    assert 'self._file_format = self._format("#f8fafc")' in legacy
    assert "/* Terminal render surface foundation */" in APP_STYLE
    assert "QWebEngineView#terminalWebView" in APP_STYLE
    xterm_widget = (root / "src" / "widgets" / "xterm_web_widget.py").read_text(encoding="utf-8")
    assert "self._view.setContextMenuPolicy(Qt.CustomContextMenu)" in xterm_widget
    assert "customContextMenuRequested.emit(self._view.mapTo(self, pos))" in xterm_widget
    assert "#06090d" not in canvas
    assert "#d6deeb" not in canvas


def test_center_stage_uses_web_home_until_sessions_open(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    window.update_center_stage_state()

    assert not window.web_shell.isHidden()
    assert window.session_tab_widget.isHidden()

    page = QWidget()
    window.session_tab_widget.addTab(page, "Session")
    window.show_terminal_workspace()

    assert window.web_shell.isHidden()
    assert not window.session_tab_widget.isHidden()
    assert window.left_sidebar_compact
    assert not window.activity_home_button.isChecked()

    window.activity_home_button.click()

    assert not window.web_shell.isHidden()
    assert window.session_tab_widget.isHidden()
    assert window.session_tab_widget.count() == 1
    assert not window.left_sidebar_compact
    assert window.activity_home_button.isChecked()

    window.show_terminal_workspace()

    assert window.web_shell.isHidden()
    assert not window.session_tab_widget.isHidden()


def test_left_device_pool_hides_on_home_and_returns_for_sessions(
    app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = app
    monkeypatch.setenv("QT_QPA_PLATFORM", "")
    window = DeviceDesktopApp()
    window.left_sidebar_active_panel = "devices"

    window.update_center_stage_state()

    assert window.left_sidebar_collapsed

    window.left_sidebar_collapsed = False
    window.apply_left_sidebar_state()
    window.show_web_home()

    assert window.left_sidebar_collapsed
    assert not window.left_sidebar_content.isVisible()
    assert window.left_sidebar_shell.maximumWidth() == 46

    window.session_tab_widget.addTab(QWidget(), "Session")
    window.show_terminal_workspace()

    assert not window.left_sidebar_collapsed
    assert window.left_sidebar_compact
    assert window.left_sidebar_shell.minimumWidth() == window.TERMINAL_SIDEBAR_MIN_WIDTH
    assert window.left_sidebar_shell.maximumWidth() == window.TERMINAL_SIDEBAR_MAX_WIDTH
    assert window.left_sidebar_content.minimumWidth() == window.TERMINAL_SIDEBAR_CONTENT_MIN_WIDTH
    assert window.left_sidebar_content.maximumWidth() == window.TERMINAL_SIDEBAR_CONTENT_MAX_WIDTH
    window.handle_main_splitter_moved(500, 1)
    assert window.terminal_sidebar_width == 500
    assert window.device_navigation_header.isHidden()
    assert window.device_context_panel.isHidden()

    window.show_web_home()

    assert window.left_sidebar_collapsed
    assert not window.left_sidebar_compact

    window.left_sidebar_collapsed = False
    window.left_sidebar_active_panel = "devices"
    window.apply_left_sidebar_state()

    assert not window.left_sidebar_content.isVisible()
    assert window.left_sidebar_shell.maximumWidth() == 46


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
    assert window.device_table.item(0, 0).background().color().name() == "#08101d"
    assert window.device_table.item(0, 0).foreground().color().name() == "#f8fafc"
    assert window.device_table.item(0, 2).foreground().color().name() == "#718096"
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
