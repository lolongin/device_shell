from __future__ import annotations

import asyncio

from device_tui.application.device_control import DeviceTarget, OperationView
from device_tui.application.workflows import ActivityInvocation, Event
from device_tui.application.workflow_plugins import TerminalTransferAdapter


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
