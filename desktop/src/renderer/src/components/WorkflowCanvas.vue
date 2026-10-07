<script setup lang="ts">
import { computed, nextTick, onActivated, onMounted, onUnmounted, ref, watch } from 'vue'
import { VueFlow, useVueFlow } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Maximize2, ZoomIn, ZoomOut } from 'lucide-vue-next'
import WorkflowNode from './WorkflowNode.vue'
import WorkflowLoopBoundary from './WorkflowLoopBoundary.vue'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'

interface WorkflowNode {
  id: string
  action_id: string
  config: Record<string, unknown>
  position?: { x: number; y: number }
}

interface WorkflowEdge {
  source: string
  target: string
  condition?: string
  source_handle?: string
}

interface WorkflowItem {
  id: string
  name: string
  inputs?: unknown[]
  outputs?: unknown[]
  nodes?: WorkflowNode[]
  edges?: WorkflowEdge[]
  canvas_edges?: WorkflowEdge[] | null
}

interface ValidationIssue {
  code: string
  message: string
  node_id?: string
  severity?: string
}

const props = defineProps<{
  workflow: WorkflowItem | null
  issues?: ValidationIssue[]
  interactive?: boolean
}>()

const canvasRef = ref<HTMLElement | null>(null)
const dimensionsReady = ref(false)
let resizeObserver: ResizeObserver | null = null

const NODE_WIDTH = 232
const NODE_HEIGHT = 96
const NODE_GAP = 28
const LOOP_ACTION_IDS = new Set(['device.for_each', 'loop.for_each', 'loop.until'])
const LOOP_BODY_HANDLES = new Set(['body', 'loop-body', 'loop_body'])
const LOOP_EXIT_HANDLES = new Set(['exit', 'loop-exit', 'loop_exit'])
type CanvasPosition = { x: number; y: number }
const freeformPositionsByWorkflow = new Map<string, Map<string, CanvasPosition>>()
const freeformPositionsVersion = ref(0)

function validPosition(position: { x: number; y: number } | undefined, index: number): { x: number; y: number } {
  const x = Number(position?.x)
  const y = Number(position?.y)
  return {
    x: Number.isFinite(x) ? x : 80 + (index % 3) * 260,
    y: Number.isFinite(y) ? y : 70 + Math.floor(index / 3) * 160
  }
}

function overlaps(a: { x: number; y: number }, b: { x: number; y: number }): boolean {
  return a.x < b.x + NODE_WIDTH + NODE_GAP
    && a.x + NODE_WIDTH + NODE_GAP > b.x
    && a.y < b.y + NODE_HEIGHT + NODE_GAP
    && a.y + NODE_HEIGHT + NODE_GAP > b.y
}

function separatedPosition(position: { x: number; y: number }, occupied: Array<{ x: number; y: number }>): { x: number; y: number } {
  const candidate = { ...position }
  let attempts = 0
  while (occupied.some((item) => overlaps(candidate, item)) && attempts < 100) {
    const row = Math.floor(attempts / 4)
    const column = attempts % 4
    candidate.x = position.x + column * (NODE_WIDTH + NODE_GAP)
    candidate.y = position.y + (row + 1) * (NODE_HEIGHT + NODE_GAP)
    attempts += 1
  }
  return candidate
}

function edgeHandle(edge: WorkflowEdge): string {
  return String(edge.source_handle || '').trim().toLowerCase()
}

function loopBodyNodeIds(loop: WorkflowNode, workflowNodes: WorkflowNode[], workflowEdges: WorkflowEdge[]): string[] {
  if (!LOOP_ACTION_IDS.has(loop.action_id)) return []
  const settings = loop.config || {}
  const mode = String(settings.body_mode || '').trim().toLowerCase()
  const actionInputs = settings.action_inputs
  const hasActionInputs = Boolean(actionInputs && typeof actionInputs === 'object' && !Array.isArray(actionInputs) && Object.keys(actionInputs as Record<string, unknown>).length)
  if (mode === 'action' || (loop.action_id === 'device.for_each' && mode !== 'downstream' && mode !== 'bounded' && hasActionInputs)) return []

  const nodeIds = new Set(workflowNodes.map((node) => node.id))
  const outgoing = new Map<string, WorkflowEdge[]>()
  for (const edge of workflowEdges) {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) continue
    outgoing.set(edge.source, [...(outgoing.get(edge.source) || []), edge])
  }
  const fromLoop = outgoing.get(loop.id) || []
  const bodyEdges = fromLoop.filter((edge) => LOOP_BODY_HANDLES.has(edgeHandle(edge)))
  const exitEdges = fromLoop.filter((edge) => LOOP_EXIT_HANDLES.has(edgeHandle(edge)))
  const exitTargets = new Set(exitEdges.map((edge) => edge.target))
  const explicitStart = String(settings.body_start || settings.loop_start || '').trim()
  const explicitEnd = String(settings.body_end || settings.loop_end || settings.loop_body_end || '').trim()
  const inferredBody = bodyEdges.length
    ? bodyEdges
    : loop.action_id === 'device.for_each'
      ? fromLoop.filter((edge) => !LOOP_EXIT_HANDLES.has(edgeHandle(edge)))
      : []
  const first = explicitStart || (inferredBody.length === 1 ? inferredBody[0].target : '')
  if (!first || !nodeIds.has(first)) return []

  const body: string[] = []
  let current = first
  const visited = new Set<string>()
  while (nodeIds.has(current) && !visited.has(current)) {
    visited.add(current)
    body.push(current)
    if (explicitEnd && current === explicitEnd) break
    const next = outgoing.get(current) || []
    if (next.length !== 1) break
    if (exitTargets.has(next[0].target)) break
    current = next[0].target
  }
  if (explicitEnd && !body.includes(explicitEnd)) return []
  return body
}

interface LoopLayout {
  positions: Map<string, { x: number; y: number }>
  bodyIds: string[]
  displayBodyIds: string[]
  inline: boolean
  previewId?: string
  exitTarget?: string
}

function loopContinuationTarget(loop: WorkflowNode, workflowEdges: WorkflowEdge[], bodyIds: string[]): string | undefined {
  const outgoing = workflowEdges.filter((edge) => edge.source === loop.id)
  const explicitExit = outgoing.find((edge) => LOOP_EXIT_HANDLES.has(edgeHandle(edge)))
  if (explicitExit) return explicitExit.target
  if (bodyIds.length) return undefined
  // Historical inline loops stored their continuation as the only plain edge.
  // Keep that data readable as the container exit without changing the draft.
  const continuation = outgoing.filter((edge) => !LOOP_BODY_HANDLES.has(edgeHandle(edge)))
  return continuation.length === 1 ? continuation[0].target : undefined
}

function inlineLoopPreview(loop: WorkflowNode): { id: string; actionId: string; config: Record<string, unknown>; label: string; summary: string } {
  const config = loop.config || {}
  const actionId = String(config.action_id || '').trim()
  const actionInputs = config.action_inputs
  const previewConfig = actionInputs && typeof actionInputs === 'object' && !Array.isArray(actionInputs)
    ? { ...(actionInputs as Record<string, unknown>) }
    : {}
  return {
    id: `__loop_body__${loop.id}`,
    actionId: actionId || '__loop_preview__',
    config: previewConfig,
    label: actionId || '循环体动作未配置',
    summary: actionId ? '每次迭代执行一次' : '请配置循环体动作'
  }
}

function loopLayout(
  loop: WorkflowNode,
  workflowNodes: WorkflowNode[],
  workflowEdges: WorkflowEdge[],
  positions: Map<string, { x: number; y: number }>,
  applyStructuralLayout = true
): LoopLayout | null {
  const bodyIds = loopBodyNodeIds(loop, workflowNodes, workflowEdges)
  const inline = bodyIds.length === 0
  const preview = inline ? inlineLoopPreview(loop) : undefined
  const displayBodyIds = inline ? [preview!.id] : bodyIds
  const exitTarget = loopContinuationTarget(loop, workflowEdges, bodyIds)
  if (exitTarget && bodyIds.includes(exitTarget)) return null

  const loopPosition = positions.get(loop.id)
  if (!loopPosition) return null

  // Keep the loop's own anchor, then stack its body and continuation on one axis.
  // This gives the canvas a readable execution order without rewriting saved data.
  const nextPositions = new Map(positions)
  const bodyStartY = loopPosition.y + NODE_HEIGHT + 112
  const bodyGap = 44
  const bodyX = loopPosition.x
  if (applyStructuralLayout) {
    bodyIds.forEach((nodeId, index) => {
      nextPositions.set(nodeId, { x: bodyX, y: bodyStartY + index * (NODE_HEIGHT + bodyGap) })
    })
  }
  if (inline && preview) {
    nextPositions.set(preview.id, { x: bodyX, y: bodyStartY })
  }

  const lastBodyPosition = nextPositions.get(displayBodyIds[displayBodyIds.length - 1]) || { x: bodyX, y: bodyStartY }
  if (exitTarget && applyStructuralLayout) {
    const continuationY = lastBodyPosition.y + NODE_HEIGHT + 112
    if (positions.has(exitTarget)) nextPositions.set(exitTarget, { x: bodyX, y: continuationY })
  }

  return { positions: nextPositions, bodyIds, displayBodyIds, inline, previewId: preview?.id, exitTarget }
}

const emit = defineEmits<{
  nodeSelect: [nodeId: string]
  nodeAdd: [actionId: string, position: { x: number; y: number }]
  nodeDelete: [nodeId: string]
  connect: [connection: { source: string; target: string; sourceHandle?: string | null }]
  disconnect: [edge: { id: string; source: string; target: string }]
  edgeUpdate: [update: { id: string; source: string; target: string; nextSource: string; nextTarget: string }]
  nodePositionChange: [nodeId: string, position: { x: number; y: number }]
  nodePositionsChange: [positions: Array<{ nodeId: string; position: CanvasPosition }>]
}>()

// 转换节点数据
const nodes = computed(() => {
  if (!props.workflow?.nodes) return []

  // Once the user starts dragging, keep the rendered arrangement as the source of truth.
  // The structural loop layout is only an initial arrangement.
  freeformPositionsVersion.value
  const workflowId = props.workflow.id
  const freeformPositions = freeformPositionsByWorkflow.get(workflowId)
  const structuredLoopIds = new Set(props.workflow.nodes.filter((node) => LOOP_ACTION_IDS.has(node.action_id)).map((node) => node.id))
  const occupied: Array<CanvasPosition> = []
  const realNodes = props.workflow.nodes.map((node, index) => {
    const hasIssue = props.issues?.some(issue => issue.node_id === node.id)
    // Keep an explicitly saved position exactly where the user dropped it.
    // Only auto-separate nodes that have never been positioned.
    const freeformPosition = freeformPositions?.get(node.id)
    const sourcePosition = freeformPosition || node.position
    const hasPosition = Number.isFinite(Number(sourcePosition?.x)) && Number.isFinite(Number(sourcePosition?.y))
    const position = hasPosition
      ? validPosition(sourcePosition, index)
      : separatedPosition(validPosition(sourcePosition, index), occupied)
    occupied.push(position)

    return {
      id: node.id,
      type: 'custom',
      position,
      data: {
        label: node.id,
        action_id: node.action_id,
        config: node.config,
        loopStructured: structuredLoopIds.has(node.id),
        state: hasIssue ? 'attention' : 'ready'
      }
    }
  })

  let positions = new Map(realNodes.map((node) => [node.id, node.position]))
  const loopLayouts = new Map<string, LoopLayout>()
  for (const loop of props.workflow.nodes) {
    if (!LOOP_ACTION_IDS.has(loop.action_id)) continue
    const layout = loopLayout(loop, props.workflow.nodes, props.workflow.edges || [], positions, !freeformPositions)
    if (!layout) continue
    positions = layout.positions
    loopLayouts.set(loop.id, layout)
  }

  const positionedNodes = realNodes.map((node) => {
    const position = positions.get(node.id)
    return position ? { ...node, position } : node
  })
  const contractNodes = [
    {
      id: '__workflow_input__', actionId: '__workflow_input__', label: '流程输入',
      summary: props.workflow.inputs?.length
        ? (props.workflow.inputs as Array<{ name?: string }>).map((input) => input.name || '未命名').join(' · ')
        : '点击配置运行参数',
      contractKind: 'input',
      position: freeformPositions?.get('__workflow_input__') || { x: 80, y: -NODE_HEIGHT - 28 }
    },
    {
      id: '__workflow_result__', actionId: '__workflow_result__', label: '流程结果',
      summary: props.workflow.outputs?.length
        ? (props.workflow.outputs as Array<{ name?: string; presentation?: string }>).map((output) => `${output.name || '未命名'} · ${output.presentation || '自动'}`).join('，')
        : '点击定义最终输出',
      contractKind: 'result',
      position: freeformPositions?.get('__workflow_result__') || { x: 80, y: Math.max(70, ...positionedNodes.map((node) => node.position.y + NODE_HEIGHT + 40)) }
    }
  ].map((node) => ({
    id: node.id,
    type: 'custom',
    position: node.position,
    selectable: true,
    draggable: true,
    connectable: true,
    deletable: false,
    data: {
      label: node.label, action_id: node.actionId, config: {}, contractNode: true, contractKind: node.contractKind,
      virtualLabel: node.label, virtualSummary: node.summary, state: 'ready' as const
    }
  }))
  const inlineBodyNodes = props.workflow.nodes.flatMap((loop) => {
    const layout = loopLayouts.get(loop.id)
    if (!layout?.inline || !layout.previewId) return []
    const preview = inlineLoopPreview(loop)
    const position = positions.get(layout.previewId)
    if (!position) return []
    return [{
      id: layout.previewId,
      type: 'custom',
      position,
      selectable: false,
      draggable: false,
      connectable: false,
      zIndex: 1,
      data: {
        label: layout.previewId,
        action_id: preview.actionId,
        config: preview.config,
        virtual: true,
        virtualLabel: preview.label,
        virtualSummary: preview.summary,
        state: 'ready'
      }
    }]
  })
  const boundaries = props.workflow.nodes.flatMap((loop) => {
    if (!LOOP_ACTION_IDS.has(loop.action_id)) return []
    const bodyIds = loopLayouts.get(loop.id)?.displayBodyIds
      || loopBodyNodeIds(loop, props.workflow?.nodes || [], props.workflow?.edges || [])
    const bodyPositions = bodyIds.map((id) => positions.get(id)).filter((position): position is { x: number; y: number } => Boolean(position))
    if (!bodyPositions.length) return []
    const paddingX = 24
    // Reserve a real header rail inside the loop frame. The entry handle and
    // the first body target then have enough distance to read as two points.
    const paddingTop = 68
    const paddingBottom = 24
    const minX = Math.min(...bodyPositions.map((position) => position.x)) - paddingX
    const minY = Math.min(...bodyPositions.map((position) => position.y)) - paddingTop
    const maxX = Math.max(...bodyPositions.map((position) => position.x + NODE_WIDTH)) + paddingX
    const maxY = Math.max(...bodyPositions.map((position) => position.y + NODE_HEIGHT)) + paddingBottom
    const explicit = Boolean(loop.config.body_end || loop.config.loop_end || loop.config.body_start || loop.config.loop_start)
    return [{
      id: `__loop_boundary__${loop.id}`,
      type: 'loop-boundary',
      position: { x: minX, y: minY },
      selectable: false,
      draggable: false,
      connectable: true,
      zIndex: 0,
      style: { width: `${Math.max(260, maxX - minX)}px`, height: `${Math.max(150, maxY - minY)}px` },
      data: {
        label: '循环体',
        bodyCount: bodyIds.length,
        iterationLabel: loop.action_id === 'device.for_each' ? '每台设备' : loop.action_id === 'loop.for_each' ? '每个项目' : '每次迭代',
        explicit,
        entryHandleId: 'loop-boundary-entry',
        bodyHandleId: 'loop-boundary-body',
        exitHandleId: 'loop-boundary-exit'
      }
    }]
  })
  return [...contractNodes, ...boundaries, ...positionedNodes.map((node) => ({ ...node, zIndex: 1 })), ...inlineBodyNodes]
})

watch(
  () => props.workflow?.nodes?.map((node) => ({
    id: node.id,
    x: Number(node.position?.x),
    y: Number(node.position?.y)
  })),
  (nextPositions) => {
    const workflowId = props.workflow?.id
    const freeformPositions = workflowId ? freeformPositionsByWorkflow.get(workflowId) : undefined
    if (!workflowId || !freeformPositions || !nextPositions) return
    const externallyChanged = nextPositions.some((item) => {
      const position = freeformPositions.get(item.id)
      return position && (position.x !== item.x || position.y !== item.y)
    })
    if (externallyChanged) {
      freeformPositionsByWorkflow.delete(workflowId)
      freeformPositionsVersion.value += 1
    }
  },
  { deep: true }
)

// 转换边数据
const edges = computed(() => {
  if (!props.workflow) return []

  const workflowNodes = props.workflow.nodes || []
  const workflowEdges = props.workflow.edges || []
  const visualEdges = workflowEdges.map(edge => {
    const sourceNode = props.workflow?.nodes?.find((node) => node.id === edge.source)
    const sourceHandle = edge.source_handle || (sourceNode?.action_id === 'device.for_each' ? 'loop-body' : undefined)
    const isBodyEdge = LOOP_BODY_HANDLES.has(sourceHandle || '')
    const isExitEdge = LOOP_EXIT_HANDLES.has(sourceHandle || '')
    const bodyIds = sourceNode && LOOP_ACTION_IDS.has(sourceNode.action_id)
      ? loopBodyNodeIds(sourceNode, props.workflow?.nodes || [], props.workflow?.edges || [])
      : []
    const hasLoopBoundary = Boolean(sourceNode && LOOP_ACTION_IDS.has(sourceNode.action_id))
    const isInlineContinuation = hasLoopBoundary && bodyIds.length === 0 && edge.source === sourceNode?.id
    const renderAsBodyEdge = isBodyEdge && bodyIds.length > 0
    const renderAsExitEdge = isExitEdge || isInlineContinuation
    const visualSource = renderAsExitEdge && hasLoopBoundary
      ? `__loop_boundary__${edge.source}`
      : edge.source
    const visualSourceHandle = renderAsExitEdge && hasLoopBoundary ? 'loop-boundary-exit' : sourceHandle
    const visualTarget = renderAsBodyEdge && hasLoopBoundary ? `__loop_boundary__${edge.source}` : edge.target
    const visualTargetHandle = renderAsBodyEdge && hasLoopBoundary ? 'loop-boundary-entry' : undefined
    return {
      id: `${edge.source}-${sourceHandle || 'default'}-${edge.target}`,
      source: visualSource,
      target: visualTarget,
      sourceHandle: visualSourceHandle,
      targetHandle: visualTargetHandle,
      type: edge.condition || renderAsBodyEdge || renderAsExitEdge ? 'smoothstep' : 'default',
      label: edge.condition === 'true' ? '满足' : edge.condition === 'false' ? '不满足' : '',
      animated: false,
      style: {
        stroke: edge.condition ? '#fbbf24' : renderAsExitEdge ? '#a78bfa' : renderAsBodyEdge ? '#60a5fa' : '#64748b',
        strokeWidth: visualSourceHandle ? 2.2 : 2
      },
      labelStyle: {
        fill: edge.condition ? '#fcd34d' : '#cbd5e1',
        fontSize: '11px',
        fontWeight: 650
      },
      labelBgStyle: {
        fill: '#172033',
        fillOpacity: 1,
        stroke: '#334155',
        strokeWidth: 1
      },
      labelBgPadding: [5, 3] as [number, number],
      labelBgBorderRadius: 4
    }
  })

  const bodyEntryEdges = workflowNodes.flatMap((loop) => {
    if (!LOOP_ACTION_IDS.has(loop.action_id)) return []
    const bodyIds = loopBodyNodeIds(loop, props.workflow?.nodes || [], props.workflow?.edges || [])
    const bodyTarget = bodyIds[0] || `__loop_body__${loop.id}`
    const bodyEntry = {
      id: `__loop_boundary_body__${loop.id}`,
      source: `__loop_boundary__${loop.id}`,
      sourceHandle: 'loop-boundary-body',
      target: bodyTarget,
      type: 'smoothstep',
      animated: false,
      selectable: false,
      style: { stroke: '#60a5fa', strokeWidth: 2.2 }
    }
    const inlineEntry = !bodyIds.length ? {
      id: `__loop_boundary_entry__${loop.id}`,
      source: loop.id,
      sourceHandle: 'loop-body',
      target: `__loop_boundary__${loop.id}`,
      targetHandle: 'loop-boundary-entry',
      type: 'smoothstep',
      animated: false,
      selectable: false,
      style: { stroke: '#60a5fa', strokeWidth: 2.2 }
    } : null
    return inlineEntry ? [bodyEntry, inlineEntry] : [bodyEntry]
  })

  const incoming = new Set(workflowEdges.map((edge) => edge.target))
  const outgoing = new Set(workflowEdges.map((edge) => edge.source))
  const startNodes = workflowNodes.filter((node) => !incoming.has(node.id))
  const endNodes = workflowNodes.filter((node) => !outgoing.has(node.id))
  const inferredBoundaryEdges = workflowNodes.length
    ? [
        ...startNodes.map((node) => ({
          id: `__workflow_input_edge__${node.id}`,
          source: '__workflow_input__',
          sourceHandle: 'contract-output',
          target: node.id,
          type: 'smoothstep',
          selectable: true,
          updatable: true,
          style: { stroke: '#2dd4a3', strokeWidth: 2.2 }
        })),
        ...endNodes.map((node) => ({
          id: `__workflow_result_edge__${node.id}`,
          source: node.id,
          target: '__workflow_result__',
          targetHandle: 'contract-input',
          type: 'smoothstep',
          selectable: true,
          updatable: true,
          style: { stroke: '#2dd4a3', strokeWidth: 2.2 }
        }))
      ]
    : [{
        id: '__workflow_empty_boundary_edge__',
        source: '__workflow_input__',
        sourceHandle: 'contract-output',
        target: '__workflow_result__',
        targetHandle: 'contract-input',
        type: 'smoothstep',
        selectable: true,
        updatable: true,
        style: { stroke: '#2dd4a3', strokeWidth: 2.2 }
      }]
  const boundaryEdges = props.workflow.canvas_edges == null
    ? inferredBoundaryEdges
    : props.workflow.canvas_edges.map((edge) => ({
        id: `__workflow_canvas_edge__${encodeURIComponent(edge.source)}__${encodeURIComponent(edge.target)}`,
        source: edge.source_handle === 'loop-exit' ? `__loop_boundary__${edge.source}` : edge.source,
        target: edge.target,
        sourceHandle: edge.source === '__workflow_input__'
          ? 'contract-output'
          : edge.source_handle === 'loop-exit' ? 'loop-boundary-exit' : undefined,
        targetHandle: edge.target === '__workflow_result__' ? 'contract-input' : undefined,
        type: 'smoothstep',
        selectable: true,
        updatable: true,
        style: { stroke: '#2dd4a3', strokeWidth: 2.2 }
      }))

  return [...visualEdges, ...bodyEntryEdges, ...boundaryEdges]
})

// Vue Flow 事件处理
const {
  onConnect,
  onNodeDragStop,
  onNodeClick,
  onEdgeClick,
  onEdgeUpdate,
  onPaneClick,
  screenToFlowCoordinate,
  fitView,
  zoomIn,
  zoomOut,
  setInteractive
} = useVueFlow()

watch(
  () => props.interactive !== false,
  (enabled) => setInteractive(enabled),
  { immediate: true }
)

onConnect((params) => {
  let source = params.source as string
  const target = params.target as string
  const boundaryPrefix = '__loop_boundary__'
  if (target === '__workflow_result__' && source.startsWith(boundaryPrefix)) {
    emit('connect', { source: source.slice(boundaryPrefix.length), target, sourceHandle: 'loop-exit' })
    return
  }
  if (source === '__workflow_input__' || target === '__workflow_result__') {
    emit('connect', { source, target, sourceHandle: params.sourceHandle })
    return
  }
  const isBoundaryExit = source.startsWith(boundaryPrefix)
  const isBoundaryEntry = target.startsWith(boundaryPrefix) && params.targetHandle === 'loop-boundary-entry'
  const boundaryLoopId = isBoundaryEntry ? target.slice(boundaryPrefix.length) : ''
  const boundaryLoop = isBoundaryEntry
    ? props.workflow?.nodes?.find((node) => node.id === boundaryLoopId)
    : undefined
  const boundaryBodyStart = boundaryLoop
    ? loopBodyNodeIds(boundaryLoop, props.workflow?.nodes || [], props.workflow?.edges || [])[0]
    : undefined
  emit('connect', {
    source: isBoundaryExit ? source.slice(boundaryPrefix.length) : source,
    target: boundaryBodyStart || target,
    sourceHandle: isBoundaryExit ? 'loop-exit' : params.sourceHandle
  })
})

onNodeDragStop((event) => {
  const workflowId = props.workflow?.id
  if (workflowId) {
    let freeformPositions = freeformPositionsByWorkflow.get(workflowId)
    const isFirstDrag = !freeformPositions
    if (!freeformPositions) {
      freeformPositions = new Map(
        nodes.value
          .filter((node) => !node.id.startsWith('__loop_boundary__') && !node.id.startsWith('__loop_body__'))
          .map((node) => [node.id, { x: node.position.x, y: node.position.y }])
      )
      freeformPositionsByWorkflow.set(workflowId, freeformPositions)
    }
    freeformPositions.set(event.node.id, { x: event.node.position.x, y: event.node.position.y })
    freeformPositionsVersion.value += 1
    if (isFirstDrag) {
      emit('nodePositionsChange', [...freeformPositions.entries()].map(([nodeId, position]) => ({ nodeId, position })))
    }
  }
  emit('nodePositionChange', event.node.id, event.node.position)
})

onNodeClick((event) => {
  emit('nodeSelect', event.node.id)
})

onPaneClick(() => {
  emit('nodeSelect', '')
})

onEdgeClick((event) => {
  const source = event.edge.source.startsWith('__loop_boundary__')
    ? event.edge.source.slice('__loop_boundary__'.length)
    : event.edge.source
  emit('disconnect', { id: event.edge.id, source, target: event.edge.target })
})

onEdgeUpdate(({ edge, connection }) => {
  const normalizeSource = (source: string) => source.startsWith('__loop_boundary__')
    ? source.slice('__loop_boundary__'.length)
    : source
  emit('edgeUpdate', {
    id: edge.id,
    source: normalizeSource(edge.source),
    target: edge.target,
    nextSource: normalizeSource(connection.source),
    nextTarget: connection.target
  })
})

function onDragOver(event: DragEvent): void {
  event.preventDefault()
  if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
}

function onDrop(event: DragEvent): void {
  event.preventDefault()
  const actionId = event.dataTransfer?.getData('application/x-workflow-action') || event.dataTransfer?.getData('text/plain')
  if (!actionId) return
  const target = event.currentTarget as HTMLElement | null
  const bounds = target?.getBoundingClientRect()
  if (!bounds || bounds.width <= 0 || bounds.height <= 0) return
  const position = screenToFlowCoordinate({ x: event.clientX, y: event.clientY })
  if (!Number.isFinite(position.x) || !Number.isFinite(position.y)) return
  emit('nodeAdd', actionId, { x: Math.round(position.x - 110), y: Math.round(position.y - 55) })
}

function updateDimensions(): void {
  const element = canvasRef.value
  if (!element) return
  const bounds = element.getBoundingClientRect()
  dimensionsReady.value = Number.isFinite(bounds.width) && Number.isFinite(bounds.height) && bounds.width > 1 && bounds.height > 1
}

async function fitCanvas(): Promise<void> {
  if (!dimensionsReady.value) return
  await fitView({ padding: 0.2, duration: 220 })
}

function fitAfterRender(): void {
  void nextTick().then(() => {
    if (!dimensionsReady.value) return
    window.requestAnimationFrame(() => { void fitCanvas() })
  })
}

watch(
  () => props.workflow?.id,
  () => fitAfterRender(),
  { flush: 'post' }
)

watch(dimensionsReady, (ready) => {
  if (ready) fitAfterRender()
})

onActivated(() => {
  fitAfterRender()
})

onMounted(async () => {
  await nextTick()
  updateDimensions()
  if (canvasRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(updateDimensions)
    resizeObserver.observe(canvasRef.value)
  }
})

onUnmounted(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div ref="canvasRef" class="workflow-canvas" @dragenter.capture.prevent="onDragOver" @dragover.capture="onDragOver" @drop.capture="onDrop">
    <VueFlow
      v-if="dimensionsReady"
      :nodes="nodes"
      :edges="edges"
      :nodes-draggable="props.interactive !== false"
      :nodes-connectable="props.interactive !== false"
      :pan-on-drag="props.interactive !== false ? [1, 2] : false"
      :default-zoom="1"
      :min-zoom="0.2"
      :max-zoom="4"
      :default-viewport="{ x: 0, y: 0, zoom: 1 }"
      :fit-view-on-init="true"
      class="vue-flow-wrapper"
    >
      <!-- 自定义节点 -->
      <template #node-custom="customNodeProps">
        <WorkflowNode v-bind="customNodeProps" />
      </template>
      <template #node-loop-boundary="boundaryProps">
        <WorkflowLoopBoundary v-bind="boundaryProps" />
      </template>

      <div class="canvas-floating-toolbar" @pointerdown.stop @click.stop>
        <button type="button" class="canvas-fit-button" title="适配全部节点" aria-label="适配全部节点" @click.stop="fitCanvas">
          <Maximize2 :size="14" />
          <span>适配</span>
        </button>
        <button type="button" title="放大" aria-label="放大" @click.stop="zoomIn({ duration: 160 })">
          <ZoomIn :size="14" />
        </button>
        <button type="button" title="缩小" aria-label="缩小" @click.stop="zoomOut({ duration: 160 })">
          <ZoomOut :size="14" />
        </button>
      </div>

      <!-- 背景 -->
      <Background
        pattern-color="#334155"
        :gap="20"
        :size="1"
      />

      <div v-if="!nodes.length" class="workflow-canvas-empty">
        <div class="workflow-canvas-empty-icon">+</div>
        <strong>把节点拖到这里</strong>
        <span>点击左侧动作查看配置，拖入画布创建步骤</span>
      </div>
    </VueFlow>
    <div v-if="!dimensionsReady" class="workflow-canvas-loading">正在准备画布…</div>
  </div>
</template>


<style scoped>
.workflow-canvas { position: relative; width: 100%; height: 100%; min-width: 0; min-height: 0; background: var(--workflow-bg, #0b1220); }
.vue-flow-wrapper { width: 100%; height: 100%; min-height: 0; border: 0; }
.canvas-floating-toolbar { position: absolute; top: 12px; right: 12px; z-index: 5; display: inline-flex; align-items: center; gap: 2px; min-height: 32px; padding: 3px; border: 1px solid rgba(100,116,139,.42); border-radius: 7px; background: rgba(15,23,42,.88); box-shadow: 0 7px 18px rgba(2,6,23,.24); backdrop-filter: blur(8px); }
.canvas-floating-toolbar button { display: grid; width: 26px; height: 26px; padding: 0; place-items: center; border: 0; border-radius: 4px; color: rgba(226,232,240,.7); background: transparent; cursor: pointer; }
.canvas-floating-toolbar .canvas-fit-button { display: inline-flex; width: auto; gap: 4px; padding: 0 8px; font-size: 10px; }
.canvas-floating-toolbar button:hover { color: #bfdbfe; background: rgba(37,99,235,.24); }
.workflow-canvas-empty, .workflow-canvas-loading { position: absolute; inset: 0; display: grid; place-content: center; justify-items: center; gap: 8px; color: var(--workflow-muted, rgba(226,232,240,.66)); pointer-events: none; }
.workflow-canvas-empty { margin: 54px; border: 1px dashed rgba(96,165,250,.34); border-radius: 12px; }
.workflow-canvas-empty strong { color: var(--workflow-text, #dbeafe); font-size: 13px; }
.workflow-canvas-empty span { color: var(--workflow-subtle, rgba(226,232,240,.46)); font-size: 11px; }
.workflow-canvas-empty-icon { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid rgba(96,165,250,.6); border-radius: 8px; color: #93c5fd; font-size: 20px; font-weight: 300; }
.workflow-canvas-loading { font-size: 12px; }
:deep(.vue-flow__background pattern circle) { fill: rgba(100,116,139,.34); }
:deep(.vue-flow__edge-path) { stroke: #64748b; stroke-width: 1.6; }
:deep(.vue-flow__node-loop-boundary) { z-index: 0 !important; pointer-events: none; }
:deep(.vue-flow__node-custom) { z-index: 1; }
:deep(.vue-flow__edge.selected .vue-flow__edge-path) { stroke: #4f9cf9; stroke-width: 2; }
:deep(.vue-flow__edge-text) { fill: #fcd34d; font-size: 10px; }
:global(:root[data-theme="light"]) .workflow-canvas { background: #f8fafc; }
:global(:root[data-theme="light"]) .canvas-floating-toolbar { border-color: #cbd5e1; background: rgba(255,255,255,.94); box-shadow: 0 7px 18px rgba(15,23,42,.12); }
:global(:root[data-theme="light"]) .canvas-floating-toolbar button { color: #475569; }
:global(:root[data-theme="light"]) .canvas-floating-toolbar button:hover { color: #1d4ed8; background: #eaf2ff; }
:global(:root[data-theme="light"]) .workflow-canvas-empty, :global(:root[data-theme="light"]) .workflow-canvas-loading { color: #64748b; }
:global(:root[data-theme="light"]) .workflow-canvas-empty strong { color: #172033; }
:global(:root[data-theme="light"]) .workflow-canvas-empty span { color: #718096; }
:global(:root[data-theme="light"]) :deep(.vue-flow__edge-path) { stroke: #94a3b8; }
:global(:root[data-theme="light"]) :deep(.vue-flow__edge.selected .vue-flow__edge-path) { stroke: #2563eb; }
</style>
