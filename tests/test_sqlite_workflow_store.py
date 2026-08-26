from __future__ import annotations

from pathlib import Path

from device_tui.application.workflows import (
    DecisionPoint,
    DeviceStateSnapshot,
    Event,
    MemoryWorkflowEventStore,
    Option,
    ProgressSnapshot,
    RunStatus,
    WorkflowRun,
)
from device_tui.infrastructure.persistence.sqlite_workflows import SQLiteWorkflowEventStore, SQLiteWorkflowRunStore


def test_sqlite_workflow_run_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "device.sqlite3"
    store = SQLiteWorkflowRunStore(path)
    run = WorkflowRun(
        id="run-1", workflow_id="network.package_upgrade", workflow_version="1", device_id="d1",
        status=RunStatus.WAITING_DECISION, current_state="verify", revision=4,
        device_state=DeviceStateSnapshot(reachability="pingable"),
        progress=ProgressSnapshot(stage="verify", last_event_type="version.mismatch"),
        decision_point=DecisionPoint(
            id="dp-1", run_id="run-1", revision=4, reason_code="version_mismatch",
            summary="version mismatch", options=(Option("abort", "abort", "Abort"),),
        ),
    )
    store.save(run)
    restored = store.get("run-1")
    assert restored.id == run.id
    assert restored.status == RunStatus.WAITING_DECISION
    assert restored.decision_point is not None
    assert restored.decision_point.options[0].id == "abort"


def test_sqlite_workflow_event_store_assigns_per_run_sequence_and_is_idempotent(tmp_path: Path) -> None:
    store = SQLiteWorkflowEventStore(tmp_path / "device.sqlite3")
    first = store.append(Event("workflow.started", "run-1"))
    duplicate = store.append(first)
    second = store.append(Event("action.started", "run-1"))
    other = store.append(Event("workflow.started", "run-2"))
    assert duplicate.sequence == 1
    assert second.sequence == 2
    assert other.sequence == 1
    assert [event.type for event in store.list("run-1")] == ["workflow.started", "action.started"]
