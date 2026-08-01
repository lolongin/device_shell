"""Approval records and single-use token lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
import secrets
import threading
import time
from typing import Any, Callable
from uuid import uuid4

from ..ai_device_ops import AiDeviceAction
from .core import (
    APPROVAL_TTL_SECONDS,
    AppControlError,
    action_fingerprint,
    action_to_dict,
    utc_timestamp,
)

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
