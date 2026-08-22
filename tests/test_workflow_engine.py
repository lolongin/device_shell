import asyncio

from device_tui.application.device_control import DeviceTarget
from device_tui.application.tasking import (
    Action,
    Decision,
    DecisionActor,
    Task,
    TaskStatus,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowStep,
)


class Executor:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list[str] = []

    async def execute(self, target, step, *, context):
        self.calls.append(step.id)
        if self.failures:
            self.failures -= 1
            error = RuntimeError("transient")
            error.error_class = "deterministic"
            error.retryable = True
            raise error
        return {"output": step.id}


def task() -> Task:
    return Task(id="task-1", workflow_instance_id="instance-1")


def test_engine_lifecycle_checkpoint_and_restart() -> None:
    async def scenario() -> None:
        workflow = WorkflowDefinition("wf", (WorkflowStep("one"), WorkflowStep("two", depends_on=("one",))))
        executor = Executor()
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("device-1"))
        running = engine.start(task())
        assert running.status == TaskStatus.RUNNING
        await engine.execute_step()
        paused = engine.pause()
        assert paused.status == TaskStatus.PAUSED
        assert paused.checkpoint is not None
        assert paused.checkpoint.completed_steps == ("one",)
        resumed = engine.resume()
        assert resumed.workflow is not None and resumed.workflow.current_step == "two"

        restored = WorkflowEngine(workflow, executor, target=DeviceTarget("device-1"))
        restored.start(resumed)
        await restored.execute_step()
        assert restored.task.status == TaskStatus.COMPLETED
        assert executor.calls == ["one", "two"]

    asyncio.run(scenario())


def test_deterministic_retry_and_decision_after_policy() -> None:
    async def scenario() -> None:
        workflow = WorkflowDefinition("wf", (WorkflowStep("one", retry_policy={"max_attempts": 2, "deterministic": True, "retryable": True}),))
        executor = Executor(failures=2)
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("device-1"))
        engine.start(task())
        waiting = await engine.execute_step()
        assert waiting.status == TaskStatus.WAITING_FOR_DECISION
        assert waiting.checkpoint is not None and waiting.checkpoint.failed_step_id == "one"
        assert len(executor.calls) == 2

        decision = Decision(
            decision_id="decision-1",
            actor=DecisionActor(type="user", id="operator"),
            action=Action("retry", target_step="one"),
            expected_revision=waiting.checkpoint.revision,
        )
        executor.failures = 0
        completed = engine.apply_decision(decision)
        assert completed.status == TaskStatus.RUNNING
        await engine.execute_step()
        assert engine.task.status == TaskStatus.COMPLETED
        assert engine.task.decisions == (decision,)

    asyncio.run(scenario())


def test_waiting_decision_survives_restart() -> None:
    async def scenario() -> None:
        workflow = WorkflowDefinition("wf", (WorkflowStep("one"),))
        executor = Executor(failures=1)
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("device-1"))
        engine.start(task())
        waiting = await engine.execute_step()
        assert waiting.status == TaskStatus.WAITING_FOR_DECISION

        restored = WorkflowEngine(workflow, executor, target=DeviceTarget("device-1"))
        restored.start(waiting)
        assert restored.task.status == TaskStatus.WAITING_FOR_DECISION
        assert restored.pending_decision is not None
        assert restored.pending_decision.current_step == "one"

    asyncio.run(scenario())


def test_resume_from_only_resets_target_and_dependents() -> None:
    async def scenario() -> None:
        workflow = WorkflowDefinition(
            "wf",
            (WorkflowStep("one"), WorkflowStep("two", depends_on=("one",)), WorkflowStep("three", depends_on=("two",))),
        )
        executor = Executor()
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("device-1"))
        engine.start(task())
        await engine.execute_step()
        await engine.execute_step()
        resumed = engine.resume_from("two")
        assert resumed.checkpoint is not None
        assert resumed.checkpoint.completed_steps == ("one",)
        assert resumed.workflow is not None and resumed.workflow.current_step == "two"

    asyncio.run(scenario())


def test_engine_records_structured_step_evidence() -> None:
    async def scenario() -> None:
        workflow = WorkflowDefinition("wf", (WorkflowStep("one"),))
        executor = Executor()
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("device-1"))
        engine.start(task())
        completed = await engine.execute_step()
        assert completed.checkpoint is not None
        result = completed.checkpoint.step_states[0].result
        assert result is not None
        assert result.evidence[0]["step_id"] == "one"

    asyncio.run(scenario())
