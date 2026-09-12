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
