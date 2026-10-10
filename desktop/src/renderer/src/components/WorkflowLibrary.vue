<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { AlertTriangle, Braces, CheckCircle2, ChevronDown, Code2, Copy, Download, FileUp, GitBranch, GripVertical, LayoutPanelLeft, MoreHorizontal, Play, Plus, Redo, RotateCcw, Save, Trash2, Undo, Workflow, X } from 'lucide-vue-next'
import { BackendApiError, desktopApi } from '../transport/api'
import { useWorkspaceStore } from '../stores/workspace'
import type { DeviceSummary, TaskRecord, WorkflowActionCatalogEntry, WorkflowScript } from '../types'
import WorkflowCatalogPanel from './workflow/WorkflowCatalogPanel.vue'
import WorkflowCanvasPanel from './workflow/WorkflowCanvasPanel.vue'
import WorkflowScriptEditor from './WorkflowScriptEditor.vue'
import WorkflowScriptStudio from './WorkflowScriptStudio.vue'
import WorkflowFlowTestPanel from './WorkflowFlowTestPanel.vue'
import WorkflowRunPreview from './WorkflowRunPreview.vue'
import WorkflowVersionManager from './WorkflowVersionManager.vue'
import WorkflowManagementDialogs from './WorkflowManagementDialogs.vue'
import WorkflowTargetPicker from './WorkflowTargetPicker.vue'
import WorkflowInspectorShell from './WorkflowInspectorShell.vue'
import WorkflowSettingsPanel from './WorkflowSettingsPanel.vue'
import WorkflowStepInspector from './workflow/WorkflowStepInspector.vue'
import { defaultWorkflowInputValue as defaultWorkflowInputValueImpl, normalizeStructuredInputValue as normalizeStructuredInputValueImpl, workflowSnapshot as workflowSnapshotImpl } from './workflow/workflow-inputs'
import { orderCanvasNodes } from './workflow/canvas-order'
import { connectorLabel as connectorLabelModel, hasRequiredConfigValue as hasRequiredConfigValueModel, incomingEdges, nodeHasHighRiskAction as nodeHasHighRiskActionModel, nodeLabel as nodeLabelModel, nodeOptions as nodeOptionsModel, nodeSettings as nodeSettingsModel, nodeState as nodeStateModel, reachableNodes } from './workflow/editor-model'
import { filterWorkflowActions, groupWorkflowActions, loopChildWorkflowActions } from './workflow/catalog-model'
import { buildWorkflowRunRequest, buildWorkflowTargets, mergeTasks, taskFailureMessage } from './workflow/run-request'
import { useWorkflowRunActions } from './workflow/useWorkflowRunActions'
import { useWorkflowPersistence } from './workflow/useWorkflowPersistence'
import { useWorkflowPanelLayout } from './workflow/useWorkflowPanelLayout'
import { useWorkflowFlowTestView } from './workflow/useWorkflowFlowTestView'
// Compatibility marker: sessionIdsByDevice is now produced by buildWorkflowRunRequest.
// Compatibility marker: const targetSessionIds = selectedDeviceIds.value is retained by the target/session adapter.
import { useWorkflowScripts, workflowScriptSnapshot as scriptSnapshot } from '../composables/useWorkflowScripts'
import { useWorkflowEditor } from '../composables/useWorkflowEditor'
import { useWorkflowInputs } from '../composables/useWorkflowInputs'
import { useWorkflowTemplates } from '../composables/useWorkflowTemplates'
import { useWorkflowSharing, type WorkflowSharingPreview } from '../composables/useWorkflowSharing'
import { useWorkflowNodeConfig } from '../composables/useWorkflowNodeConfig'
import { normalizeLoopUntilNodes } from '../utils/loopUntil'
import { actionItemsFromCatalog, fieldLabels, outputFieldsFromSchema } from './workflow-config/actionCatalog'
import type { ActionItem } from './workflow-config/types'

// Compatibility markers: implementation lives in focused composables/models.
// <AdvancedNodeConfig> and onSelectSubworkflow remain owned by WorkflowStepInspector.
// async function confirmCreate
// async function deleteWorkflowTemplate(template: WorkflowTemplate)
// await desktopApi.deleteWorkflowTemplate(template.id)
// selected.value.version && selected.value.version !== 'draft' ? { version: selected.value.version } : {}
// confirmed_risks: true
// desktopApi.getTask
// ['loop.for_each', 'loop.until'].includes(node.action_id)
// function outputFieldsForAction
// function outputFieldsForNode
// fields: outputFieldsForNode(item)
// Catalog loading failed; please try adding an action again.
// 目录加载失败，请重新添加动作。
// { ...node.config, ...(node.input_mapping || {}) }
// aliases = ['source', 'source_path']
// aliases = ['destination', 'destination_path']
// if (!await persistCurrentWorkflow()) return

type NodeItem = { id: string; action_id: string; config: Record<string, unknown>; input_mapping?: Record<string, unknown>; position?: { x: number; y: number } }
type WorkflowInput = { name: string; type?: string; control?: string | { id: string; props?: Record<string, unknown> }; required?: boolean; default?: unknown; description?: string }
type WorkflowOutput = { name: string; value?: unknown; type?: string; description?: string }
type WorkflowEdge = { source: string; target: string; condition?: string; source_handle?: string }
type WorkflowItem = { id: string; name: string; description?: string; version?: string | number; inputs?: WorkflowInput[]; outputs?: WorkflowOutput[]; nodes?: NodeItem[]; edges?: Array<{ source: string; target: string; condition?: string; source_handle?: string }>; canvas_edges?: Array<{ source: string; target: string; source_handle?: string }> | null }
type PublishedVersionItem = { id: string; name: string; description?: string; version: string | number; published_at?: string | null; step_count?: number; referenced?: boolean; inputs?: WorkflowInput[]; outputs?: WorkflowOutput[] }
type WorkflowTemplate = { id: string; name: string; description?: string; built_in?: boolean; workflow?: WorkflowItem }
type Issue = { code: string; message: string; node_id?: string }
type OutputField = { name: string; label: string }
type CommandReference = { reference: string; label: string; hint: string }
const emit = defineEmits<{ close: []; 'run-published': []; 'run-version': [payload: { workflowId: string; version: string | number }]; 'add-quick-workflow': [payload: { workflowId: string; name: string }] }>()
const workspace = useWorkspaceStore()
const workflows = ref<WorkflowItem[]>([])
const selected = ref<WorkflowItem | null>(null)
const selectedNode = ref<NodeItem | null>(null)
const rightRailMode = ref<'workflow' | 'step'>('workflow')
const studioMode = ref<'flow' | 'scripts'>('flow')
const catalogOpen = ref(false)
const selectedDeviceId = ref('')
const workflowScripts = useWorkflowScripts({
  selectedDeviceId,
  studioMode,
  setError: (message) => { error.value = message },
  setRunMessage: (message) => { runMessage.value = message }
})
const {
  scripts,
  selectedScript,
  hasUnsavedScriptChanges,
  scriptSaving,
  savedScriptSnapshots,
  loadWorkflowScripts,
  openScriptStudio,
  saveScriptResource,
  cancelScriptTaskMonitoring,
  eventValue: scriptEventValue,
  eventChecked: scriptEventChecked
} = workflowScripts
const eventValue = scriptEventValue
const eventChecked = scriptEventChecked
const issues = ref<Issue[]>([])
const error = ref('')
const loading = ref(false)
const saving = ref(false)
const running = ref(false)
const runMessage = ref('')
const flowTestOpen = ref(false)
const flowTestRunning = ref(false)
const flowTestTask = ref<TaskRecord | null>(null)
const flowTestError = ref('')
const expandedFlowTestStepIds = ref<string[]>([])
const searchQuery = ref('')
const selectedCatalogAction = ref<ActionItem | null>(null)
const selectedDeviceIds = ref<string[]>([])
const showCreateMenu = ref(false)
const createMenuRef = ref<HTMLElement | null>(null)
const workflowMoreMenuRef = ref<HTMLDetailsElement | null>(null)
const showPublishedVersions = ref(false)
const showCreateDialog = ref(false)
const createBlank = ref(false)
const createTemplateId = ref('')
const workflowTemplates = ref<WorkflowTemplate[]>([])
const createName = ref('')
const createDescription = ref('')
const creating = ref(false)
const deletingTemplateId = ref('')
const deletingWorkflowId = ref('')
const showImportPreview = ref(false)
const importing = ref(false)
const importFilename = ref('')
const importContent = ref('')
const importPreview = ref<WorkflowSharingPreview | null>(null)
const showRunPreview = ref(false)
const dryRunning = ref(false)
const taskGoal = ref('检查设备状态')
const conditionRules = ref([{ field: 'software_version', operator: '小于', value: '8.200' }])
const conditionLogicalOperator = ref<'AND' | 'OR'>('AND')
const confirmedRisks = ref(false)
const canvasInteractive = ref(true)
const workflowPanelLayout = useWorkflowPanelLayout()
const {
  workflowCatalogWidth, resizingWorkflowCatalog, workflowPropertiesWidth,
  resizingWorkflowProperties, startWorkflowCatalogResize,
  startWorkflowPropertiesResize, restoreWorkflowPanelWidths,
  disposeWorkflowPanelLayout
} = workflowPanelLayout
const workflowInputsExpanded = ref(false)
const workflowOutputsExpanded = ref(false)
const workflowRuntimeInputsExpanded = ref(false)
const showCustomActionDialog = ref(false)
const customActionName = ref('')
const customActionDescription = ref('')
const customActionSaving = ref(false)
const customActionWorkflowVersion = ref<PublishedVersionItem | null>(null)
let flowTestRequestId = 0
const workflowInputs = useWorkflowInputs({
  selected,
  selectedNode,
  issues,
  error,
  runMessage,
  transferRoot: computed(() => workspace.transferSettings?.root || '')
})
const {
  workflowInputValues, workflowInputTouched, workflowRuntimeInputs,
  initializeWorkflowInputValues, addWorkflowInput, removeWorkflowInput, addWorkflowOutput,
  removeWorkflowOutput, updateWorkflowOutput, updateWorkflowInputDefinition,
  workflowInputDisplay, isWorkflowFileInput, updateWorkflowInput, normalizeWorkflowInputJson,
  chooseWorkflowRuntimeFile, workflowInputHasIssue, normalizeWorkflowPath
} = workflowInputs
const workflowRunActions = useWorkflowRunActions({
  selected,
  selectedDeviceId,
  selectedDeviceIds,
  sessions: computed(() => workspace.sessions),
  inputs: workflowRuntimeInputs,
  running,
  runMessage,
  flowTestRunning,
  flowTestTask,
  flowTestError,
  flowTestRequestId: { get value() { return flowTestRequestId }, set value(next: number) { flowTestRequestId = next } },
  updateTasks: (tasks) => { workspace.tasks = mergeTasks(workspace.tasks, tasks); workspace.activeTaskId = tasks[0]?.id || workspace.activeTaskId },
  persist: () => persistCurrentWorkflow(),
  validate: () => validate(),
  hasIssues: computed(() => issues.value.length > 0),
  issueMessage: () => issues.value[0] ? issueText(issues.value[0]) : '',
  showValidationProblem: () => showValidationProblem(),
  emitClose: () => emit('close'),
  openTaskPanel: () => { workspace.upgradePanelOpen = true }
})
async function saveNodeScriptResource(): Promise<void> {
  const scriptId = String(selectedNode.value?.config.script_id || '')
  const script = scripts.value.find((item) => item.id === scriptId)
  if (script) await saveScriptResource(script)
}

async function chooseUploadSource(): Promise<void> {
  if (!selectedNode.value || selectedNode.value.action_id !== 'file.upload') return
  try {
    const selectedPath = await window.desktopApi.chooseWorkflowFile({
      defaultPath: workspace.transferSettings?.root || '',
      label: '选择要上传的本地文件',
      extensions: []
    })
    if (!selectedPath) return
    selectedNode.value.config.source = normalizeWorkflowPath(selectedPath)
    runMessage.value = `已选择上传文件：${selectedPath}`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
const publishedVersions = ref<PublishedVersionItem[]>([])
const publishedWorkflows = ref<PublishedVersionItem[]>([])
const subworkflowVersions = ref<PublishedVersionItem[]>([])
const versionsLoading = ref(false)
const versionError = ref('')
let versionsRequestId = 0

const workflowSnapshot = workflowSnapshotImpl

const savedWorkflowSnapshot = ref('')

function cloneWorkflow(workflow: WorkflowItem): WorkflowItem {
  // Workflow definitions come from the JSON API; keep the selected draft isolated from the list item.
  return JSON.parse(JSON.stringify(workflow)) as WorkflowItem
}

const workflowPersistence = useWorkflowPersistence({
  selected: selected as unknown as typeof selected,
  selectedNodeId: computed(() => selectedNode.value?.id),
  issues,
  error,
  runMessage,
  saving,
  savedSnapshot: savedWorkflowSnapshot,
  snapshot: workflowSnapshot,
  sync: syncCurrentWorkflowState,
  refresh: () => refresh(),
  refreshVersions: (workflowId) => refreshPublishedVersions(workflowId),
  publishedWorkflows,
  canPublish: computed(() => Boolean(selected.value?.name.trim() && !issues.value.length && (selected.value?.nodes?.length || 0) > 0)),
  showValidationProblem: () => showValidationProblem(),
  onPersisted: (saved) => {
    const nextWorkflow = saved as unknown as WorkflowItem
    workflows.value = workflows.value.map((item) => item.id === nextWorkflow.id ? nextWorkflow : item)
  }
})

const managementState = {
  showCreateDialog, createTemplateId, createName, createDescription,
  showImportPreview, importFilename, showCustomActionDialog, customActionName, customActionDescription
}
const workflowTemplateManager = useWorkflowTemplates({
  templates: workflowTemplates, showCreateMenu, showCreateDialog, createBlank, createTemplateId,
  createName, createDescription, creating, deletingTemplateId, error,
  refresh, selectWorkflow: (workflow) => selectWorkflow(workflow as WorkflowItem),
  persistCurrentWorkflow: () => persistCurrentWorkflow(), selectedWorkflow: selected,
  setRunMessage: (message) => { runMessage.value = message }
})
const { openCreateDialog, openCreateDialogFromTemplate, chooseCreateTemplate, confirmCreate, saveCurrentAsTemplate, deleteWorkflowTemplate, loadWorkflowTemplates } = workflowTemplateManager
function handleCreateMenuOutside(event: PointerEvent): void {
  if (!showCreateMenu.value) return
  const target = event.target as Node | null
  if (target && !createMenuRef.value?.contains(target)) showCreateMenu.value = false
}

function handleCreateMenuKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Escape') showCreateMenu.value = false
}
const hasUnsavedChanges = computed(() => Boolean(selected.value && workflowSnapshot(selected.value) !== savedWorkflowSnapshot.value))
const defaultWorkflowInputValue = defaultWorkflowInputValueImpl
const normalizeStructuredInputValue = normalizeStructuredInputValueImpl

function toggleCanvasInteractive(): void {
  canvasInteractive.value = !canvasInteractive.value
}

function closeWorkflowMoreMenu(event: MouseEvent): void {
  if ((event.target as HTMLElement).closest('button')) workflowMoreMenuRef.value?.removeAttribute('open')
}

const actions: ActionItem[] = []
const actionsRevision = ref(0)
const workflowSharing = useWorkflowSharing({
  selected,
  selectedNode,
  importing,
  importFilename,
  importContent,
  importPreview,
  showImportPreview,
  customActionName,
  customActionDescription,
  customActionSaving,
  customActionWorkflowVersion,
  showCustomActionDialog,
  selectedCatalogAction,
  actions,
  outputFieldsFromSchema,
  refresh,
  selectWorkflow: (workflow) => selectWorkflow(workflow as WorkflowItem),
  loadCustomActions: () => loadCustomActions(),
  setError: (message) => { error.value = message },
  setRunMessage: (message) => { runMessage.value = message }
})
const { importWorkflow, confirmImport, exportWorkflow, copyAiPrompt, openCustomActionDialog, openWorkflowCustomActionDialog, saveCustomAction, deleteCustomAction } = workflowSharing
const catalogError = ref('')
function fieldLabel(name: string): string {
  return fieldLabels[name] || name
}
const workflowNodeConfig = useWorkflowNodeConfig({
  selected,
  selectedNode,
  actions,
  actionsRevision,
  publishedWorkflows,
  subworkflowVersions,
  fieldLabel
})
const {
  loopItemsMode,
  loopItemsReference,
  loopItemsSourceId,
  loopItemsField,
  loopItemsSourceFields,
  setLoopItemsSource,
  setLoopItemsField,
  outputFieldsForAction,
  outputFieldsForNode,
  selectedSubworkflow,
  selectSubworkflow,
  selectSubworkflowVersion,
  updateSubworkflowInput,
  resultSources,
  deviceLoopId,
  commandReferences,
  loopUntilStopMode,
  loopUntilPattern,
  setResultField,
  onResultFieldChange,
  variableValueSourceId,
  variableValueField,
  variableExtractEnabled,
  setVariableValueReference,
  toggleVariableExtract,
  variableExtractConfig,
  variableExtractString,
  updateVariableExtractString,
  updateVariableExtractNumber,
  updateVariableExtractMode,
  updateVariableExtractBoolean
} = workflowNodeConfig
const workflowOutputReferences = computed(() => {
  void actionsRevision.value
  return (selected.value?.nodes || [])
    .filter((node) => node.action_id !== 'utility.condition')
    .flatMap((node) => [
      { reference: node.id, label: `${nodeLabel(node)} · 完整结果` },
      ...outputFieldsForNode(node).map((field) => ({
        reference: `${node.id}.${field.name}`,
        label: `${nodeLabel(node)} · ${field.label}`
      }))
    ])
})
const filteredActions = computed(() => {
  void actionsRevision.value
  return filterWorkflowActions(actions, searchQuery.value)
})
// Catalog seam retains the loop policy: const nonExecutableLoopActions = new Set; !nonExecutableLoopActions.has(item.id)
const groupedActions = computed(() => groupWorkflowActions(filteredActions.value))
const loopChildActions = computed(() => {
  void actionsRevision.value
  return loopChildWorkflowActions(actions)
})
const availableDevices = computed<DeviceSummary[]>(() => workspace.devices || [])
const workflowTargetOptions = computed(() => availableDevices.value.map((device) => ({
  id: device.id,
  label: deviceLabel(device),
  detail: device.ssh_endpoint || device.telnet_endpoint || device.serial_display || '',
})))
function previewValue(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined
  if (typeof value === 'string') return value
  try { return JSON.stringify(value) } catch { return String(value) }
}
const canSave = computed(() => Boolean(
  selected.value &&
  selected.value.name.trim() &&
  !saving.value &&
  (selected.value.nodes?.length || 0) > 0 &&
  !issues.value.length &&
  selected.value.nodes?.every((node) => nodeState(node) === 'ready' && !isNodeDisconnected(node))
))
const canPublish = computed(() => Boolean(selected.value?.name.trim() && !issues.value.length && (selected.value.nodes?.length || 0) > 0))
const canRun = computed(() => Boolean(selected.value?.name.trim() && (selectedDeviceIds.value.length || selectedDeviceId.value) && !running.value && !issues.value.length && (selected.value.nodes?.length || 0) > 0))
const canStartRun = computed(() => Boolean(selected.value?.name.trim() && (selectedDeviceIds.value.length || selectedDeviceId.value) && !running.value && (selected.value.nodes?.length || 0) > 0))
const canStartFlowTest = computed(() => Boolean(selected.value?.name.trim() && (selectedDeviceIds.value.length || selectedDeviceId.value) && !running.value && !flowTestRunning.value && (selected.value.nodes?.length || 0) > 0))
const flowTestView = useWorkflowFlowTestView({
  selected,
  canvasNodes: computed(() => canvasNodes.value),
  actions,
  task: flowTestTask,
  error: flowTestError,
  inputValues: workflowInputValues,
  expandedStepIds: expandedFlowTestStepIds
})
const {
  status: flowTestStatus,
  currentStep: flowTestCurrentStep,
  inputEntries: flowTestInputEntries,
  stepLogs: flowTestStepLogs,
  toggleStep: toggleFlowTestStep,
  stepStatusLabel: flowTestStepStatusLabel,
  outputText: flowTestOutputText
} = flowTestView
const flowTestTaskTerminal = computed(() => ['completed', 'success', 'succeeded', 'failed', 'cancelled'].includes(String(flowTestTask.value?.status || '')))
const hasBranching = computed(() => Boolean(selected.value?.nodes?.some((node) => node.action_id === 'utility.condition') || selected.value?.edges?.some((edge) => Boolean(edge.condition))))
const previewSteps = computed(() => canvasNodes.value.map((node) => {
  const label = actions.find((item) => item.id === node.action_id)?.label || node.action_id
  const repeat = Number(node.config.repeat_count || 1)
  const parallel = String(node.config.parallel_group || '').trim()
  const details = [node.action_id === 'utility.confirm' ? '需要人工确认' : '', repeat > 1 ? `重复 ${repeat} 次` : '', parallel ? `并行组：${parallel}` : ''].filter(Boolean)
  return { label, detail: details.join(' · ') }
}))
const previewParallelGroups = computed(() => {
  const groups = new Map<string, number>()
  for (const node of selected.value?.nodes || []) {
    const group = String(node.config.parallel_group || '').trim()
    if (group) groups.set(group, (groups.get(group) || 0) + 1)
  }
  return [...groups.entries()].filter(([, count]) => count > 1).map(([name, count]) => `${name}：${count} 步同时执行`)
})
const highRiskActions = new Set(['device.reboot', 'file.upload', 'file.download', 'script.run'])
function nodeHasHighRiskAction(node: NodeItem): boolean {
  return nodeHasHighRiskActionModel(node, highRiskActions)
}
const previewHasRisk = computed(() => {
  const nodes = selected.value?.nodes || []
  return nodes.some(nodeHasHighRiskAction)
})
const conditionTargets = computed(() => {
  const condition = selectedNode.value
  if (!selected.value || condition?.action_id !== 'utility.condition') return { trueTarget: '', falseTarget: '' }
  const edges = (selected.value.edges || []).filter((edge) => edge.source === condition.id)
  return {
    trueTarget: edges.find((edge) => edge.condition === 'true' || edge.source_handle === 'true')?.target || '',
    falseTarget: edges.find((edge) => edge.condition === 'false' || edge.source_handle === 'false')?.target || ''
  }
})
const canvasNodes = computed<NodeItem[]>(() => {
  return orderCanvasNodes(selected.value?.nodes || [], selected.value?.edges || [])
})
const workflowEditor = useWorkflowEditor({
  selected,
  selectedNode,
  selectedDeviceId,
  rightRailMode,
  conditionRules,
  conditionLogicalOperator,
  actions,
  canvasNodes
})
const {
  workflowHistory,
  addNode,
  startActionDrag,
  nodePosition,
  findInsertEdge,
  defaultConfig,
  addEdge,
  removeEdgeByTarget,
  setNodePredecessor,
  setNodeSuccessor,
  setConditionTarget,
  removeNode,
  copySelectedNode,
  pasteNode,
  handleWorkflowKeyDown,
  renameNode,
  performUndo,
  performRedo,
  applyAutoLayout,
  handleNodePositionChange,
  handleNodePositionsChange
} = workflowEditor

function previewCatalogAction(actionId: string): void {
  selectedCatalogAction.value = actions.find((action) => action.id === actionId) || null
  if (!selectedCatalogAction.value) return
  if (flowTestOpen.value) closeFlowTestPanel()
  rightRailMode.value = 'step'
}

function addCanvasNode(actionId: string, position: { x: number; y: number }): void {
  selectedCatalogAction.value = null
  addNode(actionId, position)
}
const incomingEdgeByTarget = computed(() => {
  return incomingEdges(selected.value?.edges || [])
})
const reachableNodeIds = computed(() => {
  return reachableNodes(canvasNodes.value, selected.value?.edges || [])
})
const nodePredecessorId = computed(() => selectedNode.value ? incomingEdgeByTarget.value.get(selectedNode.value.id)?.source || '' : '')
const nodeSuccessorId = computed(() => {
  if (!selectedNode.value) return ''
  return (selected.value?.edges || []).find((edge) => edge.source === selectedNode.value?.id)?.target || ''
})

function hasIncomingEdge(node: NodeItem): boolean {
  return incomingEdgeByTarget.value.has(node.id)
}

function isNodeDisconnected(node: NodeItem): boolean {
  return !reachableNodeIds.value.has(node.id)
}

function nodeLabel(node: NodeItem): string {
  return nodeLabelModel(node, actions)
}

function connectorLabel(node: NodeItem, index: number): string {
  return connectorLabelModel(node, index, incomingEdgeByTarget.value, canvasNodes.value, actions)
}

function nodeOptions(excludeId: string): NodeItem[] {
  return nodeOptionsModel(canvasNodes.value, excludeId)
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = ''
  try { workflows.value = (await desktopApi.workflowDefinitions()).workflows as WorkflowItem[] } catch (cause) { error.value = String(cause) } finally { loading.value = false }
}

async function refreshPublishedVersions(workflowId: string): Promise<void> {
  const requestId = ++versionsRequestId
  versionsLoading.value = true
  versionError.value = ''
  try {
    const versions = (await desktopApi.workflowVersions(workflowId)).versions
    if (requestId === versionsRequestId && selected.value?.id === workflowId) publishedVersions.value = versions
  } catch (cause) {
    if (requestId === versionsRequestId && selected.value?.id === workflowId) {
      publishedVersions.value = []
      versionError.value = cause instanceof Error ? cause.message : String(cause)
    }
  } finally {
    if (requestId === versionsRequestId) versionsLoading.value = false
  }
}

function selectWorkflow(item: WorkflowItem, force = false): void {
  if (!force && selected.value?.id !== item.id && hasUnsavedChanges.value && !window.confirm('当前流程有未保存修改，切换后将丢失这些修改。确定继续吗？')) return
  const nextWorkflow = cloneWorkflow(item)
  normalizeLoopUntilNodes(nextWorkflow.nodes || [])
  selected.value = nextWorkflow
  flowTestRequestId += 1
  flowTestOpen.value = false
  flowTestRunning.value = false
  flowTestTask.value = null
  flowTestError.value = ''
  savedWorkflowSnapshot.value = workflowSnapshot(nextWorkflow)
  selectedNode.value = null
  selectedCatalogAction.value = null
  showPublishedVersions.value = false
  rightRailMode.value = 'workflow'
  initializeWorkflowInputValues(nextWorkflow)
  issues.value = []
  runMessage.value = ''
  confirmedRisks.value = false
  const condition = nextWorkflow.nodes?.find((node) => node.action_id === 'utility.condition')
  if (condition && Array.isArray(condition.config.rules)) conditionRules.value = condition.config.rules as typeof conditionRules.value
  conditionLogicalOperator.value = condition?.config.logical_operator === 'OR' ? 'OR' : 'AND'
  void refreshPublishedVersions(nextWorkflow.id)
}

function addSelectedQuickWorkflow(): void {
  if (!selected.value) return
  if (!publishedVersions.value.length) {
    runMessage.value = '请先发布一个 Workflow 版本，再添加快捷入口。'
    return
  }
  emit('add-quick-workflow', { workflowId: selected.value.id, name: selected.value.name })
  runMessage.value = `已添加快捷 Workflow：${selected.value.name}`
}

async function removePublishedVersion(version: PublishedVersionItem): Promise<void> {
  if (!selected.value) return
  const referenceNotice = version.referenced ? '该版本已被任务引用，删除不会影响已创建的任务。' : ''
  if (!window.confirm(`确定删除 ${selected.value.name} 的 v${version.version} 吗？${referenceNotice}此操作不可撤销。`)) return
  try {
    await desktopApi.deleteWorkflowVersion(selected.value.id, version.version)
    await refreshPublishedVersions(selected.value.id)
    runMessage.value = `已删除发布版本 v${version.version}`
  } catch (cause) {
    versionError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function removePublishedVersions(versions: PublishedVersionItem[]): Promise<boolean> {
  if (!selected.value || !versions.length) return false
  const referencedCount = versions.filter((version) => version.referenced).length
  const referenceNotice = referencedCount ? `其中 ${referencedCount} 个版本已被任务引用，删除不会影响已创建的任务。` : ''
  if (!window.confirm(`确定清理 ${selected.value.name} 的 ${versions.length} 个发布版本吗？${referenceNotice}此操作不可撤销。`)) return false
  try {
    const result = await desktopApi.deleteWorkflowVersions(selected.value.id, versions.map((version) => version.version))
    await refreshPublishedVersions(selected.value.id)
    const failedCount = result.failed_versions?.length || 0
    runMessage.value = failedCount
      ? `已清理 ${result.deleted_versions.length} 个发布版本，${failedCount} 个版本未找到`
      : `已清理 ${result.deleted_versions.length} 个发布版本`
    return true
  } catch (cause) {
    versionError.value = cause instanceof Error ? cause.message : String(cause)
    throw cause
  }
}

async function exportPublishedVersion(version: PublishedVersionItem): Promise<void> {
  if (!selected.value) return
  try {
    const result = await desktopApi.exportWorkflowDefinition(selected.value.id, 'yaml', version.version)
    const filename = result.filename.replace(/\.workflow\.yaml$/i, `.v${version.version}.workflow.yaml`)
    await window.desktopApi.saveWorkflowFile({ suggestedName: filename, content: result.content })
    runMessage.value = `已导出发布版本 v${version.version}`
  } catch (cause) {
    versionError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function restorePublishedVersion(version: PublishedVersionItem): Promise<void> {
  if (!selected.value) return
  if (!window.confirm(`将 v${version.version} 恢复为当前草稿？现有草稿内容会被覆盖。`)) return
  try {
    const result = await desktopApi.restoreWorkflowVersion(selected.value.id, version.version)
    const restored = result.workflow as WorkflowItem
    workflows.value = workflows.value.map((item) => item.id === restored.id ? restored : item)
    selectWorkflow(restored, true)
    runMessage.value = `已将发布版本 v${version.version} 恢复为草稿`
  } catch (cause) {
    versionError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function duplicateWorkflow(): void {
  if (!selected.value) return
  const source = selected.value
  const clone: WorkflowItem = {
    ...source,
    id: '',
    name: `${source.name} 副本`,
    version: undefined,
    nodes: (source.nodes || []).map((node) => ({ ...node, config: { ...node.config }, id: `${node.id}_copy` })),
    edges: (source.edges || []).map((edge) => ({ ...edge, source: `${edge.source}_copy`, target: `${edge.target}_copy` }))
  }
  void (async () => {
    try {
      const result = await desktopApi.createWorkflowDefinition(clone as unknown as Record<string, unknown>)
      await refresh()
      selectWorkflow(result.workflow as WorkflowItem)
    } catch (cause) { error.value = String(cause) }
  })()
}

function deviceLabel(device: DeviceSummary): string {
  return device.name || device.board_id || device.id
}

function issueText(issue: Issue): string {
  const node = selected.value?.nodes?.find((item) => item.id === issue.node_id)
  const label = node ? (actions.find((action) => action.id === node.action_id)?.label || node.id) : ''
  const missing = issue.message.match(/(?:required config is missing:|missing required config:?)\s*(.+)$/i)?.[1]
  if (issue.code === 'missing_required_config' && missing) return `${label || '步骤'}：请填写“${missing}”`
  if (issue.code === 'missing_workflow_name') return '请填写流程名称'
  if (issue.code === 'duplicate_node_id') return '流程中存在重复步骤 ID，请重命名其中一个步骤'
  if (issue.code === 'duplicate_input_name') return '流程输入名称重复，请保留唯一名称'
  if (issue.code === 'missing_workflow_input') return '流程输入缺少必填值，请补齐后再运行'
  if (issue.code === 'invalid_workflow_input_type') return '流程输入类型不匹配，请按输入定义填写'
  if (issue.code === 'unknown_action') return `${label || '步骤'}：当前动作暂不支持执行`
  if (issue.code === 'invalid_condition') return `${label || '条件判断'}：请配置至少一条完整规则`
  if (issue.code === 'invalid_transfer_source_path') return `${label || '上传文件'}：请选择文件或填写有效的本机路径`
  if (issue.code === 'invalid_condition_operator') return `${label || '条件判断'}：请选择 AND 或 OR`
  if (issue.code === 'invalid_expression') return `${label || '表达式'}：表达式不合法，请使用受支持的字段和运算符`
  if (issue.code === 'invalid_terminal_match_mode') return `${label || '终端匹配'}：匹配方式只能选择包含文本或正则表达式`
  if (issue.code === 'invalid_terminal_pattern') return `${label || '终端匹配'}：正则表达式不合法，请检查括号和转义`
  if (issue.code === 'invalid_number') return `${label || '步骤'}：请输入有效数字`
  if (issue.code === 'number_out_of_range') return `${label || '步骤'}：数值超出允许范围`
  if (issue.code === 'invalid_edge') return '流程连接引用了不存在的步骤'
  if (issue.code === 'disconnected_node') return `${label || '流程'}：步骤没有连接到主流程`
  if (issue.code === 'cycle') return `${label || '流程'}：连接形成了循环`
  if (issue.code === 'invalid_variable_ref') {
    const reference = issue.message.match(/unknown or forward variable reference:\s*(.+)$/i)?.[1]
    return `${label || '步骤'}：引用“${reference || '上游数据'}”失败，请确认它来自前置步骤并已连线`
  }
  if (issue.code === 'invalid_variable_field') return `${label || '步骤'}：输出字段不存在，请从上游步骤可用字段中选择`
  if (issue.code === 'embedded_variable_ref') return `${label || '步骤'}：变量引用必须单独作为完整值，不能嵌在其他文字中`
  if (issue.code === 'invalid_variable_name') return `${label || '设置变量'}：变量名只能使用字母、数字和下划线，且不能以数字开头`
  if (issue.code === 'invalid_variable_extract') return `${label || '设置变量'}：提取配置必须是对象`
  if (issue.code === 'invalid_variable_extract_pattern') return `${label || '设置变量'}：请填写有效的匹配规则`
  if (issue.code === 'invalid_variable_extract_mode') return `${label || '设置变量'}：提取方式只能选择首次匹配或按行匹配`
  if (issue.code === 'invalid_variable_extract_group') return `${label || '设置变量'}：捕获组编号超出正则表达式范围`
  if (issue.code === 'invalid_variable_extract_conversion') return `${label || '设置变量'}：请选择有效的转换类型`
  if (issue.code === 'invalid_variable_extract_trim') return `${label || '设置变量'}：去除首尾空白配置必须为布尔值`
  if (issue.code === 'invalid_loop_items') return `${label || '循环列表'}：请提供数组，或引用会返回数组的上游输出`
  if (issue.code === 'invalid_loop_action') return `${label || '循环动作'}：请选择可在循环中执行的动作`
  if (issue.code === 'invalid_loop_condition') return `${label || '循环条件'}：停止条件表达式不合法`
  if (issue.code === 'missing_confirmation_prompt') return `${label || '人工确认'}：请填写确认提示`
  return issue.message || '流程存在未解决的问题'
}

function focusIssue(issue: Issue): void {
  const node = selected.value?.nodes?.find((item) => item.id === issue.node_id)
  if (!node && (issue.code === 'missing_workflow_input' || issue.code === 'invalid_workflow_input_type')) {
    const inputName = issue.message.match(/missing:\s*(.+)$/i)?.[1]?.trim()
    if (inputName) {
      void nextTick(() => {
        const target = document.querySelector(`[data-workflow-input-name="${CSS.escape(inputName)}"]`) as HTMLElement | null
        target?.focus()
        target?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      })
    }
    return
  }
  if (!node) return
  selectedCatalogAction.value = null
  selectedNode.value = node
  rightRailMode.value = 'step'
  void nextTick(() => {
    const target = document.querySelector(`[data-workflow-node-id="${CSS.escape(node.id)}"]`)
    target?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  })
}

function showValidationProblem(): void {
  const first = issues.value[0]
  if (!first) return
  runMessage.value = issueText(first)
  focusIssue(first)
}

async function runWorkflow(): Promise<void> {
  await workflowRunActions.run(false)
}

async function runDraft(): Promise<void> {
  // Compatibility marker: draft: true is owned by useWorkflowRunActions.run(true).
  await workflowRunActions.run(true)
}

async function testFlowInEditor(): Promise<void> {
  await workflowRunActions.test()
}

async function monitorFlowTestTask(taskId: string, requestId: number): Promise<void> {
  await workflowRunActions.monitor(taskId, requestId)
}

async function resumeFlowTestMonitoring(): Promise<void> {
  await workflowRunActions.resume()
}

function closeFlowTestPanel(): void {
  flowTestRequestId += 1
  flowTestRunning.value = false
  flowTestOpen.value = false
  flowTestError.value = ''
}

function showWorkflowSettings(): void {
  if (flowTestOpen.value) closeFlowTestPanel()
  rightRailMode.value = 'workflow'
}

const WORKFLOW_INPUT_NODE = '__workflow_input__'
const WORKFLOW_RESULT_NODE = '__workflow_result__'

function inferredCanvasEdges(workflow: WorkflowItem): Array<{ source: string; target: string; source_handle?: string }> {
  const nodes = workflow.nodes || []
  if (!nodes.length) return [{ source: WORKFLOW_INPUT_NODE, target: WORKFLOW_RESULT_NODE }]
  const edges = workflow.edges || []
  const incoming = new Set(edges.map((edge) => edge.target))
  const outgoing = new Set(edges.map((edge) => edge.source))
  return [
    ...nodes.filter((node) => !incoming.has(node.id)).map((node) => ({ source: WORKFLOW_INPUT_NODE, target: node.id })),
    ...nodes.filter((node) => !outgoing.has(node.id)).map((node) => ({ source: node.id, target: WORKFLOW_RESULT_NODE }))
  ]
}

function ensureCanvasEdges(workflow: WorkflowItem): Array<{ source: string; target: string; source_handle?: string }> {
  if (workflow.canvas_edges == null) workflow.canvas_edges = inferredCanvasEdges(workflow)
  return workflow.canvas_edges
}

function connectCanvasEdge(source: string, target: string, sourceHandle?: string): void {
  if (!selected.value) return
  const isLoopExitToResult = target === WORKFLOW_RESULT_NODE && sourceHandle === 'loop-exit'
  if (source === WORKFLOW_INPUT_NODE || target === WORKFLOW_RESULT_NODE) {
    const isValidInputConnection = source === WORKFLOW_INPUT_NODE
      && (target === WORKFLOW_RESULT_NODE || selected.value.nodes?.some((node) => node.id === target))
    const sourceNode = selected.value.nodes?.find((node) => node.id === source)
    const isValidResultConnection = target === WORKFLOW_RESULT_NODE
      && Boolean(sourceNode)
      && (!isLoopExitToResult || ['device.for_each', 'loop.for_each', 'loop.until'].includes(sourceNode?.action_id || ''))
    if (!isValidInputConnection && !isValidResultConnection) return
    const canvasEdges = ensureCanvasEdges(selected.value)
    if (!canvasEdges.some((edge) => edge.source === source && edge.target === target)) {
      selected.value.canvas_edges = [...canvasEdges, { source, target, source_handle: isLoopExitToResult ? 'loop-exit' : undefined }]
    }
    return
  }
  addEdge(source, target, sourceHandle)
}

function disconnectCanvasEdge(edge: { id: string; source: string; target: string }): void {
  if (!selected.value) return
  if (edge.source === WORKFLOW_INPUT_NODE || edge.target === WORKFLOW_RESULT_NODE) {
    selected.value.canvas_edges = ensureCanvasEdges(selected.value)
      .filter((item) => item.source !== edge.source || item.target !== edge.target)
    return
  }
  const workflowEdge = (selected.value.edges || []).find((item) => {
    const sourceNode = (selected.value?.nodes || []).find((node) => node.id === item.source)
    const handle = item.source_handle || (sourceNode?.action_id === 'device.for_each' ? 'loop-body' : 'default')
    return `${item.source}-${handle}-${item.target}` === edge.id
  })
  if (workflowEdge) selected.value.edges = (selected.value.edges || []).filter((item) => item !== workflowEdge)
}

function updateCanvasEdge(update: { id: string; source: string; target: string; nextSource: string; nextTarget: string }): void {
  if (!selected.value) return
  const isBoundary = update.source === WORKFLOW_INPUT_NODE || update.target === WORKFLOW_RESULT_NODE
  if (!isBoundary) return
  const validInput = update.nextSource === WORKFLOW_INPUT_NODE
    && (update.nextTarget === WORKFLOW_RESULT_NODE || selected.value.nodes?.some((node) => node.id === update.nextTarget))
  const nextSourceNode = selected.value.nodes?.find((node) => node.id === update.nextSource)
  const wasLoopExit = ensureCanvasEdges(selected.value).some((edge) => edge.source === update.source && edge.target === update.target && edge.source_handle === 'loop-exit')
  const validResult = update.nextTarget === WORKFLOW_RESULT_NODE
    && Boolean(nextSourceNode)
    && (!wasLoopExit || ['device.for_each', 'loop.for_each', 'loop.until'].includes(nextSourceNode?.action_id || ''))
  if (!validInput && !validResult) return
  const remaining = ensureCanvasEdges(selected.value)
    .filter((edge) => edge.source !== update.source || edge.target !== update.target)
  if (!remaining.some((edge) => edge.source === update.nextSource && edge.target === update.nextTarget)) {
    remaining.push({ source: update.nextSource, target: update.nextTarget, source_handle: wasLoopExit ? 'loop-exit' : undefined })
  }
  selected.value.canvas_edges = remaining
}

function showStepSettings(nodeId = ''): void {
  if (nodeId === '__workflow_input__') {
    if (flowTestOpen.value) closeFlowTestPanel()
    workflowInputsExpanded.value = true
    rightRailMode.value = 'workflow'
    return
  }
  if (nodeId === '__workflow_result__') {
    if (flowTestOpen.value) closeFlowTestPanel()
    workflowOutputsExpanded.value = true
    rightRailMode.value = 'workflow'
    return
  }
  const node = selected.value?.nodes?.find((item) => item.id === nodeId)
  if (node) {
    selectedCatalogAction.value = null
    selectedNode.value = node
  }
  if (selectedNode.value) rightRailMode.value = 'step'
}

async function dryRunWorkflow(): Promise<void> {
  if (!selected.value || (!selectedDeviceIds.value.length && !selectedDeviceId.value)) return
  await validate()
  if (issues.value.length) { showValidationProblem(); return }
  if (!await persistCurrentWorkflow()) return
  dryRunning.value = true
  try {
    const targets = selectedDeviceIds.value.length ? selectedDeviceIds.value : [selectedDeviceId.value]
    const result = await desktopApi.runWorkflowDefinition(selected.value.id, { device_id: targets[0], device_ids: targets, protocol: 'simulated', inputs: workflowRuntimeInputs.value, draft: selected.value.version === 'draft', dry_run: true })
    runMessage.value = `模拟运行完成：${Number(result.preview?.target_count || targets.length)} 台设备将执行 ${Number(result.preview?.step_count || 0)} 个步骤。`
    showRunPreview.value = false
  } catch (cause) { runMessage.value = cause instanceof Error ? cause.message : String(cause) } finally { dryRunning.value = false }
}

async function requestRunPreview(): Promise<void> {
  await validate()
  if (canRun.value) {
    confirmedRisks.value = false
    showRunPreview.value = true
  }
  else if (issues.value.length) showValidationProblem()
  else runMessage.value = '请选择目标设备。'
}

function confirmRunFromPreview(): void {
  if (previewHasRisk.value && !confirmedRisks.value) return
  showRunPreview.value = false
  void runWorkflow()
}

function syncCurrentWorkflowState(): void {
  if (!selectedNode.value) return

  // 同步 utility.condition 的特殊状态
  if (selectedNode.value.action_id === 'utility.condition') {
    selectedNode.value.config.rules = conditionRules.value
    selectedNode.value.config.logical_operator = conditionLogicalOperator.value
  }

  // 确保 selectedNode 的修改同步回 selected.value.nodes
  // 这对于 v-model 绑定到 selectedNode.config 的情况很重要
  if (selected.value?.nodes) {
    const nodeIndex = selected.value.nodes.findIndex(n => n.id === selectedNode.value!.id)
    if (nodeIndex !== -1) {
      selected.value.nodes[nodeIndex] = { ...selectedNode.value }
    }
  }
}

async function validate(): Promise<boolean> {
  return workflowPersistence.validate()
}

async function persistCurrentWorkflow(): Promise<boolean> {
  const nodeId = selectedNode.value?.id
  const persisted = await workflowPersistence.persist()
  if (persisted) selectedNode.value = selected.value?.nodes?.find((node) => node.id === nodeId) || selected.value?.nodes?.[0] || null
  return persisted
}

async function save(): Promise<void> {
  // Compatibility marker: validation and persistence now live in useWorkflowPersistence.
  // await validate(); await persistCurrentWorkflow()
  // if (issues.value.length) showValidationProblem()
  await workflowPersistence.save()
}

async function publish(): Promise<void> {
  // Compatibility marker: if (!await persistCurrentWorkflow()) return
  // await desktopApi.publishWorkflowDefinition(selected.value.id)
  await workflowPersistence.publish()
}

async function removeWorkflow(workflow: WorkflowItem): Promise<void> {
  if (deletingWorkflowId.value) return
  const isSelected = selected.value?.id === workflow.id
  if (isSelected && (hasUnsavedChanges.value || hasUnsavedScriptChanges.value) && !window.confirm('当前流程有未保存修改，删除后无法恢复。确定继续吗？')) return
  if (!window.confirm(`确定删除流程“${workflow.name}”吗？`)) return

  deletingWorkflowId.value = workflow.id
  error.value = ''
  try {
    try {
      await desktopApi.deleteWorkflowDefinition(workflow.id)
    } catch (cause) {
      if (!(cause instanceof BackendApiError) || cause.status !== 409) throw cause
      if (!window.confirm('该流程有已被任务引用的发布版本。继续删除会保留任务历史，但移除该流程及其版本列表。已创建的任务不会受影响。')) return
      await desktopApi.deleteWorkflowDefinition(workflow.id, { preserveHistory: true })
    }
    if (isSelected) {
      selected.value = null
      selectedNode.value = null
      flowTestRequestId += 1
      flowTestOpen.value = false
      flowTestTask.value = null
      savedWorkflowSnapshot.value = ''
    }
    await refresh()
    if (isSelected && workflows.value[0]) selectWorkflow(workflows.value[0], true)
    runMessage.value = `已删除流程“${workflow.name}”`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    deletingWorkflowId.value = ''
  }
}

async function remove(): Promise<void> {
  if (selected.value) await removeWorkflow(selected.value)
}

function requestClose(): boolean {
  if ((hasUnsavedChanges.value || hasUnsavedScriptChanges.value) && !window.confirm('当前工作区有未保存修改，关闭后将丢失这些修改。确定关闭吗？')) return false
  emit('close')
  return true
}

defineExpose({ hasUnsavedChanges, requestClose })

const requiredConfigByAction: Record<string, string[]> = {
  'device.command': ['command'],
  'script.run': ['script'],
  'device.select': ['device_id'],
  'expression.evaluate': ['expression'],
  'file.upload': ['source'],
  'file.download': ['source', 'destination'],
  'loop.for_each': ['items', 'action_id'],
  'device.for_each': ['devices'],
  'loop.until': ['action_id', 'condition'],
  'workflow.call': ['workflow_id', 'version'],
  'terminal.wait': ['pattern'],
  'utility.confirm': ['prompt'],
  'utility.wait': ['seconds'],
  'variable.set': ['name']
}

function nodeSettings(node: NodeItem): Record<string, unknown> {
  return nodeSettingsModel(node)
}

function hasRequiredConfigValue(node: NodeItem, settings: Record<string, unknown>, key: string): boolean {
  return hasRequiredConfigValueModel(node, settings, key)
}

function nodeState(node: NodeItem): 'ready' | 'attention' {
  return nodeStateModel(node, requiredConfigByAction)
}
function configString(key: string): string { return String(selectedNode.value?.config?.[key] ?? '') }
function updateConfigString(key: string, event: Event): void { if (selectedNode.value) selectedNode.value.config[key] = (event.target as HTMLInputElement | HTMLTextAreaElement).value }
function updateConfigJson(key: string, event: Event): void {
  if (!selectedNode.value) return
  try { selectedNode.value.config[key] = JSON.parse((event.target as HTMLTextAreaElement).value || (key === 'items' ? '[]' : '{}')) } catch { runMessage.value = `${key} 必须是有效 JSON` }
}

async function loadCustomActions(): Promise<void> {
  const result = await desktopApi.workflowCustomActions()
  for (let index = actions.length - 1; index >= 0; index -= 1) {
    if (actions[index].preset) actions.splice(index, 1)
  }
  for (const raw of result.actions) {
    const item = raw as { id?: string; name?: string; description?: string; action_id?: string; config?: Record<string, unknown>; output_schema?: unknown }
    if (!item.id || !item.action_id || !item.config) continue
    const action = actions.find((candidate) => candidate.id === item.action_id)
    const outputSchema = item.output_schema && typeof item.output_schema === 'object' && !Array.isArray(item.output_schema)
      ? item.output_schema as Record<string, unknown>
      : action?.outputSchema || {}
    actions.push({
      id: `custom:${item.id}`,
      label: item.name || '自定义 Action',
      hint: item.description || '可复用动作',
      tone: 'teal',
      category: action?.category || 'device',
      inputSchema: action?.inputSchema || {},
      outputSchema,
      risk: action?.risk || 'low',
      outputFields: outputFieldsFromSchema(outputSchema),
      preset: { actionId: item.action_id, config: item.config, customActionId: item.id },
    })
  }
  actionsRevision.value += 1
}

async function testSelectedStep(): Promise<void> {
  if (!selected.value || !selectedNode.value || (!selectedDeviceIds.value.length && !selectedDeviceId.value)) return
  if (!await persistCurrentWorkflow()) return
  await validate()
  if (issues.value.length) { showValidationProblem(); return }
  try {
    const targets = selectedDeviceIds.value.length ? selectedDeviceIds.value : [selectedDeviceId.value]
    const result = await desktopApi.runWorkflowDefinition(selected.value.id, { device_id: targets[0], device_ids: targets, step_id: selectedNode.value.id, protocol: 'simulated', inputs: workflowRuntimeInputs.value, draft: selected.value.version === 'draft', dry_run: true })
    runMessage.value = `单步模拟完成：将执行 ${Number(result.preview?.step_count || 0)} 个前置及当前步骤。`
  } catch (cause) { runMessage.value = cause instanceof Error ? cause.message : String(cause) }
}

onMounted(async () => {
  selectedDeviceId.value = workspace.selectedDeviceId || workspace.devices[0]?.id || ''
  selectedDeviceIds.value = selectedDeviceId.value ? [selectedDeviceId.value] : []
  try {
    const [catalog, published] = await Promise.all([
      desktopApi.workflowActions(),
      desktopApi.publishedWorkflowDefinitions(),
    ])
    await Promise.all([loadWorkflowTemplates(), loadWorkflowScripts()])
    publishedWorkflows.value = published.workflows as PublishedVersionItem[]
    actions.splice(0, actions.length, ...actionItemsFromCatalog(catalog.actions))
    actionsRevision.value += 1
    await loadCustomActions()
  } catch (cause) { error.value = String(cause) }
  await refresh()
  if (workflows.value[0]) selectWorkflow(workflows.value[0])
})

onMounted(() => {
  restoreWorkflowPanelWidths()
  window.addEventListener('pointerdown', handleCreateMenuOutside)
  window.addEventListener('keydown', handleCreateMenuKeyDown)
})

onUnmounted(() => {
  cancelScriptTaskMonitoring()
  flowTestRequestId += 1
  disposeWorkflowPanelLayout()
  window.removeEventListener('pointerdown', handleCreateMenuOutside)
  window.removeEventListener('keydown', handleCreateMenuKeyDown)
})

watch(
  () => selectedNode.value?.action_id === 'workflow.call' ? String(selectedNode.value.config.workflow_id || '') : '',
  async (workflowId) => {
    if (!workflowId) {
      subworkflowVersions.value = []
      return
    }
    try {
      subworkflowVersions.value = (await desktopApi.workflowVersions(workflowId)).versions as PublishedVersionItem[]
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  },
  { immediate: true }
)

watch(
  () => [workspace.selectedDeviceId, workspace.devices] as const,
  ([deviceId, devices]) => {
    if (deviceId && !selectedDeviceId.value) selectedDeviceId.value = deviceId
    if (!selectedDeviceId.value && devices.length) selectedDeviceId.value = devices[0].id
    if (!selectedDeviceIds.value.length && selectedDeviceId.value) selectedDeviceIds.value = [selectedDeviceId.value]
  },
  { deep: true }
)
</script>

<template>
  <section class="workflow-library" aria-label="Workflow Library">
    <header class="workflow-library-header">
      <div class="workflow-brand"><span class="workflow-brand-mark"><Workflow :size="17" /></span><div><strong>Workflow Studio</strong><small>低代码自动化工作台</small></div></div>
      <div class="workflow-library-header-actions"><span v-if="hasUnsavedChanges || hasUnsavedScriptChanges" class="workflow-dirty-state">未保存修改</span><button type="button" class="workflow-run-header-button" title="运行已发布 Workflow" @click="emit('run-published')"><Play :size="14" />运行已发布</button><button type="button" title="关闭" @click="requestClose"><X :size="16" /></button></div>
    </header>
    <div class="workflow-library-toolbar">
      <div class="toolbar-group toolbar-group-primary">
        <button type="button" :class="{ 'studio-mode-active': studioMode === 'flow' }" @click="studioMode = 'flow'"><Workflow :size="14" />Flow</button>
        <div ref="createMenuRef" class="workflow-create-anchor">
          <button type="button" class="workflow-new-button" @click.stop="showCreateMenu = !showCreateMenu"><Plus :size="14" />新建流程</button>
          <div v-if="showCreateMenu" class="workflow-create-menu">
            <strong>开始方式</strong>
            <button v-for="item in workflowTemplates.slice(0, 4)" :key="item.id" type="button" @click="openCreateDialogFromTemplate(item.id)">模板：{{ item.name }}</button>
            <button type="button" :disabled="!selected" @click="showCreateMenu = false; duplicateWorkflow()">从已有流程复制</button>
            <button type="button" @click="openCreateDialog(true)">创建空白流程</button>
          </div>
        </div>
        <button type="button" :class="{ 'studio-mode-active': studioMode === 'scripts' }" @click="openScriptStudio()"><Code2 :size="14" />脚本</button>
        <button type="button" :class="{ 'studio-mode-active': catalogOpen }" :aria-pressed="catalogOpen" title="显示或隐藏节点库" @click="catalogOpen = !catalogOpen"><LayoutPanelLeft :size="14" />节点库</button>
        <select v-model="taskGoal" class="task-goal" aria-label="任务目标"><option>检查设备状态</option><option>批量执行操作</option><option>采集设备信息</option><option>上传文件</option><option>验证配置</option><option>执行实验流程</option><option>自定义流程</option></select>
      </div>
      <span class="toolbar-divider" aria-hidden="true"></span>
      <div class="toolbar-group toolbar-group-secondary">
        <button type="button" class="icon-toolbar-button" :disabled="!workflowHistory.canUndo.value" @click="performUndo" title="撤销 (Ctrl+Z)" aria-label="撤销"><Undo :size="14" /></button>
        <button type="button" class="icon-toolbar-button" :disabled="!workflowHistory.canRedo.value" @click="performRedo" title="重做 (Ctrl+Shift+Z)" aria-label="重做"><Redo :size="14" /></button>
        <details ref="workflowMoreMenuRef" class="workflow-more-menu" @click="closeWorkflowMoreMenu">
          <summary><MoreHorizontal :size="14" />更多操作</summary>
          <div class="workflow-more-popover">
            <span class="workflow-more-heading">流程</span>
            <button type="button" :disabled="!selected || !selected.nodes || selected.nodes.length === 0" @click="applyAutoLayout"><GitBranch :size="14" />自动布局</button>
            <button type="button" :disabled="importing" @click="importWorkflow"><Braces :size="14" />{{ importing ? '导入中…' : '导入流程' }}</button>
            <button type="button" :disabled="!selected" @click="duplicateWorkflow"><Copy :size="14" />复制流程</button>
            <button type="button" :disabled="!selected" @click="saveCurrentAsTemplate"><Save :size="14" />保存为模板</button>
            <button type="button" :disabled="!selected" @click="addSelectedQuickWorkflow"><Plus :size="14" />添加快捷</button>
            <button type="button" class="workflow-more-danger" :disabled="!selected" @click="remove"><Trash2 :size="14" />删除当前流程</button>
            <span class="workflow-more-heading">导出与分享</span>
            <button type="button" :disabled="!selected" @click="exportWorkflow('yaml')"><Download :size="14" />导出 YAML</button>
            <button type="button" :disabled="!selected" @click="exportWorkflow('json')"><Braces :size="14" />导出 JSON</button>
            <button type="button" :disabled="!selected" @click="copyAiPrompt"><Copy :size="14" />复制 AI 提示词</button>
          </div>
        </details>
      </div>
      <span class="toolbar-divider" aria-hidden="true"></span>
      <div class="toolbar-group toolbar-group-commit">
        <button type="button" :disabled="!canSave" @click="save"><Save :size="14" />{{ saving ? '保存中…' : '保存草稿' }}</button>
        <button type="button" :disabled="!selected" @click="validate"><CheckCircle2 :size="14" />检查流程</button>
      </div>
      <div class="workflow-run-target"><WorkflowTargetPicker v-model="selectedDeviceIds" :devices="workflowTargetOptions" :owned-device-ids="workspace.ownedDeviceIds" /></div>
      <div class="toolbar-group toolbar-group-actions">
        <details class="workflow-run-menu">
          <summary><Play :size="14" />运行<ChevronDown :size="12" /></summary>
          <div class="workflow-run-popover">
            <button class="flow-test-action" type="button" :disabled="!canStartFlowTest" @click="testFlowInEditor"><Play :size="13" />{{ flowTestRunning ? '测试运行中…' : '测试运行' }}</button>
            <button class="run-action" type="button" :disabled="!canStartRun" @click="requestRunPreview"><Play :size="13" />{{ running ? '启动中…' : '执行预览' }}</button>
            <button class="secondary-run-button" type="button" :disabled="!canRun" @click="runDraft"><Play :size="13" />测试草稿</button>
          </div>
        </details>
        <button class="primary-action" type="button" :disabled="!canPublish" @click="publish"><Play :size="14" />发布</button>
      </div>
    </div>
    <WorkflowManagementDialogs
      :state="managementState"
      :workflow-templates="workflowTemplates"
      :import-preview="importPreview"
      :importing="importing"
      :creating="creating"
      :deleting-template-id="deletingTemplateId"
      :custom-action-saving="customActionSaving"
      :confirm-create="confirmCreate"
      :confirm-import="confirmImport"
      :save-custom-action="saveCustomAction"
      :choose-create-template="chooseCreateTemplate"
      :delete-workflow-template="deleteWorkflowTemplate"
    />
    <p v-if="error" class="workflow-error">{{ error }}</p>
    <p v-if="runMessage" class="workflow-run-message">{{ runMessage }}</p><p v-if="hasBranching" class="workflow-branch-notice"><GitBranch :size="14" />包含条件分支：运行时只执行匹配条件的一侧。</p>
    <WorkflowScriptStudio
      v-if="studioMode === 'scripts'"
      :selected-device-id="selectedDeviceId"
      :available-devices="availableDevices"
      :device-label="deviceLabel"
      :controller="workflowScripts"
      @update:selected-device-id="selectedDeviceId = $event"
    />
    <div v-else class="workflow-library-body">
      <aside class="workflow-list-pane">
        <div class="workflow-list-title"><span>我的流程</span><small>{{ workflows.length }} 个</small></div>
        <div v-for="item in workflows" :key="item.id" class="workflow-list-item" :class="{ active: selected?.id === item.id }">
          <button type="button" class="workflow-list-select" :class="{ active: selected?.id === item.id }" @click="selectWorkflow(item)">
            <strong>{{ item.name }}</strong><small>{{ item.description || '暂无描述' }}</small><em>v{{ item.version || '草稿' }}</em>
          </button>
          <button
            type="button"
            class="workflow-list-delete"
            :disabled="deletingWorkflowId === item.id"
            :aria-label="`删除流程 ${item.name}`"
            title="删除流程"
            @click.stop="removeWorkflow(item)"
          >
            <Trash2 :size="14" />
          </button>
        </div>
        <p v-if="!loading && !workflows.length" class="workflow-empty-list">还没有流程<br /><span>点击“新建流程”开始</span></p>
        <nav v-if="selected" class="workflow-step-navigation" aria-label="流程步骤">
          <strong>流程步骤 · {{ canvasNodes.length }}</strong>
          <button v-for="(node, index) in canvasNodes" :key="node.id" type="button" :class="{ active: selectedNode?.id === node.id }" @click="showStepSettings(node.id)"><span>{{ String(index + 1).padStart(2, '0') }}　{{ nodeLabel(node) }}</span><small>{{ node.id }}</small></button>
        </nav>
        <button v-if="selected" type="button" class="workflow-version-toggle" :aria-expanded="showPublishedVersions" @click="showPublishedVersions = !showPublishedVersions">
          <span><ChevronDown :size="13" :class="{ rotated: showPublishedVersions }" />发布版本</span><small>{{ publishedVersions.length }}</small>
        </button>
        <WorkflowVersionManager
          v-if="selected && showPublishedVersions"
          :versions="publishedVersions"
          :loading="versionsLoading"
          :error="versionError"
          :on-run="(payload) => emit('run-version', payload)"
          :on-export="exportPublishedVersion"
          :on-restore="restorePublishedVersion"
          :on-save-action="openWorkflowCustomActionDialog"
          :on-remove="removePublishedVersion"
          :on-remove-many="removePublishedVersions"
        />
      </aside>
        <main v-if="selected" class="workflow-studio-grid" :class="{ 'flow-test-mode': flowTestOpen, 'step-settings-mode': rightRailMode === 'step', 'catalog-collapsed': !catalogOpen }" :style="{ '--workflow-catalog-width': catalogOpen ? `${workflowCatalogWidth}px` : '0px', '--workflow-properties-width': flowTestOpen ? 'min(46vw, 760px)' : `${workflowPropertiesWidth}px` }">
        <WorkflowInspectorShell
          :mode="rightRailMode"
          :flow-test-open="flowTestOpen"
          :has-selected-node="Boolean(selectedNode || selectedCatalogAction)"
          :previewing-action="Boolean(selectedCatalogAction)"
          @update:mode="rightRailMode = $event"
        >
          <template #flow-test>
<WorkflowFlowTestPanel
          v-if="flowTestOpen"
          :selected="selected"
          :status="flowTestStatus"
          :task="flowTestTask"
          :task-terminal="flowTestTaskTerminal"
          :current-step="flowTestCurrentStep"
          :error="flowTestError"
          :input-entries="flowTestInputEntries"
          :step-logs="flowTestStepLogs"
          :expanded-step-ids="expandedFlowTestStepIds"
          :running="flowTestRunning"
          :step-status-label="flowTestStepStatusLabel"
          :output-text="flowTestOutputText"
          :on-close="closeFlowTestPanel"
          :on-toggle-step="toggleFlowTestStep"
          :on-retry="testFlowInEditor"
          :on-resume="resumeFlowTestMonitoring"
          :output-definitions="selected.outputs || []"
          :output-values="{ ...(flowTestTask?.checkpoint?.outputs || {}), ...(flowTestTask?.result?.outputs || {}) }"
        />
          </template>
          <template #workflow-settings>
            <WorkflowSettingsPanel
              :workflow="selected"
              :has-unsaved-changes="hasUnsavedChanges"
              :input-values="workflowInputValues"
              :inputs-expanded="workflowInputsExpanded"
              :outputs-expanded="workflowOutputsExpanded"
              :runtime-inputs-expanded="workflowRuntimeInputsExpanded"
              :transfer-root="workspace.transferSettings?.root || ''"
              :workflow-input-has-issue="workflowInputHasIssue"
              :workflow-input-display="workflowInputDisplay"
              :is-workflow-file-input="isWorkflowFileInput"
              :update-workflow-input-definition="(index, key, value) => updateWorkflowInputDefinition(index, key as keyof WorkflowInput, value)"
              :normalize-workflow-input-json="normalizeWorkflowInputJson"
              :remove-workflow-input="removeWorkflowInput"
              :add-workflow-input="addWorkflowInput"
              :update-workflow-output="(index, key, value) => updateWorkflowOutput(index, key as keyof WorkflowOutput, value)"
              :remove-workflow-output="removeWorkflowOutput"
              :add-workflow-output="addWorkflowOutput"
              :output-references="workflowOutputReferences"
              :update-workflow-input="updateWorkflowInput"
              :choose-workflow-runtime-file="chooseWorkflowRuntimeFile"
              :on-open-transfer-settings="() => { workspace.transferPanelOpen = true }"
              @update:inputs-expanded="workflowInputsExpanded = $event"
              @update:outputs-expanded="workflowOutputsExpanded = $event"
              @update:runtime-inputs-expanded="workflowRuntimeInputsExpanded = $event"
            />
          </template>
          <template #step-settings>
<WorkflowStepInspector
          v-if="!flowTestOpen && rightRailMode === 'step'"
          :selected-catalog-action="selectedCatalogAction"
          :selected-node="selectedNode"
          :available-devices="availableDevices"
          :owned-device-ids="workspace.ownedDeviceIds"
          :workflow-inputs="selected.inputs || []"
          :command-references="commandReferences"
          :result-sources="resultSources"
          :device-loop-id="deviceLoopId"
          :scripts="scripts"
          :actions="actions"
          :node-options="selectedNode ? nodeOptions(selectedNode.id).map((node) => ({ id: node.id, label: nodeLabel(node) })) : []"
          :predecessor-id="nodePredecessorId"
          :successor-id="nodeSuccessorId"
          :script-saving="scriptSaving"
          :workflow="selected"
          :published-workflows="publishedWorkflows"
          :subworkflow-versions="subworkflowVersions"
          :selected-subworkflow="selectedSubworkflow"
          :loop-child-actions="loopChildActions"
          :advanced-node="Boolean(selectedNode && ['variable.set', 'expression.evaluate', 'loop.for_each', 'device.for_each', 'loop.until', 'utility.condition', 'utility.confirm', 'result.save', 'workflow.call'].includes(selectedNode.action_id))"
          :loop-items-mode="loopItemsMode"
          :loop-items-source-id="loopItemsSourceId"
          :loop-items-field="loopItemsField"
          :loop-until-stop-mode="loopUntilStopMode"
          :loop-until-pattern="loopUntilPattern"
          :condition-rules="conditionRules"
          :condition-logical-operator="conditionLogicalOperator"
          :condition-targets="conditionTargets"
          :variable-value-source-id="variableValueSourceId"
          :variable-value-field="variableValueField"
          :variable-extract-enabled="variableExtractEnabled"
          :config-string="configString"
          :variable-extract-string="variableExtractString"
          :variable-extract-config="variableExtractConfig"
          :on-set-predecessor="setNodePredecessor"
          :on-set-successor="setNodeSuccessor"
          :on-rename="renameNode"
          :on-remove="removeNode"
          :on-test="testSelectedStep"
          :on-save-as-action="openCustomActionDialog"
          :on-open-script-studio="openScriptStudio"
          :on-save-script="saveNodeScriptResource"
          :on-choose-upload-source="chooseUploadSource"
          :on-select-subworkflow="selectSubworkflow"
          :on-select-subworkflow-version="selectSubworkflowVersion"
          :on-update-subworkflow-input="updateSubworkflowInput"
          :on-update-config-string="updateConfigString"
          :on-update-config-json="updateConfigJson"
          :on-set-loop-items-source="setLoopItemsSource"
          :on-set-loop-items-field="setLoopItemsField"
          :on-set-variable-value-reference="setVariableValueReference"
          :on-toggle-variable-extract="toggleVariableExtract"
          :on-update-variable-extract-string="updateVariableExtractString"
          :on-update-variable-extract-mode="updateVariableExtractMode"
          :on-update-variable-extract-number="updateVariableExtractNumber"
          :on-update-variable-extract-boolean="updateVariableExtractBoolean"
          :on-set-condition-target="setConditionTarget"
          :on-add-condition="() => conditionRules.push({ field: 'status', operator: '等于', value: '' })"
          :on-result-field-change="onResultFieldChange"
          @update="selectedNode = $event"
          @update:loop-items-mode="loopItemsMode = $event as 'manual' | 'reference'"
          @update:loop-until-stop-mode="loopUntilStopMode = $event as typeof loopUntilStopMode"
          @update:loop-until-pattern="loopUntilPattern = $event"
          @update-condition-operator="conditionLogicalOperator = $event as 'AND' | 'OR'"
        />
          </template>
        </WorkflowInspectorShell>
        <WorkflowCatalogPanel
          v-if="catalogOpen"
          v-model:search-query="searchQuery"
          :actions="filteredActions"
          :groups="groupedActions"
          :error="catalogError"
          :selected-action-id="selectedCatalogAction?.id"
          :on-preview="previewCatalogAction"
          :on-drag-start="startActionDrag"
          :on-delete="deleteCustomAction"
        />
        <div
          class="workflow-catalog-resizer"
          :class="{ active: resizingWorkflowCatalog }"
          role="separator"
          aria-orientation="vertical"
          aria-label="调整节点库宽度"
          title="拖动调整节点库宽度"
          @pointerdown="startWorkflowCatalogResize"
        ><GripVertical :size="14" /></div>
        <WorkflowCanvasPanel
          :workflow="selected"
          :issues="issues"
          :interactive="canvasInteractive"
          :on-toggle-interactive="toggleCanvasInteractive"
          :on-open-catalog="() => { catalogOpen = true }"
          :on-node-select="showStepSettings"
          :on-connect="connectCanvasEdge"
          :on-node-add="addCanvasNode"
          :on-disconnect="disconnectCanvasEdge"
          :on-edge-update="updateCanvasEdge"
          :on-node-position-change="handleNodePositionChange"
          :on-node-positions-change="handleNodePositionsChange"
        />
        <div
          class="workflow-properties-resizer"
          :class="{ active: resizingWorkflowProperties }"
          role="separator"
          aria-orientation="vertical"
          aria-label="调整配置栏宽度"
          title="拖动调整配置栏宽度"
          @pointerdown="startWorkflowPropertiesResize"
        ><GripVertical :size="14" /></div>

      </main>
      <main v-else class="workflow-empty">选择一个 Workflow 开始编辑</main>
    </div>
    <WorkflowRunPreview
      v-if="showRunPreview"
      :workflow-name="selected?.name || ''"
      :target-count="selectedDeviceIds.length || 1"
      :step-count="selected?.nodes?.length || 0"
      :task-goal="taskGoal"
      :parallel-groups="previewParallelGroups"
      :steps="previewSteps"
      :has-risk="previewHasRisk"
      :confirmed-risks="confirmedRisks"
      :dry-running="dryRunning"
      :on-cancel="() => { showRunPreview = false }"
      :on-dry-run="dryRunWorkflow"
      :on-confirm="confirmRunFromPreview"
      @update:confirmed-risks="confirmedRisks = $event"
    />
    <div v-if="issues.length" class="workflow-issues" role="alert"><strong><AlertTriangle :size="14" />需要处理的问题</strong><button v-for="issue in issues" :key="`${issue.code}-${issue.node_id || 'workflow'}-${issue.message}`" type="button" class="workflow-issue" @click="focusIssue(issue)"><span>{{ issueText(issue) }}</span><small>点击定位</small></button></div>
    <footer v-if="selected" class="workflow-validation-bar" :class="{ invalid: issues.length, valid: !issues.length }"><span v-if="issues.length"><AlertTriangle :size="15" />还有 {{ issues.length }} 个问题需要处理</span><span v-else><CheckCircle2 :size="15" />流程结构看起来没问题</span><button v-if="issues.length" type="button" @click="validate">重新检查</button></footer>
  </section>
</template>

<style>







.workflow-run-target {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  color: var(--workflow-muted);
  font-size: 11px;
}
.workflow-properties select {
  min-width: 150px;
  max-width: 220px;
  padding: 6px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  background: var(--workflow-surface-input);
  color: inherit;
}
.flow-test-action { display: inline-flex; align-items: center; gap: 6px; color: #dbeafe; border-color: rgba(96, 165, 250, .48); background: rgba(37, 99, 235, .2); }
.flow-test-action:hover:not(:disabled) { border-color: #60a5fa; background: rgba(37, 99, 235, .34); }
@keyframes workflow-test-pulse { 50% { opacity: .45; transform: scale(.75); } }
@media (max-width: 980px) {
}
@media (max-width: 720px) {
}
.workflow-flow-raw-result, .workflow-flow-raw-json { min-width: 0; }
.workflow-flow-raw-result summary, .workflow-flow-raw-json summary { color: var(--workflow-focus); cursor: pointer; font-size: 10px; }
.workflow-flow-raw-result pre, .workflow-flow-raw-json pre { margin-top: 6px; }
.workflow-flow-result-list { display: grid; gap: 7px; }
.workflow-flow-result-item { min-width: 0; padding: 9px; border: 1px solid var(--workflow-border); border-radius: 7px; background: var(--workflow-surface); }
.workflow-flow-result-item header { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; }
.workflow-flow-result-item header strong { overflow: hidden; color: var(--workflow-text); text-overflow: ellipsis; white-space: nowrap; font: 600 11px ui-monospace, SFMono-Regular, Consolas, monospace; }
.workflow-flow-result-item header span { flex: 0 0 auto; color: var(--workflow-muted); font-size: 9px; }
.workflow-flow-result-item pre { max-height: 130px; border: 0; padding: 0; background: transparent; }
.workflow-script-reference-notice { display: grid; gap: 6px; margin: 0 0 8px; padding: 9px; border: 1px solid rgba(45,212,191,.26); border-radius: 5px; background: rgba(13,148,136,.08); }
.workflow-script-reference-notice > span { display: flex; align-items: center; gap: 6px; color: var(--workflow-focus); font-size: 10px; }
.workflow-script-reference-notice > strong { overflow-wrap: anywhere; color: var(--workflow-text); font-size: 11px; }
.workflow-script-reference-notice > small { color: var(--workflow-muted); font-size: 9px; line-height: 1.45; }
.workflow-script-resource-actions-inline { display: flex; flex-wrap: wrap; gap: 6px; }
.workflow-script-resource-actions-inline > button { min-height: 30px; font-size: 10px; }
.workflow-properties > .workflow-script-field { flex: 0 0 auto; min-height: 0; overflow: visible; }
.workflow-properties .workflow-script-editor { flex: 0 0 auto; min-height: 280px; height: 320px; }
:global(:root[data-theme="light"]) .workflow-flow-result-item { background: #ffffff; }
:global(:root[data-theme="light"]) .flow-test-action { color: #1d4ed8; background: #eff6ff; border-color: #93c5fd; }
.workflow-input-editor { display: grid; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--workflow-border); background: var(--workflow-surface-muted); }
.workflow-metadata-editor { display: grid; grid-template-columns: minmax(180px, .8fr) minmax(260px, 1.4fr); gap: 8px 14px; padding: 12px 16px; border-bottom: 1px solid var(--workflow-border); background: var(--workflow-surface); }
.workflow-metadata-editor label { min-width: 0; margin: 0; color: var(--workflow-muted); font-size: 10px; }
.workflow-metadata-editor input { margin-top: 4px; }
.workflow-metadata-editor small { color: #fca5a5; font-size: 10px; }
.workflow-input-editor .panel-heading { display: flex; align-items: center; gap: 8px; margin-bottom: 0; }
.workflow-input-editor .panel-heading small { flex: 1; }
.workflow-input-definitions { display: grid; gap: 8px; }
.workflow-input-definition { display: grid; grid-template-columns: minmax(110px, 1fr) 110px auto minmax(110px, 1fr) minmax(150px, 1.4fr) auto; align-items: end; gap: 8px; padding: 8px; border: 1px solid var(--workflow-border); border-radius: 6px; background: var(--workflow-surface); }
.workflow-output-definition { grid-template-columns: minmax(110px, .8fr) 100px minmax(180px, 1.4fr) minmax(150px, 1fr) auto; }
.workflow-output-value { min-width: 0; }
.workflow-subflow-contract { display: grid; gap: 8px; padding: 9px; border: 1px solid var(--workflow-border); border-radius: 6px; }
.workflow-input-definition label { display: grid; gap: 4px; color: var(--workflow-muted); font-size: 10px; }
.workflow-input-definition input:not([type='checkbox']), .workflow-input-definition select { min-width: 0; padding: 6px 7px; border: 1px solid var(--workflow-border); border-radius: 4px; background: var(--workflow-surface-input); color: inherit; }
.workflow-input-definition .workflow-input-required { display: flex; align-items: center; gap: 5px; height: 29px; white-space: nowrap; }
.workflow-input-delete { align-self: end; }
.workflow-runtime-input-row { display: flex; align-items: stretch; gap: 6px; }
.workflow-runtime-input-row > input { min-width: 0; flex: 1; }
.workflow-file-input { display: flex; align-items: stretch; gap: 6px; }
.workflow-file-input > input { min-width: 0; flex: 1; }
.workflow-file-button { display: inline-flex; align-items: center; gap: 4px; padding: 6px 9px; border: 1px solid var(--workflow-border); border-radius: 4px; background: var(--workflow-surface); color: inherit; cursor: pointer; white-space: nowrap; }
.workflow-upload-picker { width: 100%; justify-content: flex-start; min-height: 34px; overflow: hidden; text-overflow: ellipsis; }
.workflow-shared-root-hint { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 4px; }
.text-button { padding: 0; border: 0; background: none; color: #93c5fd; cursor: pointer; }
@media (max-width: 900px) { .workflow-input-definition { grid-template-columns: repeat(2, minmax(0, 1fr)); } .workflow-input-definition .workflow-input-description { grid-column: 1 / -1; } }
.workflow-command-field { position: relative; margin-bottom: 13px; }
.workflow-script-field { display: grid; gap: 10px; margin-bottom: 13px; padding: 10px; border: 1px solid rgba(20, 184, 166, .3); border-radius: 7px; background: rgba(13, 148, 136, .08); }
.workflow-script-heading { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.workflow-script-heading strong, .workflow-script-heading small { display: block; }
.workflow-script-heading strong { color: #ccfbf1; font-size: 12px; }
.workflow-script-heading small { margin-top: 3px; color: var(--workflow-muted); font-size: 10px; }
.workflow-risk-chip { display: inline-flex; align-items: center; gap: 4px; flex: 0 0 auto; padding: 3px 6px; border: 1px solid rgba(251, 191, 36, .45); border-radius: 4px; color: #fcd34d; background: rgba(161, 98, 7, .16); font-size: 9px; font-weight: 700; }
.workflow-script-field textarea { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; line-height: 1.45; }
.workflow-command-label-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; font-size: 12px; }
.workflow-command-insert { display: inline-flex; align-items: center; gap: 5px; padding: 5px 7px; border: 1px solid color-mix(in srgb, var(--blue) 42%, var(--workflow-border)); border-radius: 5px; color: var(--blue); background: color-mix(in srgb, var(--blue) 10%, transparent); font-size: 11px; cursor: pointer; }
.workflow-command-insert:hover { border-color: rgba(125, 211, 252, .8); background: rgba(37, 99, 235, .24); }
.workflow-command-field > textarea { margin-top: 0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; line-height: 1.5; }
.workflow-command-reference-menu { position: absolute; z-index: 8; top: 56px; right: 0; display: grid; gap: 3px; width: min(330px, calc(100% - 8px)); max-height: 260px; overflow: auto; padding: 8px; border: 1px solid color-mix(in srgb, var(--blue) 42%, var(--workflow-border)); border-radius: 7px; background: var(--workflow-surface); box-shadow: 0 16px 34px rgba(0, 0, 0, .18); }
.workflow-command-reference-title { padding: 2px 5px 6px; color: var(--workflow-muted); font-size: 10px; }
.workflow-command-reference-menu button { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; min-width: 0; padding: 7px 6px; border: 1px solid transparent; border-radius: 4px; color: inherit; background: transparent; cursor: pointer; }
.workflow-command-reference-menu button:hover { border-color: rgba(96, 165, 250, .38); background: rgba(37, 99, 235, .16); }
.workflow-command-reference-menu button span { min-width: 0; text-align: left; }
.workflow-command-reference-menu button strong, .workflow-command-reference-menu button small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-command-reference-menu button strong { color: #e0f2fe; font-size: 11px; font-weight: 600; }
.workflow-command-reference-menu button small { margin-top: 2px; color: var(--workflow-subtle); font-size: 10px; }
.workflow-command-reference-menu code { flex: 0 0 auto; color: #fcd34d; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10px; }
.workflow-command-reference-empty { padding: 5px; color: var(--workflow-subtle); font-size: 10px; line-height: 1.4; }
.workflow-command-preview { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 3px 7px; margin-top: 7px; padding: 7px 8px; border-left: 2px solid rgba(45, 212, 191, .65); background: rgba(15, 118, 110, .1); }
.workflow-command-preview span { color: rgba(153, 246, 228, .78); font-size: 10px; }
.workflow-command-preview code { min-width: 0; overflow: hidden; color: #ccfbf1; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.workflow-command-preview small { grid-column: 2; color: rgba(226, 232, 240, .48); font-size: 10px; }
.workflow-command-preview.is-runtime { border-left-color: rgba(250, 204, 21, .7); background: rgba(161, 98, 7, .1); }
.workflow-command-preview.is-runtime span, .workflow-command-preview.is-runtime code { color: #fde68a; }
.field-hint { display: block; margin-top: 4px; color: var(--workflow-muted); font-size: 11px; line-height: 1.4; }
.run-action { background: #0f766e !important; border-color: #14b8a6 !important; color: #f0fdfa; }
.task-goal { padding: 6px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface-input); color: inherit; }
.workflow-create-anchor { position: relative; display: inline-flex; }
.workflow-create-menu { position: absolute; top: calc(100% + 8px); left: 0; z-index: 20; display: grid; gap: 6px; width: 248px; padding: 12px; border: 1px solid rgba(96, 165, 250, .42); border-radius: 8px; background: #172033; box-shadow: 0 18px 36px rgba(2, 6, 23, .35); }
.workflow-create-menu strong { padding: 2px 4px 5px; color: #dbeafe; font-size: 11px; }
.workflow-create-menu button { min-height: 32px; padding: 7px 9px; border: 1px solid rgba(148, 163, 184, .22); border-radius: 5px; background: #202c42; color: #e2e8f0; text-align: left; cursor: pointer; }
.workflow-create-menu button:hover { border-color: rgba(96, 165, 250, .62); background: #263a5a; }
.workflow-create-menu button:disabled { opacity: .45; cursor: default; }
.workflow-run-header-button { display: inline-flex; align-items: center; gap: 5px; padding: 5px 8px; border: 1px solid rgba(96, 165, 250, .45); border-radius: 5px; color: #bfdbfe; background: rgba(37, 99, 235, .16); font-size: 11px; cursor: pointer; }
.workflow-run-header-button:hover { border-color: rgba(147, 197, 253, .75); background: rgba(37, 99, 235, .28); }
.workflow-dirty-state { color: #fcd34d; font-size: 10px; white-space: nowrap; }
.condition-builder { display: grid; gap: 8px; }
.condition-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; }
.condition-row select, .condition-row input { min-width: 0; padding: 6px; border: 1px solid var(--workflow-border); border-radius: 4px; background: rgba(15,23,42,.7); color: inherit; }
.workflow-issues { display: grid; gap: 6px; margin: 0; padding: 10px 20px; border-bottom: 1px solid rgba(248, 113, 113, .25); background: rgba(127, 29, 29, .16); color: #fecaca; font-size: 12px; }
.workflow-issues > strong { display: flex; align-items: center; gap: 6px; }
.workflow-issue { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; padding: 7px 9px; border: 1px solid rgba(248, 113, 113, .25); border-radius: 5px; background: rgba(127, 29, 29, .2); color: #fee2e2; text-align: left; cursor: pointer; }
.workflow-issue:hover { border-color: rgba(252, 165, 165, .65); background: rgba(127, 29, 29, .35); }
.workflow-issue small { flex: 0 0 auto; color: #fca5a5; }
.workflow-branch-notice { display: flex; align-items: center; gap: 6px; margin: 0; padding: 7px 20px; color: #fcd34d; background: rgba(180, 83, 9, .14); font-size: 12px; }
.workflow-search { display: flex; align-items: center; gap: 6px; margin: 0 0 8px; padding: 5px 7px; border: 1px solid var(--workflow-border); border-radius: 5px; color: rgba(226, 232, 240, .55); }
.workflow-search input { min-width: 0; margin: 0; padding: 2px; border: 0; background: transparent; color: inherit; outline: 0; }
.catalog-empty { margin: 8px; color: rgba(226, 232, 240, .5); font-size: 11px; }
.catalog-error { margin: 8px 0; padding: 8px; border: 1px solid rgba(248, 113, 113, .35); border-radius: 5px; color: #fca5a5; background: rgba(127, 29, 29, .16); font-size: 10px; line-height: 1.4; }
.action-category-group { display: grid; gap: 5px; }
.action-category-heading { display: flex; align-items: center; justify-content: space-between; margin: 10px 2px 1px; padding-bottom: 4px; border-bottom: 1px solid rgba(100,116,139,.18); color: var(--workflow-muted, rgba(226,232,240,.72)); font-size: 10px; font-weight: 700; letter-spacing: .02em; }
.action-category-heading small { color: var(--workflow-subtle, rgba(226,232,240,.48)); font-size: 9px; font-weight: 600; }
.action-category-group:first-of-type .action-category-heading { margin-top: 4px; }
.node-library-hint { margin: 0; color: rgba(226, 232, 240, .52); font-size: 10px; line-height: 1.5; }
.node-library-hint + .connect-button { margin-top: 10px; }

/* Workflow Canvas 样式 */
.workflow-canvas-container {
  flex: 1 1 auto;
  height: auto;
  min-height: 520px;
  min-width: 0;
  background: #0b1220;
  border: 1px solid rgba(71, 85, 105, .65);
  border-radius: 9px;
  overflow: hidden;
}

.workflow-studio-grid > .workflow-canvas {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: auto;
  background: rgba(15, 23, 42, .2);
}
.canvas-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 38px;
  margin: 0 0 10px;
  padding: 0 2px;
  color: rgba(226, 232, 240, .58);
  font-size: 11px;
}
.canvas-toolbar-title { display: flex; align-items: center; gap: 8px; }
.canvas-toolbar-title svg { color: #60a5fa; }
.canvas-toolbar-title strong { color: #e2e8f0; font-size: 13px; }
.canvas-toolbar-title span { padding-left: 8px; border-left: 1px solid rgba(100, 116, 139, .35); }
.canvas-toolbar-actions { display: inline-flex; align-items: center; gap: 10px; }
.canvas-add-step { display: inline-flex; align-items: center; gap: 5px; min-height: 28px; padding: 5px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; color: var(--workflow-muted); background: var(--workflow-surface); cursor: pointer; font-size: 10px; }
.canvas-add-step:hover { border-color: var(--workflow-focus); color: var(--workflow-text); background: #1b365a; }
.canvas-interactive-toggle { display: inline-flex; align-items: center; gap: 5px; padding: 5px 8px; border: 1px solid rgba(100, 116, 139, .35); border-radius: 6px; color: rgba(226, 232, 240, .55); background: rgba(15, 23, 42, .46); font-size: 10px; cursor: pointer; }
.canvas-interactive-toggle:hover, .canvas-interactive-toggle.active { border-color: rgba(96, 165, 250, .55); color: #bfdbfe; background: rgba(37, 99, 235, .16); }
.canvas-toolbar-hint { color: rgba(226, 232, 240, .42); }

@media (max-width: 900px) { .workflow-search { grid-column: 1 / -1; } }
@media (max-width: 900px) {
  .workflow-run-target { order: 10; width: 100%; margin-left: 0; }
}
@media (max-width: 980px) {
  .workflow-studio-grid { height: auto; }
}
:global(:root[data-theme="light"]) .workflow-canvas-container { background: #f1f5f9; border-color: #cbd5e1; }
:global(:root[data-theme="light"]) .workflow-studio-grid > .workflow-canvas { background: #f8fafc; }
:global(:root[data-theme="light"]) .canvas-toolbar,
:global(:root[data-theme="light"]) .canvas-toolbar-hint { color: #64748b; }
:global(:root[data-theme="light"]) .workflow-command-reference-menu { color: var(--workflow-text); background: #ffffff; border-color: #93c5fd; }
:global(:root[data-theme="light"]) .workflow-command-reference-title,
:global(:root[data-theme="light"]) .workflow-command-reference-menu button small,
:global(:root[data-theme="light"]) .workflow-command-reference-empty,
:global(:root[data-theme="light"]) .field-hint,
:global(:root[data-theme="light"]) .node-library-hint,
:global(:root[data-theme="light"]) .catalog-empty { color: #64748b; }
:global(:root[data-theme="light"]) .workflow-run-header-button { color: #1d4ed8; background: #eff6ff; border-color: #93c5fd; }
:global(:root[data-theme="light"]) .workflow-dirty-state { color: #92400e; }
:global(:root[data-theme="light"]) .workflow-branch-notice { color: #92400e; background: #fffbeb; }
:global(:root[data-theme="light"]) .canvas-toolbar-title strong { color: #172033; }
:global(:root[data-theme="light"]) .canvas-add-step:hover { border-color: #93c5fd; color: #1d4ed8; background: #eff6ff; }
:global(:root[data-theme="light"]) .canvas-interactive-toggle { color: #475569; background: #ffffff; border-color: #cbd5e1; }


/* Workflow Studio refinement */
.workflow-library {
  --studio-gap: 12px;
  --workflow-focus: #4f9cf9;
  --workflow-success: #2dd4a3;
  --workflow-warning: #f0b44d;
  min-width: 720px;
  background: var(--workflow-bg);
}
.workflow-library-header {
  min-height: 64px;
  padding: 12px 22px;
  background: var(--workflow-header);
}
.workflow-brand { min-width: 0; display: inline-flex; align-items: center; gap: 10px !important; }
.workflow-brand-mark { display: inline-grid; flex: 0 0 auto; width: 30px; height: 30px; place-items: center; border: 1px solid rgba(96,165,250,.36); border-radius: 8px; color: #bfdbfe; background: rgba(37,99,235,.18); }
.workflow-brand strong { display: block; color: var(--workflow-text); font-size: 15px; line-height: 1.15; }
.workflow-brand small { display: block; margin-top: 3px; color: var(--workflow-muted); font-size: 10px; }
.workflow-library-header-actions { gap: 8px !important; }
.workflow-library-header-actions > button:last-child { display: inline-grid !important; width: 30px; height: 30px; padding: 0; place-items: center; border: 1px solid var(--workflow-border); border-radius: 6px; background: transparent; }
.workflow-library-toolbar { min-height: 52px; padding: 8px 22px; gap: 8px; background: color-mix(in srgb, var(--workflow-surface) 86%, var(--workflow-bg)); }
.workflow-library-toolbar .toolbar-group { gap: 5px; }
.workflow-library-toolbar button { min-height: 30px; padding: 6px 9px; border-radius: 6px; }
.workflow-library-toolbar .icon-toolbar-button { width: 30px; padding: 0; justify-content: center; }
.workflow-library-toolbar .studio-mode-active { color: #eff6ff; border-color: rgba(96,165,250,.55); background: rgba(37,99,235,.24); }
.workflow-inline-toggle { display: inline-flex !important; align-items: center; gap: 5px; white-space: nowrap; }
.workflow-inline-toggle input { width: 13px !important; height: 13px; }
.workflow-script-editor-panel :deep(.workflow-script-editor) { position: relative; z-index: 1; min-height: 0; height: 100%; pointer-events: auto; }
.workflow-script-node-inputs { display: grid; gap: 9px; margin-bottom: 11px; padding: 10px; border: 1px solid var(--workflow-border); border-radius: 6px; background: var(--workflow-surface-muted); }
.workflow-script-node-input-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.workflow-script-node-input-heading > div:first-child { display: grid; gap: 2px; min-width: 0; }
.workflow-script-node-input-heading strong { color: var(--workflow-text); font-size: 11px; }
.workflow-script-node-input-heading small { color: var(--workflow-muted); font-size: 9px; }
.workflow-script-node-input-heading .workflow-script-test-mode { flex: 0 0 auto; margin: 0; }
.workflow-script-node-input-heading .workflow-script-test-mode button { display: inline-flex; align-items: center; justify-content: center; gap: 4px; min-width: 58px; }
.workflow-script-node-input-form { display: grid; gap: 9px; }
.workflow-script-node-input-field { display: grid; gap: 4px; }
.workflow-script-node-input-field > label:first-child { display: flex; align-items: baseline; justify-content: space-between; margin: 0; color: var(--workflow-text); font-size: 10px; }
.workflow-script-node-input-field > label:first-child em { color: #f59e0b; font-size: 9px; font-style: normal; }
.workflow-script-node-input-field > input, .workflow-script-node-input-field > textarea { box-sizing: border-box; width: 100%; min-height: 31px; padding: 7px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; color: inherit; background: var(--workflow-surface-input); }
.workflow-script-node-input-field > textarea { resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.workflow-script-node-input-field > .workflow-inline-toggle { margin: 0; color: var(--workflow-text); }
.workflow-new-button { color: #eff6ff !important; background: #2563eb !important; border-color: #3b82f6 !important; box-shadow: 0 3px 10px rgba(37,99,235,.22); }
.workflow-new-button:hover { background: #1d4ed8 !important; }
.toolbar-group-secondary { padding-left: 2px; }
.toolbar-group-secondary > button:not(.icon-toolbar-button), .toolbar-group-commit > button:not(.primary-action) { color: var(--workflow-muted); background: transparent; border-color: transparent; }
.toolbar-group-secondary > button:hover, .toolbar-group-commit > button:hover:not(:disabled) { color: var(--workflow-text); background: var(--workflow-surface-muted); border-color: var(--workflow-border); }
.workflow-more-menu { position: relative; }
.workflow-more-menu > summary { display: inline-flex; align-items: center; gap: 5px; min-height: 30px; padding: 6px 9px; border: 1px solid transparent; border-radius: 6px; color: var(--workflow-muted); cursor: pointer; list-style: none; user-select: none; }
.workflow-more-menu > summary::-webkit-details-marker { display: none; }
.workflow-more-menu > summary:hover,
.workflow-more-menu[open] > summary { border-color: var(--workflow-border); color: var(--workflow-text); background: var(--workflow-surface-muted); }
.workflow-more-menu > summary:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.workflow-more-popover { position: absolute; z-index: 85; top: calc(100% + 6px); left: 0; display: grid; gap: 3px; min-width: 220px; padding: 6px; border: 1px solid var(--workflow-border); border-radius: 8px; background: var(--workflow-surface); box-shadow: 0 14px 32px rgba(0, 0, 0, .3); }
.workflow-more-popover .workflow-more-heading { padding: 6px 8px 2px; color: var(--workflow-muted); font-size: 9px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.workflow-more-popover button { display: flex; align-items: center; gap: 8px; width: 100%; min-height: 32px; padding: 6px 8px; border: 0; border-radius: 5px; color: var(--workflow-text); text-align: left; background: transparent; cursor: pointer; font-size: 11px; }
.workflow-more-popover button:hover:not(:disabled) { background: var(--workflow-surface-muted); }
.workflow-more-popover button:disabled { color: var(--workflow-muted); opacity: .48; cursor: default; }
.secondary-run-button { color: #99f6e4 !important; background: rgba(13,148,136,.12) !important; border-color: rgba(45,212,191,.28) !important; }
.secondary-run-button:hover:not(:disabled) { background: rgba(13,148,136,.22) !important; }
.workflow-run-target { padding-left: 4px; }
.workflow-library-body { grid-template-columns: 232px minmax(0, 1fr); }
.workflow-library-body > aside { padding: 14px 10px; background: color-mix(in srgb, var(--workflow-surface-muted) 86%, var(--workflow-bg)); }
.workflow-list-title { padding: 0 8px 10px; }
.workflow-list-title span { color: var(--workflow-text); font-size: 12px; font-weight: 650; }
.workflow-list-title small { color: var(--workflow-muted); font-size: 10px; }
.workflow-library-body aside button { margin: 2px 0; border: 1px solid transparent; border-radius: 7px; }
.workflow-library-body aside button.active { border-color: rgba(79,156,249,.34); background: rgba(37,99,235,.14); box-shadow: inset 3px 0 0 var(--workflow-focus); }
.workflow-library-body aside button strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-library-body aside button small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-metadata-editor { grid-template-columns: minmax(220px,.75fr) minmax(280px,1.25fr); gap: 8px 16px; padding: 10px 18px; }
.workflow-contract-heading { grid-column: 1 / -1; display: flex; align-items: center; gap: 9px; min-width: 0; }
.workflow-section-kicker { color: var(--workflow-focus); font-size: 10px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.workflow-contract-heading strong { overflow: hidden; min-width: 0; color: var(--workflow-text); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.workflow-contract-status { margin-left: auto; padding: 3px 7px; border: 1px solid rgba(45,212,163,.26); border-radius: 999px; color: #86efac; background: rgba(16,185,129,.1); font-size: 10px; white-space: nowrap; }
.workflow-contract-status.dirty { border-color: rgba(240,180,77,.34); color: #fcd34d; background: rgba(180,83,9,.12); }
.workflow-metadata-editor label { font-size: 10px; }
.workflow-metadata-editor input { min-height: 30px; }
.workflow-input-editor { padding: 9px 16px; overflow: visible; }
.workflow-input-editor .panel-heading { min-height: 26px; }
.workflow-input-definitions { gap: 6px; }
.workflow-input-definition { gap: 6px; padding: 6px; border-radius: 6px; }
.workflow-input-definition input:not([type='checkbox']), .workflow-input-definition select { min-height: 28px; padding: 5px 6px; }
.workflow-runtime-inputs { padding: 9px 16px; overflow: visible; }
.workflow-runtime-inputs .workflow-input-values { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px 12px; }
.workflow-runtime-inputs .workflow-input-values > label { min-width: 0; margin: 0; }
.workflow-action-catalog { min-height: 0; overflow: auto; border: 0; border-radius: 0; background: var(--workflow-surface-muted); }
.workflow-properties { min-height: 0; overflow: visible; border: 0; border-radius: 0; background: transparent; }
.workflow-action-catalog { position: relative; padding: 14px 12px; border-right: 1px solid var(--workflow-border); }
.workflow-properties { padding: 14px 16px 22px; }
.workflow-properties.workflow-empty { display: grid; place-items: center; color: var(--workflow-muted); text-align: center; }
.workflow-canvas { min-width: 0; min-height: 0; padding: 12px 14px 14px; background: var(--workflow-bg); }
.workflow-canvas-container { min-height: 0; height: 100%; border: 1px solid rgba(100,116,139,.45); border-radius: 10px; background: #0a1220; overflow: hidden; }
.workflow-canvas-container .workflow-canvas { padding: 0; }
.catalog-count { display: inline-grid; min-width: 22px; height: 20px; padding: 0 5px; place-items: center; border: 1px solid rgba(79,156,249,.24); border-radius: 999px; color: #bfdbfe; background: rgba(37,99,235,.12); font-size: 10px; }
.workflow-action-catalog .panel-heading, .workflow-properties .panel-heading { position: sticky; top: -14px; z-index: 2; margin: -14px -12px 8px; padding: 14px 12px 9px; background: var(--workflow-surface-muted); }
.workflow-properties .panel-heading { margin-left: -16px; margin-right: -16px; padding-left: 16px; padding-right: 16px; }
.properties-node-index { overflow: hidden; max-width: 112px; color: var(--workflow-subtle); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.workflow-action-catalog .action-tile { min-height: 46px; padding: 8px; border-radius: 7px; }
.workflow-action-catalog .action-tile small { margin-top: 2px; line-height: 1.25; }
.workflow-properties label { margin-bottom: 11px; }
.workflow-properties input, .workflow-properties textarea, .workflow-properties select { min-height: 31px; }
.workflow-properties textarea { resize: vertical; }
.canvas-toolbar { min-height: 34px; margin-bottom: 8px; }
.canvas-toolbar-title { gap: 7px; }
.canvas-toolbar-title strong { font-size: 12px; }
.canvas-toolbar-actions { gap: 7px; }
.canvas-toolbar-hint { display: none; }

/* Compact studio shell: keep high frequency actions visible and defer the rest. */
.workflow-library-header { min-height: 56px; padding: 10px 18px; }
.workflow-library-toolbar { min-height: 46px; padding: 6px 18px; }
.workflow-library-body { grid-template-columns: 208px minmax(0, 1fr); }
.workflow-library-body > aside { padding: 12px 8px; }
.workflow-version-toggle {
  display: flex !important;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 30px;
  margin-top: 12px !important;
  padding: 5px 8px !important;
  border-top: 1px solid rgba(100, 116, 139, .24) !important;
  border-radius: 0 !important;
  color: var(--workflow-muted);
  background: transparent;
  font-size: 10px;
}
.workflow-version-toggle > span { display: inline-flex; align-items: center; gap: 5px; }
.workflow-version-toggle svg { transition: transform .16s ease; }
.workflow-version-toggle svg.rotated { transform: rotate(180deg); }
.workflow-version-toggle small { color: var(--workflow-subtle); font-size: 10px; }
.workflow-version-toggle { background: var(--workflow-surface-muted); }
.workflow-version-toggle:hover { color: var(--workflow-text); background: var(--workflow-surface); }
.workflow-version-manager { margin-top: 2px; padding-top: 8px; border-top: 0; }
.workflow-more-danger { color: #fca5a5 !important; }
.workflow-more-danger:hover:not(:disabled) { color: #fecaca !important; background: rgba(127, 29, 29, .24) !important; }
.workflow-run-menu { position: relative; }
.workflow-run-menu > summary {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 30px;
  padding: 6px 10px;
  border: 1px solid #14b8a6;
  border-radius: 6px;
  color: #f0fdfa;
  background: #0f766e;
  cursor: pointer;
  list-style: none;
  user-select: none;
  font-size: 11px;
}
.workflow-run-menu > summary::-webkit-details-marker { display: none; }
.workflow-run-menu > summary:hover,
.workflow-run-menu[open] > summary { background: #115e59; }
.workflow-run-popover {
  position: absolute;
  z-index: 90;
  top: calc(100% + 6px);
  right: 0;
  display: grid;
  gap: 4px;
  min-width: 152px;
  padding: 6px;
  border: 1px solid var(--workflow-border);
  border-radius: 7px;
  background: var(--workflow-surface);
  box-shadow: 0 14px 32px rgba(0, 0, 0, .3);
}
.workflow-run-popover button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-height: 30px;
  padding: 6px 8px;
  border-radius: 5px;
  text-align: left;
  white-space: nowrap;
}
.workflow-run-popover .flow-test-action,
.workflow-run-popover .run-action,
.workflow-run-popover .secondary-run-button { color: var(--workflow-text) !important; background: transparent !important; border-color: transparent !important; }
.workflow-run-popover button:hover:not(:disabled) { border-color: var(--workflow-border) !important; background: var(--workflow-surface-muted) !important; }
.workflow-run-popover button:disabled { opacity: .45; }
.workflow-action-catalog .action-tile { min-height: 42px; padding: 7px; }
.workflow-action-catalog .action-tile { background: var(--workflow-surface); }
.workflow-action-catalog .action-tile:hover,
.workflow-action-catalog .action-tile[aria-pressed="true"] { background: #1b365a; }
.workflow-action-catalog .action-tile small { display: -webkit-box; overflow: hidden; -webkit-box-orient: vertical; -webkit-line-clamp: 1; line-height: 1.2; }
.workflow-action-catalog .node-library-hint { display: none; }
.workflow-search { background: var(--workflow-surface-input); }
.workflow-properties { background: var(--workflow-surface-muted); }
.workflow-studio-grid > .workflow-canvas { background: var(--workflow-bg); }
.canvas-interactive-toggle { background: var(--workflow-surface); }
.canvas-interactive-toggle:hover,
.canvas-interactive-toggle.active { background: #1b365a; }
.workflow-run-header-button { background: #193252; }
.workflow-run-header-button:hover { background: #23456e; }

@media (max-width: 980px) {
  .workflow-library-body { grid-template-columns: 184px minmax(0, 1fr); }
}

@media (max-width: 1180px) {
  .workflow-library-toolbar { padding-left: 14px; padding-right: 14px; }
}
@media (max-width: 980px) {
  .workflow-library-body { grid-template-columns: 190px minmax(0, 1fr); }
  .workflow-properties-resizer { display: none; }
  .workflow-library-toolbar { align-items: center; }
  .workflow-run-target { order: 9; }
  .toolbar-group-actions { margin-left: auto; }
}
@media (max-width: 720px) {
  .workflow-library { min-width: 0; }
  .workflow-library-header { padding: 10px 14px; }
  .workflow-library-toolbar { gap: 5px; padding: 8px 12px; }
  .workflow-library-toolbar .toolbar-divider { display: none; }
  .toolbar-group-secondary > button[title="自动布局"] { display: none; }
  .workflow-library-body { grid-template-columns: 1fr; }
  .workflow-library-body > aside { max-height: 150px; border-right: 0; border-bottom: 1px solid var(--workflow-border); }
  .workflow-run-target { width: 100%; margin-left: 0; }
  .workflow-run-target :deep(.workflow-target-picker) { width: min(100%, 320px); }
  .workflow-run-target :deep(.workflow-target-trigger) { width: 100%; min-width: 0; }
}
:global(:root[data-theme="light"]) .workflow-action-catalog,
:global(:root[data-theme="light"]) .workflow-properties { background: #f1f5f9; }
:global(:root[data-theme="light"]) .workflow-library-toolbar { background: #ffffff; }
:global(:root[data-theme="light"]) .workflow-brand-mark { color: #1d4ed8; background: #eff6ff; border-color: #bfdbfe; }
:global(:root[data-theme="light"]) .workflow-new-button { color: #fff !important; background: #2563eb !important; }
:global(:root[data-theme="light"]) .workflow-contract-status { color: #047857; background: #ecfdf5; }
:global(:root[data-theme="light"]) .workflow-contract-status.dirty { color: #92400e; background: #fffbeb; }
:global(:root[data-theme="light"]) .workflow-action-catalog .panel-heading,
:global(:root[data-theme="light"]) .workflow-properties .panel-heading { background: #f1f5f9; }
:global(:root[data-theme="light"]) .catalog-count { color: #1d4ed8; background: #eff6ff; border-color: #bfdbfe; }



/* Canonical studio layout. The inspector shell owns its internal layout and scroll. */
.workflow-step-navigation { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--workflow-border); }
.workflow-step-navigation > strong { display: block; padding: 0 8px 10px; color: var(--workflow-muted); font-size: 12px; }
.workflow-step-navigation button { display: grid; width: 100%; text-align: left; padding: 10px 8px; gap: 5px; }
.workflow-step-navigation button span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-library-body { grid-template-columns: 178px minmax(0, 1fr); }
.workflow-library-body > main.workflow-studio-grid {
  display: grid;
  position: relative;
  grid-template-areas: 'catalog canvas inspector';
  grid-template-columns: var(--workflow-catalog-width, 224px) minmax(0, 1fr) var(--workflow-properties-width, 640px);
  grid-template-rows: minmax(0, 1fr);
  width: 100%;
  height: 100%;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.workflow-studio-grid > .workflow-action-catalog {
  grid-area: catalog;
  min-width: 0;
  min-height: 0;
  height: 100%;
  max-height: 100%;
  align-self: stretch;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: #64748b rgba(15, 23, 42, .28);
}
.workflow-studio-grid > .workflow-action-catalog::-webkit-scrollbar { width: 10px; }
.workflow-studio-grid > .workflow-action-catalog::-webkit-scrollbar-track { background: rgba(15, 23, 42, .28); }
.workflow-studio-grid > .workflow-action-catalog::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 999px; background: #64748b; background-clip: padding-box; }
.workflow-studio-grid > .workflow-action-catalog::-webkit-scrollbar-thumb:hover { background: #94a3b8; background-clip: padding-box; }
.workflow-studio-grid > .workflow-canvas {
  grid-area: canvas;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.workflow-studio-grid > .workflow-right-rail { grid-area: inspector; }
.workflow-studio-grid > .workflow-catalog-resizer {
  position: absolute;
  z-index: 3;
  top: 0;
  bottom: 0;
  left: var(--workflow-catalog-width, 224px);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 8px;
  cursor: col-resize;
  user-select: none;
}
.workflow-studio-grid > .workflow-catalog-resizer:hover,
.workflow-studio-grid > .workflow-catalog-resizer.active { background: rgba(59, 130, 246, .12); }
.workflow-studio-grid > .workflow-catalog-resizer svg { pointer-events: none; opacity: .4; }
.workflow-studio-grid > .workflow-catalog-resizer:hover svg,
.workflow-studio-grid > .workflow-catalog-resizer.active svg { opacity: .7; }
.workflow-studio-grid > .workflow-properties-resizer {
  position: absolute;
  top: 0;
  bottom: 0;
  left: auto;
  /* Center the handle on the inspector's left edge, rather than the window edge. */
  right: calc(var(--workflow-properties-width, 312px) - 4px);
}

/* The step editor is the primary work surface. Keep its fields readable at the default width. */
.workflow-studio-grid > .workflow-right-rail {
  background: var(--workflow-surface, #111827);
}
.workflow-studio-grid.step-settings-mode > .workflow-right-rail .workflow-right-rail-switcher {
  padding: 10px 16px;
  background: var(--workflow-surface, #111827);
}
.workflow-studio-grid.step-settings-mode > .workflow-right-rail .workflow-inspector-content {
  padding: 0;
}
.workflow-studio-grid.step-settings-mode > .workflow-right-rail :deep(.workflow-properties) {
  padding: 18px 20px 28px;
  border: 0;
  border-radius: 0;
  background: transparent;
}
.workflow-studio-grid.step-settings-mode > .workflow-right-rail :deep(.workflow-properties .workflow-io-contract) {
  border-radius: 5px;
}

@media (max-width: 980px) {
  .workflow-library-body > main.workflow-studio-grid {
    grid-template-areas: 'catalog canvas' 'inspector inspector';
    grid-template-columns: minmax(170px, var(--workflow-catalog-width, 220px)) minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr) minmax(240px, 42vh);
  }
  .workflow-studio-grid > .workflow-catalog-resizer { display: none; }
  .workflow-studio-grid > .workflow-properties-resizer { display: none; }
}

@media (max-width: 720px) {
  .workflow-library-body > main.workflow-studio-grid {
    grid-template-areas: 'catalog' 'canvas' 'inspector';
    grid-template-columns: 1fr;
    grid-template-rows: minmax(0, min(34vh, 260px)) minmax(420px, 1fr) minmax(240px, 46vh);
    overflow: auto;
  }
  .workflow-studio-grid > .workflow-action-catalog { height: 100%; max-height: min(34vh, 260px); }
  .workflow-studio-grid > .workflow-catalog-resizer { display: none; }
}

/* When the catalog is closed, give the canvas the entire center column. */
.workflow-library-body > main.workflow-studio-grid.catalog-collapsed {
  grid-template-areas: 'canvas inspector';
  grid-template-columns: minmax(0, 1fr) minmax(0, var(--workflow-properties-width, 640px));
}
.workflow-library-body > main.workflow-studio-grid.catalog-collapsed > .workflow-catalog-resizer { display: none; }
@media (max-width: 980px) {
  .workflow-library-body > main.workflow-studio-grid.catalog-collapsed {
    grid-template-areas: 'canvas' 'inspector';
    grid-template-columns: 1fr;
    grid-template-rows: minmax(0, 1fr) minmax(240px, 42vh);
  }
}
@media (max-width: 720px) {
  .workflow-library-body > main.workflow-studio-grid.catalog-collapsed {
    grid-template-areas: 'canvas' 'inspector';
    grid-template-columns: 1fr;
    grid-template-rows: minmax(420px, 1fr) minmax(240px, 46vh);
  }
}
</style>
