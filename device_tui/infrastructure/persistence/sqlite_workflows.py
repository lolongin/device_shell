"""SQLite persistence for the generic workflow framework."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from device_tui.application.workflows.events import Event, WorkflowEventStore
from device_tui.application.workflows.models import (
    ActionAttempt,
    ActionStatus,
    DecisionPoint,
    DeviceStateSnapshot,
    Option,
    ProgressSnapshot,
    WorkflowRun,
)
from device_tui.application.workflows.orchestrator import TaskRun, TaskRunStore


class SQLiteWorkflowRunStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def save(self, run: WorkflowRun) -> WorkflowRun:
        payload = json.dumps(run.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflow_runs (id, workflow_id, workflow_version, device_id, status, revision, updated_at, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    revision=excluded.revision,
                    updated_at=excluded.updated_at,
                    payload=excluded.payload
                """ ,
                (run.id, run.workflow_id, run.workflow_version, run.device_id, str(run.status), run.revision, run.progress.last_progress_at, payload),
            )
        return run

    def get(self, run_id: str) -> WorkflowRun:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"workflow run not found: {run_id}")
        return _run_from_dict(json.loads(str(row["payload"])))

    def list(self, *, limit: int = 500) -> list[WorkflowRun]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM workflow_runs ORDER BY updated_at DESC, id DESC LIMIT ?", (max(0, limit),)).fetchall()
        return [_run_from_dict(json.loads(str(row["payload"]))) for row in rows]

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    workflow_version TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_workflow_runs_updated ON workflow_runs(updated_at DESC, id DESC)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


class SQLiteTaskRunStore(TaskRunStore):
    """Durable store for Task-level composition state."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def save(self, run: TaskRun) -> TaskRun:
        payload = json.dumps(run.to_dict(), ensure_ascii=False, separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_runs (id, plan_id, device_id, status, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    plan_id=excluded.plan_id,
                    device_id=excluded.device_id,
                    status=excluded.status,
                    payload=excluded.payload
                """,
                (run.id, run.plan_id, run.device_id, str(run.status), payload),
            )
        return run

    def get(self, task_run_id: str) -> TaskRun:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM task_runs WHERE id = ?", (task_run_id,)).fetchone()
        if row is None:
            raise KeyError(f"task run not found: {task_run_id}")
        return _task_run_from_dict(json.loads(str(row["payload"])))

    def list(self, *, limit: int = 500) -> list[TaskRun]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM task_runs ORDER BY rowid DESC LIMIT ?",
                (max(0, limit),),
            ).fetchall()
        return [_task_run_from_dict(json.loads(str(row["payload"]))) for row in rows]

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_runs (
                    id TEXT PRIMARY KEY,
                    plan_id TEXT NOT NULL,
                    device_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


class SQLiteWorkflowEventStore(WorkflowEventStore):
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def append(self, event: Event) -> Event:
        with self._connect() as connection:
            existing = connection.execute("SELECT payload FROM workflow_events WHERE event_id = ?", (event.event_id,)).fetchone()
            if existing is not None:
                return _event_from_dict(json.loads(str(existing["payload"])))
            sequence = int(connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM workflow_events WHERE run_id = ?", (event.run_id,)).fetchone()[0])
            stored = Event(
                type=event.type, run_id=event.run_id, action_id=event.action_id,
                sequence=sequence, event_id=event.event_id, source=event.source,
                payload=dict(event.payload), correlation_id=event.correlation_id,
                observed_at=event.observed_at, progress=event.progress,
                evidence_ref=event.evidence_ref,
            )
            connection.execute("INSERT INTO workflow_events (event_id, run_id, sequence, payload) VALUES (?, ?, ?, ?)", (stored.event_id, stored.run_id, stored.sequence, json.dumps(stored.to_dict(), ensure_ascii=False, separators=(",", ":"))))
            return stored

    def list(self, run_id: str, *, after_sequence: int = 0) -> list[Event]:
        with self._connect() as connection:
            rows = connection.execute("SELECT payload FROM workflow_events WHERE run_id = ? AND sequence > ? ORDER BY sequence", (run_id, after_sequence)).fetchall()
        return [_event_from_dict(json.loads(str(row["payload"]))) for row in rows]

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_events (
                    event_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_workflow_events_run_sequence ON workflow_events(run_id, sequence)")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


def _run_from_dict(payload: dict[str, Any]) -> WorkflowRun:
    raw_device = dict(payload.get("device_state") or {})
    raw_progress = dict(payload.get("progress") or {})
    raw_decision = payload.get("decision_point")
    raw_attempts = payload.get("attempts") or ()
    return WorkflowRun(
        id=str(payload.get("id") or ""),
        workflow_id=str(payload.get("workflow_id") or ""),
        workflow_version=str(payload.get("workflow_version") or "1"),
        device_id=str(payload.get("device_id") or ""),
        status=str(payload.get("status") or "pending"),
        current_state=str(payload.get("current_state") or ""),
        revision=int(payload.get("revision") or 0),
        context=dict(payload.get("context") or {}),
        device_state=DeviceStateSnapshot(**raw_device),
        progress=ProgressSnapshot(**raw_progress),
        attempts=tuple(ActionAttempt(**dict(item)) for item in raw_attempts if isinstance(item, dict)),
        decision_point=(DecisionPoint(
            id=str(raw_decision.get("id") or ""), run_id=str(raw_decision.get("run_id") or ""),
            revision=int(raw_decision.get("revision") or 0), reason_code=str(raw_decision.get("reason_code") or ""),
            summary=str(raw_decision.get("summary") or ""),
            options=tuple(
                Option(
                    id=str(item.get("id") or ""), kind=str(item.get("kind") or ""),
                    label=str(item.get("label") or ""), description=str(item.get("description") or ""),
                    risk=str(item.get("risk") or "normal"),
                    allowed_actors=tuple(str(value) for value in item.get("allowed_actors", ("human", "agent", "rule"))),
                    requires_reason=bool(item.get("requires_reason", False)),
                    input_schema=dict(item.get("input_schema") or {}),
                    preconditions=tuple(dict(value) for value in item.get("preconditions", ()) if isinstance(value, dict)),
                    next_state=str(item.get("next_state") or ""),
                )
                for item in raw_decision.get("options", ()) if isinstance(item, dict)
            ),
            evidence=tuple(dict(item) for item in raw_decision.get("evidence", ()) if isinstance(item, dict)),
            expires_at=str(raw_decision.get("expires_at") or ""),
        ) if isinstance(raw_decision, dict) else None),
        error=dict(payload.get("error") or {}) if isinstance(payload.get("error"), dict) else None,
        outputs=dict(payload.get("outputs") or {}),
    )


def _task_run_from_dict(payload: dict[str, Any]) -> TaskRun:
    return TaskRun(
        id=str(payload.get("id") or ""),
        plan_id=str(payload.get("plan_id") or ""),
        device_id=str(payload.get("device_id") or ""),
        status=str(payload.get("status") or "created"),
        inputs=dict(payload.get("inputs") or {}),
        node_runs={str(key): str(value) for key, value in dict(payload.get("node_runs") or {}).items()},
        outputs=dict(payload.get("outputs") or {}),
        error=dict(payload.get("error") or {}) if isinstance(payload.get("error"), dict) else None,
        context=dict(payload.get("context") or {}),
    )


def _event_from_dict(payload: dict[str, Any]) -> Event:
    return Event(
        type=str(payload.get("type") or ""), run_id=str(payload.get("run_id") or ""),
        action_id=str(payload.get("action_id") or ""), sequence=int(payload.get("sequence") or 0),
        event_id=str(payload.get("event_id") or ""), source=str(payload.get("source") or "engine"),
        payload=dict(payload.get("payload") or {}), correlation_id=str(payload.get("correlation_id") or ""),
        observed_at=str(payload.get("observed_at") or ""), progress=bool(payload.get("progress", False)),
        evidence_ref=str(payload.get("evidence_ref") or ""),
    )


__all__ = ["SQLiteTaskRunStore", "SQLiteWorkflowEventStore", "SQLiteWorkflowRunStore"]
