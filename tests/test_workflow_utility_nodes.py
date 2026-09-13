from __future__ import annotations

import asyncio

import pytest

from device_tui.application.workflow_studio.expression import evaluate_expression
from device_tui.application.workflow_plugins.utility import (
    ForEachActivityHandler,
    VariableSetActivityHandler,
)
from device_tui.framework import ActivityContext, ActivityInvocation, ActivityStatus, WorkflowRun


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
