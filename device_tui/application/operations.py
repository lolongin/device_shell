"""Unified in-process records for cancellable desktop operations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import uuid4

from .errors import ResourceNotFoundError, UnsupportedOperationError
from .events import EventBus


TERMINAL_OPERATION_STATUSES = {"staged", "completed", "failed", "cancelled", "interrupted"}


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
    bytes_transferred: int = 0
    total_bytes: int = 0
    bytes_per_second: int = 0
    eta_seconds: int | None = None
    queue_position: int | None = None
    retry_of: str | None = None
    cancellable: bool = True
    error_code: str = ""
    revision: int = 0
    created_at: str = ""
    updated_at: str = ""
    data: dict[str, object] = field(default_factory=dict)


class OperationStore(Protocol):
    def list_operations(self, *, kind: str, limit: int) -> list[OperationRecord]: ...

    def upsert_operation(self, record: OperationRecord) -> None: ...

    def delete_terminal_operations(self, *, kind: str) -> int: ...

    def prune_terminal_operations(self, *, kind: str, keep: int) -> None: ...


class MemoryOperationStore:
    def __init__(self) -> None:
        self._records: dict[str, OperationRecord] = {}

    def list_operations(self, *, kind: str, limit: int) -> list[OperationRecord]:
        records = [record for record in self._records.values() if record.kind == kind]
        records.sort(key=lambda record: (record.created_at, record.id), reverse=True)
        return [replace(record, data=dict(record.data)) for record in records[:limit]]

    def upsert_operation(self, record: OperationRecord) -> None:
        self._records[record.id] = replace(record, data=dict(record.data))

    def delete_terminal_operations(self, *, kind: str) -> int:
        targets = [
            operation_id
            for operation_id, record in self._records.items()
            if record.kind == kind and record.status in TERMINAL_OPERATION_STATUSES
        ]
        for operation_id in targets:
            self._records.pop(operation_id, None)
        return len(targets)

    def prune_terminal_operations(self, *, kind: str, keep: int) -> None:
        terminal = [
            record
            for record in self._records.values()
            if record.kind == kind and record.status in TERMINAL_OPERATION_STATUSES
        ]
        terminal.sort(key=lambda record: (record.created_at, record.id), reverse=True)
        for record in terminal[max(0, keep):]:
            self._records.pop(record.id, None)


class OperationManager:
    def __init__(
        self,
        events: EventBus,
        store: OperationStore | None = None,
        *,
        persistent_kinds: set[str] | None = None,
        history_limit: int = 200,
    ) -> None:
        self._events = events
        self._store = store or MemoryOperationStore()
        self._persistent_kinds = set(persistent_kinds or set())
        self._history_limit = max(1, int(history_limit))
        self._records: dict[str, OperationRecord] = {}
        self._cancellers: dict[str, Callable[[], None]] = {}
        self._restore()

    def create(
        self,
        *,
        kind: str,
        direction: str,
        device_id: str,
        session_id: str,
        stage: str,
        message: str,
        status: str = "running",
        total_bytes: int = 0,
        retry_of: str | None = None,
        data: dict[str, object] | None = None,
    ) -> OperationRecord:
        now = self._now()
        record_data = dict(data or {})
        if kind == "package_upgrade":
            # Package replacement is exposed as one guarded operation, but its
            # internal stages are useful evidence for the parent Task timeline.
            # Keep a bounded, secret-free history in the operation payload.
            record_data.setdefault(
                "stage_history",
                [
                    {
                        "stage": stage,
                        "status": status,
                        "message": message,
                        "progress_percent": 0,
                        "actions": [],
                    }
                ],
            )
        record = OperationRecord(
            id=str(uuid4()),
            kind=kind,
            direction=direction,
            device_id=device_id,
            session_id=session_id,
            status=status,
            stage=stage,
            message=message,
            total_bytes=max(0, int(total_bytes)),
            retry_of=retry_of,
            created_at=now,
            updated_at=now,
            data=record_data,
        )
        if status in TERMINAL_OPERATION_STATUSES:
            record = replace(record, cancellable=False)
        self._records[record.id] = record
        self._persist(record)
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
        bytes_transferred: int | None = None,
        total_bytes: int | None = None,
        bytes_per_second: int | None = None,
        eta_seconds: int | None = None,
        clear_eta: bool = False,
        queue_position: int | None = None,
        clear_queue_position: bool = False,
        cancellable: bool | None = None,
        error_code: str | None = None,
        stage_actions: list[str] | tuple[str, ...] | None = None,
        data: dict[str, object] | None = None,
    ) -> OperationRecord:
        current = self.get(operation_id)
        merged_data = dict(current.data)
        if data:
            merged_data.update(data)
        next_status = current.status if status is None else status
        next_stage = current.stage if stage is None else stage
        next_message = current.message if message is None else message
        next_progress = (
            current.progress_percent
            if progress_percent is None
            else max(0, min(100, int(progress_percent)))
        )
        if current.kind == "package_upgrade" and next_stage != current.stage:
            history = merged_data.get("stage_history")
            entries = [dict(item) for item in history if isinstance(item, dict)] if isinstance(history, list) else []
            entries.append(
                {
                    "stage": next_stage,
                    "status": next_status,
                    "message": next_message,
                    "progress_percent": next_progress,
                    "actions": [str(item) for item in (stage_actions or ()) if str(item).strip()],
                }
            )
            merged_data["stage_history"] = entries[-32:]
        updated = replace(
            current,
            status=next_status,
            stage=next_stage,
            message=next_message,
            progress_percent=next_progress,
            bytes_transferred=(
                current.bytes_transferred
                if bytes_transferred is None
                else max(0, int(bytes_transferred))
            ),
            total_bytes=(
                current.total_bytes if total_bytes is None else max(0, int(total_bytes))
            ),
            bytes_per_second=(
                current.bytes_per_second
                if bytes_per_second is None
                else max(0, int(bytes_per_second))
            ),
            eta_seconds=(
                None if clear_eta else current.eta_seconds if eta_seconds is None else max(0, int(eta_seconds))
            ),
            queue_position=(
                None
                if clear_queue_position
                else current.queue_position if queue_position is None else max(1, int(queue_position))
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
        self._persist(updated)
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

    def delete_terminal(self, *, kind: str) -> int:
        targets = [
            operation_id
            for operation_id, record in self._records.items()
            if record.kind == kind and record.status in TERMINAL_OPERATION_STATUSES
        ]
        for operation_id in targets:
            self._records.pop(operation_id, None)
            self._cancellers.pop(operation_id, None)
        if kind in self._persistent_kinds:
            self._store.delete_terminal_operations(kind=kind)
        return len(targets)

    def _restore(self) -> None:
        for kind in self._persistent_kinds:
            for stored in self._store.list_operations(kind=kind, limit=self._history_limit + 500):
                record = stored
                if record.status not in TERMINAL_OPERATION_STATUSES:
                    subject = "换包操作" if record.kind == "package_upgrade" else "文件传输"
                    record = replace(
                        record,
                        status="interrupted",
                        stage="interrupted",
                        message=f"应用重启，{subject}已中断。",
                        cancellable=False,
                        error_code="operation_interrupted",
                        queue_position=None,
                        bytes_per_second=0,
                        eta_seconds=None,
                        revision=record.revision + 1,
                        updated_at=self._now(),
                    )
                    self._store.upsert_operation(record)
                self._records[record.id] = self._clone(record)
            self._store.prune_terminal_operations(kind=kind, keep=self._history_limit)

    def _persist(self, record: OperationRecord) -> None:
        if record.kind not in self._persistent_kinds:
            return
        self._store.upsert_operation(record)
        if record.status in TERMINAL_OPERATION_STATUSES:
            self._store.prune_terminal_operations(kind=record.kind, keep=self._history_limit)

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
