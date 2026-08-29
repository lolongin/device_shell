from __future__ import annotations

import asyncio
import sys

from device_tui.application.device_control import OperationView
from device_tui.application.composition.workflows import build_default_activity_executor
from device_tui.framework import (
    ActionRegistry,
    ActionSpec,
    ActivityContext,
    ActivityActionHandler,
    ActivityInvocation,
    ActivityStatus,
    StateNode,
    WorkflowDefinition,
    WorkflowRun,
    WorkflowRuntime,
)


class _TransferControl:
    def __init__(self) -> None:
        self.revision = 0

    def transfer(self, target, request, *, context=None):
        return OperationView(
            operation_id="op-1", kind="managed_file_transfer", device_id=target.device_id,
            session_id=target.session_id, status="queued", stage="queued", message="queued", revision=0,
        )

    def get_operation(self, operation_id: str) -> OperationView:
        self.revision += 1
        return OperationView(
            operation_id=operation_id, kind="managed_file_transfer", device_id="dev-1",
            session_id="sess-1", status="completed", stage="completed", message="completed", revision=self.revision,
            progress_percent=100, bytes_transferred=10, total_bytes=10,
        )

    def cancel_operation(self, operation_id: str) -> OperationView:
        return self.get_operation(operation_id)


def test_activity_handler_runs_through_workflow_runtime() -> None:
    activities = build_default_activity_executor()
    actions = ActionRegistry()
    actions.register(ActivityActionHandler(activities, "script.run"), item_id="script.run")
    runtime = WorkflowRuntime(actions=actions)
    definition = WorkflowDefinition(
        id="script-workflow",
        version="1",
        start_state="run",
        states=(
            StateNode(
                "run",
                ActionSpec(
                    "run", "script.run",
                    params={"argv": [sys.executable, "-c", "print('runtime-ok')"]},
                ),
                next_state="done",
            ),
            StateNode("done", terminal=True),
        ),
    )
    run = runtime.start(definition, device_id="local")

    result = asyncio.run(runtime.run_until_blocked(run.id))

    assert str(result.status) == "succeeded"
    assert result.outputs["run"]["returncode"] == 0
    assert "runtime-ok" in result.outputs["run"]["output"]


def test_default_transfer_registration_wraps_adapter_in_activity_handler() -> None:
    activities = build_default_activity_executor(_TransferControl())
    invocation = ActivityInvocation(
        "file.transfer", "inv-1", "run-1",
        inputs={
            "device_id": "dev-1", "session_id": "sess-1", "direction": "upload",
            "source_path": "firmware.bin", "destination_path": "flash:/firmware.bin",
        },
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)
    events = []

    result = asyncio.run(activities.execute(invocation, context, events.append))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["verified"] is True
    assert any(event.type == "transfer.completed" for event in events)
