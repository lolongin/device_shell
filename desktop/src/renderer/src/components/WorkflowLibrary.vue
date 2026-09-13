<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { CheckCircle2, GitBranch, Play, Plus, Save, Search, Trash2, Workflow, X, AlertTriangle, Copy } from 'lucide-vue-next'
import { desktopApi } from '../transport/api'
import { useWorkspaceStore } from '../stores/workspace'
import type { DeviceSummary } from '../types'

type NodeItem = { id: string; action_id: string; config: Record<string, unknown>; input_mapping?: Record<string, unknown> }
type WorkflowInput = { name: string; type?: string; required?: boolean; default?: unknown; description?: string }
type WorkflowEdge = { source: string; target: string; condition?: string; source_handle?: string }
type WorkflowItem = { id: string; name: string; description?: string; version?: string | number; inputs?: WorkflowInput[]; nodes?: NodeItem[]; edges?: Array<{ source: string; target: string; condition?: string; source_handle?: string }> }
type Issue = { code: string; message: string; node_id?: string | null }

const emit = defineEmits<{ close: [] }>()
const workspace = useWorkspaceStore()
const workflows = ref<WorkflowItem[]>([])
const selected = ref<WorkflowItem | null>(null)
const selectedNode = ref<NodeItem | null>(null)
const issues = ref<Issue[]>([])
const error = ref('')
const loading = ref(false)
const saving = ref(false)
const running = ref(false)
const runMessage = ref('')
const searchQuery = ref('')
const selectedDeviceId = ref('')
const selectedDeviceIds = ref<string[]>([])
const showCreateMenu = ref(false)
const showRunPreview = ref(false)
const dryRunning = ref(false)
const taskGoal = ref('检查设备状态')
const conditionRules = ref([{ field: 'software_version', operator: '小于', value: '8.200' }])
const conditionLogicalOperator = ref<'AND' | 'OR'>('AND')
const workflowInputs = ref<Record<string, unknown>>({})
const confirmedRisks = ref(false)
const loopItemsMode = computed<'manual' | 'reference'>({
  get: () => selectedNode.value?.action_id === 'loop.for_each' && typeof selectedNode.value.config.items === 'string' ? 'reference' : 'manual',
  set: (mode) => {
    if (selectedNode.value?.action_id !== 'loop.for_each') return
    if (mode === 'reference') {
      const current = selectedNode.value.config.items
      selectedNode.value.config.items = typeof current === 'string' && current ? current : ''
    }
    else if (!Array.isArray(selectedNode.value.config.items)) {
      selectedNode.value.config.items = []
    }
  }
})
const loopItemsReference = computed<string>({
  get: () => selectedNode.value?.action_id === 'loop.for_each' && typeof selectedNode.value.config.items === 'string' ? selectedNode.value.config.items : '',
  set: (reference) => {
    if (selectedNode.value?.action_id === 'loop.for_each') selectedNode.value.config.items = reference
  }
})
const loopItemsSourceId = computed(() => {
  const reference = loopItemsReference.value
  return resultSources.value.find((source) => reference === source.id || reference.startsWith(`${source.id}.`))?.id || ''
})
const loopItemsField = computed(() => {
  const source = loopItemsSourceId.value
  return source && loopItemsReference.value.startsWith(`${source}.`) ? loopItemsReference.value.slice(source.length + 1) : ''
})
function setLoopItemsSource(sourceId: string): void {
  loopItemsReference.value = sourceId ? `${sourceId}${loopItemsField.value ? `.${loopItemsField.value}` : ''}` : ''
}
function setLoopItemsField(field: string): void {
  loopItemsReference.value = loopItemsSourceId.value ? `${loopItemsSourceId.value}${field ? `.${field}` : ''}` : ''
}

const actions = [
  { id: 'device.select', label: '选择设备', hint: '指定后续步骤的目标设备', tone: 'blue' },
  { id: 'device.connect', label: '连接设备', hint: '自动选择可用连接方式', tone: 'blue' },
  { id: 'device.ssh', label: 'SSH 连接', hint: '使用 SSH 恢复连接', tone: 'blue' },
  { id: 'device.telnet', label: 'Telnet 连接', hint: '使用 Telnet 恢复连接', tone: 'blue' },
  { id: 'device.info', label: '获取设备信息', hint: '读取型号、版本和状态', tone: 'blue' },
  { id: 'device.command', label: '执行操作', hint: '选择一个操作模板并执行', tone: 'blue' },
  { id: 'file.upload', label: '上传文件', hint: '将本地文件上传到设备', tone: 'amber' },
  { id: 'file.download', label: '下载文件', hint: '从设备下载文件到本地', tone: 'amber' },
  { id: 'device.reboot', label: '重启设备', hint: '重新启动目标设备', tone: 'red' },
  { id: 'utility.wait', label: '等待', hint: '等待设备或流程继续', tone: 'amber' },
  { id: 'utility.confirm', label: '人工确认', hint: '暂停流程并等待人员决定', tone: 'amber' },
  { id: 'utility.condition', label: '如果 / 否则', hint: '根据数据选择真分支或假分支', tone: 'purple' },
  { id: 'result.save', label: '保存结果', hint: '保存本步骤输出供后续使用', tone: 'green' },
  { id: 'variable.set', label: '设置变量', hint: '保存一个可复用的流程变量', tone: 'green' },
  { id: 'expression.evaluate', label: '计算表达式', hint: '计算受限表达式并输出结果', tone: 'purple' },
  { id: 'loop.for_each', label: '循环 FOR', hint: '遍历列表执行一个动作', tone: 'purple' }
]
const filteredActions = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return actions
  return actions.filter((item) => `${item.id} ${item.label} ${item.hint}`.toLowerCase().includes(query))
})
const availableDevices = computed<DeviceSummary[]>(() => workspace.devices || [])
const selectedAction = computed(() => actions.find((item) => item.id === selectedNode.value?.action_id))
const resultSources = computed(() => {
  if (!selected.value || !selectedNode.value) return []
  const nodes = selected.value.nodes || []
  const index = nodes.findIndex((item) => item.id === selectedNode.value?.id)
  return nodes.slice(0, index).filter((item) => item.action_id !== 'utility.condition').map((item) => ({ id: item.id, label: actions.find((action) => action.id === item.action_id)?.label || item.id }))
})
function setResultField(source: string, field: string): void {
  if (!selectedNode.value) return
  selectedNode.value.config.value = source && field ? `\${${source}.${field}}` : ''
}
function onResultFieldChange(event: Event): void {
  const value = String((event.target as HTMLSelectElement).value || '')
  const parts = value.split('.')
  setResultField(parts.shift() || '', parts.join('.'))
}
const canPublish = computed(() => Boolean(selected.value && !issues.value.length && (selected.value.nodes?.length || 0) > 0))
const canRun = computed(() => Boolean(selected.value && (selectedDeviceIds.value.length || selectedDeviceId.value) && !running.value && !issues.value.length && (selected.value.nodes?.length || 0) > 0))
const canStartRun = computed(() => Boolean(selected.value && (selectedDeviceIds.value.length || selectedDeviceId.value) && !running.value && (selected.value.nodes?.length || 0) > 0))
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
const highRiskActions = new Set(['device.reboot', 'file.upload', 'file.download'])
const previewHasRisk = computed(() => {
  const nodes = selected.value?.nodes || []
  return nodes.some((node) => highRiskActions.has(node.action_id) || (node.action_id === 'loop.for_each' && highRiskActions.has(String(node.config.action_id || ''))))
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
  const nodes = selected.value?.nodes || []
  if (nodes.length < 2) return nodes
  const ids = new Set(nodes.map((node) => node.id))
  const incoming = new Map(nodes.map((node) => [node.id, 0]))
  const outgoing = new Map(nodes.map((node) => [node.id, [] as string[]]))
  for (const edge of selected.value?.edges || []) {
    if (!ids.has(edge.source) || !ids.has(edge.target) || edge.source === edge.target) continue
    incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1)
    outgoing.get(edge.source)?.push(edge.target)
  }
  const pending = nodes.filter((node) => !incoming.get(node.id))
  const ordered: NodeItem[] = []
  const emitted = new Set<string>()
  while (pending.length) {
    const node = pending.shift()
    if (!node || emitted.has(node.id)) continue
    emitted.add(node.id)
    ordered.push(node)
    for (const target of outgoing.get(node.id) || []) {
      const count = (incoming.get(target) || 0) - 1
      incoming.set(target, count)
      if (!count) {
        const targetNode = nodes.find((item) => item.id === target)
        if (targetNode) pending.push(targetNode)
      }
    }
  }
  return ordered.length === nodes.length ? ordered : nodes
})
const incomingEdgeByTarget = computed(() => {
  const map = new Map<string, WorkflowEdge>()
  for (const edge of selected.value?.edges || []) {
    if (!map.has(edge.target)) map.set(edge.target, edge)
  }
  return map
})
const reachableNodeIds = computed(() => {
  const nodes = canvasNodes.value
  if (nodes.length < 2) return new Set(nodes.map((node) => node.id))
  const adjacency = new Map<string, string[]>()
  for (const edge of selected.value?.edges || []) adjacency.set(edge.source, [...(adjacency.get(edge.source) || []), edge.target])
  const reachable = new Set<string>()
  const pending = [nodes[0].id]
  while (pending.length) {
    const id = pending.pop()
    if (!id || reachable.has(id)) continue
    reachable.add(id)
    for (const target of adjacency.get(id) || []) if (!reachable.has(target)) pending.push(target)
  }
  return reachable
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
  return actions.find((action) => action.id === node.action_id)?.label || node.action_id
}

function connectorLabel(node: NodeItem, index: number): string {
  if (!index) return '开始'
  const edge = incomingEdgeByTarget.value.get(node.id)
  if (!edge) return '未连接'
  const source = canvasNodes.value.find((item) => item.id === edge.source)
  if (edge.condition === 'true' || edge.source_handle === 'true') return `满足条件 → ${nodeLabel(source || node)}`
  if (edge.condition === 'false' || edge.source_handle === 'false') return `不满足条件 → ${nodeLabel(source || node)}`
  return source ? `来自 ${nodeLabel(source)}` : '未连接'
}

function nodeOptions(excludeId: string): NodeItem[] {
  return canvasNodes.value.filter((node) => node.id !== excludeId)
}

async function refresh(): Promise<void> {
  loading.value = true
  error.value = ''
  try { workflows.value = (await desktopApi.workflowDefinitions()).workflows as WorkflowItem[] } catch (cause) { error.value = String(cause) } finally { loading.value = false }
}

function selectWorkflow(item: WorkflowItem): void {
  selected.value = item
  selectedNode.value = item.nodes?.[0] || null
  issues.value = []
  runMessage.value = ''
  workflowInputs.value = Object.fromEntries((item.inputs || []).map((input) => [input.name, input.default ?? '']))
  confirmedRisks.value = false
  const condition = item.nodes?.find((node) => node.action_id === 'utility.condition')
  if (condition && Array.isArray(condition.config.rules)) conditionRules.value = condition.config.rules as typeof conditionRules.value
  conditionLogicalOperator.value = condition?.config.logical_operator === 'OR' ? 'OR' : 'AND'
}

function addWorkflowInput(): void {
  if (!selected.value) return
  selected.value.inputs = [...(selected.value.inputs || []), { name: '', type: 'string', required: false, default: '' }]
}

function removeWorkflowInput(index: number): void {
  if (!selected.value?.inputs) return
  const removed = selected.value.inputs[index]
  selected.value.inputs = selected.value.inputs.filter((item) => item !== removed)
  if (removed?.name) {
    const nextInputs = { ...workflowInputs.value }
    delete nextInputs[removed.name]
    workflowInputs.value = nextInputs
  }
}

async function create(blank = false): Promise<void> {
  const result = await desktopApi.createWorkflowDefinition({
    name: '设备检查流程',
    description: '检查设备版本并输出结果',
    inputs: [],
    nodes: blank ? [] : [{ id: 'command_1', action_id: 'device.command', config: { command: 'display version' } }],
    edges: []
  })
  await refresh()
  selectWorkflow(result.workflow as WorkflowItem)
}

function addNode(actionId: string): void {
  if (!selected.value) return
  const nodes = selected.value.nodes || []
  const node: NodeItem = {
    id: `${actionId.split('.').pop()}_${Date.now().toString(36)}`,
    action_id: actionId,
    config: defaultConfig(actionId)
  }
  selected.value.nodes = [...nodes, node]
  const previous = nodes[nodes.length - 1]
  if (previous) selected.value.edges = [...(selected.value.edges || []), { source: previous.id, target: node.id }]
  selectedNode.value = node
}

function defaultConfig(actionId: string): Record<string, unknown> {
  if (actionId === 'device.select') return { device_id: selectedDeviceId.value || '' }
  if (actionId === 'device.connect') return { device_id: selectedDeviceId.value || '', timeout: 30 }
  if (actionId === 'device.info') return { fields: ['name', 'software_version', 'status'] }
  if (actionId === 'device.command') return { command: '' }
  if (actionId === 'file.upload' || actionId === 'file.download') return { source: '', destination: '' }
  if (actionId === 'utility.wait') return { seconds: 1 }
  if (actionId === 'utility.confirm') return { prompt: '请确认是否继续执行后续步骤。', approve_label: '确认继续', reject_label: '取消流程' }
  if (actionId === 'utility.condition') return { expression: '', rules: [{ field: 'software_version', operator: '小于', value: '' }], logical_operator: 'AND', true_label: '满足条件', false_label: '不满足条件' }
  if (actionId === 'result.save') return { key: '检查结果' }
  if (actionId === 'variable.set') return { name: '', value: '' }
  if (actionId === 'expression.evaluate') return { expression: '', values: {} }
  if (actionId === 'loop.for_each') return { items: [], action_id: 'result.save', action_inputs: {} }
  return {}
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
  if (issue.code === 'unknown_action') return `${label || '步骤'}：当前动作暂不支持执行`
  if (issue.code === 'invalid_condition') return `${label || '条件判断'}：请配置至少一条完整规则`
  if (issue.code === 'invalid_condition_operator') return `${label || '条件判断'}：请选择 AND 或 OR`
  if (issue.code === 'invalid_number') return `${label || '步骤'}：请输入有效数字`
  if (issue.code === 'number_out_of_range') return `${label || '步骤'}：数值超出允许范围`
  if (issue.code === 'invalid_variable_ref') return `${label || '步骤'}：引用了尚未产生的数据`
  if (issue.code === 'invalid_edge') return '流程连接引用了不存在的步骤'
  if (issue.code === 'disconnected_node') return `${label || '流程'}：步骤没有连接到主流程`
  if (issue.code === 'cycle') return `${label || '流程'}：连接形成了循环`
  if (issue.code === 'missing_confirmation_prompt') return `${label || '人工确认'}：请填写确认提示`
  return issue.message || '流程存在未解决的问题'
}

function focusIssue(issue: Issue): void {
  const node = selected.value?.nodes?.find((item) => item.id === issue.node_id)
  if (!node) return
  selectedNode.value = node
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
  if (!selected.value || (!selectedDeviceIds.value.length && !selectedDeviceId.value)) return
  runMessage.value = ''
  await validate()
  if (!canRun.value) {
    if (issues.value.length) showValidationProblem()
    else runMessage.value = '请选择目标设备。'
    return
  }
  running.value = true
  try {
    const targets = selectedDeviceIds.value.length ? selectedDeviceIds.value : [selectedDeviceId.value]
    const targetSessionIds = selectedDeviceIds.value
      .map((deviceId) => [deviceId, workspace.sessions.find((session) => session.device_id === deviceId && session.status === 'connected')?.id || ''] as const)
      .filter(([, sessionId]) => sessionId)
    const sessionIdsByDevice = Object.fromEntries(targetSessionIds)
    const result = await desktopApi.runWorkflowDefinition(selected.value.id, {
      device_id: targets[0],
      device_ids: targets,
      session_ids: sessionIdsByDevice,
      protocol: 'auto',
      inputs: workflowInputs.value,
      ...(selected.value.version && selected.value.version !== 'draft' ? { version: selected.value.version } : {}),
      ...(previewHasRisk.value && confirmedRisks.value ? { confirmed_risks: true } : {})
    })
    if (!result.task) { runMessage.value = '模拟运行完成：流程结构和参数均可执行。'; return }
    const tasks = result.tasks?.length ? result.tasks : result.task ? [result.task] : []
    if (!tasks.length) { runMessage.value = '任务已提交，但暂未返回任务记录。'; return }
    const createdIds = new Set(tasks.map((item) => item.id))
    workspace.tasks = [...tasks, ...workspace.tasks.filter((item) => !createdIds.has(item.id))]
    workspace.activeTaskId = tasks[0].id
    runMessage.value = tasks.length > 1
      ? `已为 ${tasks.length} 台设备创建任务，正在打开任务监控。`
      : `任务 ${tasks[0].id.slice(0, 8)} 已创建，正在打开任务监控。`
    emit('close')
    workspace.upgradePanelOpen = true
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause)
    runMessage.value = message
  } finally { running.value = false }
}

async function runDraft(): Promise<void> {
  if (!selected.value || (!selectedDeviceIds.value.length && !selectedDeviceId.value)) return
  runMessage.value = ''
  await validate()
  if (issues.value.length) { showValidationProblem(); return }
  running.value = true
  try {
    const targets = selectedDeviceIds.value.length ? selectedDeviceIds.value : [selectedDeviceId.value]
    const targetSessionIds = selectedDeviceIds.value
      .map((deviceId) => [deviceId, workspace.sessions.find((session) => session.device_id === deviceId && session.status === 'connected')?.id || ''] as const)
      .filter(([, sessionId]) => sessionId)
    const sessionIdsByDevice = Object.fromEntries(targetSessionIds)
    const result = await desktopApi.runWorkflowDefinition(selected.value.id, {
      device_id: targets[0],
      device_ids: targets,
      session_ids: sessionIdsByDevice,
      protocol: 'auto',
      inputs: workflowInputs.value,
      draft: true,
      ...(previewHasRisk.value && confirmedRisks.value ? { confirmed_risks: true } : {})
    })
    const task = result.task
    if (!task) { runMessage.value = '草稿测试运行未返回任务记录。'; return }
    workspace.tasks = [task, ...workspace.tasks.filter((item) => item.id !== task.id)]
    workspace.activeTaskId = task.id
    runMessage.value = `草稿任务 ${task.id.slice(0, 8)} 已创建，正在打开任务监控。`
    emit('close')
    workspace.upgradePanelOpen = true
  } catch (cause) {
    runMessage.value = cause instanceof Error ? cause.message : String(cause)
  } finally { running.value = false }
}

async function dryRunWorkflow(): Promise<void> {
  if (!selected.value || (!selectedDeviceIds.value.length && !selectedDeviceId.value)) return
  dryRunning.value = true
  try {
    const targets = selectedDeviceIds.value.length ? selectedDeviceIds.value : [selectedDeviceId.value]
    const result = await desktopApi.runWorkflowDefinition(selected.value.id, { device_id: targets[0], device_ids: targets, protocol: 'simulated', inputs: workflowInputs.value, dry_run: true })
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

function addEdge(sourceId: string, targetId: string): void {
  if (!selected.value || !sourceId || !targetId || sourceId === targetId) return
  const exists = (selected.value.edges || []).some((edge) => edge.source === sourceId && edge.target === targetId)
  if (exists) return
  const source = (selected.value.nodes || []).find((node) => node.id === sourceId)
  const edge: WorkflowEdge = { source: sourceId, target: targetId }
  if (source?.action_id === 'utility.condition') {
    const hasTrueBranch = (selected.value.edges || []).some((item) => item.source === sourceId && (item.condition === 'true' || item.source_handle === 'true'))
    edge.condition = hasTrueBranch ? 'false' : 'true'
    edge.source_handle = edge.condition
  }
  selected.value.edges = [...(selected.value.edges || []), edge]
}

function removeEdgeByTarget(targetId: string): void {
  if (!selected.value) return
  selected.value.edges = (selected.value.edges || []).filter((edge) => edge.target !== targetId)
}

function setNodePredecessor(event: Event): void {
  if (!selectedNode.value) return
  const target = String((event.target as HTMLSelectElement).value || '')
  removeEdgeByTarget(selectedNode.value.id)
  if (target) addEdge(target, selectedNode.value.id)
}

function setNodeSuccessor(event: Event): void {
  if (!selectedNode.value) return
  const target = String((event.target as HTMLSelectElement).value || '')
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

async function validate(): Promise<void> {
  if (!selected.value) return
  const result = await desktopApi.validateWorkflowDefinition(selected.value.id, selected.value)
  issues.value = result.errors || []
}

async function save(): Promise<void> {
  if (!selected.value) return
  if (selectedNode.value?.action_id === 'utility.condition') {
    selectedNode.value.config.rules = conditionRules.value
    selectedNode.value.config.logical_operator = conditionLogicalOperator.value
  }
  saving.value = true
  try { const result = await desktopApi.saveWorkflowDefinition(selected.value.id, selected.value as unknown as Record<string, unknown>); selectWorkflow(result.workflow as WorkflowItem); await validate() } catch (cause) { error.value = String(cause) } finally { saving.value = false }
}

async function publish(): Promise<void> {
  if (!selected.value) return
  await validate()
  if (!canPublish.value) return
  const result = await desktopApi.publishWorkflowDefinition(selected.value.id)
  if (!result.published) issues.value = (result.errors || []).map((item) => ({ code: item.code || 'publish_error', message: item.message, node_id: item.node_id }))
  await refresh()
}

async function remove(): Promise<void> {
  if (!selected.value) return
  await desktopApi.deleteWorkflowDefinition(selected.value.id)
  selected.value = null
  selectedNode.value = null
  await refresh()
}

function nodeState(node: NodeItem): 'ready' | 'attention' {
  const required = node.action_id === 'device.command'
    ? ['command']
    : node.action_id === 'variable.set'
      ? ['name']
      : node.action_id === 'expression.evaluate'
        ? ['expression']
        : node.action_id === 'loop.for_each'
          ? ['action_id']
    : node.action_id === 'utility.condition'
      ? []
      : node.action_id === 'device.select'
        ? ['device_id']
        : node.action_id === 'device.connect'
          ? ['device_id']
          : node.action_id === 'device.ssh' || node.action_id === 'device.telnet'
            ? ['host']
          : node.action_id === 'file.upload' || node.action_id === 'file.download'
            ? ['source', 'destination']
            : []
  if (required.some((key) => !String(node.config[key] ?? '').trim())) return 'attention'
  if (node.action_id === 'utility.condition') {
    const rules = node.config.rules
    if (!Array.isArray(rules) || !rules.some((rule) => rule && String(rule.field || '').trim() && String(rule.operator || '').trim() && String(rule.value || '').trim())) return 'attention'
  }
  return 'ready'
}
function configString(key: string): string { return String(selectedNode.value?.config?.[key] ?? '') }
function updateConfigString(key: string, event: Event): void { if (selectedNode.value) selectedNode.value.config[key] = (event.target as HTMLInputElement | HTMLTextAreaElement).value }
function updateConfigJson(key: string, event: Event): void {
  if (!selectedNode.value) return
  try { selectedNode.value.config[key] = JSON.parse((event.target as HTMLTextAreaElement).value || (key === 'items' ? '[]' : '{}')) } catch { runMessage.value = `${key} 必须是有效 JSON` }
}

async function testSelectedStep(): Promise<void> {
  if (!selected.value || !selectedNode.value || (!selectedDeviceIds.value.length && !selectedDeviceId.value)) return
  await validate()
  if (issues.value.length) { showValidationProblem(); return }
  try {
    const targets = selectedDeviceIds.value.length ? selectedDeviceIds.value : [selectedDeviceId.value]
    const result = await desktopApi.runWorkflowDefinition(selected.value.id, { device_id: targets[0], device_ids: targets, step_id: selectedNode.value.id, protocol: 'simulated', inputs: workflowInputs.value, dry_run: true })
    runMessage.value = `单步模拟完成：将执行 ${Number(result.preview?.step_count || 0)} 个前置及当前步骤。`
  } catch (cause) { runMessage.value = cause instanceof Error ? cause.message : String(cause) }
}

onMounted(async () => {
  selectedDeviceId.value = workspace.selectedDeviceId || workspace.devices[0]?.id || ''
  selectedDeviceIds.value = selectedDeviceId.value ? [selectedDeviceId.value] : []
  try {
    const catalog = await desktopApi.workflowActions()
    for (const raw of catalog.actions) {
      const item = raw as { id?: string; name?: string; category?: string }
      if (item.id && !actions.some((action) => action.id === item.id)) actions.push({ id: item.id, label: item.name || item.id, hint: item.category || '工作流动作', tone: 'blue' })
    }
  } catch (cause) { error.value = String(cause) }
  await refresh()
  if (workflows.value[0]) selectWorkflow(workflows.value[0])
})

watch(
  () => selected.value?.inputs,
  (inputs) => {
    if (!inputs) return
    workflowInputs.value = Object.fromEntries(inputs.map((input) => [input.name, workflowInputs.value[input.name] ?? input.default ?? '']))
  },
  { deep: true }
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
      <div><Workflow :size="18" /><div><strong>Workflow Studio</strong><small>把重复操作变成可复用流程</small></div></div>
      <button type="button" title="关闭" @click="emit('close')"><X :size="16" /></button>
    </header>
    <div class="workflow-library-toolbar">
      <button type="button" @click="showCreateMenu = !showCreateMenu"><Plus :size="14" />新建流程</button>
      <select v-model="taskGoal" class="task-goal" aria-label="任务目标"><option>检查设备状态</option><option>批量执行操作</option><option>采集设备信息</option><option>上传文件</option><option>验证配置</option><option>执行实验流程</option><option>自定义流程</option></select>
      <button type="button" :disabled="!selected" @click="duplicateWorkflow"><Copy :size="14" />复制</button>
      <button type="button" :disabled="!selected || saving" @click="save"><Save :size="14" />{{ saving ? '保存中…' : '保存草稿' }}</button>
      <button type="button" :disabled="!selected" @click="validate"><CheckCircle2 :size="14" />检查流程</button>
      <label class="workflow-run-target">目标设备<select v-model="selectedDeviceIds" multiple aria-label="测试运行目标设备"><option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">{{ deviceLabel(device) }}</option></select></label>
      <button class="run-action" type="button" :disabled="!canStartRun" @click="requestRunPreview"><Play :size="14" />{{ running ? '启动中…' : '执行预览' }}</button>
      <button type="button" :disabled="!canRun" @click="runDraft">测试草稿</button>
      <button class="primary-action" type="button" :disabled="!canPublish" @click="publish"><Play :size="14" />发布</button>
      <button class="danger-action" type="button" :disabled="!selected" @click="remove"><Trash2 :size="14" />删除</button>
    </div>
    <div v-if="showCreateMenu" class="workflow-create-menu"><strong>开始方式</strong><button type="button" @click="showCreateMenu = false; create()">使用模板：设备检查</button><button type="button" :disabled="!selected" @click="showCreateMenu = false; duplicateWorkflow()">从已有流程复制</button><button type="button" @click="showCreateMenu = false; create(true)">创建空白流程</button></div>
    <p v-if="error" class="workflow-error">{{ error }}</p>
    <p v-if="runMessage" class="workflow-run-message">{{ runMessage }}</p><p v-if="hasBranching" class="workflow-branch-notice"><GitBranch :size="14" />包含条件分支：运行时只执行匹配条件的一侧。</p>
    <div class="workflow-library-body">
      <aside class="workflow-list-pane">
        <div class="workflow-list-title"><span>我的流程</span><small>{{ workflows.length }} 个</small></div>
        <button v-for="item in workflows" :key="item.id" type="button" :class="{ active: selected?.id === item.id }" @click="selectWorkflow(item)">
          <strong>{{ item.name }}</strong><small>{{ item.description || '暂无描述' }}</small><em>v{{ item.version || '草稿' }}</em>
        </button>
        <p v-if="!loading && !workflows.length" class="workflow-empty-list">还没有流程<br /><span>点击“新建流程”开始</span></p>
      </aside>
      <main v-if="selected" class="workflow-studio-grid">
        <section class="workflow-action-catalog">
          <div class="panel-heading"><strong>节点库</strong><small>添加并接入流程末尾</small></div>
          <label class="workflow-search"><Search :size="13" /><input v-model="searchQuery" placeholder="搜索动作" aria-label="搜索动作" /></label>
          <button v-for="action in filteredActions" :key="action.id" type="button" :class="`action-tile tone-${action.tone}`" @click="addNode(action.id)"><span class="action-icon"><Plus :size="12" /></span><span><b>{{ action.label }}</b><small>{{ action.hint }}</small></span></button>
          <p v-if="!filteredActions.length" class="catalog-empty">没有匹配的动作</p>
          <p class="node-library-hint">新步骤会自动连接到当前主链末尾；需要调整时在步骤卡片中修改上下游。</p>
        </section>
        <section class="workflow-canvas">
          <div class="workflow-meta-fields"><label>流程名称<input v-model="selected.name" placeholder="例如：设备版本巡检" /></label><label>说明<input v-model="selected.description" placeholder="让团队知道这个流程做什么" /></label></div>
          <div class="workflow-inputs">
            <strong>流程输入</strong>
            <div v-for="(input, index) in selected.inputs || []" :key="index" class="workflow-input-declaration">
              <label>名称<input v-model="input.name" placeholder="例如：attempts" /></label>
              <label>类型<select v-model="input.type"><option value="string">文本</option><option value="number">数字</option><option value="integer">整数</option><option value="boolean">布尔</option><option value="object">对象</option><option value="array">数组</option></select></label>
              <label>默认值<input v-model="input.default" placeholder="运行时可不填" /></label>
              <label class="workflow-input-required">必填<input v-model="input.required" type="checkbox" /></label>
              <button type="button" title="删除输入" @click="removeWorkflowInput(index)"><Trash2 :size="13" /></button>
            </div>
            <button type="button" class="connect-button" @click="addWorkflowInput"><Plus :size="13" />添加输入</button>
            <div v-if="selected.inputs?.length" class="workflow-input-values"><strong>运行时取值</strong><label v-for="input in selected.inputs" :key="input.name">{{ input.name }}<input v-model="workflowInputs[input.name]" :placeholder="input.description || input.type || '输入值'" /></label></div>
          </div>
          <div class="canvas-hint"><span>开始</span><i></i><span>{{ (selected.nodes || []).length }} 个步骤 · {{ (selected.edges || []).length }} 条连接</span><i></i><span>结束</span></div>
          <div class="workflow-node-list">
            <span class="workflow-terminal">开始</span>
            <template v-for="(node, index) in canvasNodes" :key="node.id">
              <div class="node-connector" :class="{ connected: hasIncomingEdge(node), missing: !hasIncomingEdge(node) }"><i></i><small>{{ connectorLabel(node, index) }}</small></div>
              <button type="button" class="workflow-node-card" :data-workflow-node-id="node.id" :class="[{ active: selectedNode === node, disconnected: isNodeDisconnected(node) }, `state-${nodeState(node)}`]" @click="selectedNode = node"><span class="node-index">{{ index + 1 }}</span><span><strong>{{ nodeLabel(node) }}</strong><small>{{ node.id }}</small></span><CheckCircle2 v-if="nodeState(node) === 'ready' && !isNodeDisconnected(node)" :size="15" /><AlertTriangle v-else :size="15" /></button>
            </template>
            <div class="node-connector" :class="{ connected: Boolean(canvasNodes.length) }"><i></i><small>{{ canvasNodes.length ? '结束' : '' }}</small></div>
            <span class="workflow-terminal">结束</span>
            <p v-if="!canvasNodes.length" class="canvas-empty">从左侧节点库添加步骤<br /><small>新步骤会自动接入主流程</small></p>
          </div>
        </section>
        <section v-if="selectedNode" class="workflow-properties">
          <div class="panel-heading"><strong>步骤设置</strong><small>{{ selectedAction?.label }}</small></div>
          <label>步骤名称<input :value="selectedNode.id" @change="renameNode" /></label>
          <label>上游步骤<select :value="nodePredecessorId" @change="setNodePredecessor"><option value="">无（流程起点）</option><option v-for="node in nodeOptions(selectedNode.id)" :key="node.id" :value="node.id">{{ nodeLabel(node) }}</option></select></label>
          <label>下游步骤<select :value="nodeSuccessorId" @change="setNodeSuccessor"><option value="">无（流程终点）</option><option v-for="node in nodeOptions(selectedNode.id)" :key="`${node.id}-successor`" :value="node.id">{{ nodeLabel(node) }}</option></select></label>
          <label v-if="selectedNode.action_id === 'device.select'">目标设备<select v-model="selectedNode.config.device_id"><option value="">选择设备</option><option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">{{ deviceLabel(device) }}</option></select></label>
          <template v-else-if="selectedNode.action_id === 'device.connect'">
            <label>目标设备<select v-model="selectedNode.config.device_id"><option value="">选择设备</option><option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">{{ deviceLabel(device) }}</option></select></label>
            <label>超时时间<input v-model.number="selectedNode.config.timeout" type="number" min="1" max="300" /> 秒</label>
          </template>
          <label v-else-if="selectedNode.action_id === 'device.info'">采集字段<select v-model="selectedNode.config.fields" multiple size="4"><option value="name">名称</option><option value="address">地址</option><option value="model">型号</option><option value="software_version">软件版本</option><option value="status">状态</option><option value="output">原始输出</option></select><small class="field-hint">可多选，后续条件和保存结果可使用这些字段。</small></label>
          <label v-if="selectedNode.action_id === 'device.command'">要执行的命令<textarea :value="configString('command')" rows="3" placeholder="例如：display version" @input="updateConfigString('command', $event)" /></label>
          <template v-if="selectedNode.action_id === 'variable.set'"><label>变量名<input :value="configString('name')" @input="updateConfigString('name', $event)" /></label><label>变量值<input :value="configString('value')" placeholder="支持 ${node.field}" @input="updateConfigString('value', $event)" /></label></template>
          <template v-if="selectedNode.action_id === 'expression.evaluate'"><label>表达式<textarea :value="configString('expression')" rows="2" placeholder="例如：inputs.version &lt; 10" @input="updateConfigString('expression', $event)" /></label><label>表达式上下文 JSON<textarea :value="JSON.stringify(selectedNode.config.values || {})" rows="2" @change="updateConfigJson('values', $event)" /></label></template>
          <template v-if="selectedNode.action_id === 'loop.for_each'"><label>列表来源<select v-model="loopItemsMode"><option value="manual">手动输入列表</option><option value="reference">引用前置步骤输出</option></select></label><label v-if="loopItemsMode === 'manual'">遍历列表 JSON<textarea :value="JSON.stringify(selectedNode.config.items || [])" rows="2" @change="updateConfigJson('items', $event)" /></label><template v-else><label>列表来源步骤<select :value="loopItemsSourceId" @change="setLoopItemsSource(($event.target as HTMLSelectElement).value)"><option value="">选择步骤</option><option v-for="source in resultSources" :key="source.id" :value="source.id">{{ source.label }}</option></select></label><label>输出字段<select :value="loopItemsField" @change="setLoopItemsField(($event.target as HTMLSelectElement).value)"><option value="">完整输出</option><option value="items">items</option><option value="output">output</option><option value="value">value</option><option value="result">result</option></select><small class="field-hint">引用会在运行时解析为列表；适合消费采集、表达式或保存结果步骤的输出。</small></label></template><label>循环动作<select v-model="selectedNode.config.action_id"><option v-for="action in actions" :key="action.id" :value="action.id">{{ action.label }}</option></select></label><label>动作参数 JSON<textarea :value="JSON.stringify(selectedNode.config.action_inputs || {})" rows="2" @change="updateConfigJson('action_inputs', $event)" /></label></template>
          <template v-if="selectedNode.action_id === 'utility.confirm'"><label>确认提示<textarea :value="configString('prompt')" rows="3" placeholder="例如：请确认设备已备份配置" @input="updateConfigString('prompt', $event)" /></label><label>同意按钮文字<input :value="configString('approve_label')" @input="updateConfigString('approve_label', $event)" /></label><label>拒绝按钮文字<input :value="configString('reject_label')" @input="updateConfigString('reject_label', $event)" /></label><small class="field-hint">执行到此步骤会暂停，任务页会显示确认或取消选项。</small></template>
          <label v-if="selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.wait' && selectedNode.action_id !== 'utility.confirm'">失败重试次数<input v-model.number="selectedNode.config.retry_attempts" type="number" min="1" max="5" placeholder="1" /><small class="field-hint">失败后自动重试，最多 5 次。</small></label>
          <label v-if="selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.wait' && selectedNode.action_id !== 'utility.confirm'">失败重试间隔（秒）<input v-model.number="selectedNode.config.retry_backoff_seconds" type="number" min="0" max="60" step="0.1" placeholder="0" /><small class="field-hint">两次重试之间等待的时间，最多 60 秒。</small></label>
          <label v-if="selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.confirm'">并行组（可选）<input :value="configString('parallel_group')" placeholder="例如：信息采集" @input="updateConfigString('parallel_group', $event)" /><small class="field-hint">同一组中互相独立的步骤可并行执行；留空表示按顺序执行。</small></label>
          <label v-if="selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.confirm'">重复执行次数<input v-model.number="selectedNode.config.repeat_count" type="number" min="1" max="20" placeholder="1" /><small class="field-hint">将此步骤最多执行 20 次，适合重复探测和轮询。</small></label>
          <template v-if="selectedNode.action_id === 'file.upload' || selectedNode.action_id === 'file.download'">
            <label>源文件<input :value="configString('source')" placeholder="本地或设备路径" @input="updateConfigString('source', $event)" /></label>
            <label>目标路径<input :value="configString('destination')" placeholder="本地或设备路径" @input="updateConfigString('destination', $event)" /></label>
          </template>
          <label v-if="selectedNode.action_id === 'utility.wait'">等待秒数<input v-model.number="selectedNode.config.seconds" type="number" min="1" max="3600" /></label>
          <div v-else-if="selectedNode.action_id === 'utility.condition'" class="condition-builder"><strong>如果</strong><label>多个条件<select v-model="conditionLogicalOperator"><option value="AND">全部满足（AND）</option><option value="OR">任一满足（OR）</option></select></label><div v-for="(rule, index) in conditionRules" :key="index" class="condition-row"><select v-model="rule.field"><option value="software_version">软件版本</option><option value="status">状态</option><option value="name">名称</option></select><select v-model="rule.operator"><option>等于</option><option>不等于</option><option>包含</option><option>不包含</option><option>大于</option><option>小于</option><option>是否为空</option></select><input v-model="rule.value" placeholder="比较值" /></div><button type="button" class="connect-button" @click="conditionRules.push({ field: 'status', operator: '等于', value: '' })">+ 添加条件</button><label>满足条件时<select :value="conditionTargets.trueTarget" @change="setConditionTarget('true', $event)"><option value="">选择真分支步骤</option><option v-for="node in (selected.nodes || []).filter((item) => item.id !== selectedNode?.id)" :key="node.id" :value="node.id">{{ actions.find((action) => action.id === node.action_id)?.label || node.id }}</option></select></label><label>不满足时<select :value="conditionTargets.falseTarget" @change="setConditionTarget('false', $event)"><option value="">选择假分支步骤</option><option v-for="node in (selected.nodes || []).filter((item) => item.id !== selectedNode?.id)" :key="node.id" :value="node.id">{{ actions.find((action) => action.id === node.action_id)?.label || node.id }}</option></select></label><small>运行时只会执行其中一条分支，后续步骤会沿用分支条件。</small></div>
          <label v-else-if="selectedNode.action_id === 'result.save'">结果名称<input v-model="selectedNode.config.key" placeholder="例如：版本检查结果" /><span class="field-hint">保存哪个数据</span><select :value="String(selectedNode.config.value || '')" @change="onResultFieldChange"><option value="">上一步完整结果</option><option v-for="source in resultSources" :key="`${source.id}-version`" :value="`${source.id}.software_version`">{{ source.label }} · 软件版本</option><option v-for="source in resultSources" :key="`${source.id}-status`" :value="`${source.id}.status`">{{ source.label }} · 状态</option><option v-for="source in resultSources" :key="`${source.id}-output`" :value="`${source.id}.output`">{{ source.label }} · 输出</option></select><small class="field-hint">通过选择器传递上一步数据，无需填写表达式。</small></label>
          <button class="remove-node-button" type="button" @click="removeNode"><Trash2 :size="13" />删除步骤</button>
          <button class="connect-button" type="button" @click="testSelectedStep">测试此步骤</button>
        </section>
        <section v-else class="workflow-properties workflow-empty">选择一个步骤编辑参数</section>
      </main>
      <main v-else class="workflow-empty">选择一个 Workflow 开始编辑</main>
    </div>
    <div v-if="showRunPreview" class="workflow-preview-backdrop"><div class="workflow-preview"><h3>执行预览</h3><p><b>流程名称：</b>{{ selected?.name }}</p><p><b>目标数量：</b>{{ selectedDeviceIds.length || 1 }} 台</p><p><b>步骤数量：</b>{{ selected?.nodes?.length || 0 }} 步</p><p><b>任务目标：</b>{{ taskGoal }}</p><p v-if="previewParallelGroups.length" class="preview-parallel-summary"><b>并行执行：</b>{{ previewParallelGroups.join('；') }}</p><ol class="preview-step-list"><li v-for="(step, index) in previewSteps" :key="`${step.label}-${index}`">{{ index + 1 }}. {{ step.label }}<small v-if="step.detail">{{ step.detail }}</small></li></ol><p class="preview-check">✓ 目标设备已选择　✓ 必填字段已填写　✓ 条件配置完整</p><p v-if="previewHasRisk" class="preview-risk-warning"><AlertTriangle :size="14" />包含重启或文件传输操作，请确认影响后继续。</p><label v-if="previewHasRisk" class="preview-risk-confirm"><input v-model="confirmedRisks" type="checkbox" />我已确认高风险操作的影响</label><div class="preview-actions"><button type="button" @click="showRunPreview = false">取消</button><button type="button" :disabled="dryRunning" @click="dryRunWorkflow">模拟运行</button><button class="primary-action" type="button" :disabled="previewHasRisk && !confirmedRisks" @click="confirmRunFromPreview">确认开始</button></div></div></div>
    <div v-if="issues.length" class="workflow-issues" role="alert"><strong><AlertTriangle :size="14" />需要处理的问题</strong><button v-for="issue in issues" :key="`${issue.code}-${issue.node_id || 'workflow'}-${issue.message}`" type="button" class="workflow-issue" @click="focusIssue(issue)"><span>{{ issueText(issue) }}</span><small>点击定位</small></button></div>
    <footer v-if="selected" class="workflow-validation-bar" :class="{ invalid: issues.length, valid: !issues.length }"><span v-if="issues.length"><AlertTriangle :size="15" />还有 {{ issues.length }} 个问题需要处理</span><span v-else><CheckCircle2 :size="15" />流程结构看起来没问题</span><button v-if="issues.length" type="button" @click="validate">重新检查</button></footer>
  </section>
</template>

<style scoped>
.workflow-run-target {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  color: rgba(226, 232, 240, .72);
  font-size: 11px;
}
.workflow-run-target select,
.workflow-properties select {
  min-width: 150px;
  max-width: 220px;
  padding: 6px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  background: rgba(15, 23, 42, .7);
  color: inherit;
}
.workflow-run-target select[multiple] { min-height: 68px; }
.field-hint { display: block; margin-top: 4px; color: rgba(226, 232, 240, .58); font-size: 11px; line-height: 1.4; }
.run-action { background: #0f766e !important; border-color: #14b8a6 !important; color: #f0fdfa; }
.task-goal { padding: 6px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; background: rgba(15,23,42,.7); color: inherit; }
.workflow-create-menu { position: absolute; z-index: 4; top: 96px; left: 20px; display: grid; gap: 6px; width: 220px; padding: 12px; border: 1px solid var(--workflow-border); border-radius: 8px; background: #172033; box-shadow: 0 12px 30px rgba(0,0,0,.3); }
.workflow-create-menu button { padding: 8px; border: 1px solid var(--workflow-border); border-radius: 5px; background: rgba(30,41,59,.7); color: inherit; text-align: left; cursor: pointer; }
.condition-builder { display: grid; gap: 8px; }
.condition-row { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 5px; }
.condition-row select, .condition-row input { min-width: 0; padding: 6px; border: 1px solid var(--workflow-border); border-radius: 4px; background: rgba(15,23,42,.7); color: inherit; }
.workflow-preview-backdrop { position: fixed; inset: 0; z-index: 30; display: grid; place-items: center; background: rgba(2,6,23,.62); }
.workflow-preview { width: min(420px, calc(100vw - 32px)); padding: 22px; border: 1px solid var(--workflow-border); border-radius: 10px; background: #172033; box-shadow: 0 20px 60px rgba(0,0,0,.4); }
.preview-step-list { display: grid; gap: 5px; margin: 12px 0; padding-left: 22px; color: rgba(226, 232, 240, .85); font-size: 12px; }
.preview-step-list small { margin-left: 7px; color: #fcd34d; }
.preview-parallel-summary { color: #93c5fd; }
.workflow-preview h3 { margin: 0 0 14px; }
.preview-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 18px; }
.workflow-run-message { margin: 0; padding: 7px 20px; color: #99f6e4; background: rgba(13, 148, 136, .12); font-size: 12px; }
.workflow-issues { display: grid; gap: 6px; margin: 0; padding: 10px 20px; border-bottom: 1px solid rgba(248, 113, 113, .25); background: rgba(127, 29, 29, .16); color: #fecaca; font-size: 12px; }
.workflow-issues > strong { display: flex; align-items: center; gap: 6px; }
.workflow-issue { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; padding: 7px 9px; border: 1px solid rgba(248, 113, 113, .25); border-radius: 5px; background: rgba(127, 29, 29, .2); color: #fee2e2; text-align: left; cursor: pointer; }
.workflow-issue:hover { border-color: rgba(252, 165, 165, .65); background: rgba(127, 29, 29, .35); }
.workflow-issue small { flex: 0 0 auto; color: #fca5a5; }
.workflow-branch-notice { display: flex; align-items: center; gap: 6px; margin: 0; padding: 7px 20px; color: #fcd34d; background: rgba(180, 83, 9, .14); font-size: 12px; }
.workflow-search { display: flex; align-items: center; gap: 6px; margin: 0 0 8px; padding: 5px 7px; border: 1px solid var(--workflow-border); border-radius: 5px; color: rgba(226, 232, 240, .55); }
.workflow-search input { min-width: 0; margin: 0; padding: 2px; border: 0; background: transparent; color: inherit; outline: 0; }
.catalog-empty { margin: 8px; color: rgba(226, 232, 240, .5); font-size: 11px; }
.node-library-hint { margin: 0; color: rgba(226, 232, 240, .52); font-size: 10px; line-height: 1.5; }
.node-library-hint + .connect-button { margin-top: 10px; }
@media (max-width: 900px) { .workflow-search { grid-column: 1 / -1; } }
@media (max-width: 900px) {
  .workflow-run-target { order: 10; width: 100%; margin-left: 0; }
  .workflow-run-target select { flex: 1; max-width: none; }
}
</style>
