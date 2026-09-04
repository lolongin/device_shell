"""Read-only projections from the framework run model to legacy API DTOs.

The framework owns execution state.  ``TaskRecord`` remains available to the
desktop and MCP adapters, but is deliberately produced as a projection and
must not be used to drive a run.
"""

from __future__ import annotations

from typing import Any, Mapping

from device_tui.framework import TaskRun, TaskRunStatus

from .models import TaskRecord, TaskStatus, WorkflowResult


_STATUS_MAP = {
    TaskRunStatus.CREATED.value: TaskStatus.PENDING.value,
    TaskRunStatus.RUNNING.value: TaskStatus.RUNNING.value,
    TaskRunStatus.WAITING_CHILD.value: TaskStatus.RUNNING.value,
    TaskRunStatus.WAITING_DECISION.value: TaskStatus.WAITING_FOR_DECISION.value,
    TaskRunStatus.WAITING_RECONCILE.value: TaskStatus.PAUSED.value,
    TaskRunStatus.UNKNOWN.value: TaskStatus.PAUSED.value,
    TaskRunStatus.SUCCEEDED.value: TaskStatus.COMPLETED.value,
    TaskRunStatus.FAILED.value: TaskStatus.FAILED.value,
    TaskRunStatus.CANCELLED.value: TaskStatus.CANCELLED.value,
}


class TaskRunProjector:
    """Project a ``TaskRun`` without mutating or executing anything."""

    def project(
        self,
        run: TaskRun,
        *,
        workflow_id: str | None = None,
        session_id: str = "",
        source: str = "framework",
        created_at: str = "",
        updated_at: str = "",
        workflow_view: Mapping[str, Any] | None = None,
    ) -> TaskRecord:
        status = str(run.status)
        error = dict(run.error or {})
        message = str(error.get("message") or self._message(status))
        result = WorkflowResult(
            status=_STATUS_MAP.get(status, status),
            steps=(),
            outputs=dict(run.outputs),
            error_code=str(error.get("code") or ""),
            message=message,
        )
        return TaskRecord(
            id=run.id,
            status=_STATUS_MAP.get(status, status),
            workflow_id=str(workflow_id or run.plan_id),
            device_id=run.device_id,
            session_id=session_id,
            source=source,
            created_at=created_at,
            updated_at=updated_at,
            progress_percent=100 if status == TaskRunStatus.SUCCEEDED.value else 0,
            current_step_id=next(reversed(run.node_runs), "") if run.node_runs else "",
            error_code=str(error.get("code") or ""),
            message=message,
            result=result,
            workflow_view=dict(workflow_view or {}),
        )

    @staticmethod
    def _message(status: str) -> str:
        return {
            TaskRunStatus.CREATED.value: "Task queued.",
            TaskRunStatus.RUNNING.value: "Task running.",
            TaskRunStatus.WAITING_CHILD.value: "Task waiting for child workflow.",
            TaskRunStatus.WAITING_DECISION.value: "Task waiting for decision.",
            TaskRunStatus.WAITING_RECONCILE.value: "Task waiting for reconciliation.",
            TaskRunStatus.UNKNOWN.value: "Task outcome is unknown.",
            TaskRunStatus.SUCCEEDED.value: "Task completed.",
            TaskRunStatus.FAILED.value: "Task failed.",
            TaskRunStatus.CANCELLED.value: "Task cancelled.",
        }.get(status, "Task status updated.")


__all__ = ["TaskRunProjector"]
