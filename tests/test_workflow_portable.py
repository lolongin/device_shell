import json

from device_tui.application.workflow_studio import WorkflowDraft, WorkflowNode, WorkflowEdge, dump_document, export_document, from_document, parse_document


def test_portable_yaml_round_trip() -> None:
    draft = WorkflowDraft("local", "版本检查", nodes=(WorkflowNode("command", "device.command", {"command": "display version"}), WorkflowNode("save", "result.save", {"key": "version"})), edges=(WorkflowEdge("command", "save"),))
    document = export_document(draft)
    restored = from_document(parse_document(dump_document(document), filename="version.workflow.yaml")).draft
    assert restored.name == draft.name
    assert restored.nodes[0].action_id == "device.command"
    assert restored.edges[0].source == "command"


def test_portable_json_round_trip() -> None:
    draft = WorkflowDraft("local", "JSON", nodes=(WorkflowNode("wait", "utility.wait", {"seconds": 1}),))
    content = dump_document(export_document(draft), fmt="json")
    assert json.loads(content)["format"] == "device-tui.workflow"
    assert from_document(parse_document(content, filename="workflow.json")).draft.nodes[0].config["seconds"] == 1


def test_portable_import_maps_ai_friendly_retry() -> None:
    document = {"format": "device-tui.workflow", "schema_version": 1, "workflow": {"name": "Retry", "steps": [{"id": "command", "action": "device.command", "with": {"command": "show version"}, "retry": {"attempts": 2}}]}}
    node = from_document(document).draft.nodes[0]
    assert node.config["retry_attempts"] == 2
