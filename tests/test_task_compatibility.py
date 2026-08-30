from __future__ import annotations

import pytest

from device_tui.application.device_control import DeviceTarget
from device_tui.application.errors import ApplicationConflictError, ApplicationError
from device_tui.application.tasking import (
    MemoryTaskStore,
    TaskCreate,
    TaskRecord,
    TaskRecordCompatibilityBackend,
    WorkflowDefinition,
)
from device_tui.framework import TaskPlan, WorkflowNode


def _request(*, framework: bool = False) -> TaskCreate:
    metadata = {"canonical_workflow_id": "terminal.command", "framework_inputs": {"command": "display version"}} if framework else {}
    workflow = WorkflowDefinition("history", (), metadata=metadata)
    plan = TaskPlan("plan-1", nodes=(WorkflowNode("command", "terminal.command"),)) if framework else None
    return TaskCreate(workflow=workflow, target=DeviceTarget(device_id="d1"), framework_plan=plan)


def _record(task_id: str, status: str) -> TaskRecord:
    return TaskRecord(task_id, status, "history", "d1")


def test_compatibility_backend_loads_history_and_fences_inflight_records() -> None:
    store = MemoryTaskStore()
    request = _request()
    store.upsert_task(_record("pending", "pending"), request)
    store.upsert_task(_record("running", "running"), request)
    store.upsert_task(_record("done", "completed"), request)

    backend = TaskRecordCompatibilityBackend(store)

    assert backend.get("pending").status == "paused"
    assert backend.get("running").status == "paused"
    assert backend.get("pending").error_code == "app_restarted"
    assert backend.get("done").status == "completed"
    assert {item.id for item in backend.list()} == {"pending", "running", "done"}


def test_compatibility_backend_rejects_old_execution_and_decisions() -> None:
    backend = TaskRecordCompatibilityBackend()
    request = _request()

    with pytest.raises(ApplicationError, match="Legacy task execution"):
        backend.create(request)

    backend._records["task-1"] = _record("task-1", "paused")
    backend._requests["task-1"] = request
    with pytest.raises(ApplicationError, match="cannot accept decisions"):
        backend.apply_decision("task-1", "retry")
    with pytest.raises(ApplicationError, match="Legacy task execution"):
        backend.resume("task-1")


def test_compatibility_backend_only_deletes_terminal_history() -> None:
    backend = TaskRecordCompatibilityBackend()
    request = _request()
    backend._records["active"] = _record("active", "paused")
    backend._requests["active"] = request
    backend._records["done"] = _record("done", "failed")
    backend._requests["done"] = request

    with pytest.raises(ApplicationConflictError):
        backend.delete_task("active")
    backend.delete_task("done")
    with pytest.raises(Exception):
        backend.get("done")


def test_framework_projection_is_persisted_and_restored_without_scheduler() -> None:
    store = MemoryTaskStore()
    request = _request(framework=True)
    record = _record("framework-1", "running")
    backend = TaskRecordCompatibilityBackend(store)
    backend.persist_framework_task("framework-1", request, record)

    restarted = TaskRecordCompatibilityBackend(store)

    assert restarted.get("framework-1").status == "paused"
    assert restarted.get("framework-1").error_code == "app_restarted"
    assert not hasattr(restarted, "_jobs")
