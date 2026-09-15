<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { AlertTriangle, Braces, CheckCircle2, Copy, GitBranch, Hand, MousePointer2, Play, Plus, Redo, Save, Search, Trash2, Undo, Workflow, X } from 'lucide-vue-next'
import { desktopApi } from '../transport/api'
import { useWorkspaceStore } from '../stores/workspace'
import type { DeviceSummary } from '../types'
import WorkflowCanvas from './WorkflowCanvas.vue'
import { useUndoRedo, useUndoRedoShortcuts } from '../composables/useUndoRedo'
import { autoLayout } from '../utils/layoutAlgorithms'

type NodeItem = { id: string; action_id: string; config: Record<string, unknown>; input_mapping?: Record<string, unknown>; position?: { x: number; y: number } }
type WorkflowInput = { name: string; type?: string; required?: boolean; default?: unknown; description?: string }
type WorkflowEdge = { source: string; target: string; condition?: string; source_handle?: string }
type WorkflowItem = { id: string; name: string; description?: string; version?: string | number; inputs?: WorkflowInput[]; nodes?: NodeItem[]; edges?: Array<{ source: string; target: string; condition?: string; source_handle?: string }> }
type Issue = { code: string; message: string; node_id?: string }
type OutputField = { name: string; label: string }
type ActionItem = { id: string; label: string; hint: string; tone: string; outputFields: OutputField[] }
type CommandReference = { reference: string; label: string; hint: string }

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
const confirmedRisks = ref(false)
const canvasInteractive = ref(true)
const commandEditor = ref<HTMLTextAreaElement | null>(null)
const showCommandReferenceMenu = ref(false)
let workflowClipboard: NodeItem | null = null
const workflowInputValues = ref<Record<string, unknown>>({})
const workflowInputTouched = ref(new Set<string>())

function defaultWorkflowInputValue(input: WorkflowInput): unknown {
  if (input.default !== undefined && input.default !== null) return input.default
  if (input.type === 'boolean') return false
  return ''
}

function initializeWorkflowInputValues(workflow: WorkflowItem | null): void {
  const values: Record<string, unknown> = {}
  for (const input of workflow?.inputs || []) {
    const name = String(input.name || '').trim()
    if (name) values[name] = defaultWorkflowInputValue(input)
  }
  workflowInputValues.value = values
  workflowInputTouched.value = new Set()
}

const workflowRuntimeInputs = computed<Record<string, unknown>>(() => {
  const inputs = selected.value?.inputs || []
  return Object.fromEntries(inputs
    .filter((input) => String(input.name || '').trim())
    .filter((input) => {
      const value = workflowInputValues.value[input.name]
      const hasValue = value !== undefined && value !== null && value !== ''
      const hasDefault = input.default !== undefined && input.default !== null
      return hasValue || input.required || hasDefault || workflowInputTouched.value.has(input.name)
    })
    .map((input) => [input.name, workflowInputValues.value[input.name] ?? '']))
})

function workflowInputDisplay(input: WorkflowInput): string {
  const value = workflowInputValues.value[input.name]
  if (input.type === 'object' || input.type === 'array') {
    if (value === '' || value === undefined || value === null) return ''
    return JSON.stringify(value)
  }
  return String(value ?? '')
}

function updateWorkflowInput(name: string, event: Event): void {
  const input = selected.value?.inputs?.find((item) => item.name === name)
  if (!input) return
  const target = event.target as HTMLInputElement | HTMLTextAreaElement
  const rawValue = input.type === 'boolean'
    ? (target as HTMLInputElement).checked
    : target.value
  let value: unknown = rawValue
  if (input.type === 'number' || input.type === 'integer') {
    value = target.value === '' ? '' : Number(target.value)
  }
  else if (input.type === 'object' || input.type === 'array') {
    if (target.value === '') value = ''
    else {
      try { value = JSON.parse(target.value) } catch { value = target.value }
    }
  }
  workflowInputValues.value = { ...workflowInputValues.value, [name]: value }
  workflowInputTouched.value = new Set([...workflowInputTouched.value, name])
}

function workflowInputHasIssue(name: string): boolean {
  return issues.value.some((issue) => (
    (issue.code === 'missing_workflow_input' || issue.code === 'invalid_workflow_input_type')
    && issue.message.includes(name)
  ))
}

function toggleCanvasInteractive(): void {
  canvasInteractive.value = !canvasInteractive.value
}
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

const fallbackOutputFields: Record<string, string[]> = {
  'device.select': ['device_id', 'status'],
  'device.connect': ['output', 'status', 'execution_id', 'operation_id', 'session_id', 'device_id', 'cli_status', 'evidence'],
  'device.ssh': ['output', 'status', 'execution_id', 'operation_id', 'session_id', 'device_id', 'cli_status', 'evidence'],
  'device.telnet': ['output', 'status', 'execution_id', 'operation_id', 'session_id', 'device_id', 'cli_status', 'evidence'],
  'device.info': ['device_id', 'name', 'address', 'model', 'version', 'output', 'status', 'execution_id', 'operation_id', 'session_id', 'cli_status', 'software_version', 'requested_fields', 'evidence'],
  'device.command': ['output', 'status', 'execution_id', 'operation_id', 'session_id', 'device_id', 'cli_status', 'evidence'],
  'file.upload': ['status', 'operation_id', 'verified', 'skipped', 'skip_reason', 'output', 'evidence'],
  'file.download': ['status', 'operation_id', 'verified', 'skipped', 'skip_reason', 'output', 'evidence'],
  'device.reboot': ['output', 'status', 'execution_id', 'operation_id', 'session_id', 'device_id', 'cli_status', 'evidence'],
  'utility.wait': ['seconds', 'status'],
  'terminal.wait': ['output', 'status', 'matched', 'sequence', 'session_id'],
  'result.save': ['key', 'value', 'status'],
  'variable.set': ['name', 'value', 'matched', 'source'],
  'expression.evaluate': ['value', 'status'],
  'loop.for_each': ['items', 'results', 'count'],
  'loop.until': ['status', 'matched', 'iterations', 'result', 'results']
}

function fieldLabel(name: string): string {
  return ({
    count: '数量',
    device_id: '设备',
    execution_id: '执行 ID',
    iterations: '循环次数',
    items: '列表',
    key: '结果名称',
    matched: '是否匹配',
    operation_id: '操作 ID',
    output: '输出',
    requested_fields: '请求字段',
    address: '地址',
    model: '型号',
    name: '名称',
    result: '当前结果',
    results: '结果列表',
    seconds: '秒数',
    sequence: '终端序号',
    session_id: '会话',
    skipped: '已跳过',
    skip_reason: '跳过原因',
    software_version: '软件版本',
    source: '原始值',
    status: '状态',
    version: '版本',
    value: '值',
    verified: '已校验'
  } as Record<string, string>)[name] || name
}

function outputField(name: string): OutputField {
  return { name, label: fieldLabel(name) }
}

function outputFieldsFromSchema(schema: unknown): OutputField[] {
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) return []
  const properties = (schema as { properties?: unknown }).properties
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return []
  return Object.keys(properties).map(outputField)
}

function defaultOutputFields(actionId: string): OutputField[] {
  return (fallbackOutputFields[actionId] || []).map(outputField)
}

function outputFieldsForAction(actionId: string): OutputField[] {
  return actions.find((action) => action.id === actionId)?.outputFields || []
}

function baseAction(id: string, label: string, hint: string, tone: string): ActionItem {
  return { id, label, hint, tone, outputFields: defaultOutputFields(id) }
}

const actions: ActionItem[] = [
  baseAction('device.select', '选择设备', '指定后续步骤的目标设备', 'blue'),
  baseAction('device.connect', '连接设备', '自动选择可用连接方式', 'blue'),
  baseAction('device.ssh', 'SSH 连接', '使用 SSH 恢复连接', 'blue'),
  baseAction('device.telnet', 'Telnet 连接', '使用 Telnet 恢复连接', 'blue'),
  baseAction('device.info', '获取设备信息', '读取型号、版本和状态', 'blue'),
  baseAction('device.command', '执行命令', '选择一个命令并执行', 'blue'),
  baseAction('file.upload', '上传文件', '将本地文件上传到设备', 'amber'),
  baseAction('file.download', '下载文件', '从设备下载文件到本地', 'amber'),
  baseAction('device.reboot', '重启设备', '重新启动目标设备', 'red'),
  baseAction('utility.wait', '等待', '等待设备或流程继续', 'amber'),
  baseAction('terminal.wait', '等待终端输出', '看到指定文本后继续', 'teal'),
  baseAction('utility.confirm', '人工确认', '暂停流程并等待人员决定', 'amber'),
  baseAction('utility.condition', '如果 / 否则', '根据数据选择真分支或假分支', 'purple'),
  baseAction('result.save', '保存结果', '保存本步骤输出供后续使用', 'green'),
  baseAction('variable.set', '设置变量', '保存一个可复用的流程变量', 'green'),
  baseAction('expression.evaluate', '计算表达式', '计算受限表达式并输出结果', 'purple'),
  baseAction('loop.for_each', '循环 FOR', '遍历列表执行一个动作', 'purple'),
  baseAction('loop.until', '循环直到满足', '重复执行并等待条件成立', 'purple')
]
const actionsRevision = ref(0)
const nonExecutableLoopActions = new Set(['loop.for_each', 'loop.until', 'utility.condition', 'utility.confirm'])
const filteredActions = computed(() => {
  void actionsRevision.value
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return actions
  return actions.filter((item) => `${item.id} ${item.label} ${item.hint}`.toLowerCase().includes(query))
})
const loopChildActions = computed(() => {
  void actionsRevision.value
  return actions.filter((item) => !nonExecutableLoopActions.has(item.id))
})
const availableDevices = computed<DeviceSummary[]>(() => workspace.devices || [])
const selectedAction = computed(() => {
  void actionsRevision.value
  return actions.find((item) => item.id === selectedNode.value?.action_id)
})
const resultSources = computed(() => {
  void actionsRevision.value
  if (!selected.value || !selectedNode.value) return []
  const nodes = selected.value.nodes || []
  const sourceIds = new Set<string>()
  const pending = (selected.value.edges || [])
    .filter((edge) => edge.target === selectedNode.value?.id)
    .map((edge) => edge.source)
  while (pending.length) {
    const sourceId = pending.pop()
    if (!sourceId || sourceIds.has(sourceId)) continue
    sourceIds.add(sourceId)
    pending.push(...(selected.value.edges || []).filter((edge) => edge.target === sourceId).map((edge) => edge.source))
  }
  return nodes.filter((item) => sourceIds.has(item.id) && item.action_id !== 'utility.condition').map((item) => ({ id: item.id, label: actions.find((action) => action.id === item.action_id)?.label || item.id, fields: outputFieldsForAction(item.action_id) }))
})
const commandReferences = computed<CommandReference[]>(() => {
  const references: CommandReference[] = []
  const seen = new Set<string>()
  const add = (reference: string, label: string, hint: string): void => {
    if (!reference || seen.has(reference)) return
    seen.add(reference)
    references.push({ reference, label, hint })
  }

  for (const input of selected.value?.inputs || []) {
    const name = String(input.name || '').trim()
    if (name) add(`inputs.${name}`, `流程输入 · ${name}`, '执行流程时提供')
  }

  const sourceIds = new Set(resultSources.value.map((source) => source.id))
  for (const node of selected.value?.nodes || []) {
    if (node.action_id !== 'variable.set' || !sourceIds.has(node.id)) continue
    const name = String(node.config.name || '').trim()
    if (name) add(name, `流程变量 · ${name}`, `来自步骤 ${node.id}`)
  }

  for (const source of resultSources.value) {
    add(source.id, `步骤输出 · ${source.label}`, `完整结果 · ${source.id}`)
    for (const field of source.fields) add(`${source.id}.${field.name}`, `${source.label} · ${field.label}`, source.id)
  }
  return references
})
function previewValue(value: unknown): string | undefined {
  if (value === undefined || value === null || value === '') return undefined
  if (typeof value === 'string') return value
  try { return JSON.stringify(value) } catch { return String(value) }
}
const commandPreview = computed(() => {
  const command = configString('command')
  const inputValues = new Map<string, unknown>()
  for (const input of selected.value?.inputs || []) inputValues.set(`inputs.${input.name}`, workflowInputValues.value[input.name])
  const sourceIds = new Set(resultSources.value.map((source) => source.id))
  const variableValues = new Map<string, unknown>()
  for (const node of selected.value?.nodes || []) {
    if (node.action_id !== 'variable.set' || !sourceIds.has(node.id)) continue
    const name = String(node.config.name || '').trim()
    if (name) variableValues.set(name, node.config.value)
  }
  const resolving = new Set<string>()
  const resolveStatic = (reference: string): string | undefined => {
    const inputValue = previewValue(inputValues.get(reference))
    if (inputValue !== undefined) return inputValue
    if (!variableValues.has(reference) || resolving.has(reference)) return undefined
    resolving.add(reference)
    const raw = variableValues.get(reference)
    const exactReference = typeof raw === 'string' ? raw.match(/^\$\{([^}]+)\}$/)?.[1] : undefined
    const resolved = exactReference ? resolveStatic(exactReference) : previewValue(raw)
    resolving.delete(reference)
    return resolved
  }
  let runtimeOnly = false
  const preview = command.replace(/\$\{([^}]+)\}/g, (token, reference: string) => {
    const value = resolveStatic(reference)
    if (value !== undefined) return value
    runtimeOnly = true
    return token
  })
  return { text: preview || '等待输入命令', runtimeOnly }
})
function insertCommandReference(reference: string): void {
  if (!selectedNode.value || !reference) return
  const textarea = commandEditor.value
  const command = configString('command')
  const start = textarea?.selectionStart ?? command.length
  const end = textarea?.selectionEnd ?? start
  const token = `\${${reference}}`
  selectedNode.value.config.command = `${command.slice(0, start)}${token}${command.slice(end)}`
  showCommandReferenceMenu.value = false
  void nextTick(() => {
    const nextTextarea = commandEditor.value
    if (!nextTextarea) return
    const cursor = start + token.length
    nextTextarea.focus()
    nextTextarea.setSelectionRange(cursor, cursor)
  })
}
const loopItemsSourceFields = computed(() => resultSources.value.find((source) => source.id === loopItemsSourceId.value)?.fields || [])
function setResultField(source: string, field: string): void {
  if (!selectedNode.value) return
  selectedNode.value.config.value = source && field ? `\${${source}.${field}}` : ''
}
function onResultFieldChange(event: Event): void {
  const value = String((event.target as HTMLSelectElement).value || '')
  const parts = value.split('.')
  setResultField(parts.shift() || '', parts.join('.'))
}
const variableValueSourceId = computed(() => {
  const value = configString('value')
  const reference = value.match(/^\$\{([^}]+)\}$/)?.[1] || ''
  return resultSources.value.find((source) => reference === source.id || reference.startsWith(`${source.id}.`))?.id || ''
})
const variableValueField = computed(() => {
  const source = variableValueSourceId.value
  const value = configString('value')
  const reference = value.match(/^\$\{([^}]+)\}$/)?.[1] || ''
  return source && reference.startsWith(`${source}.`) ? reference.slice(source.length + 1) : ''
})
const variableExtractEnabled = computed(() => {
  const extract = selectedNode.value?.config.extract
  return Boolean(extract && typeof extract === 'object' && !Array.isArray(extract))
})
function setVariableValueReference(reference: string): void {
  if (!selectedNode.value) return
  if (!reference) {
    selectedNode.value.config.value = ''
    return
  }
  const parts = reference.split('.')
  const source = parts.shift() || ''
  const field = parts.join('.')
  selectedNode.value.config.value = `\${${source}${field ? `.${field}` : ''}}`
}
function toggleVariableExtract(enabled: boolean): void {
  if (!selectedNode.value) return
  if (!enabled) {
    delete selectedNode.value.config.extract
    return
  }
  const current = selectedNode.value.config.extract
  selectedNode.value.config.extract = current && typeof current === 'object' && !Array.isArray(current)
    ? current
    : { pattern: '', mode: 'match', group: 0 }
}
function variableExtractConfig(): Record<string, unknown> {
  const extract = selectedNode.value?.config.extract
  return extract && typeof extract === 'object' && !Array.isArray(extract) ? extract as Record<string, unknown> : {}
}
function variableExtractString(key: string): string {
  return String(variableExtractConfig()[key] ?? '')
}
function updateVariableExtractString(key: string, event: Event): void {
  if (!selectedNode.value) return
  const extract = variableExtractConfig()
  extract[key] = (event.target as HTMLInputElement | HTMLTextAreaElement).value
  selectedNode.value.config.extract = extract
}
function updateVariableExtractNumber(key: string, event: Event): void {
  if (!selectedNode.value) return
  const extract = variableExtractConfig()
  const value = Number((event.target as HTMLInputElement).value)
  extract[key] = Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0
  selectedNode.value.config.extract = extract
}
function updateVariableExtractMode(event: Event): void {
  if (!selectedNode.value) return
  const extract = variableExtractConfig()
  extract.mode = (event.target as HTMLSelectElement).value
  selectedNode.value.config.extract = extract
}
const canSave = computed(() => Boolean(
  selected.value &&
  !saving.value &&
  (selected.value.nodes?.length || 0) > 0 &&
  !issues.value.length &&
  selected.value.nodes?.every((node) => nodeState(node) === 'ready' && !isNodeDisconnected(node))
))
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
function nodeHasHighRiskAction(node: NodeItem): boolean {
  if (highRiskActions.has(node.action_id)) return true
  return ['loop.for_each', 'loop.until'].includes(node.action_id) && highRiskActions.has(String(node.config.action_id || ''))
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
  initializeWorkflowInputValues(item)
  issues.value = []
  runMessage.value = ''
  confirmedRisks.value = false
  const condition = item.nodes?.find((node) => node.action_id === 'utility.condition')
  if (condition && Array.isArray(condition.config.rules)) conditionRules.value = condition.config.rules as typeof conditionRules.value
  conditionLogicalOperator.value = condition?.config.logical_operator === 'OR' ? 'OR' : 'AND'
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
  const nodes = selected.value.nodes || []
  const insertEdge = position ? findInsertEdge(position) : null
  const node: NodeItem = {
    id: `${actionId.split('.').pop()}_${Date.now().toString(36)}`,
    action_id: actionId,
    config: defaultConfig(actionId),
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
}

function startActionDrag(event: DragEvent, actionId: string): void {
  if (!event.dataTransfer) return
  event.dataTransfer.effectAllowed = 'copy'
  event.dataTransfer.setData('application/x-workflow-action', actionId)
  event.dataTransfer.setData('text/plain', actionId)
}

function defaultConfig(actionId: string): Record<string, unknown> {
  if (actionId === 'device.select') return { device_id: selectedDeviceId.value || '' }
  if (actionId === 'device.connect') return { device_id: selectedDeviceId.value || '', timeout_seconds: 30 }
  if (actionId === 'device.info') return { fields: ['name', 'software_version', 'status'] }
  if (actionId === 'device.command') return { command: '' }
  if (actionId === 'file.upload' || actionId === 'file.download') return { source: '', destination: '' }
  if (actionId === 'utility.wait') return { seconds: 1 }
  if (actionId === 'terminal.wait') return { mode: 'contains', pattern: '', timeout_seconds: 30, case_sensitive: false, send_enter: true }
  if (actionId === 'utility.confirm') return { prompt: '请确认是否继续执行后续步骤。', approve_label: '确认继续', reject_label: '取消流程' }
  if (actionId === 'utility.condition') return { expression: '', rules: [{ field: 'software_version', operator: '小于', value: '' }], logical_operator: 'AND', true_label: '满足条件', false_label: '不满足条件' }
  if (actionId === 'result.save') return { key: '检查结果' }
  if (actionId === 'variable.set') return { name: '', value: '' }
  if (actionId === 'expression.evaluate') return { expression: '', values: {} }
  if (actionId === 'loop.for_each') return { items: [], action_id: 'result.save', action_inputs: {} }
  if (actionId === 'loop.until') return { action_id: 'device.info', action_inputs: {}, condition: "result.status == 'succeeded'", max_iterations: 10, interval_seconds: 2 }
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
  if (issue.code === 'duplicate_node_id') return '流程中存在重复步骤 ID，请重命名其中一个步骤'
  if (issue.code === 'duplicate_input_name') return '流程输入名称重复，请保留唯一名称'
  if (issue.code === 'missing_workflow_input') return '流程输入缺少必填值，请补齐后再运行'
  if (issue.code === 'invalid_workflow_input_type') return '流程输入类型不匹配，请按输入定义填写'
  if (issue.code === 'unknown_action') return `${label || '步骤'}：当前动作暂不支持执行`
  if (issue.code === 'invalid_condition') return `${label || '条件判断'}：请配置至少一条完整规则`
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
  if (issues.value.length) { showValidationProblem(); return }
  if (!await persistCurrentWorkflow()) return
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
      inputs: workflowRuntimeInputs.value,
      draft: selected.value.version === 'draft',
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
  if (!await persistCurrentWorkflow()) return
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
      inputs: workflowRuntimeInputs.value,
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

// 注册快捷键
let cleanupShortcuts: (() => void) | null = null
onMounted(() => {
  cleanupShortcuts = useUndoRedoShortcuts(performUndo, performRedo)
  window.addEventListener('keydown', handleWorkflowKeyDown)
})
onUnmounted(() => {
  if (cleanupShortcuts) cleanupShortcuts()
  window.removeEventListener('keydown', handleWorkflowKeyDown)
})

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

function syncCurrentWorkflowState(): void {
  if (selectedNode.value?.action_id !== 'utility.condition') return
  selectedNode.value.config.rules = conditionRules.value
  selectedNode.value.config.logical_operator = conditionLogicalOperator.value
}

async function validate(): Promise<boolean> {
  if (!selected.value) return false
  syncCurrentWorkflowState()
  const result = await desktopApi.validateWorkflowDefinition(selected.value.id, selected.value)
  issues.value = (result.errors || []).map(e => ({ ...e, node_id: e.node_id || undefined }))
  return issues.value.length === 0
}

async function persistCurrentWorkflow(): Promise<boolean> {
  if (!selected.value) return false
  syncCurrentWorkflowState()
  saving.value = true
  try {
    const selectedNodeId = selectedNode.value?.id
    const result = await desktopApi.saveWorkflowDefinition(selected.value.id, selected.value as unknown as Record<string, unknown>)
    const saved = result.workflow as WorkflowItem
    selected.value = saved
    selectedNode.value = saved.nodes?.find((node) => node.id === selectedNodeId) || saved.nodes?.[0] || null
    return true
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause)
    error.value = message
    runMessage.value = `保存失败，未执行当前流程：${message}`
    return false
  } finally { saving.value = false }
}

async function save(): Promise<void> {
  if (!selected.value || !await validate()) {
    if (issues.value.length) showValidationProblem()
    return
  }
  await persistCurrentWorkflow()
}

async function publish(): Promise<void> {
  if (!selected.value) return
  if (!await validate()) {
    showValidationProblem()
    return
  }
  if (!await persistCurrentWorkflow()) return
  if (!canPublish.value) return
  const result = await desktopApi.publishWorkflowDefinition(selected.value.id)
  if (!result.published) issues.value = (result.errors || []).map((item) => ({ code: item.code || 'publish_error', message: item.message, node_id: item.node_id || undefined }))
  await refresh()
}

async function remove(): Promise<void> {
  if (!selected.value) return
  await desktopApi.deleteWorkflowDefinition(selected.value.id)
  selected.value = null
  selectedNode.value = null
  await refresh()
}

const requiredConfigByAction: Record<string, string[]> = {
  'device.command': ['command'],
  'device.select': ['device_id'],
  'expression.evaluate': ['expression'],
  'file.upload': ['source', 'destination'],
  'file.download': ['source', 'destination'],
  'loop.for_each': ['items', 'action_id'],
  'loop.until': ['action_id', 'condition'],
  'terminal.wait': ['pattern'],
  'utility.confirm': ['prompt'],
  'utility.wait': ['seconds'],
  'variable.set': ['name']
}

function nodeSettings(node: NodeItem): Record<string, unknown> {
  return { ...node.config, ...(node.input_mapping || {}) }
}

function hasRequiredConfigValue(node: NodeItem, settings: Record<string, unknown>, key: string): boolean {
  let aliases = [key]
  if (node.action_id === 'file.upload' || node.action_id === 'file.download') {
    if (key === 'source') aliases = ['source', 'source_path']
    if (key === 'destination') aliases = ['destination', 'destination_path']
  }
  return aliases.some((alias) => {
    const value = settings[alias]
    if (Array.isArray(value)) return value.length > 0
    return value !== undefined && value !== null && String(value).trim() !== ''
  })
}

function nodeState(node: NodeItem): 'ready' | 'attention' {
  const settings = nodeSettings(node)
  const required = requiredConfigByAction[node.action_id] || []
  if (required.some((key) => !hasRequiredConfigValue(node, settings, key))) return 'attention'
  if (node.action_id === 'utility.condition') {
    const rules = settings.rules
    const expression = typeof settings.expression === 'string' ? settings.expression.trim() : ''
    if (!expression && (!Array.isArray(rules) || !rules.some((rule) => rule && String(rule.field || '').trim() && String(rule.operator || '').trim()))) return 'attention'
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
    const catalog = await desktopApi.workflowActions()
    for (const raw of catalog.actions) {
      const item = raw as { id?: string; name?: string; category?: string; output_schema?: unknown }
      if (!item.id) continue
      const fields = outputFieldsFromSchema(item.output_schema)
      const existing = actions.find((action) => action.id === item.id)
      if (existing) {
        existing.label = item.name || existing.label
        existing.hint = item.category || existing.hint
        existing.outputFields = fields.length ? fields : existing.outputFields
      }
      else {
        actions.push({
          id: item.id,
          label: item.name || item.id,
          hint: item.category || '工作流动作',
          tone: 'blue',
          outputFields: fields.length ? fields : defaultOutputFields(item.id)
        })
      }
    }
    actionsRevision.value += 1
  } catch (cause) { error.value = String(cause) }
  await refresh()
  if (workflows.value[0]) selectWorkflow(workflows.value[0])
})

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
      <div class="toolbar-group toolbar-group-primary">
        <button type="button" @click="showCreateMenu = !showCreateMenu"><Plus :size="14" />新建流程</button>
        <select v-model="taskGoal" class="task-goal" aria-label="任务目标"><option>检查设备状态</option><option>批量执行操作</option><option>采集设备信息</option><option>上传文件</option><option>验证配置</option><option>执行实验流程</option><option>自定义流程</option></select>
      </div>
      <span class="toolbar-divider" aria-hidden="true"></span>
      <div class="toolbar-group">
        <button type="button" :disabled="!selected" @click="duplicateWorkflow"><Copy :size="14" />复制</button>
        <button type="button" class="icon-toolbar-button" :disabled="!workflowHistory.canUndo.value" @click="performUndo" title="撤销 (Ctrl+Z)" aria-label="撤销"><Undo :size="14" /></button>
        <button type="button" class="icon-toolbar-button" :disabled="!workflowHistory.canRedo.value" @click="performRedo" title="重做 (Ctrl+Shift+Z)" aria-label="重做"><Redo :size="14" /></button>
        <button type="button" :disabled="!selected || !selected.nodes || selected.nodes.length === 0" @click="applyAutoLayout" title="自动布局"><GitBranch :size="14" />自动布局</button>
      </div>
      <span class="toolbar-divider" aria-hidden="true"></span>
      <div class="toolbar-group toolbar-group-commit">
        <button type="button" :disabled="!canSave" @click="save"><Save :size="14" />{{ saving ? '保存中…' : '保存草稿' }}</button>
        <button type="button" :disabled="!selected" @click="validate"><CheckCircle2 :size="14" />检查流程</button>
      </div>
      <label class="workflow-run-target">目标设备<select v-model="selectedDeviceIds" multiple aria-label="测试运行目标设备"><option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">{{ deviceLabel(device) }}</option></select></label>
      <div class="toolbar-group toolbar-group-actions">
        <button class="run-action" type="button" :disabled="!canStartRun" @click="requestRunPreview"><Play :size="14" />{{ running ? '启动中…' : '执行预览' }}</button>
        <button type="button" :disabled="!canRun" @click="runDraft">测试草稿</button>
        <button class="primary-action" type="button" :disabled="!canPublish" @click="publish"><Play :size="14" />发布</button>
        <button class="danger-action" type="button" :disabled="!selected" @click="remove"><Trash2 :size="14" />删除</button>
      </div>
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
        <section v-if="selected.inputs?.length" class="workflow-runtime-inputs" aria-label="运行参数">
          <div class="panel-heading"><strong>运行参数</strong><small>执行流程时使用的输入</small></div>
          <div class="workflow-input-values">
            <label
              v-for="input in selected.inputs"
              :key="input.name"
              :class="{ 'workflow-input-invalid': workflowInputHasIssue(input.name) }"
            >
              <span class="workflow-input-label">{{ input.name }}<b v-if="input.required"> · 必填</b></span>
              <small v-if="input.description" class="field-hint">{{ input.description }}</small>
              <textarea
                v-if="input.type === 'object' || input.type === 'array'"
                :data-workflow-input-name="input.name"
                :value="workflowInputDisplay(input)"
                rows="2"
                :placeholder="input.type === 'array' ? '例如：[a, b]' : '例如：{key: value}'"
                @input="updateWorkflowInput(input.name, $event)"
              />
              <input
                v-else
                :data-workflow-input-name="input.name"
                :type="input.type === 'boolean' ? 'checkbox' : input.type === 'number' || input.type === 'integer' ? 'number' : 'text'"
                :step="input.type === 'integer' ? '1' : 'any'"
                :checked="input.type === 'boolean' ? workflowInputValues[input.name] === true : undefined"
                :value="input.type === 'boolean' ? undefined : workflowInputDisplay(input)"
                :placeholder="input.default === undefined || input.default === null ? `请输入${input.name}` : ''"
                @input="updateWorkflowInput(input.name, $event)"
                @change="updateWorkflowInput(input.name, $event)"
              />
            </label>
          </div>
        </section>
        <section class="workflow-action-catalog">
          <div class="panel-heading"><strong>节点库</strong><small>添加并接入流程末尾</small></div>
          <label class="workflow-search"><Search :size="13" /><input v-model="searchQuery" placeholder="搜索动作" aria-label="搜索动作" /></label>
          <button v-for="action in filteredActions" :key="action.id" type="button" draggable="true" :class="`action-tile tone-${action.tone}`" @dragstart="startActionDrag($event, action.id)" @click="addNode(action.id)"><span class="action-icon"><Plus :size="12" /></span><span><b>{{ action.label }}</b><small>{{ action.hint }}</small></span></button>
          <p v-if="!filteredActions.length" class="catalog-empty">没有匹配的动作</p>
          <p class="node-library-hint">拖动节点到画布创建步骤；点击节点端口可以重新组织流程。</p>
        </section>
        <section class="workflow-canvas">
          <div class="canvas-toolbar">
            <div class="canvas-toolbar-title"><GitBranch :size="15" /><strong>流程画布</strong><span>{{ (selected.nodes || []).length }} 个步骤</span><span>{{ (selected.edges || []).length }} 条连接</span></div>
            <div class="canvas-toolbar-actions">
              <button
                type="button"
                class="canvas-interactive-toggle"
                :class="{ active: canvasInteractive }"
                :title="canvasInteractive ? '交互已开启：可拖动节点和连线' : '交互已关闭'"
                :aria-label="canvasInteractive ? '关闭节点交互' : '开启节点交互'"
                :aria-pressed="canvasInteractive"
                @click="toggleCanvasInteractive"
              >
                <MousePointer2 v-if="canvasInteractive" :size="13" />
                <Hand v-else :size="13" />
                <span>{{ canvasInteractive ? '编辑' : '浏览' }}</span>
              </button>
              <span class="canvas-toolbar-hint">拖动节点 · 从端口拉线</span>
            </div>
          </div>
          <div class="workflow-canvas-container">
            <WorkflowCanvas
              :workflow="selected"
              :issues="issues"
              :interactive="canvasInteractive"
              @node-select="(nodeId) => { selectedNode = selected?.nodes?.find(n => n.id === nodeId) || null }"
              @connect="({ source, target, sourceHandle }) => addEdge(source, target, sourceHandle)"
              @node-add="addNode"
              @disconnect="(edgeId) => { const edge = (selected?.edges || []).find((item) => `${item.source}-${item.source_handle || 'default'}-${item.target}` === edgeId); if (edge && selected) selected.edges = (selected.edges || []).filter((item) => item !== edge) }"
              @node-position-change="handleNodePositionChange"
            />
          </div>
        </section>
        <section v-if="selectedNode" class="workflow-properties">
          <div class="panel-heading"><strong>{{ selectedNode.action_id === 'variable.set' ? '设置变量' : '步骤设置' }}</strong><small v-if="selectedNode.action_id !== 'variable.set'">{{ selectedAction?.label }}</small></div>
          <template v-if="selectedNode.action_id !== 'variable.set'">
            <label>步骤名称<input :value="selectedNode.id" @change="renameNode" /></label>
            <label>上游步骤<select :value="nodePredecessorId" @change="setNodePredecessor"><option value="">无（流程起点）</option><option v-for="node in nodeOptions(selectedNode.id)" :key="node.id" :value="node.id">{{ nodeLabel(node) }}</option></select></label>
            <label>下游步骤<select :value="nodeSuccessorId" @change="setNodeSuccessor"><option value="">无（流程终点）</option><option v-for="node in nodeOptions(selectedNode.id)" :key="`${node.id}-successor`" :value="node.id">{{ nodeLabel(node) }}</option></select></label>
          </template>
          <label v-if="selectedNode.action_id === 'device.select'">目标设备<select v-model="selectedNode.config.device_id"><option value="">选择设备</option><option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">{{ deviceLabel(device) }}</option></select></label>
          <template v-else-if="selectedNode.action_id === 'device.connect'">
            <label>目标设备<select v-model="selectedNode.config.device_id"><option value="">选择设备</option><option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">{{ deviceLabel(device) }}</option></select></label>
            <label>超时时间<input v-model.number="selectedNode.config.timeout_seconds" type="number" min="1" max="300" /> 秒</label>
          </template>
          <label v-else-if="selectedNode.action_id === 'device.info'">采集字段<select v-model="selectedNode.config.fields" multiple size="4"><option value="name">名称</option><option value="address">地址</option><option value="model">型号</option><option value="software_version">软件版本</option><option value="status">状态</option><option value="output">原始输出</option></select><small class="field-hint">可多选，后续条件和保存结果可使用这些字段。</small></label>
          <div v-if="selectedNode.action_id === 'device.command'" class="workflow-command-field">
            <div class="workflow-command-label-row"><span>要执行的命令</span><button class="workflow-command-insert" type="button" :aria-expanded="showCommandReferenceMenu" title="在光标位置插入变量" @mousedown.prevent @click="showCommandReferenceMenu = !showCommandReferenceMenu"><Braces :size="13" />插入变量</button></div>
            <textarea ref="commandEditor" :value="configString('command')" rows="3" placeholder="例如：display version" @input="updateConfigString('command', $event)" />
            <div v-if="showCommandReferenceMenu" class="workflow-command-reference-menu" role="menu" aria-label="选择要插入的变量">
              <small class="workflow-command-reference-title">选择引用，插入到当前光标位置</small>
              <button v-for="item in commandReferences" :key="item.reference" type="button" role="menuitem" @mousedown.prevent @click="insertCommandReference(item.reference)"><span><strong>{{ item.label }}</strong><small>{{ item.hint }}</small></span><code>${{ '{' }}{{ item.reference }}{{ '}' }}</code></button>
              <small v-if="!commandReferences.length" class="workflow-command-reference-empty">暂无可用变量；请先连接上游步骤或定义流程输入。</small>
            </div>
            <div class="workflow-command-preview" :class="{ 'is-runtime': commandPreview.runtimeOnly }"><span>实际命令预览</span><code>{{ commandPreview.text }}</code><small>{{ commandPreview.runtimeOnly ? '运行时解析' : '当前值已解析' }}</small></div>
            <small class="field-hint">可直接输入文本，也可用“插入变量”生成 `${变量名}`。</small>
          </div>
          <template v-if="selectedNode.action_id === 'terminal.wait'"><label>匹配方式<select v-model="selectedNode.config.mode"><option value="contains">包含文本</option><option value="regex">正则表达式</option></select></label><label>等待文本<textarea :value="configString('pattern')" rows="2" placeholder="例如：Huawei、Password: 或 completed" @input="updateConfigString('pattern', $event)" /></label><label>等待超时（秒）<input v-model.number="selectedNode.config.timeout_seconds" type="number" min="1" max="86400" /></label><label class="workflow-input-required"><input v-model="selectedNode.config.send_enter" type="checkbox" />开始等待时发送回车</label><label class="workflow-input-required"><input v-model="selectedNode.config.case_sensitive" type="checkbox" />区分大小写</label><small class="field-hint">开始等待时会自动唤醒终端提示符，再监听后续输出；支持跨数据块匹配。</small></template>
          <template v-if="selectedNode.action_id === 'variable.set'">
            <label>变量名<input :value="configString('name')" @input="updateConfigString('name', $event)" /></label>
            <label>变量值<input :value="configString('value')" placeholder="固定值或支持 ${node.field}" @input="updateConfigString('value', $event)" /><details class="workflow-variable-reference"><summary>插入上游引用</summary><select :value="variableValueSourceId && variableValueField ? `${variableValueSourceId}.${variableValueField}` : variableValueSourceId" aria-label="选择上游输出" @change="setVariableValueReference(($event.target as HTMLSelectElement).value)"><option value="">选择步骤或字段</option><template v-for="source in resultSources" :key="`${source.id}-fields`"><option :value="`${source.id}`">{{ source.label }} · 完整结果</option><option v-for="field in source.fields" :key="`${source.id}-${field.name}`" :value="`${source.id}.${field.name}`">{{ source.label }} · {{ fieldLabel(field.name) }}</option></template></select></details></label>
            <label class="workflow-inline-toggle"><input :checked="variableExtractEnabled" type="checkbox" @change="toggleVariableExtract(($event.target as HTMLInputElement).checked)" /><span>提取匹配</span></label>
            <div v-if="variableExtractEnabled" class="workflow-variable-extract">
              <label>匹配规则<textarea :value="variableExtractString('pattern')" rows="2" placeholder="例如：flash:/\\S*cc\\S*" @input="updateVariableExtractString('pattern', $event)" /></label>
              <label>保存方式<select :value="variableExtractString('mode') || 'match'" @change="updateVariableExtractMode"><option value="match">匹配内容</option><option value="line">匹配所在整行</option></select></label>
              <label>捕获组<input :value="variableExtractString('group') || '0'" type="number" min="0" step="1" @input="updateVariableExtractNumber('group', $event)" /></label>
              <small class="field-hint">保存第一个匹配；无匹配时变量为空。</small>
            </div>
          </template>
          <template v-if="selectedNode.action_id === 'expression.evaluate'"><label>表达式<textarea :value="configString('expression')" rows="2" placeholder="例如：inputs.version &lt; 10" @input="updateConfigString('expression', $event)" /></label><label>表达式上下文 JSON<textarea :value="JSON.stringify(selectedNode.config.values || {})" rows="2" @change="updateConfigJson('values', $event)" /></label></template>
          <template v-if="selectedNode.action_id === 'loop.for_each'"><label>列表来源<select v-model="loopItemsMode"><option value="manual">手动输入列表</option><option value="reference">引用前置步骤输出</option></select></label><label v-if="loopItemsMode === 'manual'">遍历列表 JSON<textarea :value="JSON.stringify(selectedNode.config.items || [])" rows="2" @change="updateConfigJson('items', $event)" /></label><template v-else><label>列表来源步骤<select :value="loopItemsSourceId" @change="setLoopItemsSource(($event.target as HTMLSelectElement).value)"><option value="">选择步骤</option><option v-for="source in resultSources" :key="source.id" :value="source.id">{{ source.label }}</option></select></label><label>输出字段<select :value="loopItemsField" @change="setLoopItemsField(($event.target as HTMLSelectElement).value)"><option value="">完整输出</option><option v-for="field in loopItemsSourceFields" :key="`loop-${loopItemsSourceId}-${field.name}`" :value="field.name">{{ fieldLabel(field.name) }}</option></select><small class="field-hint">引用会在运行时解析为列表；适合消费采集、表达式或保存结果步骤的输出。</small></label></template><label>循环动作<select v-model="selectedNode.config.action_id"><option v-for="action in loopChildActions" :key="action.id" :value="action.id">{{ action.label }}</option></select></label><label>动作参数 JSON<textarea :value="JSON.stringify(selectedNode.config.action_inputs || {})" rows="2" @change="updateConfigJson('action_inputs', $event)" /></label></template>
          <template v-if="selectedNode.action_id === 'loop.until'"><label>循环动作<select v-model="selectedNode.config.action_id"><option v-for="action in loopChildActions" :key="action.id" :value="action.id">{{ action.label }}</option></select></label><label>停止条件<textarea :value="configString('condition')" rows="2" placeholder="例如：result.status == 'succeeded'" @input="updateConfigString('condition', $event)" /></label><label>最大循环次数<input v-model.number="selectedNode.config.max_iterations" type="number" min="1" max="100" /></label><label>每轮间隔（秒）<input v-model.number="selectedNode.config.interval_seconds" type="number" min="0" max="86400" step="0.1" /></label><label>循环动作参数 JSON<textarea :value="JSON.stringify(selectedNode.config.action_inputs || {})" rows="2" @change="updateConfigJson('action_inputs', $event)" /></label><small class="field-hint">每轮执行一次动作，将结果放入 result，再用受限表达式判断是否停止。</small></template>
          <template v-if="selectedNode.action_id === 'utility.confirm'"><label>确认提示<textarea :value="configString('prompt')" rows="3" placeholder="例如：请确认设备已备份配置" @input="updateConfigString('prompt', $event)" /></label><label>同意按钮文字<input :value="configString('approve_label')" @input="updateConfigString('approve_label', $event)" /></label><label>拒绝按钮文字<input :value="configString('reject_label')" @input="updateConfigString('reject_label', $event)" /></label><small class="field-hint">执行到此步骤会暂停，任务页会显示确认或取消选项。</small></template>
          <label v-if="selectedNode.action_id !== 'variable.set' && selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.wait' && selectedNode.action_id !== 'utility.confirm'">失败重试次数<input v-model.number="selectedNode.config.retry_attempts" type="number" min="1" max="5" placeholder="1" /><small class="field-hint">失败后自动重试，最多 5 次。</small></label>
          <label v-if="selectedNode.action_id !== 'variable.set' && selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.wait' && selectedNode.action_id !== 'utility.confirm'">失败重试间隔（秒）<input v-model.number="selectedNode.config.retry_backoff_seconds" type="number" min="0" max="60" step="0.1" placeholder="0" /><small class="field-hint">两次重试之间等待的时间，最多 60 秒。</small></label>
          <label v-if="selectedNode.action_id !== 'variable.set' && selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.confirm'">并行组（可选）<input :value="configString('parallel_group')" placeholder="例如：信息采集" @input="updateConfigString('parallel_group', $event)" /><small class="field-hint">同一组中互相独立的步骤可并行执行；留空表示按顺序执行。</small></label>
          <label v-if="selectedNode.action_id !== 'variable.set' && selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.confirm'">重复执行次数<input v-model.number="selectedNode.config.repeat_count" type="number" min="1" max="20" placeholder="1" /><small class="field-hint">将此步骤最多执行 20 次，适合重复探测和轮询。</small></label>
          <template v-if="selectedNode.action_id === 'file.upload' || selectedNode.action_id === 'file.download'">
            <label>源文件<input :value="configString('source')" placeholder="本地或设备路径" @input="updateConfigString('source', $event)" /></label>
            <label>目标路径<input :value="configString('destination')" placeholder="本地或设备路径" @input="updateConfigString('destination', $event)" /></label>
          </template>
          <label v-if="selectedNode.action_id === 'utility.wait'">等待秒数<input v-model.number="selectedNode.config.seconds" type="number" min="1" max="3600" /></label>
          <div v-else-if="selectedNode.action_id === 'utility.condition'" class="condition-builder"><strong>如果</strong><label>多个条件<select v-model="conditionLogicalOperator"><option value="AND">全部满足（AND）</option><option value="OR">任一满足（OR）</option></select></label><div v-for="(rule, index) in conditionRules" :key="index" class="condition-row"><select v-model="rule.field"><option value="software_version">软件版本</option><option value="status">状态</option><option value="name">名称</option></select><select v-model="rule.operator"><option>等于</option><option>不等于</option><option>包含</option><option>不包含</option><option>大于</option><option>小于</option><option>是否为空</option></select><input v-model="rule.value" placeholder="比较值" /></div><button type="button" class="connect-button" @click="conditionRules.push({ field: 'status', operator: '等于', value: '' })">+ 添加条件</button><label>满足条件时<select :value="conditionTargets.trueTarget" @change="setConditionTarget('true', $event)"><option value="">选择真分支步骤</option><option v-for="node in (selected.nodes || []).filter((item) => item.id !== selectedNode?.id)" :key="node.id" :value="node.id">{{ actions.find((action) => action.id === node.action_id)?.label || node.id }}</option></select></label><label>不满足时<select :value="conditionTargets.falseTarget" @change="setConditionTarget('false', $event)"><option value="">选择假分支步骤</option><option v-for="node in (selected.nodes || []).filter((item) => item.id !== selectedNode?.id)" :key="node.id" :value="node.id">{{ actions.find((action) => action.id === node.action_id)?.label || node.id }}</option></select></label><small>运行时只会执行其中一条分支，后续步骤会沿用分支条件。</small></div>
          <label v-else-if="selectedNode.action_id === 'result.save'">结果名称<input v-model="selectedNode.config.key" placeholder="例如：版本检查结果" /><span class="field-hint">保存哪个数据</span><select :value="String(selectedNode.config.value || '')" @change="onResultFieldChange"><option value="">上一步完整结果</option><template v-for="source in resultSources" :key="`${source.id}-result-fields`"><option :value="`${source.id}`">{{ source.label }} · 完整结果</option><option v-for="field in source.fields" :key="`${source.id}-${field.name}`" :value="`${source.id}.${field.name}`">{{ source.label }} · {{ fieldLabel(field.name) }}</option></template></select><small class="field-hint">通过选择器传递上一步数据，无需填写表达式。</small></label>
          <button class="remove-node-button" type="button" @click="removeNode"><Trash2 :size="13" />删除步骤</button>
          <button v-if="selectedNode.action_id !== 'variable.set'" class="connect-button" type="button" @click="testSelectedStep">测试此步骤</button>
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
.workflow-command-field { position: relative; margin-bottom: 13px; }
.workflow-command-label-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 6px; font-size: 12px; }
.workflow-command-insert { display: inline-flex; align-items: center; gap: 5px; padding: 5px 7px; border: 1px solid rgba(96, 165, 250, .38); border-radius: 5px; color: #bfdbfe; background: rgba(37, 99, 235, .13); font-size: 11px; cursor: pointer; }
.workflow-command-insert:hover { border-color: rgba(125, 211, 252, .8); background: rgba(37, 99, 235, .24); }
.workflow-command-field > textarea { margin-top: 0; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; line-height: 1.5; }
.workflow-command-reference-menu { position: absolute; z-index: 8; top: 56px; right: 0; display: grid; gap: 3px; width: min(330px, calc(100% - 8px)); max-height: 260px; overflow: auto; padding: 8px; border: 1px solid rgba(96, 165, 250, .42); border-radius: 7px; background: #172033; box-shadow: 0 16px 34px rgba(0, 0, 0, .38); }
.workflow-command-reference-title { padding: 2px 5px 6px; color: rgba(226, 232, 240, .58); font-size: 10px; }
.workflow-command-reference-menu button { display: flex; align-items: center; justify-content: space-between; gap: 10px; width: 100%; min-width: 0; padding: 7px 6px; border: 1px solid transparent; border-radius: 4px; color: inherit; background: transparent; cursor: pointer; }
.workflow-command-reference-menu button:hover { border-color: rgba(96, 165, 250, .38); background: rgba(37, 99, 235, .16); }
.workflow-command-reference-menu button span { min-width: 0; text-align: left; }
.workflow-command-reference-menu button strong, .workflow-command-reference-menu button small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-command-reference-menu button strong { color: #e0f2fe; font-size: 11px; font-weight: 600; }
.workflow-command-reference-menu button small { margin-top: 2px; color: rgba(226, 232, 240, .52); font-size: 10px; }
.workflow-command-reference-menu code { flex: 0 0 auto; color: #fcd34d; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10px; }
.workflow-command-reference-empty { padding: 5px; color: rgba(226, 232, 240, .5); font-size: 10px; line-height: 1.4; }
.workflow-command-preview { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 3px 7px; margin-top: 7px; padding: 7px 8px; border-left: 2px solid rgba(45, 212, 191, .65); background: rgba(15, 118, 110, .1); }
.workflow-command-preview span { color: rgba(153, 246, 228, .78); font-size: 10px; }
.workflow-command-preview code { min-width: 0; overflow: hidden; color: #ccfbf1; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.workflow-command-preview small { grid-column: 2; color: rgba(226, 232, 240, .48); font-size: 10px; }
.workflow-command-preview.is-runtime { border-left-color: rgba(250, 204, 21, .7); background: rgba(161, 98, 7, .1); }
.workflow-command-preview.is-runtime span, .workflow-command-preview.is-runtime code { color: #fde68a; }
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

.workflow-studio-grid {
  height: 100%;
  min-height: 0;
  grid-template-columns: 220px minmax(0, 1fr) 300px;
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
.canvas-interactive-toggle { display: inline-flex; align-items: center; gap: 5px; padding: 5px 8px; border: 1px solid rgba(100, 116, 139, .35); border-radius: 6px; color: rgba(226, 232, 240, .55); background: rgba(15, 23, 42, .46); font-size: 10px; cursor: pointer; }
.canvas-interactive-toggle:hover, .canvas-interactive-toggle.active { border-color: rgba(96, 165, 250, .55); color: #bfdbfe; background: rgba(37, 99, 235, .16); }
.canvas-toolbar-hint { color: rgba(226, 232, 240, .42); }

@media (max-width: 900px) { .workflow-search { grid-column: 1 / -1; } }
@media (max-width: 900px) {
  .workflow-run-target { order: 10; width: 100%; margin-left: 0; }
  .workflow-run-target select { flex: 1; max-width: none; }
}
@media (max-width: 980px) {
  .workflow-studio-grid { height: auto; }
}
</style>
