import asyncio

from device_tui.application.device_control import ControlContext, DeviceTarget
from device_tui.application.events import EventBus
from device_tui.application.tasking import (
    Checkpoint,
    TaskCreate,
    TaskManager,
    TaskRecord,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowResult,
    WorkflowStep,
    WorkflowStepResult,
)
from device_tui.infrastructure.persistence.sqlite_desktop import SQLiteDesktopStore


class FakeExecution:
    async def execute(self, target, step, *, context: ControlContext):
        if step.params.get("fail"):
            raise ValueError("failed")
        return {"output": step.id, "step": step.id}


class FakeDecision:
    async def decide(self, request):
        from device_tui.application.tasking import DecisionResult

        return DecisionResult(bool(request.step.params.get("approved")))


def test_workflow_skips_dependents_after_failure():
    workflow = WorkflowDefinition(
        "wf",
        (
            WorkflowStep("first", "command", params={"fail": True}),
            WorkflowStep("second", "command", depends_on=("first",)),
            WorkflowStep("third", "command", depends_on=("second",)),
        ),
    )
    result = asyncio.run(WorkflowEngine().run(
        workflow,
        task_id="t",
        target=DeviceTarget(device_id="d"),
        context={},
        decision=FakeDecision(),
        execution=FakeExecution(),
        cancel_event=asyncio.Event(),
    ))
    assert result.status == "failed"
    assert [step.status for step in result.steps] == ["failed", "skipped", "skipped"]


def test_workflow_detects_cycle():
    workflow = WorkflowDefinition(
        "wf",
        (WorkflowStep("a", "command", depends_on=("b",)), WorkflowStep("b", "command", depends_on=("a",))),
    )
    result = asyncio.run(WorkflowEngine().run(
        workflow,
        task_id="t",
        target=DeviceTarget(device_id="d"),
        context={},
        decision=FakeDecision(),
        execution=FakeExecution(),
        cancel_event=asyncio.Event(),
    ))
    assert result.error_code == "workflow_cycle"


def test_task_progress_updates_per_step():
    async def run():
        manager = TaskManager(FakeExecution(), EventBus())
        record = manager.create(
            TaskCreate(
                workflow=WorkflowDefinition("wf", (WorkflowStep("a", "command"), WorkflowStep("b", "command", depends_on=("a",)))),
                target=DeviceTarget(device_id="d"),
            )
        )
        for _ in range(20):
            await asyncio.sleep(0)
            current = manager.get(record.id)
            if current.status == "completed":
                break
        current = manager.get(record.id)
        assert current.status == "completed"
        assert current.progress_percent == 100
        await manager.close()

    asyncio.run(run())


def test_sqlite_task_store_round_trips_task_history(tmp_path):
    store = SQLiteDesktopStore(tmp_path / "device-tui.sqlite3")
    workflow = WorkflowDefinition("wf", (WorkflowStep("precheck", "command"),))
    request = TaskCreate(workflow=workflow, target=DeviceTarget(device_id="d", session_id="s"), source="desktop", context={"source": "desktop"})
    record = TaskRecord(
        id="task-1",
        status="completed",
        workflow_id="wf",
        device_id="d",
        session_id="s",
        source="desktop",
        created_at="2026-08-22T00:00:00+00:00",
        updated_at="2026-08-22T00:01:00+00:00",
        progress_percent=100,
        result=WorkflowResult("completed", (WorkflowStepResult("precheck", "completed", output="ok"),), message="Workflow completed."),
        checkpoint=Checkpoint(task_id="task-1", completed_steps=("precheck",)),
    )

    store.upsert_task(record, request)
    records = store.list_tasks()

    assert len(records) == 1
    restored, restored_request = records[0]
    assert restored.id == "task-1"
    assert restored.status == "completed"
    assert restored.checkpoint is not None
    assert restored.checkpoint.completed_steps == ("precheck",)
    assert restored.result is not None
    assert restored.result.steps[0].output == "ok"
    assert restored_request.workflow.steps[0].id == "precheck"
    assert restored_request.target.session_id == "s"
