"""BatchTask domain entity for batch device operations."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

BatchStatus = Literal["pending", "running", "completed", "partial_failure", "failed", "cancelled"]

@dataclass
class BatchTaskSummary:
    """Aggregate status summary for batch task."""
    total: int
    completed: int
    failed: int
    running: int
    pending: int

    @classmethod
    def from_child_statuses(cls, statuses: list[str]) -> BatchTaskSummary:
        """Create summary from child task statuses."""
        return cls(
            total=len(statuses),
            completed=sum(1 for s in statuses if s == "completed"),
            failed=sum(1 for s in statuses if s in ("failed", "cancelled")),
            running=sum(1 for s in statuses if s == "running"),
            pending=sum(1 for s in statuses if s == "pending")
        )

@dataclass
class BatchTask:
    """Batch task entity for operations on multiple devices."""
    batch_id: str
    workflow_id: str
    workflow_name: str
    target_devices: list[str]
    child_task_ids: list[str]
    aggregate_status: BatchStatus
    summary: BatchTaskSummary
    created_at: datetime
    updated_at: datetime
    concurrency: int = 5
    failure_strategy: Literal["continue", "stop_on_first", "stop_on_threshold"] = "continue"
    failure_threshold: float = 1.0  # 100% by default

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "batch_id": self.batch_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "target_devices": self.target_devices,
            "child_task_ids": self.child_task_ids,
            "aggregate_status": self.aggregate_status,
            "summary": {
                "total": self.summary.total,
                "completed": self.summary.completed,
                "failed": self.summary.failed,
                "running": self.summary.running,
                "pending": self.summary.pending
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "concurrency": self.concurrency,
            "failure_strategy": self.failure_strategy
        }

    def update_status(self, child_statuses: list[str]) -> None:
        """Update aggregate status based on child task statuses."""
        self.summary = BatchTaskSummary.from_child_statuses(child_statuses)
        self.updated_at = datetime.now()

        # Determine aggregate status
        if self.summary.total == 0:
            self.aggregate_status = "pending"
        elif self.summary.running > 0:
            self.aggregate_status = "running"
        elif self.summary.failed == self.summary.total:
            self.aggregate_status = "failed"
        elif self.summary.completed == self.summary.total:
            self.aggregate_status = "completed"
        elif self.summary.failed > 0:
            self.aggregate_status = "partial_failure"
        elif self.summary.completed + self.summary.failed == self.summary.total:
            if self.summary.failed > 0:
                self.aggregate_status = "partial_failure"
            else:
                self.aggregate_status = "completed"
        else:
            self.aggregate_status = "running"
