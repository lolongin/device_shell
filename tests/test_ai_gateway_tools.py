from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from device_tui.interfaces.mcp.actions import ActionBuilderMixin
from device_tui.interfaces.mcp.validation import RequestValidationMixin
from device_tui.application.ai.operations import AiDeviceAction, AiDeviceToolResult, RiskLevel


class _Builder(RequestValidationMixin, ActionBuilderMixin):
    pass


def test_build_action_ai_execute_command_risk() -> None:
    action = _Builder()._build_action(
        "ai_execute_command",
        {"session_id": "sess-1", "command": "display version"},
    )
    assert action.kind == "ai_gateway_execute_command"
    assert action.risk == RiskLevel.LOW
    assert action.command == "display version"


def test_build_action_ai_execute_batch_takes_max_risk() -> None:
    action = _Builder()._build_action(
        "ai_execute_batch",
        {"session_id": "sess-1", "commands": ["display version", "reboot"]},
    )
    assert action.kind == "ai_gateway_execute_batch"
    assert action.risk == RiskLevel.HIGH


def test_build_action_ai_run_skill_is_flow_risk() -> None:
    action = _Builder()._build_action(
        "ai_run_skill",
        {"session_id": "sess-1", "skill_name": "driver_reload", "params": {}},
    )
    assert action.kind == "ai_gateway_run_skill"
    assert action.risk == RiskLevel.FLOW


def test_build_action_ai_download_is_low_risk() -> None:
    action = _Builder()._build_action(
        "ai_download_file",
        {
            "device_id": "SIM-TERMINAL",
            "source_path": "config/backup.cfg",
            "destination_path": "downloads/backup.cfg",
        },
    )
    assert action.kind == "ai_gateway_download_file"
    assert action.risk == RiskLevel.LOW


def test_build_action_ai_get_result_is_observe() -> None:
    action = _Builder()._build_action(
        "ai_get_result",
        {"result_id": "R1234abcd"},
    )
    assert action.kind == "ai_gateway_get_result"
    assert action.risk == RiskLevel.OBSERVE


def _service_with_fake_backend():
    """Build an AppControlService whose backend simulates terminal_plan_start."""
    from device_tui.interfaces.mcp.service import AppControlService
    from device_tui.application.ai.gateway.service import GatewayService

    class FakeBackend:
        def __init__(self) -> None:
            self.gateway = GatewayService()

        def gateway_service(self):
            return self.gateway

        def gateway_script_style(self, device_id: str) -> str:
            return "network"

        def execute_ai_device_action(
            self,
            action: AiDeviceAction,
            *,
            approved: bool = False,
        ) -> AiDeviceToolResult:
            if action.kind == "terminal_plan_start":
                event = threading.Event()
                event.set()
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message="started",
                    data={
                        "_completion_event": event,
                        "execution_id": "e-fake",
                        "status": "completed",
                        "steps": [{"output": "display version\nVRP (R) software\n"}],
                        "error_code": "",
                    },
                )
            if action.kind == "terminal_execution_get":
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message="completed",
                    data={
                        "execution_id": "e-fake",
                        "status": "completed",
                        "steps": [{"output": "display version\nVRP (R) software\n"}],
                        "error_code": "",
                    },
                )
            if action.kind == "ai_gateway_get_result":
                # Mirror the application AI operation handler.
                data = self.gateway.get_result(
                    str(action.params.get("result_id") or ""),
                    include_raw=bool(action.params.get("include_raw", False)),
                )
                if data is None:
                    return AiDeviceToolResult(
                        action,
                        ok=False,
                        message="未找到执行结果。",
                        error_code="result_not_found",
                        http_status=404,
                    )
                result = dict(data.get("result") or {})
                if "raw_output" in data:
                    result["raw_output"] = data["raw_output"]
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message="ok",
                    data={"result": result},
                )
            return AiDeviceToolResult(action, ok=True, message="ok")

    backend = FakeBackend()
    service = AppControlService(backend, approval_mode="disabled")
    return backend, service


def test_service_routes_ai_execute_command_to_gateway() -> None:
    backend, service = _service_with_fake_backend()
    status, body = service.invoke(
        "ai_execute_command",
        {"session_id": "sess-1", "command": "display version"},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["data"]["result_id"].startswith("R")
    assert body["data"]["summary"]["command_count"] == 1


def test_service_routes_ai_execute_batch_to_gateway() -> None:
    _, service = _service_with_fake_backend()
    status, body = service.invoke(
        "ai_execute_batch",
        {"session_id": "sess-1", "commands": ["display version", "display cpu"]},
    )
    assert status == 200
    assert body["data"]["summary"]["command_count"] == 2


def test_service_ai_get_result_routes_to_app_handler() -> None:
    _, service = _service_with_fake_backend()
    # Seed the store via the backend's gateway.
    backend_gateway = service.backend.gateway_service()
    result_id = backend_gateway.result_store.store(
        "command",
        "ok output",
        metadata={"status": "success", "exit_code": 0, "command_count": 1, "duration_ms": 1},
    )
    status, body = service.invoke(
        "ai_get_result",
        {"result_id": result_id, "include_raw": True},
    )
    assert status == 200
    assert body["data"]["result"]["result_id"] == result_id
    assert "raw_output" in body["data"]["result"]


def test_service_routes_ai_create_session_open_and_wait() -> None:
    from device_tui.interfaces.mcp.service import AppControlService
    from device_tui.application.ai.gateway.service import GatewayService

    class CreateBackend:
        def __init__(self) -> None:
            self.gateway = GatewayService()

        def gateway_service(self):
            return self.gateway

        def gateway_script_style(self, device_id: str) -> str:
            return "network"

        def execute_ai_device_action(
            self,
            action: AiDeviceAction,
            *,
            approved: bool = False,
        ) -> AiDeviceToolResult:
            if action.kind == "session_manage":
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message="opened",
                    data={
                        "session": {
                            "session_id": "sess-1",
                            "device_id": action.device_id,
                            "status": "connected",
                        }
                    },
                )
            return AiDeviceToolResult(action, ok=True, message="ok")

    service = AppControlService(CreateBackend(), approval_mode="disabled")
    status, body = service.invoke(
        "ai_create_session",
        {"device_id": "SIM-TERMINAL"},
    )
    assert status == 200
    assert body["data"]["session_id"] == "sess-1"
    assert body["data"]["connected"] is True


def test_service_ai_execute_command_timeout_is_normal_outcome() -> None:
    """A timed-out execution is a NORMAL outcome: summary.status="timeout",
    partial output stays retrievable via ai_get_result (final-review Fix 1)."""
    from device_tui.interfaces.mcp.service import AppControlService
    from device_tui.application.ai.gateway.service import GatewayService

    class TimeoutBackend:
        def __init__(self) -> None:
            self.gateway = GatewayService()

        def gateway_service(self):
            return self.gateway

        def gateway_script_style(self, device_id: str) -> str:
            return "network"

        def execute_ai_device_action(
            self,
            action: AiDeviceAction,
            *,
            approved: bool = False,
        ) -> AiDeviceToolResult:
            if action.kind == "terminal_plan_start":
                return AiDeviceToolResult(
                    action,
                    ok=False,
                    message="命令执行超过 30 秒。",
                    data={
                        "execution_id": "e-fake-timeout",
                        "status": "timed_out",
                        "steps": [{"output": "partial output before hang\n"}],
                        "error_code": "command_timeout",
                    },
                    error_code="command_timeout",
                    http_status=408,
                )
            if action.kind == "ai_gateway_get_result":
                data = self.gateway.get_result(
                    str(action.params.get("result_id") or ""),
                    include_raw=bool(action.params.get("include_raw", False)),
                )
                if data is None:
                    return AiDeviceToolResult(
                        action,
                        ok=False,
                        message="未找到执行结果。",
                        error_code="result_not_found",
                        http_status=404,
                    )
                result = dict(data.get("result") or {})
                if "raw_output" in data:
                    result["raw_output"] = data["raw_output"]
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message="ok",
                    data={"result": result},
                )
            return AiDeviceToolResult(action, ok=True, message="ok")

    service = AppControlService(TimeoutBackend(), approval_mode="disabled")
    status, body = service.invoke(
        "ai_execute_command",
        {"session_id": "sess-1", "command": "display version"},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["data"]["summary"]["status"] == "timeout"
    assert body["data"]["summary"]["exit_code"] == 1
    # Partial output remains retrievable via ai_get_result.
    result_id = body["data"]["result_id"]
    status2, body2 = service.invoke(
        "ai_get_result",
        {"result_id": result_id, "include_raw": True},
    )
    assert status2 == 200
    assert "partial output before hang" in body2["data"]["result"]["raw_output"]


def test_service_ai_execute_batch_command_failure_is_failed_summary() -> None:
    """A command that fails on the device (terminal_failure) is a NORMAL
    outcome: summary.status="failed" with a result_id, not a hard HTTP error.
    The gateway result stays retrievable via ai_get_result."""
    from device_tui.interfaces.mcp.service import AppControlService
    from device_tui.application.ai.gateway.service import GatewayService

    class FailureBackend:
        def __init__(self) -> None:
            self.gateway = GatewayService()

        def gateway_service(self):
            return self.gateway

        def gateway_script_style(self, device_id: str) -> str:
            return "network"

        def execute_ai_device_action(
            self,
            action: AiDeviceAction,
            *,
            approved: bool = False,
        ) -> AiDeviceToolResult:
            if action.kind == "terminal_plan_start":
                return AiDeviceToolResult(
                    action,
                    ok=False,
                    message="终端输出匹配失败条件: Unknown command",
                    data={
                        "execution_id": "e-fake-fail",
                        "status": "failed",
                        "steps": [{"output": "display version\nUnknown command: xyz\n"}],
                        "error_code": "terminal_failure",
                    },
                    error_code="terminal_failure",
                    http_status=409,
                )
            if action.kind == "ai_gateway_get_result":
                data = self.gateway.get_result(
                    str(action.params.get("result_id") or ""),
                    include_raw=bool(action.params.get("include_raw", False)),
                )
                if data is None:
                    return AiDeviceToolResult(
                        action,
                        ok=False,
                        message="未找到执行结果。",
                        error_code="result_not_found",
                        http_status=404,
                    )
                result = dict(data.get("result") or {})
                if "raw_output" in data:
                    result["raw_output"] = data["raw_output"]
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message="ok",
                    data={"result": result},
                )
            return AiDeviceToolResult(action, ok=True, message="ok")

    service = AppControlService(FailureBackend(), approval_mode="disabled")
    status, body = service.invoke(
        "ai_execute_command",
        {"session_id": "sess-1", "command": "bad-command-xyz"},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["data"]["summary"]["status"] == "failed"
    assert body["data"]["summary"]["exit_code"] == 1
    # The failing command's output remains retrievable via ai_get_result.
    result_id = body["data"]["result_id"]
    status2, body2 = service.invoke(
        "ai_get_result",
        {"result_id": result_id, "include_raw": True},
    )
    assert status2 == 200
    assert "Unknown command" in body2["data"]["result"]["raw_output"]
