from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_package_upgrade_reboot_wait_marks_completion(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    completed: list[str] = []
    window.finish_package_upgrade_run = completed.append
    window.session_tabs_by_id["sim"] = SimpleNamespace(
        recent_output_buffer="reboot\nRebooting simulated device...\nSystem ready.\n<sim> "
    )

    window._wait_package_upgrade_reboot_completion("sim", 0, 0.0)

    assert completed == ["reboot 已完成，设备已重新进入可交互状态。"]
