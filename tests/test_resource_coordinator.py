from __future__ import annotations

import asyncio

import pytest

from device_tui.application.device_control.lease import DeviceLeaseService
from device_tui.application.errors import ApplicationConflictError
from device_tui.framework import (
    ActionRegistry,
    ActionResult,
    ActionSpec,
    ActionStatus,
    LeaseResourceCoordinator,
    ResourceRequest,
    StateNode,
    TaskOrchestrator,
    TaskPlan,
    TaskRunStatus,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowRuntime,
)


def test_resource_coordinator_is_reentrant_and_releases_backend_after_last_reference() -> None:
    backend = DeviceLeaseService(ttl_seconds=60)
    coordinator = LeaseResourceCoordinator(device_leases=backend)
    first = coordinator.acquire(ResourceRequest("device", "d1", "task-1"))
    second = coordinator.acquire(ResourceRequest("device", "d1", "task-1"))

    assert first.token == second.token
    assert coordinator.release(first) is True
    assert backend.get("d1") is not None
    assert coordinator.release(second) is True
    assert backend.get("d1") is None


def test_resource_coordinator_rejects_conflicting_owner() -> None:
    coordinator = LeaseResourceCoordinator()
    coordinator.acquire(ResourceRequest("session", "s1", "task-1"))

    with pytest.raises(ApplicationConflictError):
        coordinator.acquire(ResourceRequest("session", "s1", "task-2"))


class _Handler:
    async def execute(self, action, run, emit):
        return ActionResult(ActionStatus.SUCCEEDED, facts={"ok": True})


class _Builder:
    def build(self, workflow_id, inputs):
        return WorkflowDefinition(
            id=workflow_id,
            version="1",
            start_state="run",
            states=(
                StateNode("run", ActionSpec("run", "test.action"), next_state="done"),
                StateNode("done", terminal=True),
            ),
        )


def test_task_and_child_workflow_share_device_lease_until_task_completes() -> None:
    backend = DeviceLeaseService(ttl_seconds=60)
    coordinator = LeaseResourceCoordinator(device_leases=backend)
    actions = ActionRegistry()
    actions.register(_Handler(), item_id="test.action")
    runtime = WorkflowRuntime(actions=actions, resource_coordinator=coordinator)
    orchestrator = TaskOrchestrator(
        runtime,
        _Builder(),
        resource_coordinator=coordinator,
    )
    plan = TaskPlan("plan-1", nodes=(WorkflowNode("step", "wf"),))

    task = orchestrator.start(plan, device_id="d1")
    assert backend.get("d1") is not None

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status == TaskRunStatus.SUCCEEDED
    assert backend.get("d1") is None
