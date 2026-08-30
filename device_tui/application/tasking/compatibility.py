"""Read-only compatibility support for historical task records.

The Framework owns execution of every new task.  This module keeps the old
``TaskRecord`` shape available to API clients while deliberately providing no
legacy scheduler or workflow engine.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Iterable

from device_tui.application.errors import ApplicationConflictError, ApplicationError, ResourceNotFoundError
from device_tui.application.events import EventBus

from .models import TaskCreate, TaskRecord, TaskStatus
from .store import MemoryTaskStore, TaskStore


class TaskRecordCompatibilityBackend:
    """Persist and expose historical ``TaskRecord`` snapshots only.

    This backend is intentionally not a ``TaskLifecycle`` implementation for
    new work: ``create`` and ``resume`` reject old workflow execution.  The
    methods that remain are limited to history reads, terminal deletion, and
    fencing stale records after an application restart.
    """

    def __init__(self, store: TaskStore | None = None, events: EventBus | None = None) -> None:
        self._store = store or MemoryTaskStore()
        self._events = events
        self._records: dict[str, TaskRecord] = {}
        self._requests: dict[str, TaskCreate] = {}
        self._framework_projection_ids: set[str] = set()
        for record, request in self._store.list_tasks():
            if self._is_framework_projection(request):
                self._framework_projection_ids.add(record.id)
            if record.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
                record = replace(
                    record,
                    status=TaskStatus.PAUSED.value,
                    message="应用重启后任务等待 Framework 恢复。",
                    error_code="app_restarted",
                    updated_at=self._now(),
                )
                self._store.upsert_task(record, request)
            self._records[record.id] = record
            self._requests[record.id] = request

    def create(self, request: TaskCreate) -> TaskRecord:
        del request
        raise ApplicationError(
            "Legacy task execution is disabled; submit a Framework TaskPlan."
        )

    def get(self, task_id: str) -> TaskRecord:
        try:
            return self._records[str(task_id)]
        except KeyError as exc:
            raise ResourceNotFoundError(
                f"Unknown task: {task_id}", details={"task_id": str(task_id)}
            ) from exc

    def list(self, *, limit: int = 200) -> list[TaskRecord]:
        return sorted(
            self._records.values(),
            key=lambda item: (item.updated_at or item.created_at, item.id),
            reverse=True,
        )[: max(0, int(limit))]

    def get_decision(self, task_id: str) -> None:
        self.get(task_id)
        return None

    def apply_decision(self, task_id: str, decision: Any) -> TaskRecord:
        del decision
        self.get(task_id)
        raise ApplicationError(
            "Historical tasks cannot accept decisions; create a Framework task."
        )

    def resume(
        self,
        task_id: str,
        *,
        context: dict[str, Any] | None = None,
        step_id: str = "",
    ) -> TaskRecord:
        del context, step_id
        self.get(task_id)
        raise ApplicationError(
            "Legacy task execution is disabled; submit a Framework TaskPlan."
        )

    def pause(self, task_id: str) -> TaskRecord:
        record = self.get(task_id)
        if str(record.status) in self._TERMINAL:
            return record
        return self._update(
            record,
            status=TaskStatus.PAUSED.value,
            message="Task paused.",
            error_code="",
        )

    def cancel(self, task_id: str) -> TaskRecord:
        record = self.get(task_id)
        if str(record.status) in self._TERMINAL:
            return record
        return self._update(
            record,
            status=TaskStatus.CANCELLED.value,
            message="Task cancelled.",
            error_code="task_cancelled",
        )

    def delete_task(self, task_id: str) -> None:
        record = self.get(task_id)
        if str(record.status) not in self._TERMINAL:
            raise ApplicationConflictError(
                "只能删除已结束的任务记录。",
                details={"task_id": record.id, "status": str(record.status)},
            )
        self._records.pop(record.id, None)
        self._requests.pop(record.id, None)
        self._framework_projection_ids.discard(record.id)
        self._store.delete_task(record.id)

    def delete_tasks(self, task_ids: Iterable[str]) -> tuple[str, ...]:
        normalized = tuple(
            dict.fromkeys(str(task_id).strip() for task_id in task_ids if str(task_id).strip())
        )
        records = [self.get(task_id) for task_id in normalized]
        for record in records:
            if str(record.status) not in self._TERMINAL:
                raise ApplicationConflictError(
                    "只能删除已结束的任务记录。",
                    details={"task_id": record.id, "status": str(record.status)},
                )
        for task_id in normalized:
            self.delete_task(task_id)
        return normalized

    def cancel_session(self, session_id: str) -> int:
        cancelled = 0
        for task_id, request in tuple(self._requests.items()):
            if task_id in self._framework_projection_ids or request.target.session_id != session_id:
                continue
            if str(self.get(task_id).status) in self._TERMINAL:
                continue
            self.cancel(task_id)
            cancelled += 1
        return cancelled

    def persist_framework_task(self, task_id: str, request: TaskCreate, record: TaskRecord) -> None:
        self._framework_projection_ids.add(str(task_id))
        self._records[str(task_id)] = record
        self._requests[str(task_id)] = request
        self._store.upsert_task(record, request)

    def forget_framework_task(self, task_id: str) -> None:
        normalized = str(task_id)
        self._framework_projection_ids.discard(normalized)
        self._records.pop(normalized, None)
        self._requests.pop(normalized, None)
        self._store.delete_task(normalized)

    async def close(self) -> None:
        """Compatibility backend has no jobs or scheduler to shut down."""

    @staticmethod
    def _is_framework_projection(request: TaskCreate) -> bool:
        metadata = dict(request.workflow.metadata)
        return bool(
            request.framework_plan is not None
            or metadata.get("framework_task_plan")
            or metadata.get("canonical_workflow_id")
        )

    def _update(self, record: TaskRecord, **changes: Any) -> TaskRecord:
        updated = replace(record, updated_at=self._now(), **changes)
        self._records[record.id] = updated
        request = self._requests.get(record.id)
        if request is not None:
            self._store.upsert_task(updated, request)
        if self._events is not None:
            self._events.publish(
                "task.updated",
                resource_id=updated.id,
                data={
                    "task_id": updated.id,
                    "status": str(updated.status),
                    "workflow_id": updated.workflow_id,
                    "device_id": updated.device_id,
                    "progress_percent": updated.progress_percent,
                    "current_step_id": updated.current_step_id,
                    "error_code": updated.error_code,
                    "message": updated.message,
                },
            )
        return updated

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    _TERMINAL = frozenset(
        {
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELLED.value,
        }
    )


__all__ = ["TaskRecordCompatibilityBackend"]
