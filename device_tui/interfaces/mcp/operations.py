"""Long-running operation tracking, refresh, wait, and cancellation."""

from __future__ import annotations

from dataclasses import asdict
import json
import time
from typing import Any
from uuid import uuid4

from device_tui.application.ai.operations import AiDeviceAction, AiDeviceToolResult, RiskLevel
from .core import OPERATION_TERMINAL_STATUSES, AppControlError, utc_timestamp
from .models import OperationRecord


class OperationMixin:
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
        with self._operation_condition:
            self._operations[operation.id] = operation
            self._operation_condition.notify_all()
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
        before = (
            operation.status,
            operation.message,
            json.dumps(operation.data, ensure_ascii=False, sort_keys=True, default=str),
        )
        if operation.kind == "managed_file_transfer":
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
        after = (
            operation.status,
            operation.message,
            json.dumps(operation.data, ensure_ascii=False, sort_keys=True, default=str),
        )
        if after != before:
            with self._operation_condition:
                operation.revision += 1
                operation.updated_at = utc_timestamp()
                self._operation_condition.notify_all()
        return self._success(
            request_id,
            operation.message,
            {"operation": asdict(operation)},
        )
    def _operation_wait(
        self,
        params: dict[str, Any],
        *,
        request_id: str,
    ) -> dict[str, Any]:
        operation_id = self._required_text(params, "operation_id", max_chars=80)
        timeout_seconds = self._integer(
            params,
            "timeout_seconds",
            default=60,
            minimum=1,
            maximum=300,
        )
        since_revision = self._integer(
            params,
            "since_revision",
            default=0,
            minimum=0,
            maximum=2_147_483_647,
        )
        deadline = time.monotonic() + timeout_seconds
        first = True
        baseline_revision = since_revision
        while True:
            snapshot = self._operation_get(
                {"operation_id": operation_id},
                request_id=request_id,
            )
            operation = snapshot["data"]["operation"]
            revision = int(operation.get("revision") or 0)
            status = str(operation.get("status") or "").casefold()
            if first and baseline_revision == 0:
                baseline_revision = revision
            elif revision > baseline_revision:
                snapshot["data"]["wait_timed_out"] = False
                return snapshot
            if status in OPERATION_TERMINAL_STATUSES:
                snapshot["data"]["wait_timed_out"] = False
                return snapshot
            first = False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                snapshot["data"]["wait_timed_out"] = True
                return snapshot
            with self._operation_condition:
                self._operation_condition.wait(timeout=min(0.25, remaining))
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
        with self._operation_condition:
            operation.revision += 1
            operation.updated_at = utc_timestamp()
            self._operation_condition.notify_all()
        return self._success(
            request_id,
            operation.message,
            {"operation": asdict(operation)},
        )
