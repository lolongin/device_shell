"""Application-control request coordination."""

from __future__ import annotations

from dataclasses import asdict
import json
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from ..ai_device_ops import (
    AiDeviceAction,
    AiDeviceToolResult,
    RiskLevel,
    classify_command_risk,
)
from ..terminal_execution import detect_terminal_prompt
from ..terminal_orchestration import (
    TerminalPlanError,
    build_batch_plan,
    parse_terminal_plan,
)
from .approval import ApprovalRecord, ApprovalStore
from .audit import AuditLogger, redact_text
from .core import (
    APPROVAL_MODE_DISABLED,
    APPROVAL_MODE_REQUIRED,
    APPROVAL_TTL_SECONDS,
    DEFAULT_OUTPUT_CHARS,
    MAX_COMMAND_CHARS,
    MAX_OUTPUT_CHARS,
    OPERATION_TERMINAL_STATUSES,
    SESSION_ACTIONS,
    SESSION_PROTOCOLS,
    TERMINAL_EXECUTE_IDLE_SECONDS,
    TERMINAL_EXECUTE_POLL_SECONDS,
    TERMINAL_PLAN_MODES,
    AppControlBackend,
    AppControlError,
    action_fingerprint,
    action_to_dict,
    normalize_command,
    resolve_approval_mode,
    utc_timestamp,
)
from .actions import ActionBuilderMixin
from .execution import ExecutionMixin
from .operations import OperationMixin
from .validation import RequestValidationMixin
from .models import OperationRecord


class AppControlService(
    ActionBuilderMixin,
    ExecutionMixin,
    OperationMixin,
    RequestValidationMixin,
):
    """Translate external tools into guarded application actions."""

    def __init__(
        self,
        backend: AppControlBackend,
        *,
        dispatcher: Callable[[Callable[[], Any], float], Any] | None = None,
        approvals: ApprovalStore | None = None,
        audit: AuditLogger | None = None,
        on_approval_created: Callable[[ApprovalRecord], None] | None = None,
        call_timeout_seconds: float = 10.0,
        approval_mode: str | None = None,
    ) -> None:
        self.backend = backend
        self.dispatcher = dispatcher or (lambda callback, _timeout: callback())
        self.approvals = approvals or ApprovalStore()
        self.audit = audit or AuditLogger()
        self.on_approval_created = on_approval_created
        self.call_timeout_seconds = call_timeout_seconds
        self.approval_mode = resolve_approval_mode(approval_mode)
        self._operations: dict[str, OperationRecord] = {}
        self._idempotency: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._operation_condition = threading.Condition(self._lock)

    def invoke(
        self,
        tool: str,
        params: dict[str, Any] | None = None,
        *,
        source: str = "tool-calling",
        request_id: str | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request_id = request_id or str(uuid4())
        params = dict(params or {})
        started = time.monotonic()
        audit_action: AiDeviceAction | None = None
        try:
            audit_action = self._build_action(tool, params)
        except AppControlError:
            pass
        try:
            body = self._invoke(tool, params, source=source, request_id=request_id)
            status = int(body.pop("_http_status", 200))
        except AppControlError as exc:
            status = exc.status
            body = self._error_response(request_id, exc)
        except TimeoutError:
            status = 504
            body = self._error_response(
                request_id,
                AppControlError(
                    "ui_timeout",
                    "Device TUI 主线程未在限定时间内响应。",
                    status=504,
                ),
            )
        except Exception as exc:
            status = 500
            body = self._error_response(
                request_id,
                AppControlError(
                    "internal_error",
                    f"控制服务执行失败: {exc}",
                    status=500,
                ),
            )
        response_data = body.get("data")
        response_data = response_data if isinstance(response_data, dict) else {}
        response_session = response_data.get("session")
        response_session = (
            response_session if isinstance(response_session, dict) else {}
        )
        audit_device_id = (
            (audit_action.device_id if audit_action is not None else "")
            or str(response_data.get("device_id") or "")
            or str(response_session.get("device_id") or "")
        )
        audit_session_id = (
            str(params.get("session_id") or "")
            or str(response_data.get("session_id") or "")
            or str(response_session.get("session_id") or "")
        )
        self.audit.write(
            {
                "timestamp": utc_timestamp(),
                "request_id": request_id,
                "source": source,
                "tool": tool,
                "params": params,
                "device_id": audit_device_id,
                "session_id": audit_session_id,
                "risk": audit_action.risk.name if audit_action is not None else "",
                "device_approval_mode": self.approval_mode,
                "device_approval_bypassed": bool(
                    audit_action is not None
                    and audit_action.requires_confirmation
                    and not self.requires_device_approval
                ),
                "status": status,
                "ok": body.get("ok", False),
                "error": body.get("error"),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            }
        )
        return status, body

    @property
    def requires_device_approval(self) -> bool:
        return self.approval_mode == APPROVAL_MODE_REQUIRED

    def approve(self, approval_id: str) -> ApprovalRecord:
        record = self.approvals.approve(approval_id)
        self.audit.write(
            {
                "timestamp": utc_timestamp(),
                "tool": "approval_approve",
                "approval_id": approval_id,
                "device_id": record.action.device_id,
                "risk": record.action.risk.name,
                "status": 200,
                "ok": True,
            }
        )
        return record

    def reject(self, approval_id: str) -> ApprovalRecord:
        record = self.approvals.reject(approval_id)
        self.audit.write(
            {
                "timestamp": utc_timestamp(),
                "tool": "approval_reject",
                "approval_id": approval_id,
                "device_id": record.action.device_id,
                "risk": record.action.risk.name,
                "status": 200,
                "ok": True,
            }
        )
        return record

    def _invoke(
        self,
        tool: str,
        params: dict[str, Any],
        *,
        source: str,
        request_id: str,
    ) -> dict[str, Any]:
        if tool == "health":
            return self._success(
                request_id,
                "Device TUI 控制服务运行中。",
                {
                    "status": "ready",
                    "approval_mode": self.approval_mode,
                },
            )
        if tool == "approval_get":
            approval_id = self._required_text(params, "approval_id", max_chars=80)
            record = self.approvals.get(approval_id)
            return self._success(
                request_id,
                f"审批状态: {record.status}",
                {"approval": record.public_dict(include_token=True)},
            )
        if tool == "operation_get":
            return self._operation_get(params, request_id=request_id)
        if tool == "operation_wait":
            return self._operation_wait(params, request_id=request_id)
        if tool == "operation_cancel":
            return self._operation_cancel(params, request_id=request_id)

        action = self._build_action(tool, params)
        idempotency_key = str(params.get("idempotency_key") or "").strip()
        cache_key = (
            f"{source}\0{tool}\0{idempotency_key}"
            if idempotency_key
            else ""
        )
        if idempotency_key:
            with self._lock:
                cached = self._idempotency.get(cache_key)
            if cached is not None:
                return dict(cached)

        approval_token = str(params.get("approval_token") or "")
        if action.requires_confirmation and self.requires_device_approval:
            if not approval_token:
                record = self.approvals.request(
                    action,
                    source=source,
                    reason=self._approval_reason(action),
                )
                if self.on_approval_created is not None:
                    self.on_approval_created(record)
                return self._approval_response(request_id, record)
            self.approvals.consume(approval_token, action)

        if idempotency_key and tool in {
            "terminal_run",
            "terminal_execute_batch",
            "terminal_interact",
        }:
            action.params["coordinator_idempotency_key"] = cache_key

        if tool == "terminal_run":
            result = self._execute_terminal_run(action)
        elif tool == "terminal_execute":
            result = self._execute_terminal_command(action)
        elif tool in {"terminal_execute_batch", "terminal_interact"}:
            result = self._execute_terminal_plan(action)
        elif tool == "session_manage":
            result = self._execute_session_manage(action)
        else:
            result = self._dispatch_action(action)
        if not isinstance(result, AiDeviceToolResult):
            raise AppControlError(
                "invalid_backend_result",
                "App 动作层返回了无效结果。",
                status=500,
            )
        response = self._result_response(request_id, result)
        if tool == "system_status" and result.ok:
            response["data"]["approval_mode"] = self.approval_mode
            with self._lock:
                active = sum(
                    operation.status == "running"
                    for operation in self._operations.values()
                )
            response["data"]["active_operations"] = max(
                int(response["data"].get("active_operations", 0)),
                active,
            )
        if tool == "package_upgrade_start" and result.ok:
            operation = self._create_operation(
                action,
                result,
                kind="package_upgrade",
            )
            response["data"]["operation_id"] = operation.id
            response["data"]["operation"] = asdict(operation)
        if tool == "file_transfer_start" and result.ok:
            operation = self._create_operation(
                action,
                result,
                kind="managed_file_transfer",
                operation_id=str(result.data.get("operation_id") or ""),
            )
            response["data"]["operation_id"] = operation.id
            response["data"]["operation"] = asdict(operation)
        if idempotency_key:
            with self._lock:
                self._idempotency[cache_key] = dict(response)
        return response


    def _dispatch_action(self, action: AiDeviceAction) -> AiDeviceToolResult:
        result = self.dispatcher(
            lambda: self.backend.execute_ai_device_action(
                action,
                approved=action.requires_confirmation,
            ),
            self.call_timeout_seconds,
        )
        if not isinstance(result, AiDeviceToolResult):
            raise AppControlError(
                "invalid_backend_result",
                "App 动作层返回了无效结果。",
                status=500,
            )
        return result


















    @staticmethod
    def _success(
        request_id: str,
        message: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "request_id": request_id,
            "message": message,
            "data": data,
            "approval": None,
            "error": None,
        }

    def _result_response(
        self,
        request_id: str,
        result: AiDeviceToolResult,
    ) -> dict[str, Any]:
        if result.ok:
            return self._success(request_id, result.message, dict(result.data))
        if result.approval_required and self.requires_device_approval:
            record = self.approvals.request(
                result.action,
                source="app-action",
                reason=self._approval_reason(result.action),
            )
            return self._approval_response(request_id, record)
        return {
            "ok": False,
            "request_id": request_id,
            "message": result.message,
            "data": dict(result.data),
            "approval": None,
            "error": {
                "code": result.error_code or "action_failed",
                "message": result.message,
                "details": {"action": action_to_dict(result.action)},
            },
            "_http_status": result.http_status,
        }

    @staticmethod
    def _approval_response(
        request_id: str,
        record: ApprovalRecord,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "request_id": request_id,
            "message": "该动作需要用户在 Device TUI 中确认。",
            "data": {},
            "approval": record.public_dict(),
            "error": {
                "code": "approval_required",
                "message": "等待用户确认。",
                "details": {},
            },
            "_http_status": 409,
        }

    @staticmethod
    def _error_response(
        request_id: str,
        error: AppControlError,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "request_id": request_id,
            "message": str(error),
            "data": {},
            "approval": None,
            "error": {
                "code": error.code,
                "message": str(error),
                "details": error.details,
            },
        }
