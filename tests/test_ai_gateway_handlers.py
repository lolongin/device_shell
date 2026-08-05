from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

from src.ai_device_ops import AiDeviceAction, RiskLevel
from src.app.main_window import DeviceDesktopApp
from src.data import Device


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_ai_gateway_service_is_initialized(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert hasattr(window, "ai_gateway_service")
    assert window.ai_gateway_service is window.gateway_service()


def test_ai_gateway_script_style_simulated_is_network(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.gateway_script_style("SIM-TERMINAL") == "network"


def test_ai_gateway_script_style_linux_device_is_linux(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    # SSH-only Linux host: ssh_ip set, telnet_ip empty → whole-block script.
    window.device_by_id["linux-1"] = Device(
        id="linux-1",
        name="Linux 主机",
        domain="测试",
        device_type="服务器",
        cpu="x86_64",
        status="空闲",
        owner=None,
        ssh_ip="10.0.0.1",
        telnet_ip="",
        username="root",
        password="",
        vendor="Linux",
        model="Ubuntu",
        site="本机",
        rack="-",
        version="22.04",
        notes="SSH-only Linux host.",
    )
    assert window.gateway_script_style("linux-1") == "linux"


def test_ai_gateway_get_result_round_trip(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    # Seed the result store directly (execution itself is driven by service.py).
    result_id = window.ai_gateway_service.result_store.store(
        "command",
        "display version\nVRP (R) software, Version 8.180\n",
        metadata={"status": "success", "exit_code": 0, "command_count": 1, "duration_ms": 5},
    )
    fetched = window.execute_ai_device_action(
        AiDeviceAction(
            "ai_gateway_get_result",
            "读取网关结果",
            RiskLevel.OBSERVE,
            params={"result_id": result_id, "include_raw": True},
        )
    )
    assert fetched.ok
    assert fetched.data["result"]["result_id"] == result_id
    # raw_output is a TOP-LEVEL key of the result payload (spec contract).
    assert "raw_output" in fetched.data


def test_ai_gateway_get_result_missing_is_404(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    result = window.execute_ai_device_action(
        AiDeviceAction(
            "ai_gateway_get_result",
            "读取网关结果",
            RiskLevel.OBSERVE,
            params={"result_id": "R-does-not-exist"},
        )
    )
    assert not result.ok
    assert result.error_code == "result_not_found"
    assert result.http_status == 404
