"""Session preparation and terminal execution coordination."""

from __future__ import annotations

import threading
import sys
import time
from typing import Any
from uuid import uuid4

from ..ai_device_ops import AiDeviceAction, AiDeviceToolResult, RiskLevel
from ..terminal_execution import detect_terminal_prompt
from .core import TERMINAL_EXECUTE_IDLE_SECONDS, TERMINAL_EXECUTE_POLL_SECONDS


def _runtime_setting(instance: object, name: str, default: float) -> float:
    module = sys.modules.get(instance.__class__.__module__)
    return float(getattr(module, name, default)) if module is not None else default


class ExecutionMixin:
    def _execute_terminal_run(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        started = time.monotonic()
        session_prepare_started = started
        session_id = str(action.params.get("session_id") or "")
        ensure_session = bool(action.params.get("ensure_session", True))
        session_summary: dict[str, Any] = {}

        if ensure_session:
            operation = "status" if session_id else "open"
            session_action = AiDeviceAction(
                "session_manage",
                "准备终端会话",
                RiskLevel.LOW,
                device_id=action.device_id,
                params={
                    "action": operation,
                    "protocol": str(action.params.get("protocol") or "auto"),
                    "session_id": session_id,
                    "timeout_seconds": 15,
                },
            )
            prepared = self._execute_session_manage(session_action)
            prepared_session = prepared.data.get("session")
            session_summary = (
                dict(prepared_session) if isinstance(prepared_session, dict) else {}
            )
            if not prepared.ok:
                return AiDeviceToolResult(
                    action,
                    ok=False,
                    message=prepared.message,
                    data={"session": session_summary},
                    error_code=prepared.error_code,
                    http_status=prepared.http_status,
                )
            if session_summary.get("status") != "connected":
                reconnect_action = AiDeviceAction(
                    "session_manage",
                    "重连终端会话",
                    RiskLevel.LOW,
                    device_id=action.device_id,
                    params={
                        "action": "reconnect",
                        "protocol": str(action.params.get("protocol") or "auto"),
                        "session_id": str(session_summary.get("session_id") or session_id),
                        "timeout_seconds": 15,
                    },
                )
                prepared = self._execute_session_manage(reconnect_action)
                prepared_session = prepared.data.get("session")
                session_summary = (
                    dict(prepared_session) if isinstance(prepared_session, dict) else {}
                )
                if not prepared.ok:
                    return AiDeviceToolResult(
                        action,
                        ok=False,
                        message=prepared.message,
                        data={"session": session_summary},
                        error_code=prepared.error_code,
                        http_status=prepared.http_status,
                    )
            session_id = str(session_summary.get("session_id") or session_id)
            if not action.device_id:
                action.device_id = str(session_summary.get("device_id") or "")

        session_prepare_ms = round(
            (time.monotonic() - session_prepare_started) * 1000,
            2,
        )
        plan_params = {
            "plan_kind": "batch",
            "commands": list(action.params.get("commands") or []),
            "session_id": session_id,
            "command_timeout_seconds": int(
                action.params.get("command_timeout_seconds", 30)
            ),
            "total_timeout_seconds": float(
                action.params.get("total_timeout_seconds", 60)
            ),
            "max_output_chars_per_step": int(
                action.params.get("max_output_chars_per_step", 16_384)
            ),
            "mode": str(action.params.get("mode") or "auto"),
            "run_async": bool(action.params.get("run_async", False)),
            "coordinator_idempotency_key": str(
                action.params.get("coordinator_idempotency_key") or ""
            ),
        }
        plan_action = AiDeviceAction(
            "terminal_plan_start",
            action.label,
            action.risk,
            device_id=action.device_id,
            params=plan_params,
        )
        result = self._execute_terminal_plan(plan_action)
        data = dict(result.data)
        if session_summary:
            data.setdefault("session", session_summary)
        data.setdefault("session_id", session_id)
        total_ms = round((time.monotonic() - started) * 1000, 2)
        data["timing"] = {
            "session_prepare_ms": session_prepare_ms,
            "device_execution_ms": round(
                float(data.get("duration_ms") or max(0.0, total_ms - session_prepare_ms)),
                2,
            ),
            "total_ms": total_ms,
        }
        return AiDeviceToolResult(
            action,
            ok=result.ok,
            message=result.message,
            data=data,
            approval_required=result.approval_required,
            error_code=result.error_code,
            http_status=result.http_status,
        )
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
            time.sleep(
                _runtime_setting(self, "TERMINAL_EXECUTE_POLL_SECONDS", TERMINAL_EXECUTE_POLL_SECONDS)
            )
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
                and now - last_change
                >= _runtime_setting(
                    self,
                    "TERMINAL_EXECUTE_IDLE_SECONDS",
                    TERMINAL_EXECUTE_IDLE_SECONDS,
                )
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
            time.sleep(
                _runtime_setting(self, "TERMINAL_EXECUTE_POLL_SECONDS", TERMINAL_EXECUTE_POLL_SECONDS)
            )
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
