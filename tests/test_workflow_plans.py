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


def test_plan_compiler_rejects_package_replacement_capability() -> None:
    plan = WorkflowPlan(
        "p-package",
        "replace system package",
        {"device_id": "d1"},
        (PlanStep("upgrade", "package.upgrade", {"package_path": "target.cc"}),),
    )
    result = WorkflowPlanCompiler().validate(plan)
    assert result.status == "rejected"
    assert result.errors[0]["code"] == "capability_not_allowed"
    assert "package.upgrade" not in WorkflowPlanCompiler.CAPABILITIES


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


def test_plan_compiler_emits_framework_task_plan_with_literal_inputs() -> None:
    plan = WorkflowPlan(
        "framework-plan",
        "run a command batch",
        {"device_id": "d1"},
        (
            PlanStep(
                "batch",
                "terminal.batch",
                {"commands": ["display version", "display startup"], "timeout_seconds": 20},
            ),
        ),
    )
    result = WorkflowPlanCompiler().validate(plan)
    assert result.task_plan is not None
    assert result.task_plan.nodes[0].workflow_id == "terminal.batch"
    assert result.task_plan.nodes[0].input_mapping["commands"] == ["display version", "display startup"]


def test_plan_compiler_maps_file_capabilities_to_transfer_workflow() -> None:
    plan = WorkflowPlan(
        "upload-plan",
        "upload artifact",
        {"device_id": "d1"},
        (PlanStep("upload", "file.upload", {"source_path": "a.cc", "destination_path": "flash:/a.cc"}),),
    )
    result = WorkflowPlanCompiler().validate(plan)
    assert result.task_plan is not None
    node = result.task_plan.nodes[0]
    assert node.workflow_id == "file.transfer"
    assert node.input_mapping["direction"] == "upload"


def test_plan_compiler_publishes_capability_contracts_and_validates_params() -> None:
    specs = WorkflowPlanCompiler.capability_specs()
    assert specs["device.upgrade"]["required_params"] == ["package_path"]
    assert "package.upgrade" not in specs

    result = WorkflowPlanCompiler().validate(WorkflowPlan(
        "missing-package",
        "upgrade device",
        {"device_id": "d1"},
        (PlanStep("upgrade", "device.upgrade"),),
    ))
    assert result.status == "rejected"
    assert result.errors[0]["code"] == "parameter_required"


def test_device_upgrade_plan_is_rejected_outside_named_workflow_task() -> None:
    plan = WorkflowPlan(
        "p-upgrade",
        "stage and activate package",
        {"device_id": "d1"},
        (
            PlanStep(
                "upgrade",
                "device.upgrade",
                {"package_path": "target.cc", "activation_policy": "reboot"},
            ),
        ),
    )
    result = WorkflowPlanCompiler().validate(plan)
    assert result.status == "rejected"
    assert result.workflow is None
    assert result.errors[0]["code"] == "workflow_task_only"
