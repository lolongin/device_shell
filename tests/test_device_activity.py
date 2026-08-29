from __future__ import annotations

import asyncio

from device_tui.application.device_control import DeviceTarget
from device_tui.application.tasking.execution import DeviceWorkflowExecutionError
from device_tui.application.workflow_plugins import CompatibilityDeviceActivityHandler, DeviceActivityHandler
from device_tui.framework import (
    ActionResult,
    ActionStatus,
    ActivityContext,
    ActivityInvocation,
    ActivityStatus,
    WorkflowRun,
)


class FakeExecution:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []
        self.cancelled = []

    async def execute(self, target, step, *, context):
        self.calls.append((target, step, context))
        if self.error:
            raise self.error
        return dict(self.result or {})

    def cancel_target(self, target: DeviceTarget):
        self.cancelled.append(target)
        return "execution-1"


def _invocation(activity_id: str, **inputs):
    return ActivityInvocation(
        activity_id,
        "inv-1",
        "run-1",
        inputs={"device_id": "dev-1", "session_id": "sess-1", "protocol": "ssh", **inputs},
    )


def test_device_activity_maps_success_and_keeps_vendor_execution_behind_handler():
    backend = FakeExecution({"status": "completed", "output": "version 1", "execution_id": "exec-1", "evidence": ({"kind": "terminal"},)})
    handler = DeviceActivityHandler(backend, "device.verify_version")
    invocation = _invocation("device.verify_version", expected="1")
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)
    events = []

    result = asyncio.run(handler.execute(invocation, context, events.append))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.operation_id == "exec-1"
    assert backend.calls[0][0] == DeviceTarget(device_id="dev-1", session_id="sess-1", protocol="ssh")
    assert backend.calls[0][1].action == "verify_version"
    assert events[0].type == "device.activity.dispatching"


def test_reboot_execution_error_is_unknown_until_reconciled():
    backend = FakeExecution(error=DeviceWorkflowExecutionError("terminal_timeout", "connection lost", error_class="unknown"))
    handler = DeviceActivityHandler(backend, "device.reboot")
    invocation = _invocation("device.reboot")
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.UNKNOWN
    assert result.error["code"] == "terminal_timeout"


def test_device_activity_cancel_targets_the_bound_session():
    backend = FakeExecution({"status": "completed"})
    handler = DeviceActivityHandler(backend, "device.wait_online")
    invocation = _invocation("device.wait_online")
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    asyncio.run(handler.cancel(invocation, context))

    assert backend.cancelled == [DeviceTarget(device_id="dev-1", session_id="sess-1", protocol="ssh")]


def test_device_activity_reads_target_from_invocation_context():
    backend = FakeExecution({"status": "completed", "output": "version 1"})
    handler = DeviceActivityHandler(backend, "device.verify_version")
    invocation = ActivityInvocation(
        "device.verify_version", "inv-2", "run-1", inputs={"expected": "1"},
        context={"target": {"device_id": "dev-2", "session_id": "sess-2", "protocol": "telnet"}},
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-2"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert backend.calls[0][0] == DeviceTarget(device_id="dev-2", session_id="sess-2", protocol="telnet")


def test_device_activity_emits_legacy_reboot_and_readiness_signals_during_migration():
    invocation = _invocation("device.reboot")
    events = []

    DeviceActivityHandler._report_compatibility_events(
        "device.reboot", invocation,
        {"reboot_command_sent": True, "reboot_disconnect_observed": True}, events.append,
    )
    DeviceActivityHandler._report_compatibility_events(
        "device.wait_online", invocation,
        {"cli_status": "ready"}, events.append,
    )
    DeviceActivityHandler._report_compatibility_events(
        "device.verify_version", ActivityInvocation(
            "device.verify_version", "inv-3", "run-1", inputs={"fact": "startup_package"},
        ),
        {"status": "completed"}, events.append,
    )

    assert [event.type for event in events] == [
        "huawei.reboot.started", "huawei.cli.ready", "huawei.startup.package.match",
    ]


def test_compatibility_activity_preserves_vendor_operation_and_workflow_deadline():
    class Legacy:
        def __init__(self) -> None:
            self.action = None

        async def execute(self, action, run, emit):
            del run
            self.action = action
            emit(DeviceActivityHandler._event("huawei.startup.verified", invocation, {}))
            return ActionResult(
                ActionStatus.SUCCEEDED,
                facts={"execution_id": "exec-1", "evidence": [{"kind": "readback"}]},
            )

        async def cancel(self, action, run):
            del action, run

    invocation = _invocation(
        "device.startup.configure",
        package="target.cc",
        activity_timeout_seconds=120,
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)
    legacy = Legacy()
    handler = CompatibilityDeviceActivityHandler(
        legacy,
        "device.startup.configure",
        "huawei.startup.configure",
    )
    events = []

    result = asyncio.run(handler.execute(invocation, context, events.append))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.operation_id == "exec-1"
    assert result.evidence == ({"kind": "readback"},)
    assert legacy.action.operation == "huawei.startup.configure"
    assert legacy.action.timeout_seconds == 120
    assert events[-1].type == "huawei.startup.verified"


def test_compatibility_startup_timeout_is_unknown_until_reconciled():
    class Legacy:
        async def execute(self, action, run, emit):
            del action, run, emit
            raise DeviceWorkflowExecutionError(
                "terminal_timeout",
                "connection lost after startup command",
                error_class="unknown",
            )

        async def cancel(self, action, run):
            del action, run

    invocation = _invocation("device.startup.configure", activity_timeout_seconds=120)
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)
    result = asyncio.run(CompatibilityDeviceActivityHandler(
        Legacy(), "device.startup.configure", "huawei.startup.configure",
    ).execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.UNKNOWN
    assert result.error["code"] == "terminal_timeout"
