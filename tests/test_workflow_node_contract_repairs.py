from __future__ import annotations

import asyncio

import pytest

from device_tui.application.workflow_plugins.device_activity import DeviceActivityHandler
from device_tui.application.workflow_plugins.utility import DeviceForEachActivityHandler, VariableSetActivityHandler
from device_tui.application.workflow_plugins.utility import ResultSaveActivityHandler, TerminalWaitActivityHandler
from device_tui.application.workflow_plugins.process import ProcessActivityHandler
from device_tui.application.workflow_plugins.shell import ShellCommandActivityHandler
from device_tui.application.workflow_studio import (
    WorkflowDraft, WorkflowNode, WorkflowEdge, WorkflowInput, build_action_catalog, validate_workflow,
)
from device_tui.framework import ActivityContext, ActivityInvocation, ActivityStatus, WorkflowRun
from device_tui.framework.orchestrator import TaskOrchestrator


def run_activity(handler, inputs, context=None):
    invocation = ActivityInvocation(handler.activity_id, "inv", "run", inputs=inputs, context=context or {})
    return asyncio.run(handler.execute(
        invocation, ActivityContext(WorkflowRun("run", "wf", "1", "d1"), invocation), lambda event: None,
    ))


@pytest.mark.parametrize("device_status", ["online", "offline", "connected"])
def test_device_info_inventory_status_does_not_fail_successful_query(device_status):
    class Execution:
        async def execute_operation(self, target, action, params, *, context):
            return {"status": "completed", "output": "Version 8.120"}

    result = run_activity(DeviceActivityHandler(Execution(), "device.info"), {}, {
        "device": {"id": "d1", "status": device_status},
    })
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["status"] == "completed"
    assert result.outputs["device_status"] == device_status


def test_loop_array_reference_validates_and_resolves():
    workflow = WorkflowDraft("w", "loop", nodes=(
        WorkflowNode("loop", "loop.for_each", {
            "items": ["a"], "action_id": "variable.set", "action_inputs": {"name": "x", "value": "${item}"},
        }),
        WorkflowNode("save", "result.save", {"value": "${loop.results.0.value}"}),
    ), edges=(WorkflowEdge("loop", "save"),))
    assert not validate_workflow(workflow, build_action_catalog()).errors
    assert TaskOrchestrator._resolve_inputs(
        {"value": "${loop.results.0.value}"}, {"loop": {"results": [{"value": "a"}]}},
    ) == {"value": "a"}


def test_variable_assignment_has_all_declared_outputs():
    result = run_activity(VariableSetActivityHandler(), {"name": "x", "value": 1})
    assert result.outputs["matched"] is False
    assert result.outputs["source"] is None


@pytest.mark.parametrize("action,config", [
    ("device.command", {"command": "show", "timeout_seconds": "${inputs.number}"}),
    ("script.run", {"script": "pass", "timeout_seconds": "${inputs.number}"}),
    ("terminal.wait", {"pattern": "ready", "timeout_seconds": "${inputs.number}"}),
    ("loop.until", {"action_id": "result.save", "condition": "False", "interval_seconds": "${inputs.number}"}),
])
def test_runtime_number_references_are_accepted(action, config):
    workflow = WorkflowDraft("w", "typed", inputs=(WorkflowInput("number", "number"),),
                             nodes=(WorkflowNode("node", action, config),))
    assert not validate_workflow(workflow, build_action_catalog()).errors


def test_device_loop_honors_concurrency_and_preserves_order():
    async def run():
        active = maximum = 0
        async def child(action, inputs, context, report):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"status": "succeeded", "output": inputs["device_id"]}
        invocation = ActivityInvocation("device.for_each", "inv", "run", inputs={
            "devices": ["d1", "d2", "d3"], "action_id": "result.save", "concurrency": 2,
        })
        result = await DeviceForEachActivityHandler(child).execute(
            invocation, ActivityContext(WorkflowRun("run", "wf", "1", "d1"), invocation), lambda event: None,
        )
        assert maximum == 2
        assert [row["device_id"] for row in result.outputs["results"]] == ["d1", "d2", "d3"]
        assert result.outputs["succeeded"] == 3
    asyncio.run(run())


@pytest.mark.parametrize("strategy,expected_count", [("stop", 1), ("continue", 3)])
def test_device_loop_counts_returned_failure_and_honors_stop(strategy, expected_count):
    async def child(action, inputs, context, report):
        return {"status": "failed", "error": {"message": "failed"}}
    result = run_activity(DeviceForEachActivityHandler(child), {
        "devices": ["d1", "d2", "d3"], "action_id": "result.save", "failure_strategy": strategy,
    })
    assert result.outputs["count"] == expected_count
    assert result.outputs["failed"] == expected_count
    assert result.outputs["succeeded"] == 0
    assert result.status == (ActivityStatus.FAILED if strategy == "stop" else ActivityStatus.SUCCEEDED)


def test_duplicate_devices_are_serialized_and_parallel_stop_drains_in_flight():
    async def run():
        active = set()
        started = []
        async def child(action, inputs, context, report):
            device = inputs["device_id"]
            assert device not in active
            active.add(device)
            started.append(device)
            await asyncio.sleep(0.01)
            active.remove(device)
            if device == "fail":
                raise RuntimeError("offline")
            return {"status": "succeeded"}
        handler = DeviceForEachActivityHandler(child)
        invocation = ActivityInvocation(handler.activity_id, "inv", "run", inputs={
            "devices": ["d1", "d1", "fail", "d3", "d4"], "action_id": "result.save",
            "concurrency": 2, "failure_strategy": "stop",
        })
        result = await handler.execute(invocation, ActivityContext(WorkflowRun("run", "wf", "1", "d1"), invocation), lambda event: None)
        assert result.status == ActivityStatus.FAILED
        assert result.outputs["failed"] == 1
        assert not active
        assert "d4" not in started
    asyncio.run(run())


def test_saved_result_default_key_is_stable_across_invocations():
    first = run_activity(ResultSaveActivityHandler(), {"value": 1}, {"step_id": "save_version"})
    second = run_activity(ResultSaveActivityHandler(), {"value": 2}, {"step_id": "save_version"})
    assert first.outputs["key"] == second.outputs["key"] == "save_version"


def test_terminal_wait_is_passive_by_default_and_accepts_explicit_session():
    from device_tui.interfaces.desktop_api.session_hub import TerminalEvent
    class Hub:
        def write(self, *args, **kwargs):
            pytest.fail("passive wait wrote to the terminal")
        def subscribe(self, session_id, *, after_sequence=0):
            assert session_id == "chosen"
            return asyncio.Queue(), [TerminalEvent("terminal.output", session_id, 1, data="ready")]
        def unsubscribe(self, session_id, queue):
            pass
    result = run_activity(TerminalWaitActivityHandler(Hub()), {
        "session_id": "chosen", "pattern": "ready", "timeout_seconds": 0.1,
    }, {"target": {"session_id": "other"}})
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["session_id"] == "chosen"


@pytest.mark.parametrize("stdout,parsed,value", [('null\n', True, None), ('log\n{"version": 1}\n', True, {"version": 1}), ('log\n', False, None)])
def test_script_reports_whether_result_is_json_and_honors_unlimited_timeout(stdout, parsed, value):
    from device_tui.infrastructure.processes.local import ProcessExecutionResult
    class Adapter:
        async def run(self, invocation_id, argv, **kwargs):
            assert kwargs["timeout_seconds"] is None
            return ProcessExecutionResult("succeeded", 0, stdout, stdout, "")
    result = run_activity(ProcessActivityHandler("script.run", Adapter()), {"argv": ["python"], "timeout_seconds": 0})
    assert result.outputs["result_parsed"] is parsed
    assert result.outputs["result"] == value


def test_shell_command_zero_timeout_means_no_deadline():
    # A shell command that completes immediately is enough to verify that the
    # zero value is accepted by the handler rather than rejected as invalid.
    result = run_activity(ShellCommandActivityHandler(), {"command": "echo ok", "execution_mode": "shell", "timeout_seconds": 0})
    assert result.status == ActivityStatus.SUCCEEDED


def test_structured_script_result_reference_validates():
    workflow = WorkflowDraft("w", "script", nodes=(
        WorkflowNode("script", "script.run", {"script": "pass"}),
        WorkflowNode("save", "result.save", {"value": "${script.result.version}"}),
    ), edges=(WorkflowEdge("script", "save"),))
    assert not validate_workflow(workflow, build_action_catalog()).errors


def test_unknown_loop_child_field_still_rejected():
    workflow = WorkflowDraft("w", "loop", nodes=(
        WorkflowNode("loop", "loop.for_each", {"items": [1], "action_id": "variable.set"}),
        WorkflowNode("save", "result.save", {"value": "${loop.results.0.missing}"}),
    ), edges=(WorkflowEdge("loop", "save"),))
    assert any(error.code == "invalid_variable_field" for error in validate_workflow(workflow, build_action_catalog()).errors)


def test_until_regex_stops_on_pattern_match():
    from device_tui.application.workflow_plugins.utility import UntilActivityHandler
    async def child(action, inputs, context, report):
        return {"status": "succeeded", "output": "version 8.120"}
    result = run_activity(UntilActivityHandler(child), {
        "action_id": "device.info", "condition": r'regex_match("version 8[.]\\d+", result.output)',
        "max_iterations": 2, "interval_seconds": 0,
    })
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["matched"] is True
    assert result.outputs["iterations"] == 1


def test_until_failure_condition_observes_real_child_exception():
    from device_tui.application.workflow_plugins.utility import UntilActivityHandler
    async def child(action, inputs, context, report):
        raise RuntimeError("device offline")
    result = run_activity(UntilActivityHandler(child), {
        "action_id": "device.info", "condition": "result.status == 'failed'",
        "max_iterations": 2, "interval_seconds": 0,
    })
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["result"]["error"]["message"] == "device offline"


def test_device_loop_reports_invalid_device_without_aborting_other_devices():
    async def child(action, inputs, context, report):
        return {"status": "succeeded"}
    result = run_activity(DeviceForEachActivityHandler(child), {
        "devices": [42, "d1"], "action_id": "result.save", "concurrency": 2,
    })
    assert result.outputs["failed"] == result.outputs["succeeded"] == 1
