from __future__ import annotations

import asyncio

from device_tui.application.workflow_plugins.transfer import (
    TransferActivityHandler,
    TransferHandle,
    TransferObservation,
)
from device_tui.framework import ActivityContext, ActivityInvocation, ActivityStatus, Event, WorkflowRun


class FakeTransfer:
    def __init__(self, *, preconditions=True, verify=True, status="completed"):
        self.preconditions = preconditions
        self.verify_ok = verify
        self.status = status
        self.prepared = False
        self.cancelled = False

    async def check_preconditions(self, invocation):
        return self.preconditions

    async def prepare(self, invocation, report):
        self.prepared = True

    async def start(self, invocation, report):
        return TransferHandle("transfer-1")

    async def monitor(self, handle, invocation, report):
        report(Event(type="transfer.progress", run_id=invocation.workflow_run_id, action_id=invocation.activity_id, progress=True, payload={"percent": 50}))
        return TransferObservation(self.status, {"bytes": 100}, ({"kind": "monitor"},))

    async def verify(self, handle, observation, invocation):
        return self.verify_ok, {"verified": self.verify_ok}, ({"kind": "target-check"},)

    async def cancel(self, handle, invocation):
        self.cancelled = True


def _execute(adapter):
    handler = TransferActivityHandler(adapter)
    invocation = ActivityInvocation("file.transfer", "inv-1", "run-1")
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "d1"), invocation)
    events: list[Event] = []
    result = asyncio.run(handler.execute(invocation, context, events.append))
    return result, events


def test_transfer_activity_models_precondition_monitor_and_verification():
    adapter = FakeTransfer()
    result, events = _execute(adapter)

    assert result.status == ActivityStatus.SUCCEEDED
    assert adapter.prepared is True
    assert result.outputs["verified"] is True
    assert [event.type for event in events] == [
        "transfer.precondition.checked",
        "transfer.prepared",
        "transfer.started",
        "transfer.progress",
        "transfer.completed",
        "transfer.verification.passed",
    ]


def test_transfer_activity_does_not_treat_unknown_observation_as_failure():
    result, _ = _execute(FakeTransfer(status="unknown"))

    assert result.status == ActivityStatus.UNKNOWN
    assert result.error["code"] == "transfer_observation_unknown"


def test_transfer_activity_requires_verification_success():
    result, _ = _execute(FakeTransfer(verify=False))

    assert result.status == ActivityStatus.FAILED
    assert result.error["code"] == "transfer_verification_failed"


def test_transfer_activity_stops_before_dispatch_when_precondition_fails():
    adapter = FakeTransfer(preconditions=False)
    result, events = _execute(adapter)

    assert result.status == ActivityStatus.FAILED
    assert result.error["code"] == "transfer_precondition_failed"
    assert adapter.prepared is False
    assert events == []


def test_transfer_activity_can_skip_when_a_prior_probe_proves_destination_exists():
    class SkipAdapter(FakeTransfer):
        async def should_skip(self, invocation):
            return True

    adapter = SkipAdapter()
    handler = TransferActivityHandler(adapter)
    invocation = ActivityInvocation(
        "file.transfer", "inv-1", "run-1",
        context={"action.precheck.facts": {"package": {"present": True}}},
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "d1"), invocation)
    events: list[Event] = []

    result = asyncio.run(handler.execute(invocation, context, events.append))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["skipped"] is True
    assert "transfer.operation.queued" not in [event.type for event in events]
    assert "transfer.completed" in [event.type for event in events]
    assert adapter.prepared is False
