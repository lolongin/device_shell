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


def test_workflow_surfaces_define_light_theme_tokens_and_overrides() -> None:
    styles = STYLES.read_text(encoding="utf-8")
    library = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    assert "--workflow-bg: #f7f9fc" in styles
    assert "--workflow-surface: #ffffff" in styles
    assert "--workflow-muted: #475569" in styles
    assert "--workflow-subtle: #64748b" in styles
    assert ':root[data-theme="light"] .workflow-node' in styles
    assert ':root[data-theme="light"] .workflow-action-catalog' in styles
    assert ':root[data-theme="light"] .workflow-properties input' in styles
    assert ':root[data-theme="light"] .workflow-script-test-result' in styles
    assert ':root[data-theme="light"] .workflow-library-body input' in styles
    assert ':global(:root[data-theme="light"]) .workflow-command-reference-menu' in library


def test_workflow_studio_loads_catalog_and_preserves_edges_when_renaming() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    editor = Path("desktop/src/renderer/src/composables/useWorkflowEditor.ts").read_text(encoding="utf-8")
    assert "desktopApi.workflowActions()" in source
    assert "function renameNode" in editor
    assert "source: edge.source === previousId ? nextId" in editor
    assert "openCreateDialog(true)" in source
    assert "loop.for_each" in source


def test_workflow_studio_names_new_workflows_and_allows_renaming() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    settings = Path("desktop/src/renderer/src/components/WorkflowSettingsPanel.vue").read_text(encoding="utf-8")
    management = Path("desktop/src/renderer/src/components/WorkflowManagementDialogs.vue").read_text(encoding="utf-8")

    assert "async function confirmCreate" in source
    assert 'v-model="state.createName.value"' in management
    assert ':disabled="!state.createName.value.trim() || creating"' in management
    assert 'v-model="workflow.name"' in settings
    assert "selected.value.name.trim()" in source


def test_workflow_studio_separates_script_management_and_shows_test_output() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    scripts = Path("desktop/src/renderer/src/composables/useWorkflowScripts.ts").read_text(encoding="utf-8")
    studio = Path("desktop/src/renderer/src/components/WorkflowScriptStudio.vue").read_text(encoding="utf-8")

    assert "<WorkflowScriptStudio" in source
    assert "workflow-script-studio" in studio
    assert "脚本资源" in studio
    assert "独立脚本编辑器" in studio
    assert "desktopApi.testWorkflowScript" in scripts
    assert "desktopApi.getTask" in scripts
    assert "controller.scriptTestDetails.value.stdout" in studio
    assert "controller.scriptTestDetails.value.stderr" in studio
    assert "controller.scriptTestDetails.value.exitCode" in studio
    assert "savedScriptSnapshots" in source
    assert "hasUnsavedScriptChanges.value && !await saveWorkflowScript()" in scripts
    assert "保存并测试" in studio


def test_workflow_script_creation_offers_named_templates() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    scripts = Path("desktop/src/renderer/src/composables/useWorkflowScripts.ts").read_text(encoding="utf-8")
    studio = Path("desktop/src/renderer/src/components/WorkflowScriptStudio.vue").read_text(encoding="utf-8")

    assert "workflowScriptTemplates" in scripts
    assert "Python 主函数" in scripts
    assert "PowerShell 参数脚本" in scripts
    assert "<section class=\"workflow-script-template-grid\"" in studio
    assert "async function confirmCreateWorkflowScript" in scripts
    assert "template.input_schema" in scripts


def test_workflow_script_nodes_render_schema_inputs_with_json_escape_hatch() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    script = Path("desktop/src/renderer/src/components/workflow-config/ScriptNodeConfig.vue").read_text(encoding="utf-8")

    assert "WorkflowNodeProperties" in source
    assert "scriptNodeInputMode" in script
    assert "updateScriptNodeInputField" in script
    assert "updateScriptNodeInputBoolean" in script
    assert "updateScriptNodeInputJson" in script
    assert "updateScriptNodeInputJsonEditor" in script
    assert "JSON.parse(value)" in script
    assert "变量引用必须单独作为完整值" in script
    assert "参数表单" in script
    assert "DEVICE_TUI_INPUT_JSON" in script
    assert "支持使用 <code>${inputs.xxx}</code> 引用流程输入" in script


def test_workflow_studio_panels_keep_independent_scroll_containers() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    shell = Path("desktop/src/renderer/src/components/WorkflowInspectorShell.vue").read_text(encoding="utf-8")
    script_studio_styles = Path("desktop/src/renderer/src/components/WorkflowScriptStudio.css").read_text(encoding="utf-8")

    assert ".workflow-script-list { min-height: 0; overflow: auto;" in script_studio_styles
    assert ".workflow-script-test-panel {" in script_studio_styles
    assert "min-height: 0; overflow: auto;" in script_studio_styles
    assert "<WorkflowInspectorShell" in source
    assert ".workflow-inspector-content" in shell

    assert "display: flex;" in shell
    assert "overflow-y: auto;" in shell
    assert "<WorkflowNodeProperties" in source


def test_step_settings_puts_long_configuration_in_its_own_scroll_container() -> None:
    shell = Path("desktop/src/renderer/src/components/WorkflowInspectorShell.vue").read_text(encoding="utf-8")

    assert "flex: 1 1 auto;" in shell
    assert "min-height: 0;" in shell
    assert "overflow-y: auto;" in shell
    assert "overflow: hidden;" in shell


def test_inspector_shell_is_the_only_scroll_owner_for_settings_content() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    shell = Path("desktop/src/renderer/src/components/WorkflowInspectorShell.vue").read_text(encoding="utf-8")

    assert "overflow-y: auto;" in shell
    assert ".workflow-input-editor { padding: 9px 16px; overflow: visible; }" in source
    assert ".workflow-runtime-inputs { padding: 9px 16px; overflow: visible; }" in source
    assert ".workflow-properties { min-height: 0; overflow: visible;" in source


def test_node_catalog_has_a_stable_visible_scrollbar() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")

    catalog = source.split(".workflow-studio-grid > .workflow-action-catalog {", 1)[1].split("}", 1)[0]
    assert "min-height: 0;" in catalog
    assert "height: 100%;" in catalog
    assert "overflow-y: auto;" in catalog
    assert "scrollbar-gutter: stable;" in catalog
    assert ".workflow-studio-grid > .workflow-action-catalog::-webkit-scrollbar" in source
    assert "grid-template-areas: 'catalog canvas inspector';" in source
    assert "grid-template-areas: 'catalog canvas' 'inspector inspector';" in source
    assert "grid-template-areas: 'catalog' 'canvas' 'inspector';" in source
    assert "grid-template-rows: minmax(0, min(34vh, 260px)) minmax(420px, 1fr) minmax(240px, 46vh);" in source
    assert ".workflow-studio-grid > .workflow-catalog-resizer {" in source


def test_workflow_settings_have_their_own_panel_module() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    settings = Path("desktop/src/renderer/src/components/WorkflowSettingsPanel.vue").read_text(encoding="utf-8")

    assert "<WorkflowSettingsPanel" in source
    assert "workflow-input-definition" in settings
    assert "workflow-runtime-inputs" in settings
    assert "update:inputsExpanded" in settings
    assert "update:outputsExpanded" in settings


def test_step_properties_fill_the_inspector_rail_instead_of_shrinking_to_content() -> None:
    properties = Path("desktop/src/renderer/src/components/workflow-config/WorkflowNodeProperties.vue").read_text(encoding="utf-8")

    assert "width: 100%;" in properties
    assert "box-sizing: border-box;" in properties
    assert "align-self: stretch;" in properties
    assert "align-self: start;" not in properties


def test_script_step_resource_can_be_edited_from_step_settings() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    script = Path("desktop/src/renderer/src/components/workflow-config/ScriptNodeConfig.vue").read_text(encoding="utf-8")

    assert "class=\"workflow-script-reference-notice\"" in script
    assert "aria-label=\"步骤脚本编辑器\"" in script
    assert "script.script = value" in script
    assert '@save-script="saveNodeScriptResource"' in source
    assert "selectedNodeScript?.script || getConfigString('script')" in script


def test_workflow_studio_manages_user_templates_and_renders_subworkflow_reference() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    advanced = Path("desktop/src/renderer/src/components/workflow-config/AdvancedNodeConfig.vue").read_text(encoding="utf-8")
    management = Path("desktop/src/renderer/src/components/WorkflowManagementDialogs.vue").read_text(encoding="utf-8")
    versions = Path("desktop/src/renderer/src/components/WorkflowVersionManager.vue").read_text(encoding="utf-8")

    assert "async function deleteWorkflowTemplate(template: WorkflowTemplate)" in source
    assert "await desktopApi.deleteWorkflowTemplate(template.id)" in source
    assert "!item.built_in" in management
    assert "workflow-version-manager" in versions
    assert "已被任务引用，可删除" in versions
    assert ':disabled="version.referenced"' not in versions
    assert "if (!selected.value || version.referenced) return" not in source
    assert "删除不会影响已创建的任务" in source
    assert "'${' + node.id + '.输出名}'" in advanced
    assert "`${node.id}.输出名`" not in advanced


def test_workflow_studio_requires_explicit_draft_and_risk_confirmation() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    preview = Path("desktop/src/renderer/src/components/WorkflowRunPreview.vue").read_text(encoding="utf-8")
    assert "function runDraft" in source
    assert "draft: true" in source
    assert "selected.value.version && selected.value.version !== 'draft' ? { version: selected.value.version } : {}" in source
    assert "previewHasRisk" in source
    assert "confirmedRisks" in preview
    assert "hasRisk && !confirmedRisks" in preview
    assert "update:confirmedRisks" in preview
    assert "confirmed_risks: true" in source
    assert "draft: selected.value.version === 'draft'" in source
    assert "inputSchema" in Path("desktop/src/renderer/src/components/workflow-config/GenericNodeConfig.vue").read_text(encoding="utf-8")


def test_workflow_run_panels_are_separate_presentation_components() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    flow_panel = Path("desktop/src/renderer/src/components/WorkflowFlowTestPanel.vue").read_text(encoding="utf-8")
    flow_styles = Path("desktop/src/renderer/src/components/WorkflowFlowTestPanel.css").read_text(encoding="utf-8")
    preview = Path("desktop/src/renderer/src/components/WorkflowRunPreview.vue").read_text(encoding="utf-8")
    preview_styles = Path("desktop/src/renderer/src/components/WorkflowRunPreview.css").read_text(encoding="utf-8")

    assert "<WorkflowFlowTestPanel" in source
    assert "<WorkflowRunPreview" in source
    assert "workflow-flow-test-panel" in flow_panel
    assert "workflow-flow-test-log" in flow_styles
    assert "workflow-preview-backdrop" in preview
    assert "preview-actions" in preview_styles
    assert "preview-risk-warning" in STYLES.read_text(encoding="utf-8")
    assert "desktopApi.getTask" in source


def test_flow_test_panel_shows_execution_process_without_overlapping_outputs_section() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    panel = Path("desktop/src/renderer/src/components/WorkflowFlowTestPanel.vue").read_text(encoding="utf-8")
    styles = Path("desktop/src/renderer/src/components/WorkflowFlowTestPanel.css").read_text(encoding="utf-8")

    assert "流程输出" not in panel
    assert "outputEntries" not in panel
    assert ":output-entries=" not in source
    assert "workflow-test-outputs" not in styles
    assert ".workflow-test-process-section { min-height: 0;" in styles
    assert "workflow-output-editor" in Path("desktop/src/renderer/src/components/WorkflowSettingsPanel.vue").read_text(encoding="utf-8")


def test_quick_workflow_runner_preserves_typed_input_defaults() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowRunDialog.vue").read_text(encoding="utf-8")

    assert "JSON.stringify(input.default, null, 2)" in source
    assert "Number.isFinite(parsed)" in source
    assert "Number.isInteger(parsed)" in source
    assert "input.type === 'number' ? 'any'" in source
    assert "requestedVersionMissing" in source
    assert "发布版本 v${props.initialVersion} 不存在或已被删除" in source


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
    editor = Path("desktop/src/renderer/src/composables/useWorkflowEditor.ts").read_text(encoding="utf-8")

    assert "function copySelectedNode" in editor
    assert "function pasteNode" in editor
    assert "function handleWorkflowKeyDown" in editor
    assert "event.key === 'Delete'" in editor
    assert "window.addEventListener('keydown', handleWorkflowKeyDown)" in editor
    assert "isEditableTarget" in editor


def test_task_workspace_uses_clear_workflow_step_labels_and_progress_context() -> None:
    source = Path("desktop/src/renderer/src/components/TaskWorkspace.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "const workflowActionLabels" in source
    assert "function taskCurrentStepLabel" in source
    assert "执行命令" in source
    assert "当前步骤" in source
    assert ".task-detail-summary" in styles


def test_task_workspace_separates_history_from_detail_without_inline_creation() -> None:
    source = Path("desktop/src/renderer/src/components/TaskWorkspace.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert 'class="task-ui-content"' in source
    assert 'class="task-ui-create"' not in source
    assert "创建 Workflow Task" not in source
    assert "if (task.status === 'failed') return '工作流失败'" in source
    assert ".task-ui-content {" in styles
    assert ".task-row b {" in styles
    task_row_status = styles.split("\n.task-row b {", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap;" in task_row_status


def test_workflow_studio_exposes_editable_runtime_inputs() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    settings = Path("desktop/src/renderer/src/components/WorkflowSettingsPanel.vue").read_text(encoding="utf-8")
    assert "workflowRuntimeInputs" in source
    assert "workflowInputValues" in source
    assert "function updateWorkflowInput" in source
    assert "运行参数" in settings
    assert "inputs: workflowRuntimeInputs.value" in source
    assert '<option value="file">本地文件</option>' in settings
    assert "这是本机源文件输入" in settings
    assert "async function chooseUploadSource" in source
    assert "设备目标路径" in settings
    assert "用户无需关心暂存目录" in settings


def test_workflow_contract_add_buttons_invoke_their_handlers() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    settings = Path("desktop/src/renderer/src/components/WorkflowSettingsPanel.vue").read_text(encoding="utf-8")

    assert "addWorkflowInput(); emit('update:inputsExpanded', true)" in settings
    assert "addWorkflowOutput(); emit('update:outputsExpanded', true)" in settings


def test_workflow_studio_configures_loop_references_retry_backoff_and_batch_sessions() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    assert "loopItemsMode" in source
    assert "loopItemsReference" in source
    assert "resultSources" in source
    assert "retry_backoff_seconds" in Path("desktop/src/renderer/src/components/workflow-config/WorkflowNodeProperties.vue").read_text(encoding="utf-8")
    assert "sessionIdsByDevice" in source
    assert "const targetSessionIds = selectedDeviceIds.value" in source


def test_loop_until_default_maximum_mode_uses_false_condition() -> None:
    source = Path("desktop/src/renderer/src/composables/useWorkflowEditor.ts").read_text(encoding="utf-8")

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
    advanced = Path("desktop/src/renderer/src/components/workflow-config/AdvancedNodeConfig.vue").read_text(encoding="utf-8")

    assert "variableValueSourceId" in source
    assert "variableValueField" in source
    assert "setVariableValueReference" in source
    assert "source.id" in advanced
    assert "variableExtractEnabled" in source
    assert "delete selectedNode.value.config.extract" in source
    assert "匹配规则" in advanced
    assert 'value="match"' in advanced
    assert 'value="line"' in advanced
    assert "捕获组" in advanced
    assert "${source.id}.${field.name}" in advanced


def test_variable_node_uses_one_value_entry_with_collapsed_reference_helper() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    advanced = Path("desktop/src/renderer/src/components/workflow-config/AdvancedNodeConfig.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert 'class="workflow-variable-reference"' in advanced
    assert '<summary>插入上游引用</summary>' in advanced
    assert 'class="workflow-variable-value"' not in advanced
    assert "grid-template-columns: minmax(0, 1fr) 116px" not in styles


def test_workflow_reference_selectors_use_catalog_output_schema() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    advanced = Path("desktop/src/renderer/src/components/workflow-config/AdvancedNodeConfig.vue").read_text(encoding="utf-8")
    catalog = Path("desktop/src/renderer/src/components/workflow-config/actionCatalog.ts").read_text(encoding="utf-8")

    assert "type OutputField" in source
    assert "outputFieldsFromSchema" in source
    assert "function outputFieldsForAction" in source
    assert "function outputFieldsForNode" in source
    assert "fields: outputFieldsForNode(item)" in source
    assert 'v-for="field in source.fields"' in advanced
    assert "fieldLabel(field.name)" in advanced
    assert "`${source.id}-${field.name}`" in advanced
    assert "source.id}-version" not in advanced
    assert "Object.keys(properties as Record<string, unknown>)" in catalog


def test_workflow_action_cards_use_the_backend_catalog_as_their_source() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    catalog = Path("desktop/src/renderer/src/components/workflow-config/actionCatalog.ts").read_text(encoding="utf-8")

    assert "const actions: ActionItem[] = []" in source
    assert "actionItemsFromCatalog(catalog.actions)" in source
    assert "inputSchema," in catalog
    assert "outputSchema," in catalog
    assert "risk: entry.risk || 'low'" in catalog
    assert "fallbackOutputFields" not in source
    assert "baseAction('device.command'" not in source


def test_generic_node_configuration_uses_catalog_input_schema() -> None:
    panel = Path("desktop/src/renderer/src/components/workflow-config/WorkflowNodeProperties.vue").read_text(encoding="utf-8")
    generic = Path("desktop/src/renderer/src/components/workflow-config/GenericNodeConfig.vue").read_text(encoding="utf-8")
    command = Path("desktop/src/renderer/src/components/workflow-config/CommandNodeConfig.vue").read_text(encoding="utf-8")
    script = Path("desktop/src/renderer/src/components/workflow-config/ScriptNodeConfig.vue").read_text(encoding="utf-8")

    assert "<GenericNodeConfig" in panel
    assert "props.actions?.find((item) => item.id === props.node.action_id)?.inputSchema" in generic
    assert "schema.required" in generic
    assert "JSON.parse(target.value)" in generic
    assert "field in actions?.find((item) => item.id === node.action_id)?.outputFields" in command
    assert "field in actions?.find((item) => item.id === node.action_id)?.outputFields" in script

    assert "最小输入：指定本机文件或选择文件入参" in generic
    assert "上传文件来源 <em>必填</em>" in generic
    assert "选择上传文件的流程入参" in generic
    assert "选择设备目标路径的流程入参" in generic
    assert "选择覆盖开关的流程入参" in generic
    assert ':workflow-inputs="selected.inputs || []"' in Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    assert "输入与输出" in panel
    assert "selectedAction.outputFields" in panel


def test_workflow_advanced_nodes_use_a_dedicated_configuration_module() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    advanced = Path("desktop/src/renderer/src/components/workflow-config/AdvancedNodeConfig.vue").read_text(encoding="utf-8")

    assert "<AdvancedNodeConfig" in source
    assert "onSelectSubworkflow" in advanced
    assert "condition-builder" in advanced
    assert "loopChildActions" in advanced
    assert "workflow-variable-reference" in advanced
    assert "catalogError" in source
    assert "动作目录加载失败，请检查后端连接后重试。" in source


def test_command_editor_supports_visual_variable_insertion_and_preview() -> None:
    source = Path("desktop/src/renderer/src/components/workflow-config/CommandNodeConfig.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "const commandEditor = ref<HTMLTextAreaElement | null>(null)" in source
    assert "commandReferences" in source
    assert "function insertCommandReference(reference: string)" in source
    assert "selectionStart" in source
    assert "commandPreview" in source
    assert "插入变量" in source
    assert "运行时解析" in source
    assert "workflow-command-reference-menu" in source


def test_variable_node_property_heading_does_not_repeat_action_name() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    properties = Path("desktop/src/renderer/src/components/workflow-config/BaseNodeConfig.vue").read_text(encoding="utf-8")

    assert "node.action_id === 'variable.set'" in properties
    assert "selectedAction.label" in properties
    assert "<WorkflowNodeProperties" in source


def test_variable_node_editor_hides_shared_advanced_controls() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    properties = Path("desktop/src/renderer/src/components/workflow-config/WorkflowNodeProperties.vue").read_text(encoding="utf-8")

    assert "<BaseNodeConfig" in properties
    assert "node.action_id !== 'variable.set'" in Path("desktop/src/renderer/src/components/workflow-config/BaseNodeConfig.vue").read_text(encoding="utf-8")
    assert "WorkflowNodeProperties" in source


def test_workflow_canvas_renders_real_edges_and_marks_disconnected_nodes() -> None:
    source = Path("desktop/src/renderer/src/components/WorkflowLibrary.vue").read_text(encoding="utf-8")
    editor = Path("desktop/src/renderer/src/composables/useWorkflowEditor.ts").read_text(encoding="utf-8")
    canvas = Path("desktop/src/renderer/src/components/WorkflowCanvas.vue").read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")

    assert "const incomingEdgeByTarget" in source
    assert "const reachableNodeIds" in source
    assert "function hasIncomingEdge" in source
    assert "function isNodeDisconnected" in source
    assert "function setNodePredecessor" in editor
    assert "function setNodeSuccessor" in editor
    assert "selected.value.edges = [...(selected.value.edges || []), edge]" in editor
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
    editor = Path("desktop/src/renderer/src/composables/useWorkflowEditor.ts").read_text(encoding="utf-8")
    canvas = Path("desktop/src/renderer/src/components/WorkflowCanvas.vue").read_text(encoding="utf-8")

    assert "function findInsertEdge" in editor
    assert "const insertEdge = position ? findInsertEdge(position) : null" in editor
    assert "insertEdge.source" in editor
    assert "insertEdge.target" in editor
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
    advanced = Path("desktop/src/renderer/src/components/workflow-config/AdvancedNodeConfig.vue").read_text(encoding="utf-8")

    assert "const nonExecutableLoopActions = new Set" in source
    assert "const loopChildActions = computed" in source
    assert "!nonExecutableLoopActions.has(item.id)" in source
    assert 'v-for="action in loopChildActions"' in advanced
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


def test_task_records_keep_position_when_a_snapshot_is_refreshed() -> None:
    source = Path("desktop/src/renderer/src/stores/workspace.ts").read_text(encoding="utf-8")
    task_workspace = Path("desktop/src/renderer/src/components/TaskWorkspace.vue").read_text(encoding="utf-8")

    assert "function updateTaskSnapshot(task: TaskRecord, moveToFront = false)" in source
    assert "tasks.value.splice(index, 1, task)" in source

    get_task_start = source.index("async function getTask(")
    get_task_end = source.index("\n  async function syncTaskSession", get_task_start)
    get_task_source = source[get_task_start:get_task_end]
    assert "updateTaskSnapshot(response.task)" in get_task_source
    assert "tasks.value = [response.task, ...tasks.value.filter" not in get_task_source

    assert '@keydown.space.prevent="chooseTask(task)"' in task_workspace
    assert ":aria-current=\"task.id === workspace.activeTaskId ? 'true' : undefined\"" in task_workspace
