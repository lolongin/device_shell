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

def test_validation_warns_for_high_risk_actions() -> None:
    result = validate_workflow(WorkflowDraft("w", "x", nodes=(WorkflowNode("r", "device.reboot"),)), CATALOG)
    assert any(i.code == "high_risk_action" and i.node_id == "r" for i in result.warnings)

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
