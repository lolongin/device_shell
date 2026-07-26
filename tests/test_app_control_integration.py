from __future__ import annotations

import os
from pathlib import Path
import queue
import socket
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
    batched = run_with_qt_events(
        app,
        lambda: client.terminal_execute_batch(
            ["display version", "dir flash:/"],
            session_id=session_id,
            command_timeout_seconds=3,
            total_timeout_seconds=10,
        ),
    )
    interacted = run_with_qt_events(
        app,
        lambda: client.terminal_interact(
            [
                {"type": "send", "text": "ftp 192.0.2.10 2121"},
                {
                    "type": "expect",
                    "success": ["ftp_prompt"],
                    "responses": [
                        {
                            "match": "username_prompt",
                            "secret_ref": "transfer.username",
                        },
                        {
                            "match": "password_prompt",
                            "secret_ref": "transfer.password",
                        },
                    ],
                    "failures": ["Login incorrect", "530 "],
                },
                {"type": "send", "text": "quit"},
                {"type": "expect", "success": ["device_prompt"]},
            ],
            session_id=session_id,
            total_timeout_seconds=10,
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
    assert batched["data"]["status"] == "completed"
    assert "SimOS V1.0" in batched["data"]["steps"][1]["output"]
    assert "Directory of flash:/" in batched["data"]["steps"][3]["output"]
    assert interacted["data"]["status"] == "completed"
    assert interacted["data"]["steps"][1]["response_count"] == 2
    assert "device" not in str(interacted["data"]["steps"][1])
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


def test_package_upgrade_uses_local_ftp_interaction(
    app: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVICE_TUI_APPROVAL_MODE", raising=False)
    package = tmp_path / "target.cc"
    package.write_bytes(b"x" * 1024)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    window = DeviceDesktopApp()
    window.package_upgrade_file_input.setText(str(package))
    window.package_upgrade_server_host_input.setText("127.0.0.1")
    window.package_upgrade_port_input.setText(str(port))
    window.package_upgrade_include_slave_checkbox.setChecked(False)
    window.package_upgrade_reboot_checkbox.setChecked(False)
    state_path = tmp_path / "upgrade-app-control.json"
    assert window.start_app_control_server(state_path=state_path)
    client = AppControlClient.from_state_file(state_path)

    run_with_qt_events(app, lambda: client.device_select("SIM-TERMINAL"))
    run_with_qt_events(
        app,
        lambda: client.session_manage(
            "open",
            device_id="SIM-TERMINAL",
            protocol="auto",
            timeout_seconds=3,
        ),
    )
    state = window.package_upgrade_session_for_device("SIM-TERMINAL")
    assert state is not None
    state.session.configure_transfer_input_timeout(0.2)
    started = run_with_qt_events(
        app,
        lambda: client.package_upgrade_start("SIM-TERMINAL"),
    )
    operation_id = started["data"]["operation_id"]

    deadline = time.monotonic() + 25
    operation: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = run_with_qt_events(
            app,
            lambda: client.operation_get(operation_id),
        )
        operation = response["data"]["operation"]
        if operation["status"] != "running":
            break
        for _index in range(10):
            app.processEvents()
            time.sleep(0.02)

    assert operation["status"] == "completed"
    assert window.package_upgrade_run["download_execution_id"]
    assert window.package_upgrade_pipeline_labels["download"].text().startswith("完成")

    window.close()
    assert not state_path.exists()


def test_managed_file_transfer_lists_and_verifies_simulated_file(
    app: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVICE_TUI_APPROVAL_MODE", raising=False)
    package = tmp_path / "large-package.bin"
    package.write_bytes(b"x" * 4_096)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    window = DeviceDesktopApp()
    window.transfer_root_input.setText(str(tmp_path))
    window.transfer_host_input.setText("127.0.0.1")
    window.transfer_port_input.setText(str(port))
    window.transfer_username_input.setText("managed-user")
    window.transfer_password_input.setText("managed-password")
    state_path = tmp_path / "managed-transfer-app-control.json"
    assert window.start_app_control_server(state_path=state_path)
    client = AppControlClient.from_state_file(state_path)

    listed = run_with_qt_events(app, client.file_transfer_list)
    listed_package = next(
        item
        for item in listed["data"]["files"]
        if item["relative_path"] == "large-package.bin"
    )
    assert listed_package["name"] == "large-package.bin"
    assert listed_package["size_bytes"] == 4_096
    assert "modified_at" in listed_package
    session_result = run_with_qt_events(
        app,
        lambda: client.session_manage(
            "open",
            device_id="SIM-TERMINAL",
            protocol="auto",
            timeout_seconds=3,
        ),
    )
    session_id = session_result["data"]["session"]["session_id"]
    window.session_tabs_by_id[session_id].session.configure_transfer_input_timeout(0.2)
    started = run_with_qt_events(
        app,
        lambda: client.file_transfer_start(
            "SIM-TERMINAL",
            "large-package.bin",
            "flash:/received-package.bin",
        ),
    )
    operation_id = started["data"]["operation_id"]

    deadline = time.monotonic() + 12
    operation: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = run_with_qt_events(
            app,
            lambda: client.operation_get(operation_id),
        )
        operation = response["data"]["operation"]
        if operation["status"] != "running":
            break
        for _index in range(10):
            app.processEvents()
            time.sleep(0.01)

    terminal = run_with_qt_events(
        app,
        lambda: client.terminal_read("SIM-TERMINAL", max_chars=32_768),
    )
    output = terminal["data"]["output"]
    assert operation["status"] == "completed"
    assert operation["data"]["stage"] == "completed"
    assert operation["data"]["source_size"] == 4_096
    assert "received-package.bin" in output
    assert "4,096" in output
    assert "managed-user" not in output
    assert "managed-password" not in output
    assert "startup system-software" not in output
    assert "Rebooting simulated device" not in output

    conflict_started = run_with_qt_events(
        app,
        lambda: client.file_transfer_start(
            "SIM-TERMINAL",
            "large-package.bin",
            "flash:/received-package.bin",
        ),
    )
    conflict_id = conflict_started["data"]["operation_id"]
    conflict: dict[str, Any] = {}
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = run_with_qt_events(
            app,
            lambda: client.operation_get(conflict_id),
        )
        conflict = response["data"]["operation"]
        if conflict["status"] != "running":
            break
        app.processEvents()
        time.sleep(0.01)
    assert conflict["status"] == "failed"
    assert conflict["data"]["error_code"] == "destination_exists"

    overwrite_started = run_with_qt_events(
        app,
        lambda: client.file_transfer_start(
            "SIM-TERMINAL",
            "large-package.bin",
            "flash:/received-package.bin",
            overwrite=True,
        ),
    )
    overwrite_id = overwrite_started["data"]["operation_id"]
    overwritten: dict[str, Any] = {}
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        response = run_with_qt_events(
            app,
            lambda: client.operation_get(overwrite_id),
        )
        overwritten = response["data"]["operation"]
        if overwritten["status"] != "running":
            break
        for _index in range(5):
            app.processEvents()
            time.sleep(0.01)
    assert overwritten["status"] == "completed"

    window.close()
    assert not state_path.exists()
