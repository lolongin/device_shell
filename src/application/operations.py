"""Unified in-process records for cancellable desktop operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from .errors import ResourceNotFoundError, UnsupportedOperationError
from .events import EventBus


TERMINAL_OPERATION_STATUSES = {"completed", "failed", "cancelled"}


@dataclass(frozen=True, slots=True)
class OperationRecord:
    id: str
    kind: str
    direction: str
    device_id: str
    session_id: str
    status: str
    stage: str
    message: str
    progress_percent: int = 0
    cancellable: bool = True
    error_code: str = ""
    revision: int = 0
    created_at: str = ""
    updated_at: str = ""
    data: dict[str, object] = field(default_factory=dict)


class OperationManager:
    def __init__(self, events: EventBus) -> None:
        self._events = events
        self._records: dict[str, OperationRecord] = {}
        self._cancellers: dict[str, Callable[[], None]] = {}

    def create(
        self,
        *,
        kind: str,
        direction: str,
        device_id: str,
        session_id: str,
        stage: str,
        message: str,
        data: dict[str, object] | None = None,
    ) -> OperationRecord:
        now = self._now()
        record = OperationRecord(
            id=str(uuid4()),
            kind=kind,
            direction=direction,
            device_id=device_id,
            session_id=session_id,
            status="running",
            stage=stage,
            message=message,
            created_at=now,
            updated_at=now,
            data=dict(data or {}),
        )
        self._records[record.id] = record
        self._publish("operation.created", record)
        return self.get(record.id)

    def list(self, *, kind: str = "", limit: int = 200) -> list[OperationRecord]:
        records = sorted(
            self._records.values(),
            key=lambda record: (record.created_at, record.id),
            reverse=True,
        )
        if kind:
            records = [record for record in records if record.kind == kind]
        return [self._clone(record) for record in records[: max(0, limit)]]

    def get(self, operation_id: str) -> OperationRecord:
        record = self._records.get(operation_id)
        if record is None:
            raise ResourceNotFoundError(
                f"Unknown operation: {operation_id}",
                details={"resource": "operation", "operation_id": operation_id},
            )
        return self._clone(record)

    def update(
        self,
        operation_id: str,
        *,
        status: str | None = None,
        stage: str | None = None,
        message: str | None = None,
        progress_percent: int | None = None,
        cancellable: bool | None = None,
        error_code: str | None = None,
        data: dict[str, object] | None = None,
    ) -> OperationRecord:
        current = self.get(operation_id)
        merged_data = dict(current.data)
        if data:
            merged_data.update(data)
        next_status = current.status if status is None else status
        updated = replace(
            current,
            status=next_status,
            stage=current.stage if stage is None else stage,
            message=current.message if message is None else message,
            progress_percent=(
                current.progress_percent
                if progress_percent is None
                else max(0, min(100, int(progress_percent)))
            ),
            cancellable=(
                current.cancellable
                if cancellable is None
                else bool(cancellable)
            ),
            error_code=current.error_code if error_code is None else error_code,
            revision=current.revision + 1,
            updated_at=self._now(),
            data=merged_data,
        )
        if next_status in TERMINAL_OPERATION_STATUSES:
            updated = replace(updated, cancellable=False)
            self._cancellers.pop(operation_id, None)
        self._records[operation_id] = updated
        self._publish("operation.updated", updated)
        return self.get(operation_id)

    def register_canceller(
        self,
        operation_id: str,
        callback: Callable[[], None],
    ) -> None:
        record = self.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES:
            return
        self._cancellers[operation_id] = callback

    def cancel(self, operation_id: str) -> OperationRecord:
        record = self.get(operation_id)
        if record.status in TERMINAL_OPERATION_STATUSES:
            return record
        callback = self._cancellers.get(operation_id)
        if callback is None or not record.cancellable:
            raise UnsupportedOperationError(
                "The operation cannot be cancelled.",
                details={"operation_id": operation_id},
            )
        callback()
        latest = self.get(operation_id)
        if latest.status not in TERMINAL_OPERATION_STATUSES:
            latest = self.update(
                operation_id,
                status="cancelled",
                stage="cancelled",
                message="操作已取消。",
                error_code="operation_cancelled",
            )
        return latest

    def _publish(self, event_type: str, record: OperationRecord) -> None:
        payload = asdict(record)
        # Operation payloads are deliberately metadata-only; transfer credentials
        # and absolute source paths never enter OperationRecord.data.
        self._events.publish(event_type, resource_id=record.id, data=payload)

    @staticmethod
    def _clone(record: OperationRecord) -> OperationRecord:
        return replace(record, data=dict(record.data))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
