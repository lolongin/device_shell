from __future__ import annotations

import asyncio

import pytest

from device_tui.application.device_control import DeviceTarget
from device_tui.application.errors import ApplicationError
from device_tui.application.events import EventBus
from device_tui.application.tasking import (
    TaskCreate,
    TaskManager,
    WorkflowTarget,
    build_default_workflow_catalog,
)
from device_tui.application.workflows import WorkflowRuntime, build_default_workflow_registry


class NoopExecution:
    async def execute(self, target, step, *, context):
        del target, step, context
        return {"status": "completed"}


def _upgrade_task():
    workflow = build_default_workflow_catalog().build(
        "device_upgrade",
        WorkflowTarget("d1"),
        {"package_path": "image.cc", "activation_policy": "reboot"},
    )
    return TaskCreate(workflow=workflow, target=DeviceTarget(device_id="d1"))


def test_device_upgrade_task_is_started_by_framework_runtime() -> None:
    async def scenario() -> None:
        runtime = WorkflowRuntime()
        manager = TaskManager(
            NoopExecution(), EventBus(), framework_runtime=runtime,
            framework_workflows=build_default_workflow_registry(),
        )
        record = manager.create(_upgrade_task())

        run = runtime.runs.get(record.id)
        assert run.id == record.id
        assert run.workflow_id == "network.package_upgrade"
        assert record.workflow_id == "device_upgrade"
        assert record.workflow_view["id"] == "network.package_upgrade"
        assert record.checkpoint is not None
        assert [step.step_id for step in record.checkpoint.step_states] == [
            state["id"] for state in record.workflow_view["states"]
        ]

        await manager.close()

    asyncio.run(scenario())


def test_device_upgrade_task_requires_framework_configuration() -> None:
    manager = TaskManager(NoopExecution(), EventBus())
    with pytest.raises(ApplicationError, match="requires the Workflow Framework"):
        manager.create(_upgrade_task())
