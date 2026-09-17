import pytest

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


def test_validation_rejects_node_output_reference_without_dependency() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("command", "device.command", {"command": "display version"}),
            WorkflowNode("save", "result.save", {"value": "${command.output}"}),
        ),
    )

    codes = {item.code for item in issues(draft)}

    assert "missing_dependency" in codes


def test_validation_rejects_outputs_namespace_reference_without_dependency() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("command", "device.command", {"command": "display version"}),
            WorkflowNode("save", "result.save", {"value": "${outputs.command.output}"}),
        ),
    )

    codes = {item.code for item in issues(draft)}

    assert "missing_dependency" in codes

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


def test_validation_accepts_generic_variable_extraction() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("command", "device.command", {"command": "dir flash:/"}),
            WorkflowNode(
                "variable",
                "variable.set",
                {
                    "name": "cc_path",
                    "value": "${command.output}",
                    "extract": {"pattern": r"flash:/\S+", "mode": "match", "group": 0},
                },
            ),
        ),
        edges=(WorkflowEdge("command", "variable"),),
    )
    assert not issues(draft)


def test_validation_allows_variable_interpolation_in_command_text() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("file", "variable.set", {"name": "ccfile", "value": "flash:/config.cc"}),
            WorkflowNode("command", "device.command", {"command": "dir ${ccfile}"}),
        ),
        edges=(WorkflowEdge("file", "command"),),
    )

    assert not issues(draft)


def test_validation_rejects_unknown_output_field_reference() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("command", "device.command", {"command": "display version"}),
            WorkflowNode("save", "result.save", {"key": "raw", "value": "${command.not_a_field}"}),
        ),
        edges=(WorkflowEdge("command", "save"),),
    )

    matching = [
        issue for issue in issues(draft)
        if issue.code == "invalid_variable_field"
    ]

    assert matching
    assert "command.not_a_field" in matching[0].message


def test_validation_allows_variable_set_alias_references() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("items", "variable.set", {"name": "targets", "value": ["a", "b"]}),
            WorkflowNode("loop", "loop.for_each", {"items": "${targets}", "action_id": "result.save"}),
        ),
        edges=(WorkflowEdge("items", "loop"),),
    )

    assert not issues(draft)


def test_validation_allows_until_local_outputs_reference_in_action_inputs() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode(
                "until",
                "loop.until",
                {
                    "action_id": "result.save",
                    "condition": "outputs.status == 'saved'",
                    "action_inputs": {"value": "${outputs.status}"},
                },
            ),
        ),
    )

    assert "invalid_variable_field" not in {item.code for item in issues(draft)}


def test_validation_rejects_references_to_compile_time_condition_nodes() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("command", "device.command", {"command": "display version"}),
            WorkflowNode(
                "branch",
                "utility.condition",
                {"rules": [{"field": "output", "operator": "包含", "value": "VRP"}]},
            ),
            WorkflowNode("save", "result.save", {"key": "condition", "value": "${branch.output}"}),
        ),
        edges=(
            WorkflowEdge("command", "branch"),
            WorkflowEdge("branch", "save", condition="true"),
        ),
    )

    codes = {item.code for item in issues(draft)}

    assert "invalid_variable_ref" in codes


@pytest.mark.parametrize(
    ("extract", "code"),
    [
        ({"pattern": "["}, "invalid_variable_extract_pattern"),
        ({"pattern": "cc", "mode": "column"}, "invalid_variable_extract_mode"),
        ({"pattern": "cc", "group": -1}, "invalid_variable_extract_group"),
        ({"pattern": "(cc)", "group": 2}, "invalid_variable_extract_group"),
    ],
)
def test_validation_rejects_invalid_generic_variable_extraction(extract: dict[str, object], code: str) -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(WorkflowNode("variable", "variable.set", {"name": "value", "value": "text", "extract": extract}),),
    )
    assert code in {item.code for item in issues(draft)}


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


def test_validation_rejects_unsupported_expressions_and_embedded_references_outside_commands() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("expression", "expression.evaluate", {"expression": "__import__('os')"}),
            WorkflowNode("save", "result.save", {"key": "display ${inputs.scope}"}),
        ),
        edges=(WorkflowEdge("expression", "save"),),
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


def test_validation_checks_runtime_control_fields_from_input_mapping() -> None:
    retry_draft = WorkflowDraft(
        "w",
        "x",
        nodes=(WorkflowNode("wait", "utility.wait", {"seconds": 1}, {"retry_attempts": "bad"}),),
    )
    condition_draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode(
                "condition",
                "utility.condition",
                {"rules": [{"field": "status", "operator": "equals", "value": "ok"}]},
                {"logical_operator": "XOR"},
            ),
        ),
    )

    assert "invalid_number" in {item.code for item in issues(retry_draft)}
    assert "invalid_condition_operator" in {item.code for item in issues(condition_draft)}


def test_validation_uses_input_mapping_as_final_node_settings() -> None:
    cases = (
        (
            WorkflowNode(
                "expression",
                "expression.evaluate",
                {"expression": "1 + 1"},
                {"expression": "__import__('os')"},
            ),
            "invalid_expression",
        ),
        (
            WorkflowNode(
                "variable",
                "variable.set",
                {"name": "valid_name", "value": "x"},
                {"name": "bad-name"},
            ),
            "invalid_variable_name",
        ),
        (
            WorkflowNode(
                "terminal",
                "terminal.wait",
                {"pattern": "ok", "mode": "contains", "timeout_seconds": 1},
                {"pattern": "[", "mode": "regex"},
            ),
            "invalid_terminal_pattern",
        ),
        (
            WorkflowNode(
                "for_each",
                "loop.for_each",
                {"items": ["a"], "action_id": "result.save"},
                {"action_id": "utility.condition"},
            ),
            "invalid_loop_action",
        ),
        (
            WorkflowNode(
                "until",
                "loop.until",
                {"action_id": "result.save", "condition": "result.status == 'saved'"},
                {"condition": "__import__('os')"},
            ),
            "invalid_loop_condition",
        ),
    )

    for node, expected_code in cases:
        assert expected_code in {item.code for item in issues(WorkflowDraft("w", "x", nodes=(node,)))}


def test_validation_scans_only_final_node_settings_after_mapping_override() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("command", "device.command", {"command": "display version"}),
            WorkflowNode(
                "save",
                "result.save",
                {"key": "raw", "value": "${missing.output}"},
                {"value": "${command.output}"},
            ),
        ),
        edges=(WorkflowEdge("command", "save"),),
    )

    assert "invalid_variable_ref" not in {item.code for item in issues(draft)}


def test_validation_accepts_file_path_aliases_used_by_compiler() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode(
                "upload",
                "file.upload",
                {},
                {"source_path": "a.cc", "destination_path": "flash:/a.cc"},
            ),
        ),
    )

    assert not issues(draft)


def test_validation_accepts_absolute_file_upload_source_path() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode(
                "upload",
                "file.upload",
                {"source": r"D:\\packages\\device.cc", "destination": "flash:/device.cc"},
            ),
        ),
    )

    assert "invalid_transfer_source_path" not in {item.code for item in issues(draft)}


@pytest.mark.parametrize("action_id", ["device.ssh", "device.telnet"])
def test_validation_does_not_require_unused_connection_host(action_id: str) -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(WorkflowNode("connect", action_id),),
    )

    assert "missing_required_config" not in {item.code for item in issues(draft)}


def test_validation_rejects_values_that_runtime_handlers_cannot_execute() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("wait", "utility.wait", {"seconds": "not-a-number"}),
            WorkflowNode("loop", "loop.for_each", {"items": "literal", "action_id": "result.save"}),
        ),
    )

    codes = {item.code for item in issues(draft)}

    assert "invalid_config_type" in codes
    assert "invalid_loop_items" in codes


def test_validation_requires_supported_condition_branch_labels() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("info", "device.info"),
            WorkflowNode(
                "condition",
                "utility.condition",
                {"rules": [{"field": "status", "operator": "等于", "value": "ok"}]},
            ),
            WorkflowNode("next", "result.save"),
        ),
        edges=(
            WorkflowEdge("info", "condition"),
            WorkflowEdge("condition", "next", condition="maybe"),
        ),
    )

    assert "invalid_branch_label" in {item.code for item in issues(draft)}


def test_validation_allows_exact_references_for_typed_inputs() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("items", "variable.set", {"name": "targets", "value": ["a", "b"]}),
            WorkflowNode("loop", "loop.for_each", {"items": "${targets}", "action_id": "result.save"}),
        ),
        edges=(WorkflowEdge("items", "loop"),),
    )

    assert "invalid_config_type" not in {item.code for item in issues(draft)}


def test_validation_rejects_string_output_reference_for_array_input() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("command", "device.command", {"command": "display version"}),
            WorkflowNode("loop", "loop.for_each", {"items": "${command.output}", "action_id": "result.save"}),
        ),
        edges=(WorkflowEdge("command", "loop"),),
    )

    assert "invalid_config_type" in {item.code for item in issues(draft)}


def test_validation_rejects_string_output_reference_for_number_input() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(
            WorkflowNode("command", "device.command", {"command": "display version"}),
            WorkflowNode("wait", "utility.wait", {"seconds": "${command.output}"}),
        ),
        edges=(WorkflowEdge("command", "wait"),),
    )

    assert "invalid_config_type" in {item.code for item in issues(draft)}


def test_validation_rejects_unknown_reference_paths_in_reserved_namespaces() -> None:
    drafts = (
        WorkflowDraft("inputs", "x", nodes=(WorkflowNode("step", "device.command", {"command": "${inputs.not_defined}"}),)),
        WorkflowDraft("outputs", "x", nodes=(WorkflowNode("step", "device.command", {"command": "${outputs.missing}"}),)),
        WorkflowDraft("device", "x", nodes=(WorkflowNode("step", "device.command", {"command": "${device.unknown}"}),)),
    )

    for draft in drafts:
        assert "invalid_variable_field" in {item.code for item in issues(draft)}


def test_validation_accepts_known_workflow_input_reference_path() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        inputs=(WorkflowInput("command_text", type="string", required=True),),
        nodes=(WorkflowNode("command", "device.command", {"command": "${inputs.command_text}"}),),
    )

    codes = {item.code for item in issues(draft)}

    assert "invalid_variable_field" not in codes
    assert "invalid_config_type" not in codes


def test_catalog_marks_confirmation_prompt_as_required() -> None:
    spec = CATALOG.get("utility.confirm")

    assert spec is not None
    assert "prompt" in spec.required_inputs
