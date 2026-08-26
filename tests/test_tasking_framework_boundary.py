from __future__ import annotations

import asyncio

import pytest

from device_tui.application.device_control import DeviceTarget
from device_tui.application.errors import ApplicationError
from device_tui.application.events import EventBus
from device_tui.application.tasking import TaskCreate, TaskManager, device_upgrade_workflow
from device_tui.application.workflows import (
    WorkflowRuntime,
    build_default_workflow_registry,
)


class NoopExecution:
    async def execute(self, target, step, *, context):
        del target, step, context
        return {"status": "completed"}


def test_device_upgrade_task_is_started_by_framework_runtime() -> None:
    async def scenario() -> None:
        runtime = WorkflowRuntime()
        manager = TaskManager(
            NoopExecution(),
            EventBus(),
            framework_runtime=runtime,
            framework_workflows=build_default_workflow_registry(),
        )
        record = manager.create(TaskCreate(
            workflow=device_upgrade_workflow(device_id="d1", package="image.cc"),
            target=DeviceTarget(device_id="d1"),
        ))

        run = runtime.runs.get(record.id)
        assert run.workflow_id == "network.package_upgrade"

        await manager.close()

    asyncio.run(scenario())


def test_device_upgrade_task_requires_framework_configuration() -> None:
    manager = TaskManager(NoopExecution(), EventBus())
    with pytest.raises(ApplicationError, match="requires the Workflow Framework"):
        manager.create(TaskCreate(
            workflow=device_upgrade_workflow(device_id="d1", package="image.cc"),
            target=DeviceTarget(device_id="d1"),
        ))
