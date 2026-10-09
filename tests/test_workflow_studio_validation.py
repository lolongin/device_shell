import pytest

from device_tui.application.workflow_studio import *

CATALOG = build_action_catalog()


def test_batch_final_output_requires_loop_results_instead_of_save_object() -> None:
    from dataclasses import replace

    workflow = WorkflowDraft(
        "batch-output", "Batch output",
        nodes=(
            WorkflowNode("each", "device.for_each", {"devices": ["device-1"], "action_id": "result.save", "action_inputs": {"value": "version"}}),
            WorkflowNode("save_version", "result.save", {"value": "version"}),
        ),
        edges=(WorkflowEdge("each", "save_version"),),
        outputs=(WorkflowOutput("device_results", "${save_version}", "array"),),
    )
    errors = validate_workflow(workflow, CATALOG).errors
    assert any("resolves to object, expected array" in error.message for error in errors)
    corrected = replace(workflow, outputs=(WorkflowOutput("device_results", "${each.results}", "array"),))
    assert not validate_workflow(corrected, CATALOG).errors

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


def test_validation_accepts_variable_extraction_conversion() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(WorkflowNode(
            "variable",
            "variable.set",
            {
                "name": "count",
                "value": "count= 42 ",
                "extract": {
                    "pattern": r"=(.+)",
                    "group": 1,
                    "convert": "integer",
                    "trim": True,
                },
            },
        ),),
    )

    assert not issues(draft)


def test_validation_rejects_invalid_variable_extraction_conversion() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(WorkflowNode(
            "variable",
            "variable.set",
            {
                "name": "count",
                "value": "count=42",
                "extract": {"pattern": r"=(.+)", "convert": "decimal", "trim": "yes"},
            },
        ),),
    )

    codes = {item.code for item in issues(draft)}
    assert {"invalid_variable_extract_conversion", "invalid_variable_extract_trim"} <= codes


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


def test_validation_accepts_upload_without_device_destination() -> None:
    draft = WorkflowDraft(
        "w",
        "x",
        nodes=(WorkflowNode("upload", "file.upload", {"source": r"D:\\packages\\device.cc"}),),
    )

    assert not issues(draft)


def test_validation_accepts_file_workflow_input_as_upload_source() -> None:
    draft = WorkflowDraft(
        "w", "x",
        inputs=(
            WorkflowInput("package_file", type="file", required=True),
            WorkflowInput("target_path", type="string"),
            WorkflowInput("replace", type="boolean"),
        ),
        nodes=(WorkflowNode("upload", "file.upload", {
            "source": "${inputs.package_file}",
            "destination": "${inputs.target_path}",
            "overwrite": "${inputs.replace}",
        }),),
    )

    assert not issues(draft)


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


def test_validation_requires_script_input_references_to_be_complete_values() -> None:
    embedded = WorkflowDraft(
        "script-embedded",
        "x",
        nodes=(
            WorkflowNode(
                "script",
                "script.run",
                {
                    "script": "print('ok')",
                    "input_json": '{"message":"prefix-${inputs.name}"}',
                },
            ),
        ),
    )
    exact = WorkflowDraft(
        "script-exact",
        "x",
        inputs=(WorkflowInput("name", type="string"),),
        nodes=(
            WorkflowNode(
                "script",
                "script.run",
                {
                    "script": "print('ok')",
                    "input_json": '{"message":"${inputs.name}"}',
                },
            ),
        ),
    )

    assert "embedded_variable_ref" in {item.code for item in issues(embedded)}
    assert "embedded_variable_ref" not in {item.code for item in issues(exact)}


def test_validation_rejects_invalid_script_input_json() -> None:
    draft = WorkflowDraft(
        "script-invalid-json",
        "x",
        nodes=(WorkflowNode("script", "script.run", {"script": "print('ok')", "input_json": "{"}),),
    )

    assert "invalid_script_input_json" in {item.code for item in issues(draft)}


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


def test_validation_rejects_static_reference_and_accepts_runtime_number_reference() -> None:
    static = WorkflowDraft(
        "static", "Static",
        inputs=(WorkflowInput("device_id", type="string"),),
        nodes=(WorkflowNode("select", "device.select", {"device_id": "${inputs.device_id}"}),),
    )
    dynamic = WorkflowDraft(
        "dynamic", "Dynamic",
        inputs=(WorkflowInput("seconds", type="number"),),
        nodes=(WorkflowNode("wait", "utility.wait", {"seconds": "${inputs.seconds}"}),),
    )
    assert "static_binding_reference" not in {item.code for item in issues(static)}
    assert "invalid_config_type" not in {item.code for item in issues(dynamic)}


def test_validation_checks_devices_reference_as_array() -> None:
    draft = WorkflowDraft(
        "devices", "Devices",
        inputs=(WorkflowInput("targets", type="devices"),),
        nodes=(WorkflowNode("loop", "device.for_each", {"devices": "${inputs.targets}", "action_id": "result.save"}),),
    )
    assert "invalid_config_type" not in {item.code for item in issues(draft)}


@pytest.mark.parametrize("input_type", ["string", "device", "object"])
def test_device_select_accepts_workflow_input_bindings(input_type: str) -> None:
    draft = WorkflowDraft(
        "bound-device", "Bound device",
        inputs=(WorkflowInput("target", type=input_type),),
        nodes=(WorkflowNode("select", "device.select", {"device_id": "${inputs.target}"}),),
    )
    assert not issues(draft)


def test_catalog_marks_confirmation_prompt_as_required() -> None:
    spec = CATALOG.get("utility.confirm")

    assert spec is not None
    assert "prompt" in spec.required_inputs


def test_subworkflow_validation_accepts_bound_inputs_and_declared_outputs() -> None:
    child = WorkflowVersion(
        "child",
        1,
        "Child",
        inputs=(WorkflowInput("message", required=True),),
        nodes=(
            WorkflowNode("capture", "variable.set", {"name": "captured", "value": "${inputs.message}"}),
        ),
        outputs=(WorkflowOutput("echo", "${capture.value}", "string"),),
    )
    parent = WorkflowDraft(
        "parent",
        "Parent",
        inputs=(WorkflowInput("message", required=True),),
        nodes=(
            WorkflowNode(
                "call",
                "workflow.call",
                {"workflow_id": "child", "version": 1, "inputs": {"message": "${inputs.message}"}},
            ),
            WorkflowNode("save", "result.save", {"value": "${call.echo}"}),
        ),
        edges=(WorkflowEdge("call", "save"),),
    )

    result = validate_workflow(parent, CATALOG, lambda workflow_id, version: child)

    assert result.valid


@pytest.mark.parametrize(
    ("config", "expected_code"),
    (
        ({"workflow_id": "child", "version": "draft", "inputs": {}}, "invalid_config_type"),
        ({"workflow_id": "child", "version": 1, "inputs": {}}, "missing_subworkflow_input"),
        ({"workflow_id": "missing", "version": 1, "inputs": {}}, "unknown_workflow_version"),
    ),
)
def test_subworkflow_validation_rejects_invalid_targets_and_input_bindings(
    config: dict[str, object],
    expected_code: str,
) -> None:
    child = WorkflowVersion(
        "child",
        1,
        "Child",
        inputs=(WorkflowInput("message", required=True),),
        nodes=(WorkflowNode("capture", "variable.set", {"name": "captured", "value": "ok"}),),
    )

    def resolve(workflow_id: str, version: int | str | None) -> WorkflowVersion:
        if workflow_id != "child" or version != 1:
            raise KeyError(workflow_id)
        return child

    draft = WorkflowDraft(
        "parent",
        "Parent",
        nodes=(WorkflowNode("call", "workflow.call", config),),
    )

    assert expected_code in {item.code for item in validate_workflow(draft, CATALOG, resolve).errors}


def test_subworkflow_validation_rejects_direct_and_indirect_recursion() -> None:
    direct = WorkflowDraft(
        "parent",
        "Parent",
        nodes=(WorkflowNode("call", "workflow.call", {"workflow_id": "parent", "version": 1}),),
    )
    child = WorkflowVersion(
        "child",
        1,
        "Child",
        nodes=(WorkflowNode("back", "workflow.call", {"workflow_id": "parent", "version": 1}),),
    )
    published_parent = WorkflowVersion(
        "parent",
        1,
        "Parent",
        nodes=(WorkflowNode("call", "workflow.call", {"workflow_id": "child", "version": 1}),),
    )
    versions = {("parent", 1): published_parent, ("child", 1): child}

    assert "recursive_workflow_call" in {
        item.code for item in validate_workflow(direct, CATALOG, lambda workflow_id, version: published_parent).errors
    }
    nested = validate_workflow(
        published_parent,
        CATALOG,
        lambda workflow_id, version: versions[(workflow_id, int(version or 0))],
    )
    assert "invalid_subworkflow" in {item.code for item in nested.errors}


def test_workflow_call_cannot_be_used_as_a_loop_child() -> None:
    draft = WorkflowDraft(
        "parent",
        "Parent",
        nodes=(
            WorkflowNode(
                "loop",
                "loop.for_each",
                {"items": ["one"], "action_id": "workflow.call", "action_inputs": {}},
            ),
        ),
    )

    assert "invalid_loop_action" in {item.code for item in issues(draft)}
