from device_tui.application.workflow_studio import *

CATALOG = build_action_catalog()

def issues(workflow):
    return validate_workflow(workflow, CATALOG).errors

def test_validation_catches_unknown_action_and_missing_config() -> None:
    result = validate_workflow(WorkflowDraft("w", "x", nodes=(WorkflowNode("a", "unknown"), WorkflowNode("b", "device.command"))), CATALOG)
    assert {i.code for i in result.errors} >= {"unknown_action", "missing_required_config"}

def test_validation_catches_disconnected_and_cycles() -> None:
    draft = WorkflowDraft("w", "x", nodes=(WorkflowNode("a", "utility.wait", {"seconds": 1}), WorkflowNode("b", "utility.wait", {"seconds": 1}), WorkflowNode("c", "utility.wait", {"seconds": 1})), edges=(WorkflowEdge("a", "b"), WorkflowEdge("b", "a")))
    codes = {i.code for i in issues(draft)}
    assert "cycle" in codes and "disconnected_node" in codes

def test_validation_catches_invalid_condition_and_variable() -> None:
    draft = WorkflowDraft("w", "x", nodes=(WorkflowNode("a", "utility.condition", {"expression": ""}), WorkflowNode("b", "device.command", {"command": "${missing}"})), edges=(WorkflowEdge("a", "b", condition=" "),))
    codes = {i.code for i in issues(draft)}
    assert "invalid_condition" in codes and "invalid_variable_ref" in codes

def test_validation_does_not_block_actions_by_risk_level() -> None:
    result = validate_workflow(WorkflowDraft("w", "x", nodes=(WorkflowNode("r", "device.reboot"),)), CATALOG)
    assert not result.errors
    assert not result.warnings

def test_validation_rejects_multiple_roots_and_blank_required_values() -> None:
    draft = WorkflowDraft("w", "x", nodes=(WorkflowNode("a", "device.command", {"command": ""}), WorkflowNode("b", "device.command", {"command": "ok"})))
    codes = {i.code for i in issues(draft)}
    assert "disconnected_node" in codes and "missing_required_config" in codes

def test_validation_scans_nested_and_forward_references() -> None:
    draft = WorkflowDraft("w", "x", nodes=(WorkflowNode("a", "device.command", {"command": "${b.output}", "nested": {"x": "${missing}"}}), WorkflowNode("b", "device.command", {"command": "ok"})), edges=(WorkflowEdge("a", "b", condition=3),))
    codes = {i.code for i in issues(draft)}
    assert "invalid_variable_ref" in codes and "invalid_condition" in codes

def test_validation_rejects_duplicate_names() -> None:
    draft = WorkflowDraft("w", "x", inputs=(WorkflowInput("x"), WorkflowInput("x")), nodes=(WorkflowNode("a", "utility.wait", {"seconds": 1}), WorkflowNode("a", "utility.wait", {"seconds": 1})))
    codes = {i.code for i in issues(draft)}
    assert {"duplicate_input_name", "duplicate_node_id"} <= codes

def test_edge_condition_can_reference_source_output() -> None:
    draft = WorkflowDraft(
        "w", "x",
        nodes=(
            WorkflowNode("a", "device.command", {"command": "show version"}),
            WorkflowNode("b", "utility.condition", {"expression": "ok"}),
        ),
        edges=(WorkflowEdge("a", "b", condition="${a.output}"),),
    )
    assert "invalid_variable_ref" not in {item.code for item in issues(draft)}

def test_visual_condition_rules_are_valid_without_expression() -> None:
    draft = WorkflowDraft(
        "w", "x",
        nodes=(WorkflowNode("a", "utility.condition", {"rules": [{"field": "software_version", "operator": "小于", "value": "8.200"}]}),),
    )
    assert "invalid_condition" not in {item.code for item in issues(draft)}

def test_validation_checks_confirmation_and_repeat_boundaries() -> None:
    draft = WorkflowDraft("w", "x", nodes=(WorkflowNode("confirm", "utility.confirm"), WorkflowNode("wait", "utility.wait", {"seconds": 1, "repeat_count": 21})), edges=(WorkflowEdge("confirm", "wait"),))
    codes = {item.code for item in issues(draft)}
    assert {"missing_confirmation_prompt", "number_out_of_range"} <= codes


def test_validation_checks_utility_node_contracts() -> None:
    draft = WorkflowDraft(
        "w", "x",
        nodes=(
            WorkflowNode("var", "variable.set", {"name": "bad-name", "value": "x"}),
            WorkflowNode("expr", "expression.evaluate", {"expression": ""}),
            WorkflowNode("loop", "loop.for_each", {"items": "${var}", "action_id": "missing.action"}),
        ),
        edges=(WorkflowEdge("var", "expr"), WorkflowEdge("expr", "loop")),
    )
    codes = {item.code for item in issues(draft)}
    assert {"invalid_variable_name", "invalid_expression", "invalid_loop_action"} <= codes


def test_validation_allows_file_actions_in_parallel_group() -> None:
    draft = WorkflowDraft(
        "w", "x",
        nodes=(
            WorkflowNode("start", "utility.wait", {"seconds": 1}),
            WorkflowNode("upload", "file.upload", {"source": "a.bin", "destination": "/tmp/a", "parallel_group": "ops"}),
        ),
        edges=(WorkflowEdge("start", "upload"),),
    )
    assert not issues(draft)


def test_validation_allows_confirmation_in_parallel_group() -> None:
    draft = WorkflowDraft(
        "w", "x",
        nodes=(WorkflowNode("confirm", "utility.confirm", {"prompt": "确认", "parallel_group": "checks"}),),
    )
    assert not issues(draft)


def test_validation_rejects_unsupported_expressions_and_embedded_references() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("expression", "expression.evaluate", {"expression": "__import__('os')"}),
            WorkflowNode("command", "device.command", {"command": "display ${inputs.scope}"}),
        ),
        edges=(WorkflowEdge("expression", "command"),),
    )

    codes = {item.code for item in issues(draft)}

    assert "invalid_expression" in codes
    assert "embedded_variable_ref" in codes


def test_validation_rejects_non_executable_loop_children() -> None:
    for child_action in ("loop.for_each", "utility.condition", "utility.confirm"):
        draft = WorkflowDraft(
            "w",
            "x",
            nodes=(WorkflowNode("loop", "loop.for_each", {"items": [], "action_id": child_action}),),
        )

        assert "invalid_loop_action" in {item.code for item in issues(draft)}
