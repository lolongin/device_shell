from __future__ import annotations

import os
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.main_window import DeviceDesktopApp
from src.app_control import APPROVAL_MODE_DISABLED, APPROVAL_MODE_REQUIRED
from src.app_control_client import AppControlClient


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def run_with_qt_events(
    app: QApplication,
    callback: Callable[[], Any],
    *,
    timeout: float = 5.0,
) -> Any:
    results: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            results.put((True, callback()))
        except Exception as exc:
            results.put((False, exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    thread.join(timeout=0.2)
    assert not thread.is_alive(), "control request did not finish"
    ok, value = results.get_nowait()
    if not ok:
        raise value
    return value


def test_running_app_control_server_executes_without_device_tui_approval(
    app: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVICE_TUI_APPROVAL_MODE", raising=False)
    window = DeviceDesktopApp()
    state_path = tmp_path / "app-control.json"
    assert window.start_app_control_server(state_path=state_path)
    client = AppControlClient.from_state_file(state_path)

    devices = run_with_qt_events(app, client.device_list)
    assert any(
        device["id"] == "SIM-TERMINAL"
        for device in devices["data"]["devices"]
    )

    run_with_qt_events(app, lambda: client.device_select("SIM-TERMINAL"))
    status = run_with_qt_events(app, client.system_status)
    details = run_with_qt_events(
        app,
        lambda: client.device_get("SIM-TERMINAL"),
    )
    managed = run_with_qt_events(
        app,
        lambda: client.session_manage(
            "open",
            device_id="SIM-TERMINAL",
            protocol="auto",
            timeout_seconds=3,
        ),
    )
    session_id = managed["data"]["session"]["session_id"]
    executed = run_with_qt_events(
        app,
        lambda: client.terminal_execute(
            "display version",
            session_id=session_id,
            timeout_seconds=3,
        ),
    )
    response = run_with_qt_events(
        app,
        lambda: client.terminal_send_command("SIM-TERMINAL", "reboot"),
    )

    assert status["data"]["approval_mode"] == APPROVAL_MODE_DISABLED
    assert details["data"]["device"]["protocols"] == ["simulated"]
    assert managed["data"]["session"]["status"] == "connected"
    assert executed["data"]["completion_reason"] == "prompt"
    assert "SimOS V1.0" in executed["data"]["output"]
    assert "Power on self-test" not in executed["data"]["output"]
    assert response["ok"]
    assert window.app_control_service.approval_mode == APPROVAL_MODE_DISABLED
    assert window.ai_external_approval_list.count() == 0
    assert window.ai_external_approval_title.isHidden()
    assert window.ai_external_approval_list.isHidden()
    assert window.ai_external_approve_button.isHidden()
    assert window.ai_external_reject_button.isHidden()
    assert "内部审批已关闭" in window.ai_external_control_status_label.text()

    for _index in range(5):
        app.processEvents()
        time.sleep(0.01)
    window.close()
    assert not state_path.exists()


def test_required_mode_restores_device_tui_approval_controls(
    app: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEVICE_TUI_APPROVAL_MODE", APPROVAL_MODE_REQUIRED)
    window = DeviceDesktopApp()
    state_path = tmp_path / "required-app-control.json"
    assert window.start_app_control_server(state_path=state_path)
    assert window.app_control_service.approval_mode == APPROVAL_MODE_REQUIRED
    assert "内部审批已启用" in window.ai_external_control_status_label.text()

    response_status, _response = window.app_control_service.invoke(
        "terminal_send_command",
        {"device_id": "SIM-TERMINAL", "command": "reboot"},
        source="integration-test",
    )
    window._drain_ui_queue()

    assert response_status == 409
    assert window.ai_external_approval_list.count() == 1
    assert not window.ai_external_approval_title.isHidden()
    assert not window.ai_external_approval_list.isHidden()
    assert not window.ai_external_approve_button.isHidden()
    assert not window.ai_external_reject_button.isHidden()

    window.close()
    assert not state_path.exists()
