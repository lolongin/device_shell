from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.ai_device_ops import AiDeviceAction, AiDeviceToolResult
from src.app_control import APPROVAL_MODE_REQUIRED, AppControlService
from src.app_control_client import AppControlClient, AppControlClientError
from src.app_control_server import AppControlHttpServer


@dataclass
class HttpFakeBackend:
    actions: list[AiDeviceAction]

    def execute_ai_device_action(
        self,
        action: AiDeviceAction,
        *,
        approved: bool = False,
    ) -> AiDeviceToolResult:
        _ = approved
        self.actions.append(action)
        if action.kind == "system_status":
            return AiDeviceToolResult(
                action,
                ok=True,
                message="运行中。",
                data={
                    "ready": True,
                    "session_counts": {"total": 0},
                    "active_operations": 0,
                },
            )
        if action.kind == "device_get":
            return AiDeviceToolResult(
                action,
                ok=True,
                message="设备详情。",
                data={"device": {"id": action.device_id, "protocols": ["simulated"]}},
            )
        if action.kind == "session_list":
            return AiDeviceToolResult(
                action,
                ok=True,
                message="会话列表。",
                data={"sessions": []},
            )
        if action.kind == "list_devices":
            return AiDeviceToolResult(
                action,
                ok=True,
                message="读取成功。",
                data={"devices": [{"id": "SIM-TERMINAL", "name": "模拟终端"}]},
            )
        return AiDeviceToolResult(action, ok=True, message="执行成功。")


@pytest.fixture
def running_control_server(
    tmp_path: Path,
) -> tuple[AppControlHttpServer, AppControlService, HttpFakeBackend, Path]:
    backend = HttpFakeBackend(actions=[])
    service = AppControlService(backend)
    state_path = tmp_path / "app-control.json"
    server = AppControlHttpServer(
        service,
        state_path=state_path,
        token="test-control-token",
    )
    server.start()
    try:
        yield server, service, backend, state_path
    finally:
        server.stop()


def test_http_server_state_discovery_and_device_list(
    running_control_server: tuple[
        AppControlHttpServer,
        AppControlService,
        HttpFakeBackend,
        Path,
    ],
) -> None:
    server, _service, backend, state_path = running_control_server
    client = AppControlClient.from_state_file(state_path)

    assert client.health()["ok"]
    response = client.device_list()

    assert server.base_url.startswith("http://127.0.0.1:")
    assert response["data"]["devices"][0]["id"] == "SIM-TERMINAL"
    assert backend.actions[0].kind == "list_devices"


def test_http_client_reuses_loopback_keep_alive_connection(
    running_control_server: tuple[
        AppControlHttpServer,
        AppControlService,
        HttpFakeBackend,
        Path,
    ],
) -> None:
    _server, _service, _backend, state_path = running_control_server
    client = AppControlClient.from_state_file(state_path)

    client.health()
    first_connection = client._pool._available[0]
    client.device_list()

    assert client._pool._available[0] is first_connection
    client.close()


def test_http_operation_wait_returns_timeout_snapshot_without_polling_client(
    running_control_server: tuple[
        AppControlHttpServer,
        AppControlService,
        HttpFakeBackend,
        Path,
    ],
) -> None:
    _server, _service, _backend, state_path = running_control_server
    client = AppControlClient.from_state_file(state_path)
    started = client.package_upgrade_start("SIM-TERMINAL")

    waited = client.operation_wait(
        started["data"]["operation_id"],
        timeout_seconds=1,
        since_revision=started["data"]["operation"]["revision"],
    )

    assert waited["data"]["wait_timed_out"] is True
    assert waited["data"]["operation"]["status"] == "running"
    client.close()


def test_http_server_rejects_invalid_token(
    running_control_server: tuple[
        AppControlHttpServer,
        AppControlService,
        HttpFakeBackend,
        Path,
    ],
) -> None:
    server, _service, _backend, _state_path = running_control_server
    client = AppControlClient(server.base_url, "wrong-token")

    with pytest.raises(AppControlClientError) as captured:
        client.device_list()

    assert captured.value.response["error"]["code"] == "unauthorized"


def test_http_reliability_core_routes(
    running_control_server: tuple[
        AppControlHttpServer,
        AppControlService,
        HttpFakeBackend,
        Path,
    ],
) -> None:
    _server, _service, _backend, state_path = running_control_server
    client = AppControlClient.from_state_file(state_path)

    status = client.system_status()
    device = client.device_get("SIM-TERMINAL")
    sessions = client.session_list("SIM-TERMINAL")

    assert status["data"]["approval_mode"] == "disabled"
    assert device["data"]["device"]["id"] == "SIM-TERMINAL"
    assert sessions["data"]["sessions"] == []


def test_http_high_risk_command_executes_without_device_tui_approval(
    running_control_server: tuple[
        AppControlHttpServer,
        AppControlService,
        HttpFakeBackend,
        Path,
    ],
) -> None:
    _server, service, backend, state_path = running_control_server
    client = AppControlClient.from_state_file(state_path)

    response = client.terminal_send_command("SIM-TERMINAL", "reboot")

    assert response["ok"]
    assert backend.actions[-1].command == "reboot"
    assert service.approvals.pending() == []


def test_http_required_mode_preserves_approval_round_trip(tmp_path: Path) -> None:
    backend = HttpFakeBackend(actions=[])
    service = AppControlService(
        backend,
        approval_mode=APPROVAL_MODE_REQUIRED,
    )
    state_path = tmp_path / "required-app-control.json"
    server = AppControlHttpServer(
        service,
        state_path=state_path,
        token="required-control-token",
    )
    server.start()
    try:
        client = AppControlClient.from_state_file(state_path)
        with pytest.raises(AppControlClientError) as captured:
            client.terminal_send_command("SIM-TERMINAL", "reboot")
        approval_id = captured.value.response["approval"]["id"]
        service.approve(approval_id)
        approval = client.approval_get(approval_id)
        token = approval["data"]["approval"]["approval_token"]

        response = client.terminal_send_command(
            "SIM-TERMINAL",
            "reboot",
            approval_token=token,
        )
    finally:
        server.stop()

    assert response["ok"]
    assert backend.actions[-1].command == "reboot"


def test_server_removes_its_state_file_on_stop(
    running_control_server: tuple[
        AppControlHttpServer,
        AppControlService,
        HttpFakeBackend,
        Path,
    ],
) -> None:
    server, _service, _backend, state_path = running_control_server
    assert state_path.exists()

    server.stop()

    assert not state_path.exists()
