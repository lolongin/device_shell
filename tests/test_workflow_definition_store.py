from pathlib import Path
import pytest

from device_tui.application.workflow_studio import WorkflowDraft, WorkflowNode
from device_tui.application.workflow_studio.store import MemoryWorkflowDefinitionStore
from device_tui.infrastructure.persistence.sqlite_workflows import SQLiteWorkflowDefinitionStore


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_definition_crud_publish_snapshot_and_reference_protection(kind, tmp_path: Path):
    store = MemoryWorkflowDefinitionStore() if kind == "memory" else SQLiteWorkflowDefinitionStore(tmp_path / "workflow.sqlite3")
    draft = WorkflowDraft("w1", "Demo", nodes=(WorkflowNode("n1", "utility.wait", {"seconds": 1}),))
    store.create(draft)
    published = store.publish("w1")
    store.save(WorkflowDraft("w1", "Changed"))
    assert store.get("w1", published.version).name == "Demo"
    assert store.publish("w1").version == 2
    store.mark_referenced("w1", published.version)
    with pytest.raises(ValueError):
        store.delete("w1", published.version)
