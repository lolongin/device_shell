from __future__ import annotations

import asyncio
import sys

import pytest

from device_tui.application import build_desktop_application
from device_tui.application.tasking import Action, TaskCreate, TaskPlanLifecycle, TaskService, WorkflowDefinition, WorkflowStep
from device_tui.application.device_control import DeviceTarget
from device_tui.framework import TaskPlan, TaskRun, TaskRunStatus, WorkflowNode
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.session_hub import SessionHub


class _Orchestrator:
    def __init__(self) -> None:
        self.started: tuple[TaskPlan, str, dict[str, object] | None, dict[str, object] | None, str | None] | None = None
        self.executed: tuple[str, TaskPlan] | None = None

    def start(self, plan: TaskPlan, *, device_id: str, inputs=None, context=None, task_run_id=None, child_run_id=None) -> TaskRun:
        del child_run_id
        self.started = (plan, device_id, inputs, context, task_run_id)
        return TaskRun("run-1", plan.id, device_id, status=TaskRunStatus.RUNNING)

    async def execute(self, task_run_id: str, plan: TaskPlan) -> TaskRun:
        self.executed = (task_run_id, plan)
        return TaskRun(task_run_id, plan.id, "device-1", status=TaskRunStatus.SUCCEEDED)

    def get(self, task_run_id: str) -> TaskRun:
        return TaskRun(task_run_id, "plan-1", "device-1")

    def list(self, *, limit: int = 500) -> list[TaskRun]:
        return []

    def pause(self, task_run_id: str) -> TaskRun:
        return TaskRun(task_run_id, "plan-1", "device-1", status=TaskRunStatus.WAITING_RECONCILE)

    def resume(self, task_run_id: str, *, context=None) -> TaskRun:
        return TaskRun(task_run_id, "plan-1", "device-1", status=TaskRunStatus.RUNNING)

    def cancel(self, task_run_id: str) -> TaskRun:
        return TaskRun(task_run_id, "plan-1", "device-1", status=TaskRunStatus.CANCELLED)


def _plan() -> TaskPlan:
    return TaskPlan("plan-1", nodes=(WorkflowNode("step", "script.run"),))


def test_task_service_delegates_generic_plan_lifecycle() -> None:
    orchestrator = _Orchestrator()
    service = TaskService(object(), orchestrator)  # type: ignore[arg-type]

    started = service.start_plan(
        _plan(), device_id="device-1", inputs={"x": 1},
        context={"target": {"session_id": "sess-1"}}, task_run_id="run-1",
    )
    executed = asyncio.run(service.execute_plan(started.id, _plan()))

    assert started.id == "run-1"
    assert executed.status == TaskRunStatus.SUCCEEDED
    assert orchestrator.started == (_plan(), "device-1", {"x": 1}, {"target": {"session_id": "sess-1"}}, "run-1")
    assert orchestrator.executed == ("run-1", _plan())


def test_task_service_projects_generic_task_workflow_for_the_desktop() -> None:
    service = TaskService(object(), _Orchestrator())  # type: ignore[arg-type]
    workflow = WorkflowDefinition(
        id="ui-plan",
        name="检查设备",
        steps=(WorkflowStep("command", action=Action("command")),),
    )
    record = service.create(TaskCreate(
        workflow=workflow,
        target=DeviceTarget(device_id="device-1"),
        framework_plan=_plan(),
    ))

    assert record.workflow_view["id"] == "ui-plan"
    assert record.workflow_view["states"] == [{
        "id": "command",
        "label": "command",
        "terminal": True,
        "action_id": "command",
        "operation": "command",
    }]


def test_task_plan_lifecycle_is_structurally_separate_from_legacy_lifecycle() -> None:
    assert isinstance(_Orchestrator(), TaskPlanLifecycle)


def test_task_service_reports_missing_orchestrator() -> None:
    service = TaskService(object())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="generic TaskPlan orchestration is not configured"):
        service.start_plan(_plan(), device_id="device-1")
    with pytest.raises(RuntimeError, match="generic TaskPlan orchestration is not configured"):
        asyncio.run(service.execute_plan("run-1", _plan()))


def test_desktop_composition_binds_task_service_to_orchestrator() -> None:
    application = build_desktop_application(SampleDeviceRepository(), SessionHub())

    assert application.task_service.start_plan(_plan(), device_id="device-1").plan_id == "plan-1"


def test_desktop_task_service_executes_builtin_activity_workflow() -> None:
    application = build_desktop_application(SampleDeviceRepository(), SessionHub())
    plan = TaskPlan(
        "script-plan",
        nodes=(WorkflowNode("script", "script.run", input_mapping={"argv": "${argv}"}),),
    )
    task = application.task_service.start_plan(
        plan,
        device_id="local",
        inputs={"argv": [sys.executable, "-c", "print('task-ok')"]},
    )

    result = asyncio.run(application.task_service.execute_plan(task.id, plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert result.outputs["script"]["run"]["returncode"] == 0
    assert "task-ok" in result.outputs["script"]["run"]["output"]
