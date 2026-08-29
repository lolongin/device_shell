from __future__ import annotations

import asyncio

import pytest

from device_tui.application.device_control import DeviceTarget
from device_tui.application.errors import ApplicationError
from device_tui.application.events import EventBus
from device_tui.application.tasking import (
    MemoryTaskStore,
    TaskCreate,
    TaskManager,
    TaskRecord,
    WorkflowTarget,
    build_default_workflow_catalog,
)
from device_tui.application.workflows import TaskOrchestrator, WorkflowRuntime, build_default_workflow_registry


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


def test_orchestrated_framework_lifecycle_projects_pause_and_cancel_before_child_start() -> None:
    async def scenario() -> None:
        runtime = WorkflowRuntime()
        orchestrator = TaskOrchestrator(runtime, build_default_workflow_registry())
        manager = TaskManager(
            NoopExecution(), EventBus(), framework_runtime=runtime,
            framework_workflows=build_default_workflow_registry(),
            task_orchestrator=orchestrator,
        )
        record = manager.create(_upgrade_task())

        paused = manager.pause(record.id)
        assert paused.status == "paused"
        assert orchestrator.get(record.id).status == "waiting_reconcile"

        cancelled = manager.cancel(record.id)
        assert cancelled.status == "cancelled"
        assert orchestrator.get(record.id).status == "cancelled"

        await manager.close()

    asyncio.run(scenario())


def test_framework_task_restore_requires_reconcile_before_resume() -> None:
    async def scenario() -> None:
        store = MemoryTaskStore()
        runtime = WorkflowRuntime()
        request = _upgrade_task()
        framework = build_default_workflow_registry().build(
            "network.package_upgrade",
            dict(request.workflow.metadata["framework_inputs"]),
        )
        runtime.start(framework, device_id="d1", run_id="task-restarted", context={"target": {"device_id": "d1"}})
        store.upsert_task(
            TaskRecord(
                id="task-restarted",
                status="running",
                workflow_id="device_upgrade",
                device_id="d1",
            ),
            request,
        )

        manager = TaskManager(
            NoopExecution(),
            EventBus(),
            store=store,
            framework_runtime=runtime,
            framework_workflows=build_default_workflow_registry(),
        )

        assert manager.get("task-restarted").status == "paused"
        assert runtime.runs.get("task-restarted").status == "paused"
        resumed = manager.resume("task-restarted")
        assert resumed.status == "running"
        assert runtime.runs.get("task-restarted").status == "recovering"

        await manager.close()

    asyncio.run(scenario())
