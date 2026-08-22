import json

from device_tui.application.tasking import (
    Action,
    Checkpoint,
    Decision,
    DecisionActor,
    DecisionContext,
    StepStatus,
    Task,
    TaskStatus,
    ToolError,
    ToolResult,
    ToolStatus,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStep,
)


def test_tool_result_contains_facts_not_next_action() -> None:
    result = ToolResult(
        tool="terminal.execute",
        status=ToolStatus.SUCCEEDED,
        facts={"prompt_seen": True, "version": "1.2.3"},
        operation_id="op-1",
    )

    payload = result.to_dict()

    assert payload["status"] == "succeeded"
    assert payload["facts"]["version"] == "1.2.3"
    assert "next_action" not in payload
    assert ToolResult.from_json(result.to_json()) == result


def test_workflow_protocol_round_trip_is_json_safe() -> None:
    workflow = WorkflowDefinition(
        id="upgrade",
        version="2",
        name="Package upgrade",
        steps=(
            WorkflowStep(
                id="apply",
                kind="tool",
                action=Action(
                    name="package_upgrade",
                    parameters={"package_path": "images/a.cc"},
                    risk="high",
                    confirmation_required=True,
                ),
                retry_policy={"max_attempts": 3},
            ),
        ),
    )

    restored = WorkflowDefinition.from_json(workflow.to_json())

    assert restored == workflow
    assert isinstance(restored.steps[0].action, Action)
    assert restored.steps[0].action.parameters["package_path"] == "images/a.cc"
    json.loads(workflow.to_json())


def test_task_checkpoint_and_decision_are_persistable() -> None:
    tool_result = ToolResult(
        tool="storage.check",
        status="failed",
        error=ToolError(
            code="insufficient_space",
            message="Not enough space",
            error_class="deterministic",
            retryable=False,
        ),
    )
    checkpoint = Checkpoint(
        id="cp-1",
        task_id="task-1",
        workflow_instance_id="instance-1",
        revision=4,
        current_step="storage",
        completed_steps=("precheck",),
        outputs={"precheck": {"ok": True}},
        failed_step_id="storage",
        pending_decision_id="decision-1",
    )
    instance = WorkflowInstance(
        id="instance-1",
        task_id="task-1",
        workflow_id="upgrade",
        status=TaskStatus.WAITING_FOR_DECISION,
        current_step="storage",
        checkpoint=checkpoint,
        step_states=(),
    )
    task = Task(
        id="task-1",
        workflow_instance_id=instance.id,
        status=TaskStatus.WAITING_FOR_DECISION,
        operator_type="agent",
        workflow=instance,
        checkpoint=checkpoint,
    )
    context = DecisionContext(
        task_id=task.id,
        workflow_id=instance.workflow_id,
        current_step="storage",
        error=tool_result.error,
        result=tool_result,
        context={"device_id": "device-1"},
        available_actions=(
            Action(name="retry", target_step="storage"),
            Action(name="pause"),
        ),
        decision_modes=("user", "agent"),
        checkpoint_revision=checkpoint.revision,
    )
    decision = Decision(
        decision_id="decision-1",
        actor=DecisionActor(type="agent", id="agent-1"),
        action=Action(name="retry", target_step="storage"),
        reason="Space was freed by a cleanup action.",
        timestamp="2026-08-22T00:00:00Z",
        task_id=task.id,
        workflow_id=instance.workflow_id,
        expected_revision=checkpoint.revision,
    )

    restored_task = Task.from_json(task.to_json())
    restored_context = DecisionContext.from_json(context.to_json())
    restored_decision = Decision.from_json(decision.to_json())

    assert restored_task == task
    assert restored_task.checkpoint is not None
    assert restored_task.checkpoint.pending_decision_id == "decision-1"
    assert isinstance(restored_context.result, ToolResult)
    assert restored_context.available_actions[0].name == "retry"
    assert restored_decision.actor.type == "agent"
    assert restored_decision.action.target_step == "storage"
    assert StepStatus.FAILED.value == "failed"
