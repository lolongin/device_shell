from __future__ import annotations

import asyncio

from device_tui.application.device_control import DeviceTarget
from device_tui.application.tasking.execution import DeviceWorkflowExecutionError
from device_tui.application.workflow_plugins import DeviceActivityHandler
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


def test_device_info_activity_exposes_a_structured_software_version():
    backend = FakeExecution({"status": "completed", "output": "SimOS V8.120 build 1", "execution_id": "exec-2"})
    handler = DeviceActivityHandler(backend, "device.info")
    invocation = _invocation("device.info", fields=["software_version"])
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["software_version"] == "8.120"
    assert result.outputs["requested_fields"] == ["software_version"]
    assert backend.calls[0][1].action == "verify_version"


def test_device_info_activity_normalizes_legacy_comma_separated_fields():
    backend = FakeExecution({"status": "completed", "output": "version 8.120"})
    handler = DeviceActivityHandler(backend, "device.info")
    invocation = _invocation("device.info", fields="name, software_version, status")
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.outputs["requested_fields"] == ["name", "software_version", "status"]


def test_device_info_activity_keeps_metadata_fields_stable_for_downstream_nodes():
    backend = FakeExecution({"status": "completed", "output": "SimOS V8.120 build 1"})
    handler = DeviceActivityHandler(backend, "device.info")
    invocation = ActivityInvocation(
        "device.info",
        "inv-4",
        "run-1",
        inputs={"fields": ["name"]},
        context={"device": {"id": "dev-1", "name": "Router A", "model": "SimRouter", "version": "8.120"}},
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.outputs["name"] == "Router A"
    assert result.outputs["model"] == "SimRouter"
    assert result.outputs["software_version"] == "8.120"


def test_device_info_activity_keeps_catalog_fields_resolvable_when_not_requested():
    backend = FakeExecution({"status": "completed", "output": "SimOS V8.120 build 1"})
    handler = DeviceActivityHandler(backend, "device.info")
    invocation = ActivityInvocation(
        "device.info",
        "inv-catalog-fields",
        "run-1",
        inputs={"fields": ["name"]},
        context={
            "device": {
                "id": "dev-1",
                "name": "Router A",
                "model": "SimRouter",
                "version": "8.120",
            }
        },
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.outputs["name"] == "Router A"
    assert result.outputs["model"] == "SimRouter"
    assert result.outputs["version"] == "8.120"
    assert result.outputs["software_version"] == "8.120"
    assert result.outputs["address"] == ""


def test_connection_activity_keeps_execution_catalog_fields_resolvable():
    backend = FakeExecution({
        "status": "completed",
        "device_id": "dev-1",
        "session_id": "sess-1",
        "recovery_protocol": "ssh",
        "probe_execution_id": "probe-1",
        "probe_output": "display version",
    })
    handler = DeviceActivityHandler(backend, "device.wait_online")
    invocation = _invocation(
        "device.wait_online",
        host="10.0.0.8",
        port=2222,
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["output"] == "display version"
    assert result.outputs["execution_id"] == "probe-1"
    assert result.outputs["operation_id"] == "probe-1"
    assert result.outputs["host"] == "10.0.0.8"
    assert result.outputs["port"] == 2222


def test_device_info_activity_projects_safe_device_metadata_from_context():
    backend = FakeExecution({"status": "completed", "output": "SimOS V8.120 build 1"})
    handler = DeviceActivityHandler(backend, "device.info")
    invocation = ActivityInvocation(
        "device.info",
        "inv-3",
        "run-1",
        inputs={"fields": ["name", "address", "model", "software_version", "status"]},
        context={
            "device": {
                "id": "dev-1",
                "name": "Router A",
                "ssh_endpoint": "10.0.0.1:22",
                "telnet_endpoint": "10.0.0.1:23",
                "model": "SimRouter",
                "status": "connected",
                "version": "8.120",
            }
        },
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.outputs["device_id"] == "dev-1"
    assert result.outputs["name"] == "Router A"
    assert result.outputs["address"] == "10.0.0.1:22"
    assert result.outputs["model"] == "SimRouter"
    assert result.outputs["status"] == "connected"
    assert result.outputs["software_version"] == "8.120"


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


def test_device_activity_falls_back_to_workflow_device_id_when_target_context_is_missing():
    backend = FakeExecution({"status": "completed", "output": "version 1"})
    handler = DeviceActivityHandler(backend, "device.verify_version")
    invocation = ActivityInvocation(
        "device.verify_version", "inv-no-target", "run-1", inputs={"expected": "1"}
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-from-run"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert backend.calls[0][0].device_id == "dev-from-run"


def test_device_activity_preserves_custom_endpoint_in_target():
    backend = FakeExecution({"status": "completed", "output": "version 1"})
    handler = DeviceActivityHandler(backend, "device.verify_version")
    invocation = ActivityInvocation(
        "device.verify_version",
        "inv-custom-endpoint",
        "run-1",
        inputs={
            "device_id": "dev-1",
            "protocol": "ssh",
            "host": "10.10.10.20",
            "port": 2222,
            "expected": "1",
        },
    )
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "dev-1"), invocation)

    result = asyncio.run(handler.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert backend.calls[0][0] == DeviceTarget(
        device_id="dev-1",
        protocol="ssh",
        host="10.10.10.20",
        port=2222,
    )


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
