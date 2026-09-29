import { nextTick, onMounted, onUnmounted, watch, type Ref, type ComputedRef } from 'vue'
import { useUndoRedo, useUndoRedoShortcuts } from './useUndoRedo'
import { autoLayout } from '../utils/layoutAlgorithms'

type EditorContext = {
  selected: Ref<any>
  selectedNode: Ref<any>
  selectedDeviceId: Ref<string>
  rightRailMode: Ref<'workflow' | 'step'>
  conditionRules: Ref<any[]>
  conditionLogicalOperator: Ref<'AND' | 'OR'>
  actions: any[]
  canvasNodes: ComputedRef<any[]>
}

type NodeItem = {
  id: string
  action_id: string
  config: Record<string, unknown>
  input_mapping?: Record<string, unknown>
  position?: { x: number; y: number }
}
type WorkflowEdge = { source: string; target: string; condition?: string; source_handle?: string }
type WorkflowEditorWorkflow = { id: string; name: string; version?: string | number; nodes?: NodeItem[]; edges?: WorkflowEdge[]; [key: string]: any }

export function useWorkflowEditor(context: EditorContext) {
  const { selected: selectedState, selectedNode: selectedNodeState, selectedDeviceId, rightRailMode, conditionRules, conditionLogicalOperator, actions, canvasNodes: canvasNodeState } = context
  const selected = selectedState as Ref<WorkflowEditorWorkflow | null>
  const selectedNode = selectedNodeState as Ref<NodeItem | null>
  const canvasNodes = canvasNodeState as ComputedRef<NodeItem[]>
  let workflowClipboard: any = null
const WORKFLOW_NODE_WIDTH = 232
const WORKFLOW_NODE_HEIGHT = 128
const INSERT_EDGE_DISTANCE = 86

function nodePosition(node: NodeItem, index: number): { x: number; y: number } {
  const x = Number(node.position?.x)
  const y = Number(node.position?.y)
  return {
    x: Number.isFinite(x) ? x : 80 + (index % 3) * 260,
    y: Number.isFinite(y) ? y : 70 + Math.floor(index / 3) * 160
  }
}

function pointToSegmentDistance(point: { x: number; y: number }, start: { x: number; y: number }, end: { x: number; y: number }): number {
  const dx = end.x - start.x
  const dy = end.y - start.y
  const lengthSquared = dx * dx + dy * dy
  if (!lengthSquared) return Math.hypot(point.x - start.x, point.y - start.y)
  const projection = Math.max(0, Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared))
  return Math.hypot(point.x - (start.x + projection * dx), point.y - (start.y + projection * dy))
}

function findInsertEdge(position: { x: number; y: number }): WorkflowEdge | null {
  if (!selected.value) return null
  const nodes = canvasNodes.value
  const positions = new Map(nodes.map((node, index) => [node.id, nodePosition(node, index)]))
  const dropCenter = {
    x: position.x + WORKFLOW_NODE_WIDTH / 2,
    y: position.y + WORKFLOW_NODE_HEIGHT / 2
  }
  let nearest: { edge: WorkflowEdge; distance: number } | null = null
  for (const edge of selected.value.edges || []) {
    const source = (selected.value.nodes || []).find((node) => node.id === edge.source)
    const target = (selected.value.nodes || []).find((node) => node.id === edge.target)
    const sourcePosition = source ? positions.get(source.id) : undefined
    const targetPosition = target ? positions.get(target.id) : undefined
    if (!source || !target || !sourcePosition || !targetPosition) continue
    const sourceIsCondition = source.action_id === 'utility.condition'
    const start = sourceIsCondition
      ? { x: sourcePosition.x + WORKFLOW_NODE_WIDTH, y: sourcePosition.y + (edge.source_handle === 'false' ? WORKFLOW_NODE_HEIGHT * 0.68 : WORKFLOW_NODE_HEIGHT * 0.38) }
      : { x: sourcePosition.x + WORKFLOW_NODE_WIDTH / 2, y: sourcePosition.y + WORKFLOW_NODE_HEIGHT }
    const end = { x: targetPosition.x + WORKFLOW_NODE_WIDTH / 2, y: targetPosition.y }
    const distance = pointToSegmentDistance(dropCenter, start, end)
    if (distance <= INSERT_EDGE_DISTANCE && (!nearest || distance < nearest.distance)) nearest = { edge, distance }
  }
  return nearest?.edge || null
}

function addNode(actionId: string, position?: { x: number; y: number }): void {
  if (!selected.value) return
  const actionPreset = actions.find((item) => item.id === actionId)?.preset
  const actualActionId = actionPreset?.actionId || actionId
  const nodes = selected.value.nodes || []
  const insertEdge = position ? findInsertEdge(position) : null
  const node: NodeItem = {
    id: nextNodeId(actualActionId),
    action_id: actualActionId,
    config: actionPreset ? JSON.parse(JSON.stringify(actionPreset.config)) : defaultConfig(actualActionId),
    position
  }
  if (insertEdge) {
    const targetIndex = nodes.findIndex((item) => item.id === insertEdge.target)
    const nextNodes = [...nodes]
    nextNodes.splice(targetIndex < 0 ? nextNodes.length : targetIndex, 0, node)
    selected.value.nodes = nextNodes
    selected.value.edges = [
      ...(selected.value.edges || []).filter((edge) => edge !== insertEdge),
      {
        source: insertEdge.source,
        target: node.id,
        condition: insertEdge.condition,
        source_handle: insertEdge.source_handle
      },
      { source: node.id, target: insertEdge.target }
    ]
  } else {
    selected.value.nodes = [...nodes, node]
    const previous = nodes[nodes.length - 1]
    if (previous) selected.value.edges = [...(selected.value.edges || []), { source: previous.id, target: node.id }]
  }
  selectedNode.value = node
  rightRailMode.value = 'step'
}

function startActionDrag(event: DragEvent, actionId: string): void {
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/x-workflow-action', actionId)
  event.dataTransfer.setData('text/plain', actionId)
}

function defaultConfig(actionId: string): Record<string, unknown> {
  if (actionId === 'device.select') return { device_id: selectedDeviceId.value || '' }
  if (actionId === 'device.connect') return { device_id: selectedDeviceId.value || '', timeout_seconds: 0 }
  if (actionId === 'device.info') return { fields: ['name', 'software_version', 'status'] }
  if (actionId === 'device.command') return { execution_mode: 'device', command: '', timeout_seconds: 0, retry_attempts: 1, retry_backoff_seconds: 0, failure_strategy: 'stop' }
  if (actionId === 'script.run') return { language: 'python', script_id: '', script: '', input_json: '{}', cwd: '', env: {}, timeout_seconds: 0, max_output_chars: 1_048_576, retry_attempts: 1, retry_backoff_seconds: 0 }
  if (actionId === 'file.upload') return { source: '', destination: '', overwrite: true }
  if (actionId === 'file.download') return { source: '', destination: '' }
  if (actionId === 'utility.wait') return { seconds: 1 }
  if (actionId === 'terminal.wait') return { mode: 'contains', pattern: '', timeout_seconds: 0, case_sensitive: false, send_enter: true }
  if (actionId === 'utility.confirm') return { prompt: '请确认是否继续执行后续步骤。', approve_label: '确认继续', reject_label: '取消流程' }
  if (actionId === 'utility.condition') return { expression: '', rules: [{ field: 'software_version', operator: '小于', value: '' }], logical_operator: 'AND', true_label: '满足条件', false_label: '不满足条件' }
  if (actionId === 'result.save') return { key: '检查结果' }
  if (actionId === 'variable.set') return { name: '', value: '' }
  if (actionId === 'expression.evaluate') return { expression: '', values: {} }
  if (actionId === 'loop.for_each') return { items: [], action_id: 'result.save', action_inputs: {} }
  if (actionId === 'device.for_each') return { devices: [], action_id: 'device.command', action_inputs: {}, concurrency: 1, failure_strategy: 'continue' }
  if (actionId === 'loop.until') return { action_id: 'device.command', action_inputs: { command: 'display version' }, condition: "False", max_iterations: 10, interval_seconds: 2 }
  if (actionId === 'workflow.call') return { workflow_id: '', version: '', inputs: {} }
  return {}
}


function addEdge(sourceId: string, targetId: string, sourceHandle?: string | null): void {
  if (!selected.value || !sourceId || !targetId || sourceId === targetId) return
  const exists = (selected.value.edges || []).some((edge) => edge.source === sourceId && edge.target === targetId && (edge.source_handle || '') === (sourceHandle || ''))
  if (exists) return
  const source = (selected.value.nodes || []).find((node) => node.id === sourceId)
  const edge: WorkflowEdge = { source: sourceId, target: targetId, source_handle: sourceHandle || undefined }
  if (source?.action_id === 'utility.condition') {
    const requestedBranch = sourceHandle === 'true' || sourceHandle === 'false' ? sourceHandle : undefined
    const hasTrueBranch = (selected.value.edges || []).some((item) => item.source === sourceId && (item.condition === 'true' || item.source_handle === 'true'))
    edge.condition = requestedBranch || (hasTrueBranch ? 'false' : 'true')
    edge.source_handle = edge.condition
  }
  selected.value.edges = [...(selected.value.edges || []), edge]
}

function removeEdgeByTarget(targetId: string): void {
  if (!selected.value) return
  selected.value.edges = (selected.value.edges || []).filter((edge) => edge.target !== targetId)
}

function setNodePredecessor(event: Event | string): void {
  if (!selectedNode.value) return
  const target = String(typeof event === 'string' ? event : (event.target as HTMLSelectElement).value || '')
  removeEdgeByTarget(selectedNode.value.id)
  if (target) addEdge(target, selectedNode.value.id)
}

function setNodeSuccessor(event: Event | string): void {
  if (!selectedNode.value) return
  const target = String(typeof event === 'string' ? event : (event.target as HTMLSelectElement).value || '')
  removeEdgeByTarget(target)
  if (target) addEdge(selectedNode.value.id, target)
}

function setConditionTarget(branch: 'true' | 'false', event: Event): void {
  if (!selected.value || selectedNode.value?.action_id !== 'utility.condition') return
  const target = (event.target as HTMLSelectElement).value
  const source = selectedNode.value.id
  const remaining = (selected.value.edges || []).filter((edge) => !(edge.source === source && (edge.condition === branch || edge.source_handle === branch)))
  if (target) remaining.push({ source, target, condition: branch })
  selected.value.edges = remaining
}

function removeNode(): void {
  if (!selected.value || !selectedNode.value) return
  const id = selectedNode.value.id
  selected.value.nodes = (selected.value.nodes || []).filter((node) => node !== selectedNode.value)
  selected.value.edges = (selected.value.edges || []).filter((edge) => edge.source !== id && edge.target !== id)
  selectedNode.value = selected.value.nodes?.[0] || null
}

function copySelectedNode(): void {
  if (!selectedNode.value) return
  workflowClipboard = JSON.parse(JSON.stringify(selectedNode.value)) as NodeItem
}

function nextNodeId(actionId: string): string {
  const existingIds = new Set((selected.value?.nodes || []).map((node) => node.id))
  const base = `${actionId.split('.').pop()}_${Date.now().toString(36)}`
  let candidate = base
  let suffix = 2
  while (existingIds.has(candidate)) candidate = `${base}_${suffix++}`
  return candidate
}

function pasteNode(): void {
  if (!selected.value || !workflowClipboard) return
  const copied = JSON.parse(JSON.stringify(workflowClipboard)) as NodeItem
  const position = copied.position && Number.isFinite(copied.position.x) && Number.isFinite(copied.position.y)
    ? { x: copied.position.x + 40, y: copied.position.y + 40 }
    : undefined
  const node: NodeItem = {
    ...copied,
    id: nextNodeId(copied.action_id),
    config: { ...copied.config },
    input_mapping: copied.input_mapping ? { ...copied.input_mapping } : undefined,
    position
  }
  selected.value.nodes = [...(selected.value.nodes || []), node]
  selectedNode.value = node
}

function isEditableTarget(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null
  return Boolean(element && (
    element.tagName === 'INPUT' ||
    element.tagName === 'TEXTAREA' ||
    element.tagName === 'SELECT' ||
    element.isContentEditable
  ))
}

function handleWorkflowKeyDown(event: KeyboardEvent): void {
  if (isEditableTarget(event.target)) return
  const key = event.key.toLowerCase()
  const modifier = event.ctrlKey || event.metaKey
  if (modifier && key === 'c' && selectedNode.value) {
    event.preventDefault()
    copySelectedNode()
    return
  }
  if (modifier && key === 'v' && workflowClipboard) {
    event.preventDefault()
    pasteNode()
    return
  }
  if (!modifier && event.key === 'Delete' && selectedNode.value) {
    event.preventDefault()
    removeNode()
  }
}

function renameNode(event: Event): void {
  if (!selected.value || !selectedNode.value) return
  const nextId = String((event.target as HTMLInputElement).value || '').trim()
  const previousId = selectedNode.value.id
  if (!nextId || nextId === previousId || (selected.value.nodes || []).some((node) => node !== selectedNode.value && node.id === nextId)) return
  selectedNode.value.id = nextId
  selected.value.edges = (selected.value.edges || []).map((edge) => ({
    ...edge,
    source: edge.source === previousId ? nextId : edge.source,
    target: edge.target === previousId ? nextId : edge.target
  }))
}


// 撤销/重做功能
const workflowHistory = useUndoRedo({
  initialState: selected.value,
  maxHistory: 50
})

let isUndoRedoAction = false

watch(
  () => selected.value,
  (newWorkflow) => {
    if (isUndoRedoAction || !newWorkflow) return
    workflowHistory.commit(JSON.parse(JSON.stringify(newWorkflow)))
  },
  { deep: true }
)

function performUndo(): void {
  if (!workflowHistory.canUndo.value) return
  isUndoRedoAction = true
  workflowHistory.undo()
  selected.value = JSON.parse(JSON.stringify(workflowHistory.state.value))
  nextTick(() => { isUndoRedoAction = false })
}

function performRedo(): void {
  if (!workflowHistory.canRedo.value) return
  isUndoRedoAction = true
  workflowHistory.redo()
  selected.value = JSON.parse(JSON.stringify(workflowHistory.state.value))
  nextTick(() => { isUndoRedoAction = false })
}

// 自动布局功能
async function applyAutoLayout(): Promise<void> {
  if (!selected.value || !selected.value.nodes || selected.value.nodes.length === 0) return

  const { nodes: layoutedNodes } = await autoLayout(
    selected.value.nodes.map(n => ({ ...n, position: n.position || { x: 0, y: 0 } })),
    (selected.value.edges || []).map((e, idx) => ({ ...e, id: `${e.source}-${e.target}-${idx}` })),
    {
      direction: 'TB',
      spacing: 100,
      nodeWidth: 220,
      nodeHeight: 120
    }
  )

  // 更新节点位置，保留其他属性
  selected.value.nodes = selected.value.nodes.map((node, index) => ({
    ...node,
    position: layoutedNodes[index]?.position || node.position
  }))
}

// 节点位置更新
function handleNodePositionChange(nodeId: string, position: { x: number; y: number }): void {
  if (!selected.value || !selected.value.nodes) return

  const node = selected.value.nodes.find(n => n.id === nodeId)
  if (node) {
    node.position = position
  }
}


  let cleanupShortcuts: (() => void) | null = null
  onMounted(() => {
    cleanupShortcuts = useUndoRedoShortcuts(performUndo, performRedo)
    window.addEventListener('keydown', handleWorkflowKeyDown)
  })
  onUnmounted(() => {
    if (cleanupShortcuts) cleanupShortcuts()
    window.removeEventListener('keydown', handleWorkflowKeyDown)
  })

  return {
    workflowHistory, addNode, startActionDrag,
    nodePosition, findInsertEdge, defaultConfig, addEdge, removeEdgeByTarget,
    setNodePredecessor, setNodeSuccessor, setConditionTarget, removeNode,
    copySelectedNode, pasteNode, handleWorkflowKeyDown, renameNode,
    performUndo, performRedo, applyAutoLayout, handleNodePositionChange
  }
}
