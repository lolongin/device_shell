from __future__ import annotations

import asyncio

import pytest

from device_tui.application.workflow_studio.expression import evaluate_expression
from device_tui.application.workflow_plugins.utility import (
    ForEachActivityHandler,
    TerminalWaitActivityHandler,
    UntilActivityHandler,
    VariableSetActivityHandler,
    ExpressionActivityHandler,
    WaitActivityHandler,
    DeviceSelectActivityHandler,
)
from device_tui.framework import ActivityContext, ActivityInvocation, ActivityStatus, WorkflowRun
from device_tui.interfaces.desktop_api.session_hub import TerminalEvent


def test_expression_evaluator_supports_bounded_boolean_expression() -> None:
    assert evaluate_expression("inputs.version < 10 and inputs.ready", {"inputs": {"version": 8, "ready": True}}) is True


def test_expression_evaluator_rejects_function_calls() -> None:
    with pytest.raises(ValueError, match="unsupported expression"):
        evaluate_expression("__import__('os').getcwd()", {})


def test_variable_set_returns_named_value() -> None:
    invocation = ActivityInvocation(
        "variable.set", "inv-1", "run-1", inputs={"name": "package", "value": "target.cc"}
    )
    result = asyncio.run(
        VariableSetActivityHandler().execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
    )
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs == {"name": "package", "value": "target.cc"}


def test_variable_set_can_extract_a_capture_group() -> None:
    invocation = ActivityInvocation(
        "variable.set",
        "inv-1",
        "run-1",
        inputs={
            "name": "cc_path",
            "value": "found flash:/cc",
            "extract": {"pattern": r"flash:/\S+"},
        },
    )
    result = asyncio.run(
        VariableSetActivityHandler().execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
    )
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs == {
        "name": "cc_path",
        "value": "flash:/cc",
        "matched": True,
        "source": "found flash:/cc",
    }


def test_variable_set_reports_no_match_without_failing() -> None:
    invocation = ActivityInvocation(
        "variable.set",
        "inv-1",
        "run-1",
        inputs={"name": "cc_path", "value": "not found", "extract": {"pattern": "flash:/"}},
    )
    result = asyncio.run(
        VariableSetActivityHandler().execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
    )
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["value"] == ""
    assert result.outputs["matched"] is False
    assert result.outputs["source"] == "not found"


def test_variable_set_rejects_invalid_extraction_pattern() -> None:
    invocation = ActivityInvocation(
        "variable.set",
        "inv-1",
        "run-1",
        inputs={"name": "cc_path", "value": "text", "extract": {"pattern": "["}},
    )
    result = asyncio.run(
        VariableSetActivityHandler().execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
    )
    assert result.status == ActivityStatus.FAILED
    assert result.error["code"] == "variable_extract_invalid"


def test_utility_failure_results_keep_a_stable_status_and_output_shape() -> None:
    async def run(handler, invocation):
        return await handler.execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )

    invalid_variable = asyncio.run(run(
        VariableSetActivityHandler(),
        ActivityInvocation("variable.set", "inv-1", "run-1", inputs={"name": "1bad"}),
    ))
    invalid_expression = asyncio.run(run(
        ExpressionActivityHandler(),
        ActivityInvocation("expression.evaluate", "inv-2", "run-1", inputs={"expression": ""}),
    ))
    invalid_wait = asyncio.run(run(
        WaitActivityHandler(),
        ActivityInvocation("utility.wait", "inv-3", "run-1", inputs={"seconds": "soon"}),
    ))
    invalid_device = asyncio.run(run(
        DeviceSelectActivityHandler(),
        ActivityInvocation("device.select", "inv-4", "run-1", inputs={}),
    ))

    assert invalid_variable.outputs == {"name": "", "value": None, "matched": False, "source": None, "status": "failed"}
    assert invalid_expression.outputs == {"value": None, "status": "failed"}
    assert invalid_wait.outputs == {"seconds": 0, "status": "failed"}
    assert invalid_device.outputs == {"device_id": "", "status": "failed"}


def test_for_each_runs_child_action_for_each_item() -> None:
    calls: list[dict[str, object]] = []

    async def child(action_id, inputs, context, report):
        calls.append({"action_id": action_id, **inputs})
        return {"status": "completed", "item": inputs["item"]}

    invocation = ActivityInvocation(
        "loop.for_each",
        "inv-1",
        "run-1",
        inputs={"items": ["a", "b"], "action_id": "result.save", "action_inputs": {"key": "item"}},
    )
    handler = ForEachActivityHandler(child)
    result = asyncio.run(
        handler.execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
    )
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["count"] == 2
    assert [item["item"] for item in calls] == ["a", "b"]


def test_for_each_reports_failed_item_index() -> None:
    async def child(action_id, inputs, context, report):
        if inputs["index"] == 1:
            raise RuntimeError("child failed")
        return {"status": "completed"}

    invocation = ActivityInvocation(
        "loop.for_each", "inv-1", "run-1", inputs={"items": ["a", "b"], "action_id": "result.save"}
    )
    result = asyncio.run(
        ForEachActivityHandler(child).execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
    )
    assert result.status == ActivityStatus.FAILED
    assert result.error["index"] == 1
    assert result.outputs == {"items": ["a", "b"], "results": [{"status": "completed"}], "count": 1, "status": "failed"}


def test_for_each_rejects_missing_local_input_path() -> None:
    async def child(_action_id, _inputs, _context, _report):
        return {"status": "completed"}

    invocation = ActivityInvocation(
        "loop.for_each",
        "inv-1",
        "run-1",
        inputs={
            "items": [{"name": "router-1"}],
            "action_id": "result.save",
            "action_inputs": {"key": "${item.missing}"},
        },
    )

    result = asyncio.run(
        ForEachActivityHandler(child).execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
    )

    assert result.status == ActivityStatus.FAILED
    assert result.error["code"] == "loop_child_input_invalid"
    assert result.error["index"] == 0
    assert result.outputs == {"items": [{"name": "router-1"}], "results": [], "count": 0, "status": "failed"}


def test_terminal_wait_activity_matches_output_after_current_sequence() -> None:
    class Hub:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.unsubscribed = False
            self.current = 4

        def get(self, _session_id):
            return type("Managed", (), {"sequence": self.current})()

        def subscribe(self, _session_id, *, after_sequence=0):
            assert after_sequence == 4
            return self.queue, []

        def unsubscribe(self, _session_id, _queue):
            self.unsubscribed = True

    async def run():
        hub = Hub()
        await hub.queue.put(TerminalEvent("terminal.output", "s1", 5, data="Pass"))
        await hub.queue.put(TerminalEvent("terminal.output", "s1", 6, data="word:"))
        invocation = ActivityInvocation("terminal.wait", "inv-1", "run-1", inputs={"pattern": "Password:", "timeout_seconds": 1}, context={"target": {"session_id": "s1"}})
        return hub, await TerminalWaitActivityHandler(hub).execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )

    hub, result = asyncio.run(run())
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["matched"] is True
    assert result.outputs["sequence"] == 6
    assert hub.unsubscribed is True


def test_terminal_wait_can_send_enter_before_waiting_for_prompt() -> None:
    class Hub:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.sent: list[tuple[str, str, str]] = []

        def get(self, _session_id):
            return type("Managed", (), {"sequence": 4})()

        async def write(self, session_id, data, *, origin="user"):
            self.sent.append((session_id, data, origin))
            await self.queue.put(TerminalEvent("terminal.output", session_id, 5, data="<Huawei> "))

        def subscribe(self, _session_id, *, after_sequence=0):
            assert after_sequence == 4
            return self.queue, []

        def unsubscribe(self, _session_id, _queue):
            pass

    async def run():
        hub = Hub()
        invocation = ActivityInvocation(
            "terminal.wait", "inv-1", "run-1",
            inputs={"pattern": "Huawei", "send_enter": True, "timeout_seconds": 1},
            context={"target": {"session_id": "s1"}},
        )
        result = await TerminalWaitActivityHandler(hub).execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
        return hub, result

    hub, result = asyncio.run(run())
    assert result.status == ActivityStatus.SUCCEEDED
    assert hub.sent == [("s1", "\r", "workflow")]


def test_terminal_wait_resolves_connected_session_from_device_target() -> None:
    class Hub:
        def __init__(self):
            self.queue = asyncio.Queue()

        def list_sessions(self):
            return [type("Session", (), {"id": "s1", "device_id": "router-1", "status": "connected"})()]

        def get(self, session_id):
            assert session_id == "s1"
            return type("Managed", (), {"sequence": 4})()

        def subscribe(self, session_id, *, after_sequence=0):
            assert session_id == "s1"
            assert after_sequence == 4
            return self.queue, [TerminalEvent("terminal.output", session_id, 5, data="<Huawei> ")]

        def unsubscribe(self, _session_id, _queue):
            pass

    invocation = ActivityInvocation(
        "terminal.wait", "inv-1", "run-1",
        inputs={"pattern": "Huawei", "send_enter": False, "timeout_seconds": 1},
        context={"target": {"device_id": "router-1"}},
    )
    result = asyncio.run(TerminalWaitActivityHandler(Hub()).execute(
        invocation,
        ActivityContext(WorkflowRun("run-1", "wf", "1", "router-1"), invocation),
        lambda _event: None,
    ))
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["session_id"] == "s1"


def test_terminal_wait_resolves_connected_session_from_workflow_device_id() -> None:
    class Hub:
        def __init__(self):
            self.queue = asyncio.Queue()

        def list_sessions(self):
            return [type("Session", (), {"id": "s2", "device_id": "router-2", "status": "connected"})()]

        def get(self, session_id):
            assert session_id == "s2"
            return type("Managed", (), {"sequence": 4})()

        def subscribe(self, session_id, *, after_sequence=0):
            assert session_id == "s2"
            assert after_sequence == 4
            return self.queue, [TerminalEvent("terminal.output", session_id, 5, data="<Huawei> ")]

        def unsubscribe(self, _session_id, _queue):
            pass

    invocation = ActivityInvocation(
        "terminal.wait", "inv-1", "run-1",
        inputs={"pattern": "Huawei", "send_enter": False, "timeout_seconds": 1},
    )
    result = asyncio.run(TerminalWaitActivityHandler(Hub()).execute(
        invocation,
        ActivityContext(WorkflowRun("run-1", "wf", "1", "router-2"), invocation),
        lambda _event: None,
    ))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["session_id"] == "s2"


def test_terminal_wait_activity_times_out_deterministically() -> None:
    class Hub:
        def subscribe(self, _session_id, *, after_sequence=0):
            return asyncio.Queue(), []

        def unsubscribe(self, _session_id, _queue):
            pass

    invocation = ActivityInvocation("terminal.wait", "inv-1", "run-1", inputs={"pattern": "ready", "timeout_seconds": 0.01}, context={"target": {"session_id": "s1"}})
    result = asyncio.run(TerminalWaitActivityHandler(Hub()).execute(invocation, ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation), lambda _event: None))
    assert result.status == ActivityStatus.FAILED
    assert result.error["code"] == "terminal_wait_timeout"
    assert result.outputs == {"status": "timeout", "matched": False, "output": "", "sequence": 0, "session_id": "s1"}


def test_until_activity_stops_when_condition_matches() -> None:
    calls = 0

    async def child(_action_id, _inputs, _context, _report):
        nonlocal calls
        calls += 1
        return {"status": "succeeded" if calls == 2 else "running", "attempt": calls}

    invocation = ActivityInvocation("loop.until", "inv-1", "run-1", inputs={"action_id": "device.info", "condition": "result.status == 'succeeded'", "max_iterations": 4, "interval_seconds": 0})
    result = asyncio.run(UntilActivityHandler(child).execute(invocation, ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation), lambda _event: None))
    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["iterations"] == 2


def test_until_activity_runs_until_max_iterations_when_condition_is_false() -> None:
    calls: list[int] = []

    async def child_runner(action_id, inputs, context, report):
        calls.append(len(calls) + 1)
        return {"status": "succeeded", "output": str(len(calls))}

    invocation = ActivityInvocation(
        "loop.until",
        "inv-1",
        "run-1",
        inputs={
            "action_id": "device.command",
            "condition": "False",
            "max_iterations": 20,
            "interval_seconds": 0,
        },
    )
    context = ActivityContext(
        WorkflowRun("run-1", "wf", "1", "device-1"), invocation
    )

    result = asyncio.run(
        UntilActivityHandler(child_runner).execute(
            invocation, context, lambda _event: None
        )
    )

    assert len(calls) == 20
    assert result.outputs["iterations"] == 20
    assert result.outputs["matched"] is False


def test_until_activity_resolves_iteration_local_action_inputs() -> None:
    calls: list[dict[str, object]] = []

    async def child(_action_id, inputs, _context, _report):
        calls.append(dict(inputs))
        return {"status": "succeeded", "attempt": inputs["attempt"]}

    invocation = ActivityInvocation(
        "loop.until",
        "inv-1",
        "run-1",
        inputs={
            "action_id": "device.info",
            "condition": "iteration == 1",
            "max_iterations": 2,
            "interval_seconds": 0,
            "action_inputs": {"attempt": "${iteration}"},
        },
    )
    result = asyncio.run(
        UntilActivityHandler(child).execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
    )

    assert result.status == ActivityStatus.SUCCEEDED
    assert calls == [{"attempt": 1}]


def test_until_rejects_missing_previous_result_path() -> None:
    async def child(_action_id, _inputs, _context, _report):
        return {"status": "running"}

    invocation = ActivityInvocation(
        "loop.until",
        "inv-1",
        "run-1",
        inputs={
            "action_id": "device.info",
            "condition": "iteration == 1",
            "max_iterations": 2,
            "interval_seconds": 0,
            "action_inputs": {"value": "${result.missing}"},
        },
    )

    result = asyncio.run(
        UntilActivityHandler(child).execute(
            invocation,
            ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation),
            lambda _event: None,
        )
    )

    assert result.status == ActivityStatus.FAILED
    assert result.error["code"] == "loop_until_input_invalid"
    assert result.error["iteration"] == 1
