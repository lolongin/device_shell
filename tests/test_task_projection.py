from device_tui.application.tasking import TaskRunProjector
from device_tui.framework import TaskRun, TaskRunStatus


def test_task_run_projection_is_read_only_and_maps_framework_status() -> None:
    run = TaskRun(
        "run-1",
        "plan-1",
        "device-1",
        status=TaskRunStatus.WAITING_RECONCILE,
        outputs={"upload": {"bytes": 10}},
        error={"code": "transfer_unknown", "message": "reconcile required"},
    )

    record = TaskRunProjector().project(
        run,
        workflow_id="file.transfer",
        session_id="session-1",
        source="mcp",
    )

    assert record.id == run.id
    assert record.status == "paused"
    assert record.workflow_id == "file.transfer"
    assert record.result is not None
    assert record.result.outputs == run.outputs
    assert record.error_code == "transfer_unknown"
    assert run.status == TaskRunStatus.WAITING_RECONCILE


def test_task_service_can_project_without_backend_state_changes() -> None:
    from device_tui.application.tasking import TaskService

    run = TaskRun("run-2", "plan-2", "local", status=TaskRunStatus.SUCCEEDED, outputs={"ok": True})
    record = TaskService(object()).project_run(run)

    assert record.status == "completed"
    assert record.result is not None
    assert record.result.outputs == {"ok": True}
