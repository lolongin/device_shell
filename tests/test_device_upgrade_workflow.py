import asyncio

from device_tui.application.device_control import DeviceTarget
from device_tui.application.tasking import (
    Action,
    Decision,
    DecisionActor,
    DeviceWorkflowExecutionError,
    Task,
    TaskStatus,
    WorkflowEngine,
    device_upgrade_workflow,
)


class UpgradeExecutor:
    def __init__(self, failures: dict[str, int] | None = None, *, terminal: set[str] | None = None) -> None:
        self.failures = dict(failures or {})
        self.terminal = set(terminal or ())
        self.calls: list[str] = []

    async def execute(self, target, step, *, context):
        self.calls.append(step.id)
        if self.failures.get(step.id, 0):
            self.failures[step.id] -= 1
            if step.id in self.terminal:
                raise DeviceWorkflowExecutionError("validation_failed", "Validation failed.", error_class="terminal")
            error = DeviceWorkflowExecutionError("step_timeout", f"{step.id} timed out.", error_class="deterministic", retryable=True)
            raise error
        return {"output": step.id, "status": "completed"}


def make_task() -> Task:
    return Task(id="upgrade-task", workflow_instance_id="upgrade-instance", device_id="device-1")


def run_all(engine: WorkflowEngine) -> Task:
    async def loop() -> Task:
        while engine.task.status in {TaskStatus.RUNNING.value, TaskStatus.RESUMED.value}:
            await engine.execute_step()
        return engine.task

    return asyncio.run(loop())


def test_device_upgrade_workflow_is_parameterized_and_ordered() -> None:
    workflow = device_upgrade_workflow(device_id="device-1", package="images/router.cc", options={"expected_version": "V2"})
    assert workflow.id == "device_upgrade"
    assert [step.id for step in workflow.steps] == ["precheck", "backup", "upload", "verify", "activate", "reboot", "wait_online", "verify_version", "validation"]
    assert workflow.steps[2].params["device_id"] == "device-1"
    assert workflow.steps[2].params["package"] == "images/router.cc"
    assert workflow.steps[4].params["commands"] == ("startup system-software flash:/router.cc",)
    assert workflow.steps[5].action.confirmation_required is True


def test_normal_upgrade_and_reboot_confirmation() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="device-1", package="router.cc")
        executor = UpgradeExecutor()
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("device-1"))
        engine.start(make_task())
        for _ in range(6):
            await engine.execute_step()
        assert engine.task.status == TaskStatus.WAITING_FOR_USER.value
        assert engine.pending_decision is not None
        engine.apply_decision(Action("approve", target_step="reboot"))
        final = await _finish(engine)
        assert final.status == TaskStatus.COMPLETED.value
        assert executor.calls == ["precheck", "backup", "upload", "verify", "activate", "reboot", "wait_online", "verify_version", "validation"]

    asyncio.run(scenario())


async def _finish(engine: WorkflowEngine) -> Task:
    while engine.task.status in {TaskStatus.RUNNING.value, TaskStatus.RESUMED.value}:
        await engine.execute_step()
    return engine.task


def test_upload_failure_reaches_decision_after_retries() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p")
        executor = UpgradeExecutor({"upload": 3})
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        while engine.task.status == TaskStatus.RUNNING.value and engine.task.workflow.current_step != "upload":
            await engine.execute_step()
        await engine.execute_step()
        assert engine.task.status == TaskStatus.WAITING_FOR_DECISION.value
        assert executor.calls.count("upload") == 3

    asyncio.run(scenario())


def test_verify_failure_decision_then_resume() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p")
        executor = UpgradeExecutor({"verify": 2})
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        while engine.task.workflow.current_step != "verify":
            await engine.execute_step()
        waiting = await engine.execute_step()
        assert waiting.status == TaskStatus.WAITING_FOR_DECISION.value
        executor.failures["verify"] = 0
        engine.apply_decision(Decision("dec-1", DecisionActor("user"), Action("retry", target_step="verify"), expected_revision=waiting.checkpoint.revision))
        assert (await engine.execute_step()).workflow.current_step == "activate"

    asyncio.run(scenario())


def test_wait_online_timeout_retries_then_succeeds() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p")
        executor = UpgradeExecutor({"wait_online": 2})
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        while engine.task.workflow.current_step != "wait_online":
            await engine.execute_step()
            if engine.task.status == TaskStatus.WAITING_FOR_USER.value:
                engine.apply_decision(Action("approve", target_step="reboot"))
        await engine.execute_step()
        assert engine.task.status == TaskStatus.RUNNING.value
        assert executor.calls.count("wait_online") == 3

    asyncio.run(scenario())


def test_timeout_is_retried_and_terminal_failure_is_not_decision() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p", options={"validation_commands": ("validate",)})
        executor = UpgradeExecutor({"validation": 1}, terminal={"validation"})
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        while engine.task.workflow.current_step != "validation":
            await engine.execute_step()
            if engine.task.status == TaskStatus.WAITING_FOR_USER.value:
                engine.apply_decision(Action("approve", target_step="reboot"))
        failed = await engine.execute_step()
        assert failed.status == TaskStatus.FAILED.value

    asyncio.run(scenario())


def test_ambiguous_command_failure_waits_for_human_confirmation() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p")
        executor = UpgradeExecutor({"precheck": 1})

        async def ambiguous_execute(target, step, *, context):
            if step.id == "precheck" and executor.failures.get(step.id, 0):
                executor.failures[step.id] -= 1
                raise DeviceWorkflowExecutionError(
                    "terminal_failure",
                    "终端输出匹配失败条件: Unknown command",
                    error_class="ambiguous",
                )
            return {"output": step.id, "status": "completed"}

        engine = WorkflowEngine(workflow, ambiguous_execute, target=DeviceTarget("d"))
        engine.start(make_task())
        waiting = await engine.execute_step()
        assert waiting.status == TaskStatus.WAITING_FOR_DECISION.value
        assert engine.pending_decision is not None
        assert {action.name for action in engine.pending_decision.available_actions} >= {"retry", "continue", "cancel"}
        engine.apply_decision(Action("continue", target_step="precheck"))
        assert engine.task.workflow.current_step == "backup"

    asyncio.run(scenario())


def test_human_cancel_and_service_restart_restore_checkpoint() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p")
        executor = UpgradeExecutor()
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        await engine.execute_step()
        saved = engine.checkpoint()
        restored = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        restored.start(engine.task)
        assert restored.task.checkpoint.revision >= saved.revision
        assert restored.task.workflow.current_step == "backup"
        assert restored.cancel().status == TaskStatus.CANCELLED.value

    asyncio.run(scenario())
