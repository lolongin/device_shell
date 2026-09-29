from device_tui.application.workflow_studio import (
    WorkflowInput,
    WorkflowOutput,
    coerce_input_value,
    input_contract,
    output_contract,
    resolve_input_values,
    resolve_workflow_value,
    build_control_registry,
    resolve_control,
    resolve_output_renderer,
)


def test_input_contract_selects_stable_presentations_for_file_and_device_inputs() -> None:
    file_input = WorkflowInput("bundle", type="file", accept=".zip")
    device_input = WorkflowInput("target", type="devices", multiple=True)

    assert input_contract(file_input)["presentation"] == "file"
    assert input_contract(file_input)["accept"] == ".zip"
    assert input_contract(device_input)["presentation"] == "device-list"
    assert input_contract(device_input)["multiple"] is True


def test_resolve_input_values_applies_defaults_and_form_coercion() -> None:
    definitions = (
        WorkflowInput("count", type="integer", required=True),
        WorkflowInput("enabled", type="boolean", default=False),
        WorkflowInput("targets", type="devices", required=True),
        WorkflowInput("metadata", type="object"),
    )
    values, errors = resolve_input_values(
        definitions,
        {"count": "3", "targets": "r1, r2", "metadata": '{"site":"lab"}'},
    )

    assert errors == {}
    assert values == {"count": 3, "enabled": False, "targets": ["r1", "r2"], "metadata": {"site": "lab"}}


def test_output_contract_describes_published_rendering() -> None:
    output = WorkflowOutput("report", "${step.output}", type="string", presentation="download", mime_type="text/plain", download_name="report.txt")

    contract = output_contract(output)

    assert contract["presentation"] == "download"
    assert contract["mime_type"] == "text/plain"
    assert contract["download_name"] == "report.txt"
    assert contract["renderer"]["id"] == "download"


def test_coerce_input_value_keeps_file_and_device_ids_portable() -> None:
    assert coerce_input_value(WorkflowInput("path", type="file"), "C:\\tmp\\image.bin") == "C:\\tmp\\image.bin"
    assert coerce_input_value(WorkflowInput("device", type="device"), "router-1") == "router-1"


def test_resolve_workflow_value_preserves_exact_reference_types_and_renders_embedded_text() -> None:
    context = {"inputs": {"count": 3}, "step": {"output": "ready"}}

    assert resolve_workflow_value("${inputs.count}", context) == 3
    assert resolve_workflow_value("status=${step.output}", context) == "status=ready"


def test_control_registry_maps_legacy_types_to_semantic_controls() -> None:
    registry = build_control_registry()

    assert resolve_control(WorkflowInput("bundle", type="file"), registry)["id"] == "file-picker"
    assert resolve_control(WorkflowInput("target", type="device"), registry)["id"] == "device-picker"
    assert resolve_control(WorkflowInput("targets", type="devices"), registry)["id"] == "device-list-picker"


def test_control_registry_rejects_explicit_incompatible_control() -> None:
    variable = WorkflowInput("target", type="device", ui_hints={"control": "file-picker"})

    try:
        resolve_control(variable)
    except ValueError as error:
        assert "unsupported control" in str(error)
    else:
        raise AssertionError("expected incompatible control to fail")
