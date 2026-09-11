from device_tui.application.workflow_studio import *

def test_workflow_draft_round_trip() -> None:
    draft = WorkflowDraft("w1", "Demo", inputs=(WorkflowInput("host", required=True),), nodes=(WorkflowNode("n1", "device.command", {"command": "show"}),), edges=())
    assert WorkflowDraft.from_dict(draft.to_dict()) == draft

def test_workflow_version_round_trip() -> None:
    version = WorkflowVersion("w1", 2, "Demo", nodes=(WorkflowNode("n", "utility.wait", {"seconds": 1}),), published_at="2026-01-01")
    assert WorkflowVersion.from_dict(version.to_dict()) == version
