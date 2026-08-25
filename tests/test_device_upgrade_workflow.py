import asyncio

from device_tui.application.device_control import DeviceTarget
from device_tui.application.errors import PackageUpgradeError, UnsupportedOperationError
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
    assert [step.id for step in workflow.steps] == ["prepare_upgrade"]
    assert workflow.steps[0].params["device_id"] == "device-1"
    assert workflow.steps[0].params["package_path"] == "images/router.cc"
    assert workflow.steps[0].params["include_slave"] is True
    assert workflow.steps[0].metadata["result_state"] == "staged"
    activated = device_upgrade_workflow(device_id="device-1", package="images/router.cc", options={"activation_policy": "reboot"})
    assert [step.id for step in activated.steps] == ["prepare_upgrade", "reboot", "wait_online", "verify_version", "validation"]
    assert activated.steps[1].action.confirmation_required is False


def test_normal_upgrade_and_reboot_confirmation() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="device-1", package="router.cc", options={"activation_policy": "reboot"})
        executor = UpgradeExecutor()
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("device-1"))
        engine.start(make_task())
        await engine.execute_step()
        engine.apply_decision(Action("approve", target_step="prepare_upgrade"))
        await engine.execute_step()
        await engine.execute_step()
        final = await _finish(engine)
        assert final.status == TaskStatus.COMPLETED.value
        assert executor.calls == ["prepare_upgrade", "reboot", "wait_online", "verify_version", "validation"]

    asyncio.run(scenario())


async def _finish(engine: WorkflowEngine) -> Task:
    while engine.task.status in {TaskStatus.RUNNING.value, TaskStatus.RESUMED.value}:
        await engine.execute_step()
    return engine.task


def test_upload_failure_reaches_decision_after_retries() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p")
        executor = UpgradeExecutor({"prepare_upgrade": 2})
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        while engine.task.status == TaskStatus.RUNNING.value and engine.task.workflow.current_step != "prepare_upgrade":
            await engine.execute_step()
        await engine.execute_step()
        engine.apply_decision(Action("approve", target_step="prepare_upgrade"))
        await engine.execute_step()
        assert engine.task.status == TaskStatus.WAITING_FOR_DECISION.value
        assert executor.calls.count("prepare_upgrade") == 2

    asyncio.run(scenario())


def test_verify_failure_decision_then_resume() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p", options={"activation_policy": "reboot"})
        executor = UpgradeExecutor({"verify_version": 2})
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        while engine.task.workflow.current_step != "verify_version":
            await engine.execute_step()
            if engine.task.status == TaskStatus.WAITING_FOR_USER.value:
                engine.apply_decision(Action("approve", target_step=engine.task.workflow.current_step))
        waiting = await engine.execute_step()
        assert waiting.status == TaskStatus.WAITING_FOR_DECISION.value
        executor.failures["verify_version"] = 0
        engine.apply_decision(Decision("dec-1", DecisionActor("user"), Action("retry", target_step="verify_version"), expected_revision=waiting.checkpoint.revision))
        assert (await engine.execute_step()).status == TaskStatus.RUNNING.value

    asyncio.run(scenario())


def test_wait_online_timeout_retries_then_succeeds() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p", options={"activation_policy": "reboot"})
        executor = UpgradeExecutor({"wait_online": 2})
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        while engine.task.workflow.current_step != "wait_online":
            await engine.execute_step()
            if engine.task.status == TaskStatus.WAITING_FOR_USER.value:
                engine.apply_decision(Action("approve", target_step=engine.task.workflow.current_step))
        await engine.execute_step()
        assert engine.task.status == TaskStatus.RUNNING.value
        assert executor.calls.count("wait_online") == 3

    asyncio.run(scenario())


def test_timeout_is_retried_and_terminal_failure_is_not_decision() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p", options={"activation_policy": "reboot", "validation_commands": ("validate",)})
        executor = UpgradeExecutor({"validation": 1}, terminal={"validation"})
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        while engine.task.workflow.current_step != "validation":
            await engine.execute_step()
            if engine.task.status == TaskStatus.WAITING_FOR_USER.value:
                engine.apply_decision(Action("approve", target_step=engine.task.workflow.current_step))
        failed = await engine.execute_step()
        assert failed.status == TaskStatus.FAILED.value

    asyncio.run(scenario())


def test_ambiguous_command_failure_waits_for_human_confirmation() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p")
        executor = UpgradeExecutor({"prepare_upgrade": 1})

        async def ambiguous_execute(target, step, *, context):
            if step.id == "prepare_upgrade" and executor.failures.get(step.id, 0):
                executor.failures[step.id] -= 1
                raise DeviceWorkflowExecutionError(
                    "terminal_failure",
                    "终端输出匹配失败条件: Unknown command",
                    error_class="ambiguous",
                )
            return {"output": step.id, "status": "completed"}

        engine = WorkflowEngine(workflow, ambiguous_execute, target=DeviceTarget("d"))
        engine.start(make_task())
        await engine.execute_step()
        engine.apply_decision(Action("approve", target_step="prepare_upgrade"))
        waiting = await engine.execute_step()
        assert waiting.status == TaskStatus.WAITING_FOR_DECISION.value
        assert engine.pending_decision is not None
        assert {action.name for action in engine.pending_decision.available_actions} >= {"retry", "continue", "cancel"}
        engine.apply_decision(Action("continue", target_step="prepare_upgrade"))
        assert engine.task.workflow.current_step == ""

    asyncio.run(scenario())


def test_upgrade_driver_failure_cannot_be_accepted_as_success() -> None:
    async def fail_upgrade(target, step, *, context):
        if step.id == "prepare_upgrade":
            raise UnsupportedOperationError("No upgrade driver matched target SIM-TERMINAL")
        return {"output": step.id, "status": "completed"}

    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="SIM-TERMINAL", package="router.cc")
        engine = WorkflowEngine(workflow, fail_upgrade, target=DeviceTarget("SIM-TERMINAL"))
        engine.start(make_task())
        await engine.execute_step()
        engine.apply_decision(Action("approve", target_step="prepare_upgrade"))
        failed = await engine.execute_step()
        assert failed.status == TaskStatus.FAILED.value
        assert engine.pending_decision is None
        state = failed.checkpoint.step_states[0]
        assert state.error is not None
        assert state.error.code == "unsupported_operation"

    asyncio.run(scenario())


def test_package_upgrade_failure_does_not_expose_continue_action() -> None:
    async def fail_upgrade(target, step, *, context):
        raise PackageUpgradeError("系统包下载失败。")

    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="SIM-TERMINAL", package="router.cc")
        engine = WorkflowEngine(workflow, fail_upgrade, target=DeviceTarget("SIM-TERMINAL"))
        engine.start(make_task())
        await engine.execute_step()
        engine.apply_decision(Action("approve", target_step="prepare_upgrade"))
        waiting = await engine.execute_step()
        assert waiting.status == TaskStatus.WAITING_FOR_DECISION.value
        assert engine.pending_decision is not None
        assert "continue" not in {item.name for item in engine.pending_decision.available_actions}
        try:
            engine.apply_decision(Action("continue", target_step="prepare_upgrade"))
        except ValueError as exc:
            assert "not available" in str(exc)
        else:
            raise AssertionError("continue must not bypass package-upgrade failure handling")

    asyncio.run(scenario())


def test_human_cancel_and_service_restart_restore_checkpoint() -> None:
    async def scenario() -> None:
        workflow = device_upgrade_workflow(device_id="d", package="p", options={"activation_policy": "reboot"})
        executor = UpgradeExecutor()
        engine = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        engine.start(make_task())
        await engine.execute_step()
        engine.apply_decision(Action("approve", target_step="prepare_upgrade"))
        await engine.execute_step()
        saved = engine.checkpoint()
        restored = WorkflowEngine(workflow, executor, target=DeviceTarget("d"))
        restored.start(engine.task)
        assert restored.task.checkpoint.revision >= saved.revision
        assert restored.task.workflow.current_step == "reboot"
        assert restored.cancel().status == TaskStatus.CANCELLED.value

    asyncio.run(scenario())
