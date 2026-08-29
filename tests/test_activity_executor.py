from __future__ import annotations

import asyncio

import pytest

from device_tui.application.workflows import (
    ActivityContext,
    ActivityDefinition,
    ActivityExecutor,
    ActivityInvocation,
    ActivityResult,
    ActivityStatus,
    ActivityVerifier,
    Event,
    VerificationSpec,
    WorkflowRun,
    GuardSpec,
)


class Handler:
    activity_id = "file.transfer"

    async def execute(self, invocation, context, report):
        report(Event(
            type="transfer.completed",
            run_id=invocation.workflow_run_id,
            action_id=invocation.activity_id,
            progress=True,
        ))
        return ActivityResult(
            status=ActivityStatus.SUCCEEDED,
            operation_id="op-1",
            outputs={"path": "/tmp/image.cc"},
        )


class Verifier:
    verifier_id = "file.exists_and_matches"

    async def verify(self, specification, result, context):
        return ActivityResult(
            status=ActivityStatus.SUCCEEDED,
            operation_id=result.operation_id,
            outputs={**result.outputs, "verified": True},
            evidence=({"kind": "file_check"},),
        )


def test_activity_executor_runs_handler_and_post_verification() -> None:
    executor = ActivityExecutor(
        definitions={
            "file.transfer:1": ActivityDefinition(
                id="file.transfer",
                verification=VerificationSpec(
                    id="target",
                    verifier="file.exists_and_matches",
                ),
            ),
        },
        handlers={"file.transfer": Handler()},
        verifiers={"file.exists_and_matches": Verifier()},
    )
    events: list[Event] = []
    invocation = ActivityInvocation("file.transfer", "inv-1", "run-1")
    context = ActivityContext(
        workflow_run=WorkflowRun("run-1", "wf", "1", "device-1"),
        invocation=invocation,
    )

    result = asyncio.run(executor.execute(invocation, context, events.append))

    assert result.status == ActivityStatus.SUCCEEDED
    assert result.outputs["verified"] is True
    assert [event.type for event in events][-1] == "activity.succeeded"


def test_activity_executor_converts_handler_exception_to_failed_result() -> None:
    class Broken:
        activity_id = "script.run"

        async def execute(self, invocation, context, report):
            raise RuntimeError("process crashed")

    executor = ActivityExecutor(
        definitions={"script.run:1": ActivityDefinition(id="script.run")},
        handlers={"script.run": Broken()},
    )
    invocation = ActivityInvocation("script.run", "inv-1", "run-1")
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "device-1"), invocation)

    result = asyncio.run(executor.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.FAILED
    assert result.error["message"] == "process crashed"


def test_activity_executor_runs_preparation_and_rechecks_guard() -> None:
    state = {"view": "operator"}

    class Probe:
        probe_id = "session.view"

        async def probe(self, specification, context):
            return {"value": state["view"]}

    class Prepare:
        activity_id = "session.enter_user_view"

        async def execute(self, invocation, context, report):
            state["view"] = "user"
            return ActivityResult(status=ActivityStatus.SUCCEEDED)

    class Main:
        activity_id = "file.transfer"

        async def execute(self, invocation, context, report):
            return ActivityResult(status=ActivityStatus.SUCCEEDED)

    executor = ActivityExecutor(
        definitions={
            "session.enter_user_view:1": ActivityDefinition(id="session.enter_user_view"),
            "file.transfer:1": ActivityDefinition(
                id="file.transfer",
                preconditions=(GuardSpec(
                    id="required_view",
                    probe="session.view",
                    predicate={"equals": "user"},
                    on_failure="prepare",
                    preparation_activity="session.enter_user_view",
                ),),
            ),
        },
        handlers={"session.enter_user_view": Prepare(), "file.transfer": Main()},
        probes={"session.view": Probe()},
    )
    invocation = ActivityInvocation("file.transfer", "inv-1", "run-1")
    context = ActivityContext(WorkflowRun("run-1", "wf", "1", "d1"), invocation)

    result = asyncio.run(executor.execute(invocation, context, lambda event: event))

    assert result.status == ActivityStatus.SUCCEEDED
    assert state["view"] == "user"
