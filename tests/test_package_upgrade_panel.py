import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_package_upgrade_panel_exists_in_left_sidebar(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()

    window.show_left_sidebar_panel("package_upgrade")

    assert window.left_sidebar_active_panel == "package_upgrade"
    assert window.left_sidebar_stack.currentIndex() == 4
    assert window.activity_package_upgrade_button.isChecked()
    assert window.package_upgrade_one_click_button.text() == "一键更换选中设备"
    assert "华为" not in window.package_upgrade_one_click_button.text()
    assert window.package_upgrade_auto_delete_checkbox.isChecked()
    assert window.package_upgrade_include_slave is True
    assert not hasattr(window, "package_upgrade_include_slave_checkbox")
    assert window.package_upgrade_reboot_checkbox.isChecked()
    assert not window.package_upgrade_reboot_checkbox.isHidden()
    assert window.package_upgrade_startup_output.parent() is None
    assert window.package_upgrade_script_output.parent() is None
    assert window.package_upgrade_read_terminal_button.parent() is None
    assert window.package_upgrade_send_button.parent() is None
    assert set(window.package_upgrade_pipeline_labels) == {
        "precheck",
        "cleanup",
        "download",
        "verify",
        "startup",
        "confirm",
    }


def test_package_upgrade_panel_generates_dual_controller_cleanup_script(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    package = tmp_path / "target.cc"
    package.write_bytes(b"0" * 1024)
    window = DeviceDesktopApp()
    window.package_upgrade_file_input.setText(str(package))
    window.package_upgrade_server_host_combo.setCurrentText("192.0.2.10")
    window.transfer_port = 2121
    window.package_upgrade_startup_output.setPlainText(
        """
        Current startup system software: flash:/current.cc
        Next startup system software: flash:/current.cc
        """
    )
    window.package_upgrade_master_dir_output.setPlainText(
        """
          0  -rw-    500,000,000  Jan 01 2026 10:00:00  old.cc
          1  -rw-    500,000,000  Jan 01 2026 10:00:00  current.cc
        1,048,576 KB total (1 KB free)
        """
    )
    window.package_upgrade_slave_dir_output.setPlainText(
        """
          0  -rw-    500,000,000  Jan 01 2026 10:00:00  old-slave.cc
          1  -rw-    500,000,000  Jan 01 2026 10:00:00  current.cc
        1,048,576 KB total (1 KB free)
        """
    )

    window.generate_package_upgrade_script()
    script = window.package_upgrade_script_output.toPlainText()

    assert "delete /unreserved /quiet flash:/old.cc" in script
    assert "delete /unreserved /quiet slave#flash:/old-slave.cc" in script
    assert "ftp 192.0.2.10 2121" in script
    assert "copy flash:/target.cc slave#flash:/target.cc" in script
    assert "startup system-software flash:/target.cc all" in script


def test_package_upgrade_jump_keeps_upgrade_panel_visible(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.show_left_sidebar_panel("package_upgrade")
    window.jump_to_session = lambda _tab_id: window.show_left_sidebar_panel("devices")

    window.jump_to_package_upgrade_session("tab-1")

    assert window.left_sidebar_active_panel == "package_upgrade"


def test_package_upgrade_safety_report_blocks_unconfirmed_space(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    package = tmp_path / "target.cc"
    package.write_bytes(b"0" * 1024)
    window = DeviceDesktopApp()
    window.package_upgrade_file_input.setText(str(package))
    window.package_upgrade_server_host_combo.setCurrentText("192.0.2.10")
    window.package_upgrade_master_dir_output.setPlainText("Directory of flash:/\n")
    window.package_upgrade_slave_dir_output.setPlainText("Directory of slave#flash:/\n")
    config = window.package_upgrade_config()

    assert config is not None
    _entries, blockers, _status = window.package_upgrade_safety_report(config)

    assert "无法确认主控剩余空间" in blockers
    assert "无法确认备控剩余空间" in blockers


def test_one_click_precheck_downgrades_absent_standby_to_single_controller(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    package = tmp_path / "target.cc"
    package.write_bytes(b"0" * 1024)
    window = DeviceDesktopApp()
    window.package_upgrade_file_input.setText(str(package))
    config = window.package_upgrade_config()
    assert config is not None

    tab_id = "upgrade-single-controller"
    window.session_tabs_by_id[tab_id] = SimpleNamespace(
        recent_output_buffer="",
        terminal=SimpleNamespace(toPlainText=lambda: ""),
    )
    window.package_upgrade_operation_state = {
        "status": "running",
        "stage": "precheck",
        "message": "",
    }
    window.package_upgrade_run = {
        "tab_id": tab_id,
        "config": config,
        "precheck_offset": 0,
        "precheck_outputs": {
            "display startup": (
                "Current startup system software: flash:/current.cc\n"
                "Next startup system software: flash:/current.cc\n"
            ),
            f"dir {config.master_storage}": (
                "Directory of flash:/\n"
                "1,048,576 KB total (256,000 KB free)\n"
            ),
            f"dir {config.slave_storage}": "Error: The device does not exist.\n",
        },
        "cancelled": False,
    }
    captured: dict[str, object] = {}
    window._run_package_upgrade_execution = (
        lambda received_tab_id, received_config, cleanup_entries: captured.update(
            tab_id=received_tab_id,
            config=received_config,
            cleanup_entries=cleanup_entries,
        )
    )

    window._finish_package_upgrade_one_click(tab_id)

    effective_config = captured["config"]
    assert effective_config.include_slave is False
    assert captured["tab_id"] == tab_id
    assert "未检测到备控，按单主控执行" in window.package_upgrade_status_label.text()
    assert "slave#flash:/" not in window.package_upgrade_script_output.toPlainText()


def test_package_upgrade_host_is_selectable_combo(app: QApplication) -> None:
    """The local host address is a selectable (editable) combo listing IPv4
    addresses, so the operator can pick a VPN/LAN address."""
    _ = app
    window = DeviceDesktopApp()
    window.show_left_sidebar_panel("package_upgrade")
    combo = window.package_upgrade_server_host_combo
    assert combo is not None
    assert combo.isEditable()
    # Should contain at least the loopback-free IPv4 addresses of this host.
    assert combo.count() >= 1
    assert combo.currentText() != ""
    window.close()


def test_package_upgrade_dir_input_exists(app: QApplication) -> None:
    """The package-directory selector row exists alongside the file picker."""
    _ = app
    window = DeviceDesktopApp()
    window.show_left_sidebar_panel("package_upgrade")
    assert window.package_upgrade_dir_input is not None
    assert window.package_upgrade_dir_browse_button is not None
    assert window.package_upgrade_dir_browse_button.text() == "浏览"
    window.close()


def test_package_upgrade_selections_persist(
    app: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Host / dir / file selections are remembered and restored."""
    import json
    import tempfile
    from pathlib import Path

    _ = app
    with tempfile.TemporaryDirectory() as td:
        state_path = Path(td) / "state.json"
        monkeypatch.setenv("DEVICE_TUI_DESKTOP_STATE_PATH", str(state_path))
        window = DeviceDesktopApp()
        window.show_left_sidebar_panel("package_upgrade")
        window.package_upgrade_server_host_combo.setCurrentText("10.9.8.7")
        window.package_upgrade_dir_input.setText("/tmp/pkgs")
        window.package_upgrade_file_input.setText("/tmp/pkgs/upgrade.cc")
        window._remember_package_upgrade_values()
        assert window.package_upgrade_server_host == "10.9.8.7"
        assert window.package_upgrade_package_dir == "/tmp/pkgs"
        assert window.package_upgrade_package_file == "/tmp/pkgs/upgrade.cc"
        window.close()

        # A fresh instance restores the remembered values.
        second = DeviceDesktopApp()
        assert second.package_upgrade_server_host == "10.9.8.7"
        assert second.package_upgrade_package_dir == "/tmp/pkgs"
        assert second.package_upgrade_package_file == "/tmp/pkgs/upgrade.cc"
        second.close()
