"""Persistence ports for resumable workflow tasks."""

from __future__ import annotations

from typing import Protocol

from .models import TaskRecord, TaskCreate


class TaskStore(Protocol):
    def list_tasks(self, *, limit: int = 500) -> list[tuple[TaskRecord, TaskCreate]]: ...
    def upsert_task(self, record: TaskRecord, request: TaskCreate) -> None: ...


class MemoryTaskStore:
    def __init__(self) -> None:
        self._items: dict[str, tuple[TaskRecord, TaskCreate]] = {}

    def list_tasks(self, *, limit: int = 500) -> list[tuple[TaskRecord, TaskCreate]]:
        items = sorted(self._items.values(), key=lambda item: (item[0].created_at, item[0].id), reverse=True)
        return items[: max(0, limit)]

    def upsert_task(self, record: TaskRecord, request: TaskCreate) -> None:
        self._items[record.id] = (record, request)
