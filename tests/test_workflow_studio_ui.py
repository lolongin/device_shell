import json
from pathlib import Path
import subprocess


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
    assert "draft: selected.value.version === 'draft'" in source
    assert "send_enter" in source


def test_workflow_run_paths_persist_the_current_canvas_before_execution() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert "async function persistCurrentWorkflow" in source
    assert source.count("if (!await persistCurrentWorkflow()) return") >= 4


def test_workflow_publish_persists_current_canvas_before_publishing() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    publish_start = source.index("async function publish(): Promise<void>")
    publish_end = source.index("\nasync function remove(): Promise<void>", publish_start)
    publish_source = source[publish_start:publish_end]

    assert "if (!await persistCurrentWorkflow()) return" in publish_source
    assert publish_source.index("persistCurrentWorkflow") < publish_source.index("publishWorkflowDefinition")


def test_workflow_studio_does_not_persist_invalid_drafts() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    save_start = source.index("async function save(): Promise<void>")
    save_end = source.index("\nasync function publish(): Promise<void>", save_start)
    save_source = source[save_start:save_end]

    assert "const canSave = computed" in source
    assert ':disabled="!canSave"' in source
    assert "await validate()" in save_source
    assert save_source.index("await validate()") < save_source.index("persistCurrentWorkflow")
    assert "if (issues.value.length)" in save_source


def test_workflow_studio_supports_node_copy_paste_and_delete_shortcuts() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert "function copySelectedNode" in source
    assert "function pasteNode" in source
    assert "function handleWorkflowKeyDown" in source
    assert "event.key === 'Delete'" in source
    assert "window.addEventListener('keydown', handleWorkflowKeyDown)" in source
    assert "isEditableTarget" in source


def test_task_workspace_uses_clear_workflow_step_labels_and_progress_context() -> None:
    source = Path("desktop/src/renderer/src/components/TaskWorkspace.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "const workflowActionLabels" in source
    assert "function taskCurrentStepLabel" in source
    assert "执行命令" in source
    assert "当前步骤" in source
    assert ".task-detail-summary" in styles


def test_workflow_studio_exposes_editable_runtime_inputs() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    assert "workflowRuntimeInputs" in source
    assert "workflowInputValues" in source
    assert "function updateWorkflowInput" in source
    assert "运行参数" in source
    assert "inputs: workflowRuntimeInputs.value" in source


def test_workflow_studio_configures_loop_references_retry_backoff_and_batch_sessions() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    assert "loopItemsMode" in source
    assert "loopItemsReference" in source
    assert "resultSources" in source
    assert "retry_backoff_seconds" in source
    assert "sessionIdsByDevice" in source
    assert "const targetSessionIds = selectedDeviceIds.value" in source


def test_loop_until_default_maximum_mode_uses_false_condition() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    default_line = next(
        line for line in source.splitlines()
        if "if (actionId === 'loop.until') return" in line
    )

    assert 'condition: "False"' in default_line


def test_loop_until_migrates_historical_true_condition_without_changing_explicit_modes() -> None:
    module = Path("desktop/src/renderer/src/utils/loopUntil.ts").resolve().as_uri()
    script = f"""
      import {{ normalizeLoopUntilNodes }} from {json.dumps(module)}
      const nodes = [
        {{ action_id: 'loop.until', config: {{ condition: 'True' }} }},
        {{ action_id: 'loop.until', config: {{ condition: ' true ' }} }},
        {{ action_id: 'loop.until', config: {{ condition: "result.status == 'succeeded'" }} }},
        {{ action_id: 'utility.condition', config: {{ condition: 'True' }} }},
      ]
      normalizeLoopUntilNodes(nodes)
      process.stdout.write(JSON.stringify(nodes.map(node => node.config.condition)))
    """

    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == [
        "False",
        "False",
        "result.status == 'succeeded'",
        "True",
    ]


def test_workflow_risk_preview_checks_until_loop_child_actions() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert "function nodeHasHighRiskAction" in source
    assert "['loop.for_each', 'loop.until'].includes(node.action_id)" in source
    assert "return nodes.some(nodeHasHighRiskAction)" in source


def test_workflow_studio_configures_generic_variable_extraction_without_extra_actions() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert "variableValueSourceId" in source
    assert "variableValueField" in source
    assert "setVariableValueReference" in source
    assert "`${source.id}`" in source
    assert "variableExtractEnabled" in source
    assert "delete selectedNode.value.config.extract" in source
    assert "匹配规则" in source
    assert 'value="match"' in source
    assert 'value="line"' in source
    assert "捕获组" in source
    assert "${source}.${field}" in source


def test_variable_node_uses_one_value_entry_with_collapsed_reference_helper() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert 'class="workflow-variable-reference"' in source
    assert '<summary>插入上游引用</summary>' in source
    assert 'class="workflow-variable-value"' not in source
    assert "grid-template-columns: minmax(0, 1fr) 116px" not in styles


def test_workflow_reference_selectors_use_catalog_output_schema() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert "type OutputField" in source
    assert "function outputFieldsFromSchema" in source
    assert "function outputFieldsForAction" in source
    assert "fields: outputFieldsForAction(item.action_id)" in source
    assert 'v-for="field in source.fields"' in source
    assert "fieldLabel(field.name)" in source
    assert "`${source.id}-${field.name}`" in source
    assert "source.id}-version" not in source


def test_workflow_reference_fallback_includes_execution_identity_fields() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert "'device.command': ['output', 'status', 'execution_id', 'operation_id', 'session_id', 'device_id', 'cli_status', 'evidence']" in source
    assert "'file.upload': ['status', 'operation_id', 'verified', 'skipped', 'skip_reason', 'output', 'evidence']" in source


def test_command_editor_supports_visual_variable_insertion_and_preview() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "const commandEditor = ref<HTMLTextAreaElement | null>(null)" in source
    assert "const commandReferences = computed" in source
    assert "function insertCommandReference(reference: string)" in source
    assert "selectionStart" in source
    assert "commandPreview" in source
    assert "插入变量" in source
    assert "运行时解析" in source
    assert "workflow-command-reference-menu" in source


def test_variable_node_property_heading_does_not_repeat_action_name() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert "selectedNode.action_id === 'variable.set' ? '设置变量' : '步骤设置'" in source
    assert '<small v-if="selectedNode.action_id !== \'variable.set\'">{{ selectedAction?.label }}</small>' in source


def test_variable_node_editor_hides_shared_advanced_controls() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert '<template v-if="selectedNode.action_id !== \'variable.set\'">' in source
    assert source.count("selectedNode.action_id !== 'variable.set'") >= 5
    assert '<button v-if="selectedNode.action_id !== \'variable.set\'"' in source


def test_workflow_canvas_renders_real_edges_and_marks_disconnected_nodes() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    canvas = Path("desktop/src/renderer/src/components/WorkflowCanvas.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "const incomingEdgeByTarget" in source
    assert "const reachableNodeIds" in source
    assert "function hasIncomingEdge" in source
    assert "function isNodeDisconnected" in source
    assert "function setNodePredecessor" in source
    assert "function setNodeSuccessor" in source
    assert "selected.value.edges = [...(selected.value.edges || []), edge]" in source
    assert "<WorkflowCanvas" in source
    assert "onConnect" in canvas
    assert "onNodeDragStop" in canvas
    assert "screenToFlowCoordinate" in canvas
    assert ':nodes-draggable="props.interactive !== false"' in canvas
    assert ':nodes-connectable="props.interactive !== false"' in canvas
    assert "fit-view-on-init" in canvas
    assert ".workflow-canvas-container" in source


def test_workflow_canvas_drop_inserts_new_node_into_the_dropped_edge() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    canvas = Path("desktop/src/renderer/src/components/WorkflowCanvas.vue").read_text(encoding="utf-8")

    assert "function findInsertEdge" in source
    assert "const insertEdge = position ? findInsertEdge(position) : null" in source
    assert "insertEdge.source" in source
    assert "insertEdge.target" in source
    assert "emit('nodeAdd', actionId" in canvas


def test_workflow_issue_messages_cover_node_library_validation_codes() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    expected_codes = (
        "invalid_expression",
        "invalid_terminal_match_mode",
        "invalid_terminal_pattern",
        "invalid_variable_extract",
        "invalid_variable_extract_mode",
        "invalid_variable_field",
        "invalid_loop_items",
        "invalid_loop_action",
        "invalid_loop_condition",
        "duplicate_node_id",
        "duplicate_input_name",
        "missing_workflow_input",
        "invalid_workflow_input_type",
    )

    for code in expected_codes:
        assert f"issue.code === '{code}'" in source

    for phrase in ("表达式", "终端匹配", "循环列表", "输出字段", "流程输入"):
        assert phrase in source


def test_workflow_loop_child_selectors_hide_non_executable_actions() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert "const nonExecutableLoopActions = new Set" in source
    assert "const loopChildActions = computed" in source
    assert "!nonExecutableLoopActions.has(item.id)" in source
    assert 'v-for="action in loopChildActions"' in source
    assert "actions.filter((item) => !['loop.for_each', 'loop.until', 'utility.condition', 'utility.confirm'].includes(item.id))" not in source


def test_workflow_node_state_uses_final_settings_and_current_required_fields() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    assert "const requiredConfigByAction" in source
    assert "function nodeSettings(node: NodeItem)" in source
    assert "function hasRequiredConfigValue" in source
    assert "{ ...node.config, ...(node.input_mapping || {}) }" in source
    assert "'device.connect'" not in source[source.index("const requiredConfigByAction"):source.index("function nodeSettings")]
    assert "'device.ssh'" not in source[source.index("const requiredConfigByAction"):source.index("function nodeSettings")]
    assert "'device.telnet'" not in source[source.index("const requiredConfigByAction"):source.index("function nodeSettings")]
    assert "'utility.wait': ['seconds']" in source
    assert "'terminal.wait': ['pattern']" in source
    assert "'utility.confirm': ['prompt']" in source
    assert "'loop.for_each': ['items', 'action_id']" in source
    assert "'loop.until': ['action_id', 'condition']" in source
    assert "aliases = ['source', 'source_path']" in source
    assert "aliases = ['destination', 'destination_path']" in source


def test_task_workspace_localizes_workflow_input_resolution_errors() -> None:
    source = Path("desktop/src/renderer/src/components/TaskWorkspace.vue").read_text(encoding="utf-8")

    assert "unresolved_task_input" in source
    assert "流程输入引用无效" in source
    assert "请检查节点依赖和输出字段配置" in source
