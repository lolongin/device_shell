import os

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
    assert window.package_upgrade_include_slave_checkbox.isChecked()
    assert window.package_upgrade_startup_output.parent() is None
    assert window.package_upgrade_script_output.parent() is None
    assert window.package_upgrade_read_terminal_button.parent() is None
    assert window.package_upgrade_send_button.parent() is None


def test_package_upgrade_panel_generates_dual_controller_cleanup_script(
    app: QApplication,
    tmp_path,
) -> None:
    _ = app
    package = tmp_path / "target.cc"
    package.write_bytes(b"0" * 1024)
    window = DeviceDesktopApp()
    window.package_upgrade_file_input.setText(str(package))
    window.package_upgrade_server_host_input.setText("192.0.2.10")
    window.package_upgrade_port_input.setText("2121")
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
