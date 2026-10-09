from pathlib import Path
import pytest

from device_tui.application.workflow_studio import WorkflowDraft, WorkflowNode
from device_tui.application.workflow_studio.store import MemoryWorkflowDefinitionStore
from device_tui.infrastructure.persistence.sqlite_workflows import SQLiteWorkflowDefinitionStore


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_definition_crud_publish_snapshot_and_referenced_version_deletion(kind, tmp_path: Path):
    store = MemoryWorkflowDefinitionStore() if kind == "memory" else SQLiteWorkflowDefinitionStore(tmp_path / "workflow.sqlite3")
    draft = WorkflowDraft("w1", "Demo", nodes=(WorkflowNode("n1", "utility.wait", {"seconds": 1}),))
    store.create(draft)
    published = store.publish("w1")
    store.save(WorkflowDraft("w1", "Changed"))
    assert store.get("w1", published.version).name == "Demo"
    assert store.publish("w1").version == 2
    assert store.is_referenced("w1", published.version) is False
    store.mark_referenced("w1", published.version)
    assert store.is_referenced("w1", published.version) is True
    store.delete("w1", published.version)
    with pytest.raises(KeyError):
        store.get("w1", published.version)
    with pytest.raises(ValueError):
        store.delete("w1")


def test_sqlite_list_published_latest_is_grouped_by_workflow(tmp_path: Path):
    store = SQLiteWorkflowDefinitionStore(tmp_path / "workflow.sqlite3")
    for workflow_id in ("w1", "w2"):
        store.create(WorkflowDraft(workflow_id, workflow_id))

    # Publish versions in an interleaved order so a global MAX(version) filter
    # would incorrectly return an older version for one workflow.
    assert store.publish("w1").version == 1
    assert store.publish("w2").version == 1
    assert store.publish("w1").version == 2

    latest = {(item.workflow_id, int(item.version)) for item in store.list_published()}
    assert latest == {("w1", 2), ("w2", 1)}


@pytest.mark.parametrize("kind", ["memory", "sqlite"])
def test_definition_can_be_removed_while_hiding_referenced_history(kind, tmp_path: Path):
    store = MemoryWorkflowDefinitionStore() if kind == "memory" else SQLiteWorkflowDefinitionStore(tmp_path / "workflow.sqlite3")
    store.create(WorkflowDraft("w1", "Demo"))
    published = store.publish("w1")
    store.mark_referenced("w1", published.version)

    store.delete_preserving_references("w1")

    assert store.list() == []
    assert store.list_versions("w1") == []
    with pytest.raises(KeyError):
        store.get("w1", published.version)
