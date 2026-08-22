from __future__ import annotations

from device_tui.application.tasking import PlanStep, WorkflowPlan, WorkflowPlanCompiler


def test_plan_compiler_rejects_unknown_capability_and_cycles() -> None:
    plan = WorkflowPlan(
        "p1",
        "bad plan",
        {"device_id": "d1"},
        (
            PlanStep("a", "not.allowed", depends_on=("b",)),
            PlanStep("b", "terminal.command", {"command": "display version"}, depends_on=("a",)),
        ),
    )
    result = WorkflowPlanCompiler().validate(plan)
    assert result.status == "rejected"
    assert {item["code"] for item in result.errors} == {"capability_not_allowed", "workflow_cycle"}


def test_plan_compiler_marks_high_risk_steps_for_confirmation() -> None:
    plan = WorkflowPlan(
        "p2",
        "reboot device",
        {"device_id": "d1"},
        (PlanStep("reboot", "device.reboot"),),
    )
    result = WorkflowPlanCompiler().validate(plan)
    assert result.status == "requires_confirmation"
    assert result.required_actions[0].target_step == "reboot"
    assert result.workflow is not None
    assert result.workflow.steps[0].action.confirmation_required is True


def test_plan_hash_is_stable_and_compiled_metadata_keeps_hash() -> None:
    plan = WorkflowPlan(
        "p3",
        "read version",
        {"device_id": "d1"},
        (PlanStep("version", "terminal.command", {"command": "display version"}),),
    )
    result = WorkflowPlanCompiler().validate(plan)
    assert result.plan_hash == plan.content_hash()
    assert result.workflow is not None
    assert result.workflow.metadata["plan_hash"] == result.plan_hash
