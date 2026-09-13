from pathlib import Path


APP = Path("desktop/src/renderer/src/App.vue")
STYLES = Path("desktop/src/renderer/src/styles.css")


def test_workflow_studio_owns_the_full_workspace_grid() -> None:
    app = APP.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert 'v-show="!workflowPanelOpen"' in app
    assert 'v-if="operationPanelOpen && !workflowPanelOpen"' in app
    assert '!workflowPanelOpen.value && workspace.sessions.length > 0' in app
    assert '<KeepAlive>' in app
    assert "function toggleWorkflowPanel" in app
    assert ".workflow-library { grid-column: 2 / -1; grid-row: 1;" in styles


def test_workflow_studio_loads_catalog_and_preserves_edges_when_renaming() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    assert "desktopApi.workflowActions()" in source
    assert "function renameNode" in source
    assert "source: edge.source === previousId ? nextId" in source
    assert "create(true)" in source
    assert "loop.for_each" in source


def test_workflow_studio_requires_explicit_draft_and_risk_confirmation() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    assert "function runDraft" in source
    assert "draft: true" in source
    assert "selected.value.version && selected.value.version !== 'draft' ? { version: selected.value.version } : {}" in source
    assert "previewHasRisk" in source
    assert "confirmedRisks" in source
    assert "confirmed_risks: true" in source


def test_workflow_studio_declares_runtime_inputs() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    assert "function addWorkflowInput" in source
    assert "function removeWorkflowInput" in source
    assert "v-model=\"input.name\"" in source
    assert "inputs: workflowInputs.value" in source


def test_workflow_studio_configures_loop_references_retry_backoff_and_batch_sessions() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    assert "loopItemsMode" in source
    assert "loopItemsReference" in source
    assert "resultSources" in source
    assert "retry_backoff_seconds" in source
    assert "sessionIdsByDevice" in source
    assert "const targetSessionIds = selectedDeviceIds.value" in source


def test_workflow_canvas_renders_real_edges_and_marks_disconnected_nodes() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "const incomingEdgeByTarget" in source
    assert "const reachableNodeIds" in source
    assert "function hasIncomingEdge" in source
    assert "function isNodeDisconnected" in source
    assert "function setNodePredecessor" in source
    assert "function setNodeSuccessor" in source
    assert "selected.value.edges = [...(selected.value.edges || []), edge]" in source
    assert 'class="node-connector"' in source
    assert "disconnected: isNodeDisconnected(node)" in source
    assert "上游步骤" in source
    assert "下游步骤" in source
    assert "workflow-terminal" in source
    assert "未连接" in source
    assert "满足条件" in source
    assert "不满足条件" in source
    assert "const previewSteps = computed(() => canvasNodes.value.map" in source
    assert ".node-connector.connected i" in styles
    assert ".node-connector i::after" in styles
    assert ".node-connector.missing i" in styles
    assert ".workflow-node-card.disconnected" in styles
