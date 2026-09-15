from __future__ import annotations

import asyncio

from device_tui.application.device_control import DeviceTarget, OperationView
from device_tui.framework import ActivityInvocation, Event
from device_tui.application.workflow_plugins import TerminalTransferAdapter
from device_tui.application.workflow_plugins.transfer import TransferActivityHandler
from device_tui.framework import ActivityContext, ActivityStatus, WorkflowRun


class FakeControl:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = list(statuses)
        self.index = 0
        self.cancelled: list[str] = []
        self.request = None

    def transfer(self, target, request, *, context=None):
        self.request = (target, request, context)
        return OperationView(
            operation_id="op-1",
            kind="managed_file_transfer",
            device_id=target.device_id or "device-1",
            session_id=target.session_id,
            status="queued",
            stage="queued",
            message="queued",
        )

    def get_operation(self, operation_id: str) -> OperationView:
        status = self.statuses[min(self.index, len(self.statuses) - 1)]
        self.index += 1
        terminal = status == "completed"
        return OperationView(
            operation_id=operation_id,
            kind="managed_file_transfer",
            device_id="device-1",
            session_id="session-1",
            status=status,
            stage="completed" if terminal else status,
            message=status,
            progress_percent=100 if terminal else 25,
            bytes_transferred=100 if terminal else 25,
            total_bytes=100,
            revision=self.index,
            data={"destination_path": "firmware.bin"},
        )

    def cancel_operation(self, operation_id: str) -> OperationView:
        self.cancelled.append(operation_id)
        return self.get_operation(operation_id)


class ResolvingControl(FakeControl):
    def __init__(self) -> None:
        super().__init__(["completed"])
        self.resolve_calls: list[tuple[DeviceTarget, object]] = []

    async def resolve_or_open_session(self, target, *, context=None):
        self.resolve_calls.append((target, context))
        return DeviceTarget(device_id=target.device_id, session_id="session-1", protocol="simulated")


def invocation(**inputs):
    return ActivityInvocation(
        "file.transfer",
        "inv-1",
        "run-1",
        inputs={
            "device_id": "device-1",
            "session_id": "session-1",
            "direction": "upload",
            "source_path": "firmware.bin",
            "destination_path": "flash:/firmware.bin",
            **inputs,
        },
    )


def test_terminal_adapter_maps_operation_progress_and_verifies_completion():
    control = FakeControl(["queued", "transferring", "completed"])
    adapter = TerminalTransferAdapter(control, poll_interval_seconds=0.001)
    events: list[Event] = []

    async def run():
        handle = await adapter.start(invocation(), events.append)
        observation = await adapter.monitor(handle, invocation(), events.append)
        return await adapter.verify(handle, observation, invocation())

    verified, outputs, evidence = asyncio.run(run())
    assert verified is True
    assert outputs["verified"] is True
    assert evidence[0]["operation_id"] == "op-1"
    assert control.request[0] == DeviceTarget(device_id="device-1", session_id="session-1", protocol="auto")
    assert any(event.type == "transfer.operation.observed" for event in events)


def test_terminal_adapter_preserves_interrupted_as_unknown():
    control = FakeControl(["interrupted"])
    adapter = TerminalTransferAdapter(control, poll_interval_seconds=0.001)

    async def run():
        handle = await adapter.start(invocation(), lambda event: event)
        return await adapter.monitor(handle, invocation(), lambda event: event)

    result = asyncio.run(run())
    assert result.status == "unknown"


def test_terminal_adapter_timeout_is_unknown_and_cancel_is_forwarded():
    control = FakeControl(["transferring"])
    adapter = TerminalTransferAdapter(control, poll_interval_seconds=0.001)
    current = invocation(monitor_timeout_seconds=1)

    async def run():
        handle = await adapter.start(current, lambda event: event)
        await adapter.cancel(handle, current)
        return await adapter.monitor(handle, current, lambda event: event)

    result = asyncio.run(run())
    assert result.status == "unknown"
    assert control.cancelled == ["op-1"]


def test_terminal_adapter_can_open_a_session_for_direct_workflow_transfer():
    control = ResolvingControl()
    adapter = TerminalTransferAdapter(control, poll_interval_seconds=0.001)
    current = ActivityInvocation(
        "file.transfer",
        "inv-1",
        "run-1",
        inputs={
            "direction": "download",
            "source_path": "flash:/firmware.bin",
            "destination_path": "firmware.bin",
        },
        context={"target": {"device_id": "device-1", "protocol": "simulated"}},
    )

    async def run():
        assert await adapter.check_preconditions(current) is True
        return await adapter.start(current, lambda event: event)

    asyncio.run(run())

    assert control.resolve_calls
    assert control.request[0] == DeviceTarget(
        device_id="device-1",
        session_id="session-1",
        protocol="simulated",
    )


def test_transfer_activity_falls_back_to_workflow_device_id_when_target_context_is_missing():
    control = ResolvingControl()
    handler = TransferActivityHandler(TerminalTransferAdapter(control, poll_interval_seconds=0.001))
    current = ActivityInvocation(
        "file.transfer",
        "inv-1",
        "run-1",
        inputs={
            "direction": "upload",
            "source_path": "firmware.bin",
            "destination_path": "flash:/firmware.bin",
        },
    )
    context = ActivityContext(
        WorkflowRun("run-1", "wf", "1", "device-from-run"),
        current,
    )

    result = asyncio.run(handler.execute(current, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert control.request[0].device_id == "device-from-run"


def test_transfer_activity_returns_catalog_fields_on_success():
    control = FakeControl(["completed"])
    handler = TransferActivityHandler(TerminalTransferAdapter(control, poll_interval_seconds=0.001))
    current = invocation()
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), current)

    result = asyncio.run(handler.execute(current, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["operation_id"] == "op-1"
    assert result.outputs["output"] == ""
    assert result.outputs["skipped"] is False
    assert result.outputs["skip_reason"] == ""
    assert result.outputs["verified"] is True
    assert isinstance(result.outputs["evidence"], list)
