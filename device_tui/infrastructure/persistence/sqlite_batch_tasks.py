"""SQLite persistence for BatchTask."""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Protocol

from device_tui.domain.batch_task import BatchTask, BatchTaskSummary


class BatchTaskRepository(Protocol):
    """Protocol for batch task repository."""
    def save(self, batch: BatchTask) -> None: ...
    def get(self, batch_id: str) -> BatchTask | None: ...
    def list(self, limit: int = 50) -> list[BatchTask]: ...
    def delete(self, batch_id: str) -> None: ...


class SqliteBatchTaskRepository:
    """SQLite implementation of batch task repository."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            # Create batch_tasks table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batch_tasks (
                    batch_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    workflow_name TEXT NOT NULL,
                    target_devices TEXT NOT NULL,
                    child_task_ids TEXT NOT NULL,
                    aggregate_status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    concurrency INTEGER DEFAULT 5,
                    failure_strategy TEXT DEFAULT 'continue',
                    failure_threshold REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            # Add batch_id column to tasks table if it doesn't exist
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN batch_id TEXT")
            except sqlite3.OperationalError:
                pass  # Column already exists

            # Create index for faster queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_batch_tasks_created_at
                ON batch_tasks(created_at DESC)
            """)

            conn.commit()

    def save(self, batch: BatchTask) -> None:
        """Save or update a batch task."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO batch_tasks
                (batch_id, workflow_id, workflow_name, target_devices, child_task_ids,
                 aggregate_status, summary, concurrency, failure_strategy, failure_threshold,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                batch.batch_id,
                batch.workflow_id,
                batch.workflow_name,
                json.dumps(batch.target_devices),
                json.dumps(batch.child_task_ids),
                batch.aggregate_status,
                json.dumps({
                    "total": batch.summary.total,
                    "completed": batch.summary.completed,
                    "failed": batch.summary.failed,
                    "running": batch.summary.running,
                    "pending": batch.summary.pending
                }),
                batch.concurrency,
                batch.failure_strategy,
                batch.failure_threshold,
                batch.created_at.isoformat(),
                batch.updated_at.isoformat()
            ))
            conn.commit()

    def get(self, batch_id: str) -> BatchTask | None:
        """Get a batch task by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM batch_tasks WHERE batch_id = ?",
                (batch_id,)
            ).fetchone()

            if not row:
                return None

            return self._row_to_batch(row)

    def list(self, limit: int = 50) -> list[BatchTask]:
        """List recent batch tasks."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM batch_tasks ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

            return [self._row_to_batch(row) for row in rows]

    def delete(self, batch_id: str) -> None:
        """Delete a batch task."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM batch_tasks WHERE batch_id = ?", (batch_id,))
            conn.commit()

    def _row_to_batch(self, row: sqlite3.Row) -> BatchTask:
        """Convert database row to BatchTask."""
        summary_data = json.loads(row["summary"])

        return BatchTask(
            batch_id=row["batch_id"],
            workflow_id=row["workflow_id"],
            workflow_name=row["workflow_name"],
            target_devices=json.loads(row["target_devices"]),
            child_task_ids=json.loads(row["child_task_ids"]),
            aggregate_status=row["aggregate_status"],
            summary=BatchTaskSummary(**summary_data),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            concurrency=row["concurrency"],
            failure_strategy=row["failure_strategy"],
            failure_threshold=row.get("failure_threshold", 1.0)
        )


__all__ = ["BatchTaskRepository", "SqliteBatchTaskRepository"]
