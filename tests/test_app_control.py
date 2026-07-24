from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import pytest

import src.app_control as app_control_module
from src.ai_device_ops import AiDeviceAction, AiDeviceToolResult, RiskLevel
from src.app_control import (
    APPROVAL_MODE_DISABLED,
    APPROVAL_MODE_REQUIRED,
    AppControlError,
    AppControlService,
    ApprovalStore,
    AuditLogger,
    redact_text,
)


@dataclass
class FakeBackend:
    actions: list[tuple[AiDeviceAction, bool]]

    def execute_ai_device_action(
        self,
        action: AiDeviceAction,
        *,
        approved: bool = False,
    ) -> AiDeviceToolResult:
        self.actions.append((action, approved))
        if action.kind == "list_devices":
            return AiDeviceToolResult(
                action,
                ok=True,
                message="读取到 1 台设备。",
                data={
                    "devices": [
                        {
                            "id": "SIM-TERMINAL",
                            "name": "模拟终端",
                            "kind": "simulated",
                        }
                    ]
                },
            )
        if action.kind == "read_terminal":
            return AiDeviceToolResult(
                action,
                ok=True,
                message="读取完成。",
                data={"output": "ready", "truncated": False},
            )
        if action.kind == "get_package_upgrade_status":
            return AiDeviceToolResult(
                action,
                ok=True,
                message="换包已完成。",
                data={"status": "completed", "stage": "confirm"},
            )
        return AiDeviceToolResult(action, ok=True, message="执行成功。")


@dataclass
class ReliabilityBackend:
    actions: list[AiDeviceAction]
    snapshots: list[dict[str, object]]
    status_reads: int = 0

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
                message="ready",
                data={
                    "ready": True,
                    "session_counts": {"total": 1},
                    "active_operations": 0,
                },
            )
        if action.kind == "session_manage":
            operation = action.params["action"]
            if operation == "open":
                status = "connecting"
            else:
                self.status_reads += 1
                status = "connected" if self.status_reads > 1 else "connecting"
            return AiDeviceToolResult(
                action,
                ok=True,
                message=str(status),
                data={
                    "session": {
                        "session_id": "SIM-TERMINAL:simulated:7",
                        "device_id": "SIM-TERMINAL",
                        "status": status,
                    }
                },
            )
        if action.kind == "terminal_execute_start":
            return AiDeviceToolResult(
                action,
                ok=True,
                message="sent",
                data={
                    "session": {
                        "session_id": "SIM-TERMINAL:simulated:7",
                        "device_id": "SIM-TERMINAL",
                        "status": "connected",
                    },
                    "output_cursor_start": 100,
                },
            )
        if action.kind == "terminal_execution_snapshot":
            snapshot = self.snapshots.pop(0) if self.snapshots else {
                "output": "",
                "output_cursor": 100,
                "truncated": False,
                "connected": True,
                "connecting": False,
                "status": "connected",
            }
            return AiDeviceToolResult(
                action,
                ok=True,
                message="snapshot",
                data=dict(snapshot),
            )
        return AiDeviceToolResult(action, ok=True, message="ok")


def make_service(**kwargs: object) -> tuple[AppControlService, FakeBackend]:
    backend = FakeBackend(actions=[])
    service = AppControlService(backend, **kwargs)
    return service, backend


def test_read_only_command_executes_without_approval() -> None:
    service, backend = make_service()

    status, response = service.invoke(
        "terminal_send_command",
        {"device_id": "SIM-TERMINAL", "command": "display version"},
    )

    assert status == 200
    assert response["ok"]
    assert backend.actions[0][0].risk == RiskLevel.LOW
    assert not backend.actions[0][1]


def test_high_risk_command_executes_immediately_by_default() -> None:
    service, backend = make_service()

    status, response = service.invoke(
        "terminal_send_command",
        {"device_id": "SIM-TERMINAL", "command": "reboot"},
    )

    assert service.approval_mode == APPROVAL_MODE_DISABLED
    assert status == 200
    assert response["ok"]
    assert backend.actions == [
        (
            AiDeviceAction(
                "send_command",
                "发送终端命令",
                RiskLevel.HIGH,
                device_id="SIM-TERMINAL",
                command="reboot",
            ),
            True,
        )
    ]
    assert service.approvals.pending() == []


def test_high_risk_command_requires_bound_one_time_approval() -> None:
    approvals: list[str] = []
    service, backend = make_service(
        on_approval_created=lambda record: approvals.append(record.id),
        approval_mode=APPROVAL_MODE_REQUIRED,
    )

    status, response = service.invoke(
        "terminal_send_command",
        {"device_id": "SIM-TERMINAL", "command": "reboot"},
        source="test-agent",
    )

    assert status == 409
    assert response["error"]["code"] == "approval_required"
    approval_id = response["approval"]["id"]
    assert approvals == [approval_id]
    assert backend.actions == []

    service.approve(approval_id)
    approval_status, approval_response = service.invoke(
        "approval_get",
        {"approval_id": approval_id},
    )
    token = approval_response["data"]["approval"]["approval_token"]
    assert approval_status == 200

    execute_status, execute_response = service.invoke(
        "terminal_send_command",
        {
            "device_id": "SIM-TERMINAL",
            "command": "reboot",
            "approval_token": token,
        },
    )

    assert execute_status == 200
    assert execute_response["ok"]
    assert backend.actions[-1][1]

    reuse_status, reuse_response = service.invoke(
        "terminal_send_command",
        {
            "device_id": "SIM-TERMINAL",
            "command": "reboot",
            "approval_token": token,
        },
    )
    assert reuse_status == 409
    assert reuse_response["error"]["code"] == "invalid_approval_token"


def test_approval_token_cannot_be_used_for_a_different_command() -> None:
    service, _backend = make_service(approval_mode=APPROVAL_MODE_REQUIRED)
    _, response = service.invoke(
        "terminal_send_command",
        {"device_id": "SIM-TERMINAL", "command": "reboot"},
    )
    record = service.approve(response["approval"]["id"])

    status, mismatch = service.invoke(
        "terminal_send_command",
        {
            "device_id": "SIM-TERMINAL",
            "command": "save",
            "approval_token": record.token,
        },
    )

    assert status == 409
    assert mismatch["error"]["code"] == "approval_action_mismatch"


def test_approval_expires() -> None:
    current = [10.0]
    approvals = ApprovalStore(ttl_seconds=5, clock=lambda: current[0])
    action = AiDeviceAction(
        "send_command",
        "重启",
        RiskLevel.HIGH,
        device_id="SIM-TERMINAL",
        command="reboot",
    )
    record = approvals.request(action, source="test", reason="risk")
    current[0] = 16.0

    assert approvals.get(record.id).status == "expired"
    with pytest.raises(AppControlError, match="无效或已过期"):
        approvals.consume("missing", action)


def test_terminal_read_validates_output_limit() -> None:
    service, backend = make_service()

    status, response = service.invoke(
        "terminal_read",
        {"device_id": "SIM-TERMINAL", "max_chars": 32769},
    )

    assert status == 400
    assert response["error"]["code"] == "invalid_request"
    assert backend.actions == []


def test_package_upgrade_creates_queryable_operation() -> None:
    service, _backend = make_service()

    status, started = service.invoke(
        "package_upgrade_start",
        {"device_id": "SIM-TERMINAL"},
    )
    operation_id = started["data"]["operation_id"]
    query_status, queried = service.invoke(
        "operation_get",
        {"operation_id": operation_id},
    )

    assert status == 200
    assert query_status == 200
    assert queried["data"]["operation"]["status"] == "completed"


def test_unknown_approval_mode_defaults_to_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEVICE_TUI_APPROVAL_MODE", "unexpected")

    service, _backend = make_service()

    assert service.approval_mode == APPROVAL_MODE_DISABLED
    status, health = service.invoke("health")
    assert status == 200
    assert health["data"]["approval_mode"] == APPROVAL_MODE_DISABLED


def test_audit_records_internal_approval_bypass(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    service, _backend = make_service(audit=AuditLogger(audit_path))

    service.invoke(
        "terminal_send_command",
        {"device_id": "SIM-TERMINAL", "command": "reboot"},
    )

    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert payload["device_id"] == "SIM-TERMINAL"
    assert payload["risk"] == "HIGH"
    assert payload["device_approval_mode"] == APPROVAL_MODE_DISABLED
    assert payload["device_approval_bypassed"] is True


def test_system_status_includes_device_tui_approval_mode() -> None:
    backend = ReliabilityBackend(actions=[], snapshots=[])
    service = AppControlService(backend)

    status, response = service.invoke("system_status")

    assert status == 200
    assert response["data"]["ready"] is True
    assert response["data"]["approval_mode"] == APPROVAL_MODE_DISABLED


def test_session_manage_waits_until_connected() -> None:
    backend = ReliabilityBackend(actions=[], snapshots=[])
    service = AppControlService(backend)

    status, response = service.invoke(
        "session_manage",
        {
            "action": "open",
            "device_id": "SIM-TERMINAL",
            "protocol": "auto",
            "timeout_seconds": 2,
        },
    )

    assert status == 200
    assert response["data"]["session"]["status"] == "connected"
    assert backend.status_reads == 2


def test_terminal_execute_returns_only_incremental_prompt_output() -> None:
    backend = ReliabilityBackend(
        actions=[],
        snapshots=[
            {
                "output": "display version\r\nSimOS V2.0\r\n<sim> ",
                "output_cursor": 143,
                "truncated": False,
                "connected": True,
                "connecting": False,
                "status": "connected",
            }
        ],
    )
    service = AppControlService(backend)

    status, response = service.invoke(
        "terminal_execute",
        {
            "session_id": "SIM-TERMINAL:simulated:7",
            "command": "display version",
        },
    )

    assert status == 200
    assert response["data"]["device_id"] == "SIM-TERMINAL"
    assert response["data"]["output"] == (
        "display version\r\nSimOS V2.0\r\n<sim> "
    )
    assert response["data"]["completion_reason"] == "prompt"
    assert response["data"]["prompt_matched"] == "<sim>"
    assert response["data"]["output_cursor_start"] == 100
    assert response["data"]["output_cursor_end"] == 143


def test_terminal_execute_reports_idle_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app_control_module,
        "TERMINAL_EXECUTE_IDLE_SECONDS",
        0.01,
    )
    snapshot = {
        "output": "command output without a prompt",
        "output_cursor": 131,
        "truncated": False,
        "connected": True,
        "connecting": False,
        "status": "connected",
    }
    backend = ReliabilityBackend(
        actions=[],
        snapshots=[dict(snapshot), dict(snapshot)],
    )
    service = AppControlService(backend)

    status, response = service.invoke(
        "terminal_execute",
        {
            "session_id": "SIM-TERMINAL:simulated:7",
            "command": "custom command",
            "timeout_seconds": 2,
        },
    )

    assert status == 200
    assert response["data"]["completion_reason"] == "idle"
    assert response["data"]["prompt_matched"] == ""


def test_terminal_execute_disconnect_preserves_partial_output() -> None:
    backend = ReliabilityBackend(
        actions=[],
        snapshots=[
            {
                "output": "rebooting now...",
                "output_cursor": 116,
                "truncated": False,
                "connected": False,
                "connecting": False,
                "status": "disconnected",
            }
        ],
    )
    service = AppControlService(backend)

    status, response = service.invoke(
        "terminal_execute",
        {
            "session_id": "SIM-TERMINAL:simulated:7",
            "command": "reboot",
        },
    )

    assert status == 409
    assert response["error"]["code"] == "session_disconnected"
    assert response["data"]["status"] == "disconnected"
    assert response["data"]["output"] == "rebooting now..."


def test_audit_log_redacts_secrets(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.jsonl"
    logger = AuditLogger(audit_path)

    logger.write(
        {
            "command": "set password=super-secret",
            "url": "ftp://device:secret@example.test/file.cc",
            "approval_token": "one-time-secret",
        }
    )

    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    assert payload["approval_token"] == "***"
    assert "super-secret" not in payload["command"]
    assert "device:secret@" not in payload["url"]
    assert redact_text("password=hunter2") == "password=***"
