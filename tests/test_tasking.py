import asyncio

from device_tui.application.device_control import ControlContext, DeviceTarget
from device_tui.application.events import EventBus
from device_tui.application.tasking import (
    Checkpoint,
    TaskCreate,
    TaskManager,
    TaskRecord,
    MemoryTaskStore,
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


class BlockingExecution:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled: list[tuple[str, str]] = []

    async def execute(self, target, step, *, context: ControlContext):
        del target, step
        assert context.operation_callback is not None
        context.operation_callback("operation", "operation-1")
        self.started.set()
        await asyncio.Event().wait()

    def cancel_resource(self, kind: str, resource_id: str):
        self.cancelled.append((kind, resource_id))
        return {}


class EvidenceExecution:
    async def execute(self, target, step, *, context: ControlContext):
        del target, step, context
        return {
            "operation_id": "operation-2",
            "execution_id": "execution-2",
            "output": "display version\nVersion 1",
            "evidence": ({"kind": "terminal_execution", "execution_id": "execution-2"},),
        }


class InterruptedExecution:
    def get_resource(self, kind: str, resource_id: str):
        assert kind == "operation"
        assert resource_id == "operation-interrupted"
        return {"status": "interrupted"}


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


def test_task_cancel_propagates_to_registered_operation_and_checkpoints_id() -> None:
    async def scenario() -> None:
        execution = BlockingExecution()
        manager = TaskManager(execution, EventBus())
        record = manager.create(TaskCreate(
            workflow=WorkflowDefinition("wf", (WorkflowStep("run", action="command"),)),
            target=DeviceTarget(device_id="d"),
            source="agent",
        ))
        await asyncio.wait_for(execution.started.wait(), timeout=1)
        cancelled = manager.cancel(record.id)
        await asyncio.sleep(0)

        assert cancelled.status == "cancelled"
        assert ("operation", "operation-1") in execution.cancelled
        assert cancelled.checkpoint is not None
        assert "operation-1" in cancelled.checkpoint.operation_ids
        await manager.close()

    asyncio.run(scenario())


def test_stateful_task_projects_execution_ids_and_evidence() -> None:
    async def scenario() -> None:
        manager = TaskManager(EvidenceExecution(), EventBus())
        record = manager.create(TaskCreate(
            workflow=WorkflowDefinition("wf", (WorkflowStep("version", action="command"),)),
            target=DeviceTarget(device_id="d"),
            source="agent",
        ))
        for _ in range(20):
            await asyncio.sleep(0)
            if manager.get(record.id).status == "completed":
                break
        completed = manager.get(record.id)
        assert completed.result is not None
        step = completed.result.steps[0]
        assert step.operation_id == "operation-2"
        assert step.execution_id == "execution-2"
        assert step.evidence[0]["kind"] == "terminal_execution"
        await manager.close()

    asyncio.run(scenario())


def test_task_restore_reconciles_interrupted_operation() -> None:
    store = MemoryTaskStore()
    request = TaskCreate(
        workflow=WorkflowDefinition("wf", (WorkflowStep("upgrade", action="package_upgrade"),)),
        target=DeviceTarget(device_id="d"),
        source="agent",
    )
    store.upsert_task(
        TaskRecord(
            id="task-interrupted",
            status="running",
            workflow_id="wf",
            device_id="d",
            checkpoint=Checkpoint(task_id="task-interrupted", operation_ids=("operation-interrupted",)),
        ),
        request,
    )

    manager = TaskManager(InterruptedExecution(), EventBus(), store=store)
    restored = manager.get("task-interrupted")

    assert restored.status == "paused"
    assert restored.error_code == "operation_interrupted"
    assert "重新规划" in restored.message
    assert store.list_tasks()[0][0].status == "paused"
