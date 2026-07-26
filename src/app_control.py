"""Core application-control protocol, approvals, and audit logging."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Any, Callable, Protocol
from uuid import uuid4

from .ai_device_ops import (
    AiDeviceAction,
    AiDeviceToolResult,
    RiskLevel,
    classify_command_risk,
)
from .terminal_execution import detect_terminal_prompt
from .terminal_orchestration import (
    TerminalPlanError,
    build_batch_plan,
    parse_terminal_plan,
)


MAX_COMMAND_CHARS = 16_384
DEFAULT_OUTPUT_CHARS = 4_096
MAX_OUTPUT_CHARS = 32_768
APPROVAL_TTL_SECONDS = 60
APPROVAL_MODE_DISABLED = "disabled"
APPROVAL_MODE_REQUIRED = "required"
SESSION_ACTIONS = {"open", "status", "reconnect", "disconnect", "close"}
SESSION_PROTOCOLS = {"auto", "telnet", "ssh", "serial", "simulated"}
TERMINAL_PLAN_MODES = {"auto", "sync", "async"}
TERMINAL_EXECUTE_IDLE_SECONDS = 0.8
TERMINAL_EXECUTE_POLL_SECONDS = 0.05


def resolve_approval_mode(value: str | None = None) -> str:
    """Resolve the Device TUI approval policy from an explicit value or env."""
    configured = os.getenv("DEVICE_TUI_APPROVAL_MODE", "") if value is None else value
    if configured.strip().casefold() == APPROVAL_MODE_REQUIRED:
        return APPROVAL_MODE_REQUIRED
    return APPROVAL_MODE_DISABLED


class AppControlBackend(Protocol):
    def execute_ai_device_action(
        self,
        action: AiDeviceAction,
        *,
        approved: bool = False,
    ) -> AiDeviceToolResult:
        ...


class AppControlError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_command(command: str) -> str:
    return " ".join(command.strip().split())


def action_fingerprint(action: AiDeviceAction) -> str:
    payload = {
        "kind": action.kind,
        "device_id": action.device_id,
        "command": normalize_command(action.command),
        "params": action.params,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ApprovalRecord:
    id: str
    action: AiDeviceAction
    source: str
    reason: str
    created_monotonic: float
    expires_monotonic: float
    created_at: str
    expires_at: str
    status: str = "pending"
    token: str = ""

    def public_dict(self, *, include_token: bool = False) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "status": self.status,
            "source": self.source,
            "reason": self.reason,
            "risk": self.action.risk.name,
            "action": action_to_dict(self.action),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }
        if include_token and self.status == "approved":
            payload["approval_token"] = self.token
        return payload


class ApprovalStore:
    def __init__(
        self,
        *,
        ttl_seconds: int = APPROVAL_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.clock = clock
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = threading.Lock()

    def request(
        self,
        action: AiDeviceAction,
        *,
        source: str,
        reason: str,
    ) -> ApprovalRecord:
        now = self.clock()
        with self._lock:
            self._expire_locked(now)
            fingerprint = action_fingerprint(action)
            for record in self._records.values():
                if (
                    record.status == "pending"
                    and record.source == source
                    and action_fingerprint(record.action) == fingerprint
                ):
                    return record
            expires_at = datetime.fromtimestamp(
                time.time() + self.ttl_seconds,
                timezone.utc,
            ).isoformat()
            record = ApprovalRecord(
                id=str(uuid4()),
                action=action,
                source=source,
                reason=reason,
                created_monotonic=now,
                expires_monotonic=now + self.ttl_seconds,
                created_at=utc_timestamp(),
                expires_at=expires_at,
            )
            self._records[record.id] = record
            return record

    def get(self, approval_id: str) -> ApprovalRecord:
        with self._lock:
            self._expire_locked(self.clock())
            record = self._records.get(approval_id)
            if record is None:
                raise AppControlError(
                    "approval_not_found",
                    f"未找到审批请求: {approval_id}",
                    status=404,
                )
            return record

    def pending(self) -> list[ApprovalRecord]:
        with self._lock:
            self._expire_locked(self.clock())
            return [record for record in self._records.values() if record.status == "pending"]

    def approve(self, approval_id: str) -> ApprovalRecord:
        with self._lock:
            self._expire_locked(self.clock())
            record = self._records.get(approval_id)
            if record is None:
                raise AppControlError("approval_not_found", "审批请求不存在。", status=404)
            if record.status != "pending":
                raise AppControlError(
                    "approval_not_pending",
                    f"审批请求当前状态为 {record.status}。",
                    status=409,
                )
            record.status = "approved"
            record.token = secrets.token_urlsafe(32)
            return record

    def reject(self, approval_id: str) -> ApprovalRecord:
        with self._lock:
            self._expire_locked(self.clock())
            record = self._records.get(approval_id)
            if record is None:
                raise AppControlError("approval_not_found", "审批请求不存在。", status=404)
            if record.status != "pending":
                raise AppControlError(
                    "approval_not_pending",
                    f"审批请求当前状态为 {record.status}。",
                    status=409,
                )
            record.status = "rejected"
            return record

    def consume(self, approval_token: str, action: AiDeviceAction) -> ApprovalRecord:
        if not approval_token:
            raise AppControlError(
                "approval_required",
                "该动作需要用户在 Device TUI 中确认。",
                status=409,
            )
        with self._lock:
            self._expire_locked(self.clock())
            record = next(
                (
                    candidate
                    for candidate in self._records.values()
                    if candidate.token
                    and hmac.compare_digest(candidate.token, approval_token)
                ),
                None,
            )
            if record is None:
                raise AppControlError(
                    "invalid_approval_token",
                    "审批令牌无效或已过期。",
                    status=409,
                )
            if record.status != "approved":
                raise AppControlError(
                    "approval_not_available",
                    f"审批令牌当前状态为 {record.status}。",
                    status=409,
                )
            if action_fingerprint(record.action) != action_fingerprint(action):
                raise AppControlError(
                    "approval_action_mismatch",
                    "审批令牌与当前设备、命令或参数不匹配。",
                    status=409,
                )
            record.status = "consumed"
            record.token = ""
            return record

    def _expire_locked(self, now: float) -> None:
        for record in self._records.values():
            if record.status in {"pending", "approved"} and now >= record.expires_monotonic:
                record.status = "expired"
                record.token = ""


SENSITIVE_PATTERNS = (
    re.compile(r"(?i)\b(password|passwd|secret|token)\s*[=:]\s*(\S+)"),
    re.compile(r"(?i)(://[^:/\s]+:)([^@\s]+)(@)"),
)


def redact_text(text: str) -> str:
    redacted = text
    redacted = SENSITIVE_PATTERNS[0].sub(r"\1=***", redacted)
    redacted = SENSITIVE_PATTERNS[1].sub(r"\1***\3", redacted)
    return redacted


class AuditLogger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()

    def write(self, entry: dict[str, Any]) -> None:
        if self.path is None:
            return
        payload = self._redact_value(entry)
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "***" if key.casefold() in {"token", "approval_token", "password"} else self._redact_value(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        if isinstance(value, str):
            return redact_text(value)
        return value


@dataclass(slots=True)
class OperationRecord:
    id: str
    kind: str
    device_id: str
    status: str
    message: str
    created_at: str
    updated_at: str
    data: dict[str, Any] = field(default_factory=dict)


def action_to_dict(action: AiDeviceAction) -> dict[str, Any]:
    payload = asdict(action)
    payload["risk"] = action.risk.name
    return payload


class AppControlService:
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

        if idempotency_key and tool in {"terminal_execute_batch", "terminal_interact"}:
            action.params["coordinator_idempotency_key"] = cache_key

        if tool == "terminal_execute":
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
        if tool == "file_transfer_start" and result.ok:
            operation = self._create_operation(
                action,
                result,
                kind="managed_file_transfer",
                operation_id=str(result.data.get("operation_id") or ""),
            )
            response["data"]["operation_id"] = operation.id
        if idempotency_key:
            with self._lock:
                self._idempotency[cache_key] = dict(response)
        return response

    def _build_action(self, tool: str, params: dict[str, Any]) -> AiDeviceAction:
        if tool == "system_status":
            return AiDeviceAction(
                "system_status",
                "读取 Device TUI 运行状态",
                RiskLevel.OBSERVE,
            )
        if tool == "device_list":
            return AiDeviceAction("list_devices", "读取设备列表", RiskLevel.OBSERVE)
        if tool == "file_transfer_list":
            recursive = self._boolean(
                params,
                "recursive",
                default=True,
            )
            limit = self._integer(
                params,
                "limit",
                default=200,
                minimum=1,
                maximum=1_000,
            )
            return AiDeviceAction(
                "list_managed_transfer_files",
                "列出文件传输共享目录",
                RiskLevel.OBSERVE,
                params={
                    "path": self._optional_text(params, "path", max_chars=1_024),
                    "recursive": recursive,
                    "limit": limit,
                },
            )
        if tool == "session_list":
            device_id = self._optional_text(params, "device_id", max_chars=200)
            return AiDeviceAction(
                "session_list",
                "读取终端会话列表",
                RiskLevel.OBSERVE,
                device_id=device_id,
                params={"device_id": device_id},
            )
        if tool == "session_manage":
            operation = self._choice(params, "action", SESSION_ACTIONS)
            protocol = self._choice(
                params,
                "protocol",
                SESSION_PROTOCOLS,
                default="auto",
            )
            device_id = self._optional_text(params, "device_id", max_chars=200)
            session_id = self._optional_text(params, "session_id", max_chars=240)
            if operation == "open" and not device_id:
                raise AppControlError(
                    "invalid_request",
                    "打开会话需要 device_id。",
                )
            if operation != "open" and not session_id and not device_id:
                raise AppControlError(
                    "invalid_request",
                    "会话操作需要 session_id 或 device_id。",
                )
            timeout_seconds = self._integer(
                params,
                "timeout_seconds",
                default=15,
                minimum=1,
                maximum=60,
            )
            return AiDeviceAction(
                "session_manage",
                f"管理终端会话: {operation}",
                RiskLevel.LOW,
                device_id=device_id,
                params={
                    "action": operation,
                    "protocol": protocol,
                    "session_id": session_id,
                    "timeout_seconds": timeout_seconds,
                },
            )
        if tool == "terminal_execute":
            command = self._required_text(
                params,
                "command",
                max_chars=MAX_COMMAND_CHARS,
            )
            normalized = normalize_command(command)
            device_id = self._optional_text(params, "device_id", max_chars=200)
            session_id = self._optional_text(params, "session_id", max_chars=240)
            if not device_id and not session_id:
                raise AppControlError(
                    "invalid_request",
                    "执行命令需要 session_id 或 device_id。",
                )
            timeout_seconds = self._integer(
                params,
                "timeout_seconds",
                default=30,
                minimum=1,
                maximum=300,
            )
            max_output_chars = self._integer(
                params,
                "max_output_chars",
                default=16_384,
                minimum=1,
                maximum=MAX_OUTPUT_CHARS,
            )
            return AiDeviceAction(
                "terminal_execute_start",
                "执行终端命令并等待结果",
                classify_command_risk(normalized),
                device_id=device_id,
                command=normalized,
                params={
                    "session_id": session_id,
                    "timeout_seconds": timeout_seconds,
                    "max_output_chars": max_output_chars,
                },
            )
        if tool == "terminal_execute_batch":
            raw_commands = params.get("commands")
            if not isinstance(raw_commands, list):
                raise AppControlError("invalid_request", "参数 commands 必须是数组。")
            commands = [normalize_command(str(command)) for command in raw_commands]
            command_timeout_seconds = self._integer(
                params,
                "command_timeout_seconds",
                default=30,
                minimum=1,
                maximum=300,
            )
            max_output_chars = self._integer(
                params,
                "max_output_chars_per_step",
                default=16_384,
                minimum=1,
                maximum=MAX_OUTPUT_CHARS,
            )
            requested_total = params.get("total_timeout_seconds")
            total_timeout_seconds = (
                self._integer(
                    params,
                    "total_timeout_seconds",
                    default=60,
                    minimum=1,
                    maximum=3600,
                )
                if requested_total is not None
                else None
            )
            try:
                plan = build_batch_plan(
                    commands,
                    command_timeout_seconds=command_timeout_seconds,
                    total_timeout_seconds=total_timeout_seconds,
                    max_output_chars=max_output_chars,
                )
            except TerminalPlanError as exc:
                raise AppControlError(exc.code, str(exc)) from exc
            mode = self._choice(
                params,
                "mode",
                TERMINAL_PLAN_MODES,
                default="auto",
            )
            run_async = self._terminal_plan_runs_async(
                mode,
                plan.total_timeout_seconds,
                has_state_wait=False,
            )
            device_id, session_id = self._terminal_target(params)
            risk = max(
                (classify_command_risk(command) for command in commands),
                default=RiskLevel.LOW,
            )
            return AiDeviceAction(
                "terminal_plan_start",
                "批量执行终端命令",
                risk,
                device_id=device_id,
                params={
                    "plan_kind": "batch",
                    "commands": commands,
                    "session_id": session_id,
                    "command_timeout_seconds": command_timeout_seconds,
                    "total_timeout_seconds": plan.total_timeout_seconds,
                    "max_output_chars_per_step": max_output_chars,
                    "mode": mode,
                    "run_async": run_async,
                },
            )
        if tool == "terminal_interact":
            raw_steps = params.get("steps")
            if not isinstance(raw_steps, list):
                raise AppControlError("invalid_request", "参数 steps 必须是数组。")
            total_timeout_seconds = self._integer(
                params,
                "total_timeout_seconds",
                default=60,
                minimum=1,
                maximum=3600,
            )
            try:
                plan = parse_terminal_plan(
                    raw_steps,
                    total_timeout_seconds=total_timeout_seconds,
                )
            except TerminalPlanError as exc:
                raise AppControlError(exc.code, str(exc)) from exc
            mode = self._choice(
                params,
                "mode",
                TERMINAL_PLAN_MODES,
                default="auto",
            )
            has_state_wait = any(
                str(step.get("type") or "").casefold() == "wait_state"
                for step in raw_steps
                if isinstance(step, dict)
            )
            run_async = self._terminal_plan_runs_async(
                mode,
                plan.total_timeout_seconds,
                has_state_wait=has_state_wait,
            )
            device_id, session_id = self._terminal_target(params)
            risk = RiskLevel.FLOW
            for step in raw_steps:
                if not isinstance(step, dict):
                    continue
                texts = [str(step.get("text") or "")]
                responses = step.get("responses")
                if isinstance(responses, list):
                    texts.extend(
                        str(response.get("text") or "")
                        for response in responses
                        if isinstance(response, dict)
                    )
                for text in texts:
                    if text:
                        risk = max(risk, classify_command_risk(text))
            return AiDeviceAction(
                "terminal_plan_start",
                "执行交互式终端计划",
                risk,
                device_id=device_id,
                params={
                    "plan_kind": "interactive",
                    "steps": raw_steps,
                    "session_id": session_id,
                    "total_timeout_seconds": plan.total_timeout_seconds,
                    "mode": mode,
                    "run_async": run_async,
                },
            )
        if tool in {"execution_get", "execution_cancel"}:
            execution_id = self._required_text(
                params,
                "execution_id",
                max_chars=80,
            )
            return AiDeviceAction(
                "terminal_execution_get"
                if tool == "execution_get"
                else "terminal_execution_cancel",
                "读取终端执行状态"
                if tool == "execution_get"
                else "取消终端执行",
                RiskLevel.OBSERVE if tool == "execution_get" else RiskLevel.LOW,
                params={"execution_id": execution_id},
            )
        device_id = self._required_text(params, "device_id", max_chars=200)
        if tool == "device_get":
            return AiDeviceAction(
                "device_get",
                "读取设备详情",
                RiskLevel.OBSERVE,
                device_id=device_id,
            )
        if tool == "device_select":
            return AiDeviceAction(
                "select_device",
                "选择设备",
                RiskLevel.OBSERVE,
                device_id=device_id,
            )
        if tool == "session_open":
            return AiDeviceAction(
                "open_session",
                "打开终端会话",
                RiskLevel.LOW,
                device_id=device_id,
            )
        if tool == "terminal_send_command":
            command = self._required_text(
                params,
                "command",
                max_chars=MAX_COMMAND_CHARS,
            )
            normalized = normalize_command(command)
            return AiDeviceAction(
                "send_command",
                "发送终端命令",
                classify_command_risk(normalized),
                device_id=device_id,
                command=normalized,
            )
        if tool == "terminal_read":
            max_chars = self._integer(
                params,
                "max_chars",
                default=DEFAULT_OUTPUT_CHARS,
                minimum=1,
                maximum=MAX_OUTPUT_CHARS,
            )
            return AiDeviceAction(
                "read_terminal",
                "读取终端输出",
                RiskLevel.OBSERVE,
                device_id=device_id,
                params={"max_chars": max_chars},
            )
        if tool == "package_upgrade_start":
            return AiDeviceAction(
                "run_package_upgrade",
                "启动自动换包流程",
                RiskLevel.FLOW,
                device_id=device_id,
            )
        if tool == "file_transfer_start":
            return AiDeviceAction(
                "start_managed_file_transfer",
                "启动托管文件传输",
                RiskLevel.FLOW,
                device_id=device_id,
                params={
                    "source_path": self._required_text(
                        params,
                        "source_path",
                        max_chars=1_024,
                    ),
                    "destination_path": self._required_text(
                        params,
                        "destination_path",
                        max_chars=1_024,
                    ),
                    "overwrite": self._boolean(
                        params,
                        "overwrite",
                        default=False,
                    ),
                },
            )
        raise AppControlError("unknown_tool", f"未知工具: {tool}", status=404)

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

    def _execute_session_manage(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        result = self._dispatch_action(action)
        operation = str(action.params.get("action") or "")
        if not result.ok or operation not in {"open", "reconnect"}:
            return result
        session = result.data.get("session")
        session_id = str(session.get("session_id") if isinstance(session, dict) else "")
        if not session_id:
            return AiDeviceToolResult(
                action,
                ok=False,
                message="App 未返回新会话标识。",
                error_code="invalid_backend_result",
                http_status=500,
            )
        deadline = time.monotonic() + int(action.params.get("timeout_seconds", 15))
        latest = result
        while time.monotonic() < deadline:
            status_action = AiDeviceAction(
                "session_manage",
                "读取终端会话状态",
                RiskLevel.OBSERVE,
                device_id=action.device_id,
                params={
                    "action": "status",
                    "protocol": str(action.params.get("protocol") or "auto"),
                    "session_id": session_id,
                },
            )
            latest = self._dispatch_action(status_action)
            latest_session = latest.data.get("session")
            if (
                latest.ok
                and isinstance(latest_session, dict)
                and latest_session.get("status") == "connected"
            ):
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message=f"会话已连接: {session_id}",
                    data={
                        "session": latest_session,
                        "reused": bool(result.data.get("reused")),
                    },
                )
            time.sleep(TERMINAL_EXECUTE_POLL_SECONDS)
        latest_session = latest.data.get("session", session)
        return AiDeviceToolResult(
            action,
            ok=False,
            message=f"等待会话连接超时: {session_id}",
            data={"session": latest_session},
            error_code="session_connect_timeout",
            http_status=408,
        )

    def _execute_terminal_command(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        started = time.monotonic()
        execution_id = str(uuid4())
        initial = self._dispatch_action(action)
        if not initial.ok:
            return initial
        session = initial.data.get("session")
        session_id = str(session.get("session_id") if isinstance(session, dict) else "")
        if isinstance(session, dict) and not action.device_id:
            action.device_id = str(session.get("device_id") or "")
        start_cursor = int(initial.data.get("output_cursor_start", 0))
        timeout_seconds = int(action.params.get("timeout_seconds", 30))
        max_output_chars = int(action.params.get("max_output_chars", 16_384))
        deadline = started + timeout_seconds
        last_cursor = start_cursor
        last_change = started
        output = ""
        truncated = False
        end_cursor = start_cursor
        while time.monotonic() < deadline:
            snapshot_action = AiDeviceAction(
                "terminal_execution_snapshot",
                "读取命令增量输出",
                RiskLevel.OBSERVE,
                device_id=action.device_id,
                params={
                    "session_id": session_id,
                    "cursor": start_cursor,
                    "max_chars": max_output_chars,
                },
            )
            snapshot = self._dispatch_action(snapshot_action)
            if not snapshot.ok:
                return self._terminal_execution_result(
                    action,
                    execution_id=execution_id,
                    session_id=session_id,
                    status="disconnected",
                    output=output,
                    started=started,
                    completion_reason="disconnected",
                    prompt_matched="",
                    start_cursor=start_cursor,
                    end_cursor=end_cursor,
                    truncated=truncated,
                    error_code=snapshot.error_code or "session_disconnected",
                    message=snapshot.message,
                    http_status=snapshot.http_status,
                )
            output = str(snapshot.data.get("output") or "")
            end_cursor = int(snapshot.data.get("output_cursor", end_cursor))
            truncated = bool(snapshot.data.get("truncated", truncated))
            now = time.monotonic()
            if end_cursor != last_cursor:
                last_cursor = end_cursor
                last_change = now
            prompt = detect_terminal_prompt(output)
            if prompt:
                return self._terminal_execution_result(
                    action,
                    execution_id=execution_id,
                    session_id=session_id,
                    status="completed",
                    output=output,
                    started=started,
                    completion_reason="prompt",
                    prompt_matched=prompt,
                    start_cursor=start_cursor,
                    end_cursor=end_cursor,
                    truncated=truncated,
                )
            if (
                output
                and now - last_change >= TERMINAL_EXECUTE_IDLE_SECONDS
            ):
                return self._terminal_execution_result(
                    action,
                    execution_id=execution_id,
                    session_id=session_id,
                    status="completed",
                    output=output,
                    started=started,
                    completion_reason="idle",
                    prompt_matched="",
                    start_cursor=start_cursor,
                    end_cursor=end_cursor,
                    truncated=truncated,
                )
            if (
                snapshot.data.get("status") == "disconnected"
                and not snapshot.data.get("connecting")
            ):
                return self._terminal_execution_result(
                    action,
                    execution_id=execution_id,
                    session_id=session_id,
                    status="disconnected",
                    output=output,
                    started=started,
                    completion_reason="disconnected",
                    prompt_matched="",
                    start_cursor=start_cursor,
                    end_cursor=end_cursor,
                    truncated=truncated,
                    error_code="session_disconnected",
                    message=f"命令执行期间会话已断开: {session_id}",
                    http_status=409,
                )
            time.sleep(TERMINAL_EXECUTE_POLL_SECONDS)
        return self._terminal_execution_result(
            action,
            execution_id=execution_id,
            session_id=session_id,
            status="timed_out",
            output=output,
            started=started,
            completion_reason="timeout",
            prompt_matched="",
            start_cursor=start_cursor,
            end_cursor=end_cursor,
            truncated=truncated,
            error_code="command_timeout",
            message=f"命令执行超过 {timeout_seconds} 秒。",
            http_status=408,
        )

    def _execute_terminal_plan(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        initial = self._dispatch_action(action)
        if not initial.ok:
            return initial
        completion_event = initial.data.pop("_completion_event", None)
        if bool(action.params.get("run_async")):
            return initial
        if not isinstance(completion_event, threading.Event):
            return AiDeviceToolResult(
                action,
                ok=False,
                message="App 未返回终端执行完成事件。",
                error_code="invalid_backend_result",
                http_status=500,
            )
        timeout_seconds = float(action.params.get("total_timeout_seconds", 60)) + 1
        if not completion_event.wait(timeout_seconds):
            return AiDeviceToolResult(
                action,
                ok=False,
                message="等待终端执行结果超时。",
                data=dict(initial.data),
                error_code="execution_timeout",
                http_status=408,
            )
        execution_id = str(initial.data.get("execution_id") or "")
        result_action = AiDeviceAction(
            "terminal_execution_get",
            "读取终端执行结果",
            RiskLevel.OBSERVE,
            params={"execution_id": execution_id},
        )
        queried = self._dispatch_action(result_action)
        if not queried.ok:
            return queried
        status = str(queried.data.get("status") or "")
        if status == "completed":
            return AiDeviceToolResult(
                action,
                ok=True,
                message="终端执行完成。",
                data=dict(queried.data),
            )
        error_code = str(queried.data.get("error_code") or "terminal_execution_failed")
        http_status = 408 if status == "timed_out" else 409
        return AiDeviceToolResult(
            action,
            ok=False,
            message=str(queried.data.get("message") or "终端执行未完成。"),
            data=dict(queried.data),
            error_code=error_code,
            http_status=http_status,
        )

    @staticmethod
    def _terminal_execution_result(
        action: AiDeviceAction,
        *,
        execution_id: str,
        session_id: str,
        status: str,
        output: str,
        started: float,
        completion_reason: str,
        prompt_matched: str,
        start_cursor: int,
        end_cursor: int,
        truncated: bool,
        error_code: str = "",
        message: str = "",
        http_status: int = 409,
    ) -> AiDeviceToolResult:
        ok = not error_code
        return AiDeviceToolResult(
            action,
            ok=ok,
            message=message or f"命令执行完成: {action.command}",
            data={
                "execution_id": execution_id,
                "session_id": session_id,
                "device_id": action.device_id,
                "command": action.command,
                "status": status,
                "output": output,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "completion_reason": completion_reason,
                "prompt_matched": prompt_matched,
                "output_cursor_start": start_cursor,
                "output_cursor_end": end_cursor,
                "truncated": truncated,
            },
            error_code=error_code,
            http_status=http_status,
        )

    def _create_operation(
        self,
        action: AiDeviceAction,
        result: AiDeviceToolResult,
        *,
        kind: str,
        operation_id: str = "",
    ) -> OperationRecord:
        operation = OperationRecord(
            id=operation_id or str(uuid4()),
            kind=kind,
            device_id=action.device_id,
            status="running",
            message=result.message,
            created_at=utc_timestamp(),
            updated_at=utc_timestamp(),
            data=dict(result.data),
        )
        with self._lock:
            self._operations[operation.id] = operation
        return operation

    def _operation_get(
        self,
        params: dict[str, Any],
        *,
        request_id: str,
    ) -> dict[str, Any]:
        operation_id = self._required_text(params, "operation_id", max_chars=80)
        with self._lock:
            operation = self._operations.get(operation_id)
        if operation is None:
            raise AppControlError(
                "operation_not_found",
                f"未找到操作: {operation_id}",
                status=404,
            )
        if operation.kind == "package_upgrade":
            action = AiDeviceAction(
                "get_package_upgrade_status",
                "读取自动换包状态",
                RiskLevel.OBSERVE,
                device_id=operation.device_id,
            )
            result = self.dispatcher(
                lambda: self.backend.execute_ai_device_action(action),
                self.call_timeout_seconds,
            )
            if isinstance(result, AiDeviceToolResult) and result.ok:
                operation.status = str(result.data.get("status") or operation.status)
                operation.message = result.message
                operation.data.update(result.data)
                operation.updated_at = utc_timestamp()
        elif operation.kind == "managed_file_transfer":
            action = AiDeviceAction(
                "get_managed_file_transfer",
                "读取托管文件传输状态",
                RiskLevel.OBSERVE,
                device_id=operation.device_id,
                params={"operation_id": operation.id},
            )
            result = self.dispatcher(
                lambda: self.backend.execute_ai_device_action(action),
                self.call_timeout_seconds,
            )
            if isinstance(result, AiDeviceToolResult) and result.ok:
                operation.status = str(result.data.get("status") or operation.status)
                operation.message = result.message
                operation.data.update(result.data)
                operation.updated_at = utc_timestamp()
        return self._success(
            request_id,
            operation.message,
            {"operation": asdict(operation)},
        )

    def _operation_cancel(
        self,
        params: dict[str, Any],
        *,
        request_id: str,
    ) -> dict[str, Any]:
        operation_id = self._required_text(params, "operation_id", max_chars=80)
        with self._lock:
            operation = self._operations.get(operation_id)
        if operation is None:
            raise AppControlError(
                "operation_not_found",
                f"未找到操作: {operation_id}",
                status=404,
            )
        if operation.kind != "managed_file_transfer":
            raise AppControlError(
                "operation_not_cancellable",
                f"操作类型 {operation.kind} 当前不支持取消。",
                status=409,
            )
        action = AiDeviceAction(
            "cancel_managed_file_transfer",
            "取消托管文件传输",
            RiskLevel.LOW,
            device_id=operation.device_id,
            params={"operation_id": operation.id},
        )
        result = self.dispatcher(
            lambda: self.backend.execute_ai_device_action(action),
            self.call_timeout_seconds,
        )
        if not isinstance(result, AiDeviceToolResult):
            raise AppControlError(
                "invalid_backend_result",
                "App 动作层返回了无效结果。",
                status=500,
            )
        if not result.ok:
            raise AppControlError(
                result.error_code or "operation_cancel_failed",
                result.message,
                status=result.http_status,
            )
        operation.status = str(result.data.get("status") or operation.status)
        operation.message = result.message
        operation.data.update(result.data)
        operation.updated_at = utc_timestamp()
        return self._success(
            request_id,
            operation.message,
            {"operation": asdict(operation)},
        )

    def _terminal_target(self, params: dict[str, Any]) -> tuple[str, str]:
        device_id = self._optional_text(params, "device_id", max_chars=200)
        session_id = self._optional_text(params, "session_id", max_chars=240)
        if not device_id and not session_id:
            raise AppControlError(
                "invalid_request",
                "执行终端计划需要 session_id 或 device_id。",
            )
        return device_id, session_id

    @staticmethod
    def _terminal_plan_runs_async(
        mode: str,
        total_timeout_seconds: float,
        *,
        has_state_wait: bool,
    ) -> bool:
        if mode == "sync" and total_timeout_seconds > 60:
            raise AppControlError(
                "invalid_request",
                "同步终端计划的总超时不能超过 60 秒，请使用 async 模式。",
            )
        if mode == "async":
            return True
        if mode == "sync":
            return False
        return total_timeout_seconds > 60 or has_state_wait

    @staticmethod
    def _required_text(
        params: dict[str, Any],
        key: str,
        *,
        max_chars: int,
    ) -> str:
        value = str(params.get(key) or "").strip()
        if not value:
            raise AppControlError("invalid_request", f"缺少参数: {key}")
        if len(value) > max_chars:
            raise AppControlError(
                "input_too_large",
                f"参数 {key} 超过最大长度 {max_chars}。",
                status=413,
            )
        return value

    @staticmethod
    def _optional_text(
        params: dict[str, Any],
        key: str,
        *,
        max_chars: int,
    ) -> str:
        value = str(params.get(key) or "").strip()
        if len(value) > max_chars:
            raise AppControlError(
                "input_too_large",
                f"参数 {key} 超过最大长度 {max_chars}。",
                status=413,
            )
        return value

    @staticmethod
    def _choice(
        params: dict[str, Any],
        key: str,
        choices: set[str],
        *,
        default: str = "",
    ) -> str:
        value = str(params.get(key) or default).strip().casefold()
        if value not in choices:
            allowed = ", ".join(sorted(choices))
            raise AppControlError(
                "invalid_request",
                f"参数 {key} 必须是: {allowed}。",
            )
        return value

    @staticmethod
    def _integer(
        params: dict[str, Any],
        key: str,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            value = int(params.get(key, default))
        except (TypeError, ValueError) as exc:
            raise AppControlError("invalid_request", f"参数 {key} 必须是整数。") from exc
        if not minimum <= value <= maximum:
            raise AppControlError(
                "invalid_request",
                f"参数 {key} 必须在 {minimum} 到 {maximum} 之间。",
            )
        return value

    @staticmethod
    def _boolean(
        params: dict[str, Any],
        key: str,
        *,
        default: bool,
    ) -> bool:
        value = params.get(key, default)
        if not isinstance(value, bool):
            raise AppControlError(
                "invalid_request",
                f"参数 {key} 必须是布尔值。",
            )
        return value

    @staticmethod
    def _approval_reason(action: AiDeviceAction) -> str:
        if action.risk == RiskLevel.FLOW:
            return "该操作会启动受控设备变更流程。"
        if action.risk == RiskLevel.HIGH:
            return "命令可能重启设备、删除数据或修改启动配置。"
        return "命令可能修改设备配置或传输文件。"

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
