from __future__ import annotations

import asyncio

from device_tui.application.composition.workflows import build_default_activity_workflow_providers
from device_tui.application.workflow_studio import build_action_catalog
from device_tui.application.workflow_plugins.utility import (
    ResultSaveActivityHandler,
    VariableSetActivityHandler,
    WorkflowOutputsActivityHandler,
)
from device_tui.application.workflow_plugins.shell import ShellCommandActivityHandler
from device_tui.application.workflow_studio.models import (
    WorkflowEdge,
    WorkflowInput,
    WorkflowNode as StudioNode,
    WorkflowOutput,
    WorkflowVersion,
)
from device_tui.framework import (
    ActionRegistry,
    ActivityActionHandler,
    ActivityDefinition,
    ActivityExecutor,
    ActivityResult,
    ActivityStatus,
    ActionSpec,
    StateNode,
    TaskOrchestrator,
    WorkflowDefinition,
    WorkflowNode,
    WorkflowRegistry,
    WorkflowRuntime,
    WorkflowRun,
)
from device_tui.interfaces.desktop_api.routers.workflow_definitions import (
    _ACTION_WORKFLOW_IDS,
    _compile_task_plan,
    _expand_subworkflows,
)


class _ActivityBuilder:
    def build(self, workflow_id: str, inputs: dict[str, object]) -> WorkflowDefinition:
        return WorkflowDefinition(
            id=workflow_id,
            version="1",
            start_state="run",
            states=(
                StateNode(
                    "run",
                    ActionSpec("run", workflow_id, params=dict(inputs)),
                    next_state="done",
                ),
                StateNode("done", terminal=True),
            ),
        )


class _CommandActivity:
    activity_id = "terminal.command"

    async def execute(self, invocation, context, report) -> ActivityResult:
        del context, report
        return ActivityResult(
            ActivityStatus.SUCCEEDED,
            outputs={
                "output": f"result for {invocation.inputs['command']}",
                "status": "completed",
            },
        )

    async def cancel(self, invocation, context) -> None:
        del invocation, context


def _build_activity_orchestrator(command_handler: object | None = None) -> TaskOrchestrator:
    executor = ActivityExecutor()
    for activity_id in (
        "terminal.command",
        "shell.command",
        "variable.set",
        "result.save",
        "workflow.outputs",
        "loop.for_each",
        "loop.until",
    ):
        executor.register_definition(ActivityDefinition(id=activity_id))
    executor.register_handler(command_handler or _CommandActivity())
    executor.register_handler(ShellCommandActivityHandler())
    executor.register_handler(VariableSetActivityHandler())
    executor.register_handler(ResultSaveActivityHandler())
    executor.register_handler(WorkflowOutputsActivityHandler())

    async def run_child(action_id, inputs, parent_context, report):
        from device_tui.framework import ActivityContext, ActivityInvocation

        invocation = ActivityInvocation(
            activity_id=str(action_id),
            invocation_id=f"child:{action_id}",
            workflow_run_id=parent_context.workflow_run.id,
            inputs=dict(inputs),
            context=dict(parent_context.invocation.context),
        )
        result = await executor.execute(
            invocation,
            ActivityContext(parent_context.workflow_run, invocation),
            report,
        )
        if result.status != ActivityStatus.SUCCEEDED:
            raise RuntimeError((result.error or {}).get("message", "child failed"))
        return {**result.outputs, "status": str(result.status)}

    from device_tui.application.workflow_plugins.utility import ForEachActivityHandler, UntilActivityHandler

    executor.register_handler(ForEachActivityHandler(run_child))
    executor.register_handler(UntilActivityHandler(run_child))

    actions = ActionRegistry()
    for activity_id in (
        "terminal.command",
        "shell.command",
        "variable.set",
        "result.save",
        "workflow.outputs",
        "loop.for_each",
        "loop.until",
    ):
        actions.register(ActivityActionHandler(executor, activity_id), item_id=activity_id)
    runtime = WorkflowRuntime(actions=actions)

    workflows = WorkflowRegistry()
    for provider in build_default_activity_workflow_providers():
        if provider.id in {
            "terminal.command",
            "shell.command",
            "variable.set",
            "result.save",
            "workflow.outputs",
            "loop.for_each",
            "loop.until",
            "utility.confirm",
        }:
            workflows.register(provider)
    return TaskOrchestrator(runtime, workflows)


def test_compiled_command_output_reference_resolves_through_real_task_execution() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="command-to-variable",
        nodes=(
            StudioNode("command_1", "device.command", {"command": "display version"}),
            StudioNode("save", "variable.set", {"name": "version_text", "value": "${command_1.output}"}),
        ),
        edges=(WorkflowEdge("command_1", "save"),),
    )
    plan = _compile_task_plan(version, "router-1")
    orchestrator = _build_activity_orchestrator()
    task = orchestrator.start(plan, device_id="router-1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "succeeded"
    assert result.outputs["command_1"]["output"] == "result for display version"
    assert result.outputs["save"]["value"] == "result for display version"
    assert result.outputs["version_text"] == "result for display version"


def test_compiled_command_interpolates_variable_alias_before_execution() -> None:
    executed_commands: list[str] = []

    class RecordingCommand(_CommandActivity):
        async def execute(self, invocation, context, report) -> ActivityResult:
            del context, report
            command = str(invocation.inputs["command"])
            executed_commands.append(command)
            return ActivityResult(
                ActivityStatus.SUCCEEDED,
                outputs={"output": f"result for {command}", "status": "completed"},
            )

    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="variable-command",
        nodes=(
            StudioNode("file", "variable.set", {"name": "ccfile", "value": "flash:/config.cc"}),
            StudioNode("command", "device.command", {"command": "dir ${ccfile}"}),
        ),
        edges=(WorkflowEdge("file", "command"),),
    )
    plan = _compile_task_plan(version, "router-1")
    orchestrator = _build_activity_orchestrator(RecordingCommand())
    task = orchestrator.start(plan, device_id="router-1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "succeeded"
    assert executed_commands == ["dir flash:/config.cc"]


def test_compiled_confirmation_node_blocks_task_at_decision_checkpoint() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="confirm",
        nodes=(StudioNode("confirm", "utility.confirm", {"prompt": "continue?"}),),
    )
    plan = _compile_task_plan(version, "router-1")
    from device_tui.application.workflow_plugins.generic import ManualConfirmationWorkflowProvider

    actions = ActionRegistry()
    runtime = WorkflowRuntime(actions=actions)
    workflows = WorkflowRegistry()
    workflows.register(ManualConfirmationWorkflowProvider())
    orchestrator = TaskOrchestrator(runtime, workflows)
    task = orchestrator.start(plan, device_id="router-1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "waiting_decision"
    assert result.error is None
    child = runtime.runs.get(result.node_runs["confirm"])
    assert child.decision_point is not None


def test_compiled_for_each_preserves_loop_item_reference_in_real_execution() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="for-each",
        nodes=(
            StudioNode(
                "loop",
                "loop.for_each",
                {
                    "items": ["a", "b"],
                    "action_id": "variable.set",
                    "action_inputs": {"name": "current", "value": "${item}"},
                },
            ),
        ),
    )
    plan = _compile_task_plan(version, "router-1")
    orchestrator = _build_activity_orchestrator()
    task = orchestrator.start(plan, device_id="router-1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "succeeded"
    assert [item["value"] for item in result.outputs["loop"]["results"]] == ["a", "b"]


def test_compiled_until_exposes_previous_child_result_to_condition() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="until",
        nodes=(
            StudioNode(
                "loop",
                "loop.until",
                {
                    "action_id": "variable.set",
                    "action_inputs": {"name": "current", "value": "${iteration}"},
                    "condition": "result.value == 2",
                    "max_iterations": 3,
                    "interval_seconds": 0,
                },
            ),
        ),
    )
    plan = _compile_task_plan(version, "router-1")
    orchestrator = _build_activity_orchestrator()
    task = orchestrator.start(plan, device_id="router-1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "succeeded"
    assert result.outputs["loop"]["matched"] is True
    assert result.outputs["loop"]["iterations"] == 2


def test_failed_compiled_node_stops_downstream_node_with_structured_error() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="failure",
        nodes=(
            StudioNode("command", "device.command", {"command": "fail"}),
            StudioNode("save", "variable.set", {"name": "value", "value": "${command.output}"}),
        ),
        edges=(WorkflowEdge("command", "save"),),
    )
    plan = _compile_task_plan(version, "router-1")

    class FailingCommand(_CommandActivity):
        async def execute(self, invocation, context, report) -> ActivityResult:
            del invocation, context, report
            return ActivityResult(
                ActivityStatus.FAILED,
                outputs={"output": "permission denied", "status": "failed"},
                error={"code": "command_failed", "message": "command rejected", "class": "deterministic"},
            )

    orchestrator = _build_activity_orchestrator(FailingCommand())
    task = orchestrator.start(plan, device_id="router-1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "failed"
    assert result.error["code"] == "command_failed"
    assert result.outputs["command"]["output"] == "permission denied"
    assert result.outputs["command"]["status"] == "failed"
    assert "save" not in result.node_runs


def test_command_output_extracts_converts_and_selects_condition_branch() -> None:
    import sys

    command = "Write-Output 'count=42'" if sys.platform == "win32" else "printf 'count=42'"
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="command-extract-condition",
        nodes=(
            StudioNode("command", "device.command", {"command": command, "execution_mode": "shell"}),
            StudioNode("count", "variable.set", {
                "name": "item_count",
                "value": "${command.stdout}",
                "extract": {"pattern": r"count=(\d+)", "group": 1, "convert": "integer"},
            }),
            StudioNode("condition", "utility.condition", {
                "rules": [{"field": "value", "operator": "大于", "value": 40}],
            }),
            StudioNode("enough", "result.save", {"key": "branch", "value": "enough"}),
            StudioNode("few", "result.save", {"key": "branch", "value": "few"}),
        ),
        edges=(
            WorkflowEdge("command", "count"),
            WorkflowEdge("count", "condition"),
            WorkflowEdge("condition", "enough", condition="true"),
            WorkflowEdge("condition", "few", condition="false"),
        ),
    )
    plan = _compile_task_plan(version, "router-1")
    orchestrator = _build_activity_orchestrator()
    task = orchestrator.start(plan, device_id="router-1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "succeeded"
    assert result.outputs["command"]["exitCode"] == 0
    assert result.outputs["command"]["exit_code"] == 0
    assert result.outputs["count"]["value"] == 42
    assert result.outputs["item_count"] == 42
    assert result.outputs["enough"]["value"] == "enough"
    assert result.outputs["few"]["status"] == "skipped"


def test_failed_command_can_continue_and_expose_structured_error() -> None:
    class FailingCommand(_CommandActivity):
        async def execute(self, invocation, context, report) -> ActivityResult:
            del invocation, context, report
            return ActivityResult(
                ActivityStatus.FAILED,
                outputs={"output": "permission denied", "status": "failed"},
                error={"code": "command_failed", "message": "command rejected", "class": "deterministic"},
            )

    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="continue-with-error",
        nodes=(
            StudioNode("command", "device.command", {
                "command": "fail",
                "failure_strategy": "continue",
            }),
            StudioNode("save", "variable.set", {
                "name": "failure_code",
                "value": "${command.error.code}",
            }),
        ),
        edges=(WorkflowEdge("command", "save"),),
    )
    plan = _compile_task_plan(version, "router-1")
    orchestrator = _build_activity_orchestrator(FailingCommand())
    task = orchestrator.start(plan, device_id="router-1")

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "succeeded"
    assert result.outputs["command"]["error"]["code"] == "command_failed"
    assert result.outputs["save"]["value"] == "command_failed"
    assert result.context["continued_failures"] == ["command"]


def test_task_context_keeps_custom_connection_endpoint_from_node_output() -> None:
    context = {"target": {"device_id": "router-1", "protocol": "ssh"}}

    updated = TaskOrchestrator._context_with_target_output(
        context,
        {
            "device_id": "router-1",
            "session_id": "session-1",
            "protocol": "ssh",
            "host": "10.0.0.8",
            "port": 2222,
        },
    )

    assert updated["target"]["host"] == "10.0.0.8"
    assert updated["target"]["port"] == 2222


def test_confirmation_decision_projects_stable_result_for_downstream_reference() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="confirm-output",
        nodes=(
            StudioNode("confirm", "utility.confirm", {"prompt": "continue?"}),
            StudioNode("save", "variable.set", {"name": "approved_value", "value": "${confirm.approved}"}),
        ),
        edges=(WorkflowEdge("confirm", "save"),),
    )
    plan = _compile_task_plan(version, "router-1")
    from device_tui.framework import DecisionSubmission

    orchestrator = _build_activity_orchestrator()
    task = orchestrator.start(plan, device_id="router-1")

    waiting = asyncio.run(orchestrator.execute(task.id, plan))
    child = orchestrator.runtime.runs.get(waiting.node_runs["confirm"])
    assert waiting.status.value == "waiting_decision"
    assert child.decision_point is not None

    orchestrator.apply_decision(
        task.id,
        DecisionSubmission(
            decision_point_id=child.decision_point.id,
            expected_revision=child.revision,
            option_id="approve",
            actor_type="human",
            actor_id="operator-1",
        ),
    )
    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "succeeded"
    assert result.outputs["confirm"]["approved"] is True
    assert result.outputs["save"]["value"] is True


def test_rejected_confirmation_is_projected_to_parent_task_outputs() -> None:
    version = WorkflowVersion(
        workflow_id="wf",
        version=1,
        name="confirm-reject-output",
        nodes=(StudioNode("confirm", "utility.confirm", {"prompt": "continue?"}),),
    )
    plan = _compile_task_plan(version, "router-1")
    from device_tui.framework import DecisionSubmission

    orchestrator = _build_activity_orchestrator()
    task = orchestrator.start(plan, device_id="router-1")
    waiting = asyncio.run(orchestrator.execute(task.id, plan))
    child = orchestrator.runtime.runs.get(waiting.node_runs["confirm"])

    rejected = orchestrator.apply_decision(
        task.id,
        DecisionSubmission(
            decision_point_id=child.decision_point.id,
            expected_revision=child.revision,
            option_id="reject",
            actor_type="human",
            actor_id="operator-1",
            reason="maintenance window is closed",
        ),
    )

    assert rejected.status.value == "cancelled"
    assert rejected.outputs["confirm"] == {
        "approved": False,
        "option_id": "reject",
        "reason": "maintenance window is closed",
        "status": "rejected",
    }


def test_workflow_catalog_actions_have_compile_and_provider_coverage() -> None:
    catalog_ids = {item.id for item in build_action_catalog().list()}
    provider_ids = {provider.id for provider in build_default_activity_workflow_providers()}
    compile_time_only = {"utility.condition", "workflow.call"}

    assert catalog_ids - compile_time_only <= set(_ACTION_WORKFLOW_IDS)
    assert {
        _ACTION_WORKFLOW_IDS[action_id]
        for action_id in catalog_ids
        if action_id not in compile_time_only
    } <= provider_ids
    assert "utility.condition" not in provider_ids
    assert "workflow.call" not in _ACTION_WORKFLOW_IDS


def test_subworkflow_expansion_executes_bound_inputs_and_projects_outputs() -> None:
    child = WorkflowVersion(
        "child",
        1,
        "Child",
        inputs=(WorkflowInput("topic", required=True),),
        nodes=(
            StudioNode("command", "device.command", {"command": "show ${inputs.topic}"}),
        ),
        outputs=(WorkflowOutput("text", "${command.output}", "string"),),
    )
    parent = WorkflowVersion(
        "parent",
        1,
        "Parent",
        inputs=(WorkflowInput("topic", required=True),),
        nodes=(
            StudioNode(
                "call",
                "workflow.call",
                {"workflow_id": "child", "version": 1, "inputs": {"topic": "${inputs.topic}"}},
            ),
            StudioNode("save", "result.save", {"key": "child_text", "value": "${call.text}"}),
        ),
        edges=(WorkflowEdge("call", "save"),),
    )

    expanded = _expand_subworkflows(parent, lambda workflow_id, version: child)
    assert [node.id for node in expanded.nodes] == ["call__command", "call", "save"]
    assert expanded.nodes[0].config["command"] == "show ${inputs.topic}"

    plan = _compile_task_plan(expanded, "router-1")
    assert plan.nodes[1].depends_on == ("call__command",)
    assert plan.nodes[2].depends_on == ("call",)
    orchestrator = _build_activity_orchestrator()
    task = orchestrator.start(plan, device_id="router-1", inputs={"topic": "version"})

    result = asyncio.run(orchestrator.execute(task.id, plan))

    assert result.status.value == "succeeded"
    assert result.outputs["call__command"]["output"] == "result for show version"
    assert result.outputs["call"]["outputs"] == {"text": "result for show version"}
    assert result.outputs["call"]["text"] == "result for show version"
    assert result.outputs["save"]["value"] == "result for show version"


def test_nested_subworkflow_expansion_namespaces_every_child_level() -> None:
    leaf = WorkflowVersion(
        "leaf",
        1,
        "Leaf",
        nodes=(StudioNode("value", "variable.set", {"name": "answer", "value": 42}),),
        outputs=(WorkflowOutput("answer", "${value.value}", "integer"),),
    )
    middle = WorkflowVersion(
        "middle",
        2,
        "Middle",
        nodes=(
            StudioNode("leaf_call", "workflow.call", {"workflow_id": "leaf", "version": 1}),
        ),
        outputs=(WorkflowOutput("answer", "${leaf_call.answer}", "integer"),),
    )
    parent = WorkflowVersion(
        "parent",
        3,
        "Parent",
        nodes=(
            StudioNode("middle_call", "workflow.call", {"workflow_id": "middle", "version": 2}),
        ),
    )
    versions = {("leaf", 1): leaf, ("middle", 2): middle}

    expanded = _expand_subworkflows(
        parent,
        lambda workflow_id, version: versions[(workflow_id, version)],
    )

    assert [node.id for node in expanded.nodes] == [
        "middle_call__leaf_call__value",
        "middle_call__leaf_call",
        "middle_call",
    ]
    assert expanded.nodes[1].config["values"] == {
        "answer": "${middle_call__leaf_call__value.value}",
    }
    assert expanded.nodes[2].config["values"] == {
        "answer": "${middle_call__leaf_call.answer}",
    }
