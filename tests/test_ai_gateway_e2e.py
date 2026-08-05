# tests/test_ai_gateway_e2e.py
"""End-to-end gateway integration on the simulated device.

Drives ai_create_session -> ai_execute_command -> ai_get_result through the
full stack: MCP tool routing -> gateway.call -> AppControlClient HTTP call ->
HTTP route -> service._invoke -> GatewayService (with the injected terminal
executor) -> terminal_execution_coordinator -> simulated session.

The gateway executor blocks the HTTP thread (completion_event.wait) while the
runner advances on the Qt thread, so each blocking HTTP call runs on a worker
thread while this test pumps app.processEvents() — see run_with_qt_events,
mirrored from tests/test_app_control_integration.py.
"""

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

from src.device_mcp.client import AppControlClient
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def run_with_qt_events(
    app: QApplication,
    callback: Callable[[], Any],
    *,
    timeout: float = 15.0,
) -> Any:
    """Run a blocking callback on a worker thread while pumping Qt events.

    The gateway executor blocks the HTTP thread (completion_event.wait); the
    simulated session advances on the Qt thread via ui_timer, so the test
    thread must keep pumping processEvents for the runner to make progress.
    """
    results: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            results.put((True, callback()))
        except Exception as exc:  # noqa: BLE001
            results.put((False, exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    thread.join(timeout=0.2)
    assert not thread.is_alive(), "gateway request did not finish"
    ok, value = results.get_nowait()
    if not ok:
        raise value  # type: ignore[misc]
    return value


def test_e2e_create_session_execute_and_get_result(
    app: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEVICE_TUI_APPROVAL_MODE", raising=False)
    _ = app
    window = DeviceDesktopApp()
    state_path = tmp_path / "app-control.json"
    assert window.start_app_control_server(state_path=state_path)
    client = AppControlClient.from_state_file(state_path)

    created = run_with_qt_events(
        app,
        lambda: client.ai_create_session("SIM-TERMINAL"),
    )
    assert created["ok"]
    session_id = created["data"]["session_id"]
    assert session_id

    executed = run_with_qt_events(
        app,
        lambda: client.ai_execute_command(
            session_id=session_id,
            command="display version",
            timeout_seconds=5,
        ),
        timeout=20,
    )
    assert executed["ok"]
    assert executed["data"]["summary"]["status"] == "success"
    result_id = executed["data"]["result_id"]

    fetched = run_with_qt_events(
        app,
        lambda: client.ai_get_result(result_id=result_id, include_raw=True),
    )
    assert fetched["ok"]
    assert fetched["data"]["result"]["result_id"] == result_id
    assert "raw_output" in fetched["data"]

    window.close()
    assert not state_path.exists()
