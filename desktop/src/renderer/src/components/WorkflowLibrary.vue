<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { AlertTriangle, Braces, CheckCircle2, ChevronDown, Code2, Copy, Download, FileUp, GitBranch, GripVertical, Hand, MousePointer2, Play, Plus, Redo, RotateCcw, Save, Search, Trash2, Undo, Workflow, X } from 'lucide-vue-next'
import { desktopApi } from '../transport/api'
import { useWorkspaceStore } from '../stores/workspace'
import type { DeviceSummary, TaskRecord, WorkflowScript, WorkflowScriptInput, WorkflowScriptInputType } from '../types'
import WorkflowCanvas from './WorkflowCanvas.vue'
import WorkflowScriptEditor from './WorkflowScriptEditor.vue'
import { useUndoRedo, useUndoRedoShortcuts } from '../composables/useUndoRedo'
import { autoLayout } from '../utils/layoutAlgorithms'
import { normalizeLoopUntilNodes } from '../utils/loopUntil'

type NodeItem = { id: string; action_id: string; config: Record<string, unknown>; input_mapping?: Record<string, unknown>; position?: { x: number; y: number } }
type WorkflowInput = { name: string; type?: string; control?: string; required?: boolean; default?: unknown; description?: string }
type WorkflowOutput = { name: string; value?: unknown; type?: string; description?: string }
type WorkflowEdge = { source: string; target: string; condition?: string; source_handle?: string }
type WorkflowItem = { id: string; name: string; description?: string; version?: string | number; inputs?: WorkflowInput[]; outputs?: WorkflowOutput[]; nodes?: NodeItem[]; edges?: Array<{ source: string; target: string; condition?: string; source_handle?: string }> }
type PublishedVersionItem = { id: string; name: string; description?: string; version: string | number; published_at?: string | null; step_count?: number; referenced?: boolean; inputs?: WorkflowInput[]; outputs?: WorkflowOutput[] }
type WorkflowTemplate = { id: string; name: string; description?: string; built_in?: boolean; workflow?: WorkflowItem }
type Issue = { code: string; message: string; node_id?: string }
type OutputField = { name: string; label: string }
type ActionCategory = 'flow-control' | 'device' | 'transfer' | 'data' | 'workflow' | 'script'
type ActionItem = { id: string; label: string; hint: string; tone: string; category: ActionCategory; outputFields: OutputField[]; preset?: { actionId: string; config: Record<string, unknown>; customActionId: string } }
type CommandReference = { reference: string; label: string; hint: string }
type ScriptTestResult = { task?: TaskRecord; message?: string }
type ScriptTemplate = {
  id: string
  name: string
  description: string
  language: WorkflowScript['language']
  script: string
  input_schema: WorkflowScriptInput[]
}

const emit = defineEmits<{ close: []; 'run-published': []; 'run-version': [payload: { workflowId: string; version: string | number }] }>()
const workspace = useWorkspaceStore()
const workflows = ref<WorkflowItem[]>([])
const selected = ref<WorkflowItem | null>(null)
const selectedNode = ref<NodeItem | null>(null)
const rightRailMode = ref<'workflow' | 'step'>('workflow')
const studioMode = ref<'flow' | 'scripts'>('flow')
const scripts = ref<WorkflowScript[]>([])
const selectedScriptId = ref('')
const scriptSaving = ref(false)
const scriptTesting = ref(false)
const scriptTestConfirmed = ref(false)
const scriptTestInputs = ref('{}')
const scriptTestMode = ref<'form' | 'json'>('form')
const scriptTestValues = ref<Record<string, unknown>>({})
const scriptTestInputError = ref('')
const scriptTestResult = ref<ScriptTestResult | null>(null)
const scriptNodeInputMode = ref<'form' | 'json'>('form')
const savedScriptSnapshots = ref<Record<string, string>>({})
const showScriptTemplateDialog = ref(false)
const selectedScriptTemplateId = ref('python-main')
const scriptCreateName = ref('')
const scriptCreateDescription = ref('')
const scriptCreating = ref(false)
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
const selectedDeviceId = ref('')
const selectedDeviceIds = ref<string[]>([])
const showCreateMenu = ref(false)
const createMenuRef = ref<HTMLElement | null>(null)
const showCreateDialog = ref(false)
const createBlank = ref(false)
const createTemplateId = ref('')
const workflowTemplates = ref<WorkflowTemplate[]>([])
const createName = ref('')
const createDescription = ref('')
const creating = ref(false)
const deletingTemplateId = ref('')
const showImportPreview = ref(false)
const importing = ref(false)
const importFilename = ref('')
const importContent = ref('')
const importPreview = ref<{ workflow?: Record<string, unknown>; errors?: Array<{ message: string }>; warnings?: Array<{ message: string }> } | null>(null)
const showRunPreview = ref(false)
const dryRunning = ref(false)
const taskGoal = ref('检查设备状态')
const conditionRules = ref([{ field: 'software_version', operator: '小于', value: '8.200' }])
const conditionLogicalOperator = ref<'AND' | 'OR'>('AND')
const confirmedRisks = ref(false)
const canvasInteractive = ref(true)
const workflowCatalogWidth = ref(224)
const resizingWorkflowCatalog = ref(false)
let workflowCatalogResizeStartX = 0
let workflowCatalogResizeStartWidth = 224
const workflowPropertiesWidth = ref(312)
const resizingWorkflowProperties = ref(false)
const workflowInputsExpanded = ref(false)
const workflowOutputsExpanded = ref(false)
const workflowRuntimeInputsExpanded = ref(false)
let workflowPropertiesResizeStartX = 0
let workflowPropertiesResizeStartWidth = 312
const commandEditor = ref<HTMLTextAreaElement | null>(null)
const showCommandReferenceMenu = ref(false)
const showCustomActionDialog = ref(false)
const customActionName = ref('')
const customActionDescription = ref('')
const customActionSaving = ref(false)
const customActionWorkflowVersion = ref<PublishedVersionItem | null>(null)
let workflowClipboard: NodeItem | null = null
let scriptTestRequestId = 0
let flowTestRequestId = 0
const workflowInputValues = ref<Record<string, unknown>>({})
const workflowInputTouched = ref(new Set<string>())
const publishedVersions = ref<PublishedVersionItem[]>([])
const publishedWorkflows = ref<PublishedVersionItem[]>([])
const subworkflowVersions = ref<PublishedVersionItem[]>([])
const versionsLoading = ref(false)
const versionError = ref('')
let versionsRequestId = 0

function workflowSnapshot(workflow: WorkflowItem | null): string {
  return workflow ? JSON.stringify(workflow) : ''
}

const savedWorkflowSnapshot = ref('')
const hasUnsavedChanges = computed(() => Boolean(selected.value && workflowSnapshot(selected.value) !== savedWorkflowSnapshot.value))
const selectedScript = computed(() => scripts.value.find((item) => item.id === selectedScriptId.value) || null)
const scriptInputTypes: WorkflowScriptInputType[] = ['string', 'number', 'boolean', 'object', 'array']
const scriptTemplates: ScriptTemplate[] = [
  {
    id: 'python-main',
    name: 'Python 主函数',
    description: '推荐。参数从 main 函数签名自动生成。',
    language: 'python',
    script: 'def main(name: str = "world"):\n    return {"message": f"Hello {name}"}',
    input_schema: []
  },
  {
    id: 'python-async',
    name: 'Python 异步函数',
    description: '适合需要异步调用的脚本，自动等待 main 返回结果。',
    language: 'python',
    script: 'import asyncio\n\nasync def main(name: str, delay: float = 0):\n    await asyncio.sleep(delay)\n    return {"message": f"Hello {name}"}',
    input_schema: []
  },
  {
    id: 'powershell-param',
    name: 'PowerShell 参数脚本',
    description: '保留 PowerShell param 区域，参数可在编辑器中继续调整。',
    language: 'powershell',
    script: 'param(\n    [string]$Name = "world"\n)\n\nWrite-Output "Hello $Name"',
    input_schema: [{ name: 'Name', type: 'string', required: false, default: 'world' }]
  },
  {
    id: 'bash-input',
    name: 'Bash 环境输入',
    description: '读取 DEVICE_TUI_INPUT_JSON，适合命令行脚本。',
    language: 'bash',
    script: '#!/usr/bin/env bash\nprintf \'%s\\n\' "${DEVICE_TUI_INPUT_JSON:-{}}"',
    input_schema: []
  },
  {
    id: 'blank',
    name: '空白脚本',
    description: '从零开始编写，不预置参数。',
    language: 'python',
    script: '',
    input_schema: []
  }
]
const selectedScriptTemplate = computed(() => scriptTemplates.find((item) => item.id === selectedScriptTemplateId.value) || scriptTemplates[0])
const scriptValidationMessage = computed(() => {
  const script = selectedScript.value
  if (!script) return ''
  if (!script.name.trim()) return '脚本名称不能为空'
  const names = new Set<string>()
  for (const parameter of script.input_schema || []) {
    const name = String(parameter.name || '').trim()
    if (!name) return '每个输入参数都需要名称'
    if (names.has(name)) return `输入参数名称重复：${name}`
    names.add(name)
    if (!scriptInputTypes.includes(parameter.type)) return `参数“${name}”的类型无效`
  }
  return ''
})
const hasUnsavedScriptChanges = computed(() => Boolean(
  selectedScript.value && scriptSnapshot(selectedScript.value) !== savedScriptSnapshots.value[selectedScript.value.id]
))
const scriptTestDetails = computed(() => {
  const task = scriptTestResult.value?.task
  if (!task) return null
  return {
    status: task.status,
    stdout: taskResultValue(task, ['stdout', 'output']),
    stderr: taskResultValue(task, ['stderr']),
    exitCode: taskResultValue(task, ['exitCode', 'exit_code', 'returncode'])
  }
})

function scriptSnapshot(script: WorkflowScript): string {
  return JSON.stringify({
    name: script.name,
    description: script.description,
    language: script.language,
    script: script.script,
    input_schema: script.input_schema,
    entrypoint: script.entrypoint || '',
    input_schema_source: script.input_schema_source || 'manual'
  })
}

function normalizeWorkflowScript(script: WorkflowScript): WorkflowScript {
  return {
    ...script,
    input_schema: (Array.isArray(script.input_schema) ? script.input_schema : []).map((item, index) => ({
      name: String(item?.name || `input_${index + 1}`),
      type: scriptInputTypes.includes(item?.type) ? item.type : 'string',
      ...(item?.required ? { required: true } : {}),
      ...(Object.prototype.hasOwnProperty.call(item || {}, 'default') ? { default: item.default } : {}),
      ...(item?.description ? { description: String(item.description) } : {})
    }))
  }
}

function synchronizeScriptTestValues(): void {
  const script = selectedScript.value
  if (!script) {
    scriptTestValues.value = {}
    scriptTestInputs.value = '{}'
    return
  }
  const previous = scriptTestValues.value
  const next: Record<string, unknown> = {}
  for (const parameter of script.input_schema || []) {
    const name = String(parameter.name || '').trim()
    if (!name) continue
    if (Object.prototype.hasOwnProperty.call(previous, name)) next[name] = previous[name]
    else if (Object.prototype.hasOwnProperty.call(parameter, 'default')) next[name] = parameter.default
    else next[name] = parameter.type === 'boolean' ? false : ''
  }
  scriptTestValues.value = next
  scriptTestInputs.value = JSON.stringify(next, null, 2)
  scriptTestInputError.value = ''
}

watch(selectedScriptId, () => {
  scriptTestResult.value = null
  synchronizeScriptTestValues()
})

function scriptTestValueText(parameter: WorkflowScriptInput): string {
  const value = scriptTestValues.value[parameter.name]
  if (value === undefined || value === null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function scriptDefaultText(parameter: WorkflowScriptInput): string {
  if (!Object.prototype.hasOwnProperty.call(parameter, 'default')) return ''
  const value = parameter.default
  return typeof value === 'string' ? value : JSON.stringify(value)
}

function eventValue(event: Event): string {
  return (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value
}

function eventChecked(event: Event): boolean {
  return (event.target as HTMLInputElement).checked
}

function updateScriptInputField(index: number, field: keyof WorkflowScriptInput, value: unknown): void {
  if (!selectedScript.value?.input_schema[index]) return
  const schema = [...selectedScript.value.input_schema]
  schema[index] = { ...schema[index], [field]: value }
  if (field === 'type') delete schema[index].default
  selectedScript.value.input_schema = schema
  if (field === 'name' || field === 'type') synchronizeScriptTestValues()
}

function updateScriptDefault(index: number, event: Event): void {
  const parameter = selectedScript.value?.input_schema[index]
  if (!parameter) return
  const raw = eventValue(event)
  let value: unknown = raw
  if (parameter.type === 'number') value = raw.trim() ? Number(raw) : undefined
  if (parameter.type === 'boolean') value = eventChecked(event)
  if (parameter.type === 'object' || parameter.type === 'array') {
    if (!raw.trim()) value = undefined
    else {
      try { value = JSON.parse(raw) } catch { value = raw }
    }
  }
  const schema = [...selectedScript.value.input_schema]
  schema[index] = { ...schema[index] }
  if (value === undefined) delete schema[index].default
  else schema[index].default = value
  selectedScript.value.input_schema = schema
  synchronizeScriptTestValues()
}

function updateScriptTestValue(name: string, value: unknown): void {
  scriptTestValues.value = { ...scriptTestValues.value, [name]: value }
  scriptTestInputs.value = JSON.stringify(scriptTestValues.value, null, 2)
  scriptTestInputError.value = ''
}

function addScriptInput(): void {
  if (!selectedScript.value) return
  const names = new Set((selectedScript.value.input_schema || []).map((item) => item.name))
  let index = (selectedScript.value.input_schema || []).length + 1
  while (names.has(`input_${index}`)) index += 1
  selectedScript.value.input_schema = [
    ...(selectedScript.value.input_schema || []),
    { name: `input_${index}`, type: 'string', required: false, description: '' }
  ]
  synchronizeScriptTestValues()
}

function removeScriptInput(index: number): void {
  if (!selectedScript.value) return
  selectedScript.value.input_schema = selectedScript.value.input_schema.filter((_, itemIndex) => itemIndex !== index)
  synchronizeScriptTestValues()
}

function buildScriptTestInputs(): Record<string, unknown> {
  const inputs: Record<string, unknown> = {}
  for (const parameter of selectedScript.value?.input_schema || []) {
    const name = parameter.name.trim()
    let value = scriptTestValues.value[name]
    if (parameter.type === 'object' || parameter.type === 'array') {
      if (typeof value === 'string' && value.trim()) {
        try { value = JSON.parse(value) } catch { throw new Error(`参数“${name}”必须是合法 JSON`) }
      }
      if (parameter.type === 'array' && value !== '' && value !== undefined && !Array.isArray(value)) throw new Error(`参数“${name}”必须是数组`)
      if (parameter.type === 'object' && value !== '' && value !== undefined && (typeof value !== 'object' || Array.isArray(value) || value === null)) throw new Error(`参数“${name}”必须是对象`)
    }
    if (parameter.type === 'number' && value !== '' && value !== undefined) {
      value = Number(value)
      if (!Number.isFinite(value)) throw new Error(`参数“${name}”必须是数字`)
    }
    if (parameter.required && (value === '' || value === undefined || value === null)) throw new Error(`请填写必填参数“${name}”`)
    if (value !== '' && value !== undefined) inputs[name] = value
  }
  return inputs
}

function recordValue(source: unknown, keys: string[], seen = new Set<unknown>()): unknown {
  if (!source || typeof source !== 'object' || seen.has(source)) return undefined
  seen.add(source)
  const record = source as Record<string, unknown>
  for (const key of keys) {
    const value = record[key]
    if (value !== undefined && value !== null && value !== '') return value
  }
  for (const key of ['facts', 'data', 'outputs', 'result', 'script']) {
    const value = recordValue(record[key], keys, seen)
    if (value !== undefined) return value
  }
  return undefined
}

function taskResultValue(task: TaskRecord, keys: string[]): string {
  const candidates: unknown[] = [
    ...(task.result?.steps || []).slice().reverse(),
    task.result?.outputs,
    ...(task.checkpoint?.step_states || []).slice().reverse().map((item) => item.result),
    task.checkpoint?.outputs
  ]
  for (const candidate of candidates) {
    const value = recordValue(candidate, keys)
    if (value !== undefined) return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  }
  return ''
}

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

async function loadWorkflowScripts(preferredId = ''): Promise<void> {
  const result = await desktopApi.workflowScripts()
  scripts.value = result.scripts.map(normalizeWorkflowScript)
  savedScriptSnapshots.value = Object.fromEntries(result.scripts.map((item) => [item.id, scriptSnapshot(item)]))
  const nextId = preferredId || selectedScriptId.value
  selectedScriptId.value = scripts.value.some((item) => item.id === nextId) ? nextId : (scripts.value[0]?.id || '')
  synchronizeScriptTestValues()
}

function openScriptStudio(scriptId = selectedScriptId.value): void {
  studioMode.value = 'scripts'
  selectedScriptId.value = scriptId || scripts.value[0]?.id || ''
}

function createWorkflowScript(): void {
  selectedScriptTemplateId.value = 'python-main'
  scriptCreateName.value = `新建脚本 ${scripts.value.length + 1}`
  scriptCreateDescription.value = ''
  showScriptTemplateDialog.value = true
}

async function confirmCreateWorkflowScript(): Promise<void> {
  const template = selectedScriptTemplate.value
  if (!template || !scriptCreateName.value.trim()) return
  scriptCreating.value = true
  try {
    const result = await desktopApi.createWorkflowScript({
      name: scriptCreateName.value.trim(),
      description: scriptCreateDescription.value.trim(),
      language: template.language,
      script: template.script,
      input_schema: template.input_schema
    })
    scripts.value = [normalizeWorkflowScript(result.script), ...scripts.value]
    savedScriptSnapshots.value[result.script.id] = scriptSnapshot(result.script)
    selectedScriptId.value = result.script.id
    synchronizeScriptTestValues()
    showScriptTemplateDialog.value = false
    studioMode.value = 'scripts'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    scriptCreating.value = false
  }
}

async function duplicateWorkflowScript(): Promise<void> {
  if (!selectedScript.value) return
  try {
    const result = await desktopApi.createWorkflowScript({
      ...selectedScript.value,
      id: undefined,
      name: `${selectedScript.value.name} 副本`
    })
    scripts.value = [normalizeWorkflowScript(result.script), ...scripts.value]
    savedScriptSnapshots.value[result.script.id] = scriptSnapshot(result.script)
    selectedScriptId.value = result.script.id
    synchronizeScriptTestValues()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function saveScriptResource(script: WorkflowScript): Promise<boolean> {
  const invalidParameter = script.input_schema.some((parameter) => !String(parameter.name || '').trim())
  const validationMessage = !script.name.trim() ? '脚本名称不能为空' : invalidParameter ? '每个输入参数都需要名称' : ''
  if (validationMessage) {
    error.value = validationMessage
    return false
  }
  scriptSaving.value = true
  try {
    const result = await desktopApi.saveWorkflowScript(script.id, script)
    const index = scripts.value.findIndex((item) => item.id === result.script.id)
    if (index >= 0) scripts.value[index] = normalizeWorkflowScript(result.script)
    savedScriptSnapshots.value[result.script.id] = scriptSnapshot(result.script)
    runMessage.value = '脚本已保存。'
    return true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    return false
  } finally {
    scriptSaving.value = false
  }
}

async function saveWorkflowScript(): Promise<boolean> {
  if (!selectedScript.value || scriptValidationMessage.value) {
    if (scriptValidationMessage.value) error.value = scriptValidationMessage.value
    return false
  }
  return saveScriptResource(selectedScript.value)
}

async function saveNodeScriptResource(): Promise<void> {
  if (selectedNodeScript.value) await saveScriptResource(selectedNodeScript.value)
}

async function deleteWorkflowScript(): Promise<void> {
  if (!selectedScript.value || !window.confirm(`删除脚本“${selectedScript.value.name}”？`)) return
  try {
    const deletedId = selectedScript.value.id
    await desktopApi.deleteWorkflowScript(deletedId)
    scripts.value = scripts.value.filter((item) => item.id !== deletedId)
    delete savedScriptSnapshots.value[deletedId]
    selectedScriptId.value = scripts.value[0]?.id || ''
    synchronizeScriptTestValues()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function selectScriptForNode(scriptId: string): void {
  if (!selectedNode.value) return
  selectedNode.value.config.script_id = scriptId
  const script = scripts.value.find((item) => item.id === scriptId)
  if (script) {
    selectedNode.value.config.language = script.language
    selectedNode.value.config.script = script.script
    const inputs = scriptNodeInputObject()
    for (const parameter of script.input_schema || []) {
      if (Object.prototype.hasOwnProperty.call(inputs, parameter.name)) continue
      if (Object.prototype.hasOwnProperty.call(parameter, 'default')) inputs[parameter.name] = parameter.default
    }
    selectedNode.value.config.input_json = JSON.stringify(inputs, null, 2)
  }
}

async function testWorkflowScript(): Promise<void> {
  if (!selectedScript.value || !selectedDeviceId.value || !scriptTestConfirmed.value) return
  if (hasUnsavedScriptChanges.value && !await saveWorkflowScript()) return
  scriptTesting.value = true
  scriptTestResult.value = null
  scriptTestInputError.value = ''
  const requestId = ++scriptTestRequestId
  try {
    let inputs: Record<string, unknown>
    if (scriptTestMode.value === 'json') {
      try { inputs = JSON.parse(scriptTestInputs.value || '{}') as Record<string, unknown> } catch { throw new Error('测试输入必须是合法 JSON 对象') }
      if (!inputs || Array.isArray(inputs) || typeof inputs !== 'object') throw new Error('测试输入必须是 JSON 对象')
    } else {
      inputs = buildScriptTestInputs()
    }
    const result = await desktopApi.testWorkflowScript(selectedScript.value.id, {
      device_id: selectedDeviceId.value,
      protocol: 'simulated',
      inputs,
      confirmed_risks: true
    })
    scriptTestResult.value = result
    if (!result.task?.id) {
      runMessage.value = '脚本测试已提交。'
      return
    }
    runMessage.value = `脚本测试任务已创建：${result.task.id}`
    const terminalStatuses = new Set(['completed', 'success', 'succeeded', 'failed', 'cancelled'])
    for (let attempt = 0; attempt < 120 && !terminalStatuses.has(String(scriptTestResult.value?.task?.status)); attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 500))
      if (requestId !== scriptTestRequestId) return
      const task = (await desktopApi.getTask(result.task.id)).task
      scriptTestResult.value = { task }
    }
    if (!terminalStatuses.has(String(scriptTestResult.value?.task?.status))) {
      scriptTestResult.value = { ...scriptTestResult.value, message: '任务仍在运行，可稍后重新测试或在任务中心查看。' }
    }
  } catch (cause) {
    scriptTestInputError.value = cause instanceof Error ? cause.message : String(cause)
    scriptTestResult.value = { message: cause instanceof Error ? cause.message : String(cause) }
  } finally {
    scriptTesting.value = false
  }
}

function addWorkflowInput(): void {
  if (!selected.value) return
  const inputs = selected.value.inputs || []
  const names = new Set(inputs.map((input) => String(input.name || '').trim()))
  let index = inputs.length + 1
  while (names.has(`input_${index}`)) index += 1
  selected.value.inputs = [
    ...inputs,
    { name: `input_${index}`, type: 'string', required: false, description: '' }
  ]
  initializeWorkflowInputValues(selected.value)
}

function removeWorkflowInput(index: number): void {
  if (!selected.value) return
  selected.value.inputs = (selected.value.inputs || []).filter((_, itemIndex) => itemIndex !== index)
  initializeWorkflowInputValues(selected.value)
}

function addWorkflowOutput(): void {
  if (!selected.value) return
  const outputs = selected.value.outputs || []
  const names = new Set(outputs.map((output) => String(output.name || '').trim()))
  let index = outputs.length + 1
  while (names.has(`output_${index}`)) index += 1
  selected.value.outputs = [
    ...outputs,
    { name: `output_${index}`, value: '', type: 'any', description: '' }
  ]
}

function removeWorkflowOutput(index: number): void {
  if (selected.value) selected.value.outputs = (selected.value.outputs || []).filter((_, itemIndex) => itemIndex !== index)
}

function updateWorkflowOutput(index: number, field: keyof WorkflowOutput, value: unknown): void {
  if (!selected.value?.outputs?.[index]) return
  const outputs = [...selected.value.outputs]
  outputs[index] = { ...outputs[index], [field]: value }
  selected.value.outputs = outputs
}

function updateWorkflowInputDefinition(index: number, field: keyof WorkflowInput, value: unknown): void {
  if (!selected.value?.inputs?.[index]) return
  const inputs = [...selected.value.inputs]
  inputs[index] = { ...inputs[index], [field]: value }
  selected.value.inputs = inputs
  if (field === 'name') initializeWorkflowInputValues(selected.value)
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

function isWorkflowFileInput(input: WorkflowInput): boolean {
  return input.control === 'file' || input.type === 'file' || input.name === 'package_path'
}

function normalizeWorkflowPath(value: string): string {
  let normalized = value.trim().replace(/\\/g, '/')
  while (normalized.startsWith('./')) normalized = normalized.slice(2)
  return normalized
}

async function chooseUploadSource(): Promise<void> {
  if (!selectedNode.value || selectedNode.value.action_id !== 'file.upload') return
  try {
    const selectedPath = await window.desktopApi.chooseWorkflowFile({
      defaultPath: workspace.transferSettings?.root || '',
      label: '选择要上传的本地文件',
      extensions: [],
    })
    if (!selectedPath) return
    const source = normalizeWorkflowPath(selectedPath)
    selectedNode.value.config.source = source
    runMessage.value = `已选择上传文件：${selectedPath}`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function updateWorkflowInput(name: string, event: Event): void {
  const input = selected.value?.inputs?.find((item) => item.name === name)
  if (!input) return
  const target = event.target as HTMLInputElement | HTMLTextAreaElement
  const rawValue = input.type === 'boolean'
    ? (target as HTMLInputElement).checked
    : target.value
  let value: unknown = rawValue
  if (typeof rawValue === 'string' && isWorkflowFileInput(input)) value = normalizeWorkflowPath(rawValue)
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

async function chooseWorkflowRuntimeFile(input: WorkflowInput): Promise<void> {
  try {
    const selectedPath = await window.desktopApi.chooseWorkflowFile({
      defaultPath: workspace.transferSettings?.root || '',
      label: input.name === 'package_path' ? '软件包' : 'Workflow 文件',
      extensions: input.name === 'package_path' ? ['cc'] : [],
    })
    if (!selectedPath) return
    workflowInputValues.value = {
      ...workflowInputValues.value,
      [input.name]: normalizeWorkflowPath(selectedPath),
    }
    workflowInputTouched.value = new Set([...workflowInputTouched.value, input.name])
    runMessage.value = `已选择文件：${selectedPath}`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
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

function workflowCatalogResizeLimit(): { min: number; max: number } {
  const availableWidth = window.innerWidth
  return {
    min: 180,
    max: Math.max(280, Math.min(480, Math.floor(availableWidth * 0.42)))
  }
}

function startWorkflowCatalogResize(event: PointerEvent): void {
  if (window.innerWidth <= 980) return
  event.preventDefault()
  event.stopPropagation()
  workflowCatalogResizeStartX = event.clientX
  workflowCatalogResizeStartWidth = workflowCatalogWidth.value
  resizingWorkflowCatalog.value = true
  window.addEventListener('pointermove', handleWorkflowCatalogResize)
  window.addEventListener('pointerup', finishWorkflowCatalogResize, { once: true })
}

function handleWorkflowCatalogResize(event: PointerEvent): void {
  if (!resizingWorkflowCatalog.value) return
  const limits = workflowCatalogResizeLimit()
  workflowCatalogWidth.value = Math.min(
    limits.max,
    Math.max(limits.min, workflowCatalogResizeStartWidth + event.clientX - workflowCatalogResizeStartX)
  )
}

function finishWorkflowCatalogResize(): void {
  if (!resizingWorkflowCatalog.value) return
  resizingWorkflowCatalog.value = false
  window.removeEventListener('pointermove', handleWorkflowCatalogResize)
  try { window.localStorage.setItem('device-tui.workflow-catalog-width', String(workflowCatalogWidth.value)) } catch { /* storage is optional */ }
}

function workflowPropertiesResizeLimit(): { min: number; max: number } {
  return { min: 260, max: Math.max(420, Math.min(760, Math.floor(window.innerWidth * 0.58))) }
}

function startWorkflowPropertiesResize(event: PointerEvent): void {
  if (window.innerWidth <= 980) return
  event.preventDefault()
  event.stopPropagation()
  workflowPropertiesResizeStartX = event.clientX
  workflowPropertiesResizeStartWidth = workflowPropertiesWidth.value
  resizingWorkflowProperties.value = true
  window.addEventListener('pointermove', handleWorkflowPropertiesResize)
  window.addEventListener('pointerup', finishWorkflowPropertiesResize, { once: true })
}

function handleWorkflowPropertiesResize(event: PointerEvent): void {
  if (!resizingWorkflowProperties.value) return
  const limits = workflowPropertiesResizeLimit()
  workflowPropertiesWidth.value = Math.min(
    limits.max,
    Math.max(limits.min, workflowPropertiesResizeStartWidth - event.clientX + workflowPropertiesResizeStartX)
  )
}

function finishWorkflowPropertiesResize(): void {
  if (!resizingWorkflowProperties.value) return
  resizingWorkflowProperties.value = false
  window.removeEventListener('pointermove', handleWorkflowPropertiesResize)
  try { window.localStorage.setItem('device-tui.workflow-properties-width', String(workflowPropertiesWidth.value)) } catch { /* storage is optional */ }
}

function restoreWorkflowCatalogWidth(): void {
  try {
    const saved = Number(window.localStorage.getItem('device-tui.workflow-catalog-width'))
    if (Number.isFinite(saved)) {
      const limits = workflowCatalogResizeLimit()
      workflowCatalogWidth.value = Math.min(limits.max, Math.max(limits.min, saved))
    }
  } catch { /* storage is optional */ }
  try {
    const saved = Number(window.localStorage.getItem('device-tui.workflow-properties-width'))
    if (Number.isFinite(saved)) {
      const limits = workflowPropertiesResizeLimit()
      workflowPropertiesWidth.value = Math.min(limits.max, Math.max(limits.min, saved))
    }
  } catch { /* storage is optional */ }
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
  'script.run': ['stdout', 'stderr', 'output', 'result', 'returncode', 'exit_code', 'exitCode', 'status'],
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
    stdout: '标准输出',
    stderr: '错误输出',
    exitCode: '退出码',
    duration: '执行耗时',
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
  const fields = actionId === 'device.command'
    ? ['stdout', 'stderr', 'exitCode', 'status', 'duration', ...(fallbackOutputFields[actionId] || [])]
    : (fallbackOutputFields[actionId] || [])
  return fields.map(outputField)
}

function outputFieldsForAction(actionId: string): OutputField[] {
  return actions.find((action) => action.id === actionId)?.outputFields || []
}

function outputFieldsForNode(node: NodeItem): OutputField[] {
  if (node.action_id !== 'workflow.call') return outputFieldsForAction(node.action_id)
  const workflowId = String(node.config.workflow_id || '')
  const version = String(node.config.version || '')
  const published = [...subworkflowVersions.value, ...publishedWorkflows.value]
    .find((item) => item.id === workflowId && String(item.version) === version)
  return (published?.outputs || []).map((item) => outputField(item.name))
}

const ACTION_CATEGORY_LABELS: Record<ActionCategory, string> = {
  'flow-control': '基础流程控制',
  device: '设备操作',
  transfer: '文件传输',
  data: '变量与结果',
  workflow: '子流程',
  script: '脚本执行',
}

const ACTION_CATEGORY_ORDER: ActionCategory[] = ['flow-control', 'device', 'transfer', 'script', 'data', 'workflow']

function actionCategory(actionId: string, catalogCategory = ''): ActionCategory {
  if (actionId.startsWith('loop.') || ['utility.condition', 'utility.wait', 'terminal.wait', 'utility.confirm'].includes(actionId)) return 'flow-control'
  if (['variable.set', 'expression.evaluate', 'result.save'].includes(actionId)) return 'data'
  if (actionId.startsWith('file.') || catalogCategory === 'transfer') return 'transfer'
  if (actionId === 'script.run' || catalogCategory === 'script') return 'script'
  if (actionId === 'workflow.call' || catalogCategory === 'workflow') return 'workflow'
  if (actionId.startsWith('device.') || catalogCategory === 'device' || catalogCategory === 'connection') return 'device'
  return 'device'
}

function baseAction(id: string, label: string, hint: string, tone: string): ActionItem {
  return { id, label, hint, tone, category: actionCategory(id), outputFields: defaultOutputFields(id) }
}

const actions: ActionItem[] = [
  baseAction('device.select', '选择设备', '指定后续步骤的目标设备', 'blue'),
  baseAction('device.connect', '连接设备', '自动选择可用连接方式', 'blue'),
  baseAction('device.ssh', 'SSH 连接', '使用 SSH 恢复连接', 'blue'),
  baseAction('device.telnet', 'Telnet 连接', '使用 Telnet 恢复连接', 'blue'),
  baseAction('device.info', '获取设备信息', '读取型号、版本和状态', 'blue'),
  baseAction('device.command', '执行命令', '选择一个命令并执行', 'blue'),
  baseAction('script.run', '执行脚本', '运行 Python、PowerShell 或 Bash 脚本', 'teal'),
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
  baseAction('loop.until', '循环直到满足', '重复执行并等待条件成立', 'purple'),
  baseAction('workflow.call', '调用子流程', '复用固定发布版本的流程', 'teal')
]
const actionsRevision = ref(0)
const nonExecutableLoopActions = new Set(['loop.for_each', 'loop.until', 'utility.condition', 'utility.confirm', 'workflow.call'])
const filteredActions = computed(() => {
  void actionsRevision.value
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return actions
  return actions.filter((item) => `${item.id} ${item.label} ${item.hint}`.toLowerCase().includes(query))
})
const groupedActions = computed(() => ACTION_CATEGORY_ORDER
  .map((category) => ({
    category,
    label: ACTION_CATEGORY_LABELS[category],
    actions: filteredActions.value.filter((item) => item.category === category),
  }))
  .filter((group) => group.actions.length))
const loopChildActions = computed(() => {
  void actionsRevision.value
  return actions.filter((item) => !nonExecutableLoopActions.has(item.id))
})
const availableDevices = computed<DeviceSummary[]>(() => workspace.devices || [])
const selectedAction = computed(() => {
  void actionsRevision.value
  return actions.find((item) => item.id === selectedNode.value?.action_id)
})
const selectedSubworkflow = computed(() => {
  if (selectedNode.value?.action_id !== 'workflow.call') return null
  const workflowId = String(selectedNode.value.config.workflow_id || '')
  const version = String(selectedNode.value.config.version || '')
  return [...subworkflowVersions.value, ...publishedWorkflows.value]
    .find((item) => item.id === workflowId && String(item.version) === version) || null
})

async function selectSubworkflow(workflowId: string): Promise<void> {
  if (!selectedNode.value || selectedNode.value.action_id !== 'workflow.call') return
  selectedNode.value.config.workflow_id = workflowId
  subworkflowVersions.value = workflowId ? (await desktopApi.workflowVersions(workflowId)).versions as PublishedVersionItem[] : []
  const latest = subworkflowVersions.value[0]
  selectedNode.value.config.version = latest?.version ?? ''
  selectedNode.value.config.inputs = Object.fromEntries((latest?.inputs || []).map((input) => [input.name, input.default ?? '']))
}

function selectSubworkflowVersion(version: string): void {
  if (!selectedNode.value || selectedNode.value.action_id !== 'workflow.call') return
  const item = subworkflowVersions.value.find((candidate) => String(candidate.version) === version)
  selectedNode.value.config.version = item?.version ?? ''
  selectedNode.value.config.inputs = Object.fromEntries((item?.inputs || []).map((input) => [input.name, input.default ?? '']))
}

function updateSubworkflowInput(name: string, value: string): void {
  if (!selectedNode.value) return
  const inputs = selectedNode.value.config.inputs
  selectedNode.value.config.inputs = { ...(inputs && typeof inputs === 'object' ? inputs as Record<string, unknown> : {}), [name]: value }
}
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
  return nodes.filter((item) => sourceIds.has(item.id) && item.action_id !== 'utility.condition').map((item) => ({ id: item.id, label: actions.find((action) => action.id === item.action_id)?.label || item.id, fields: outputFieldsForNode(item) }))
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

// loop.until 停止条件配置
const loopUntilStopMode = computed<'output_contains' | 'output_regex' | 'success' | 'failure' | 'max_iterations'>({
  get: () => {
    if (selectedNode.value?.action_id !== 'loop.until') return 'max_iterations'
    const condition = String(selectedNode.value.config.condition || '')
    if (condition === 'False' || condition === 'false' || condition === '0' || !condition.trim()) return 'max_iterations'
    if (condition.includes("'succeeded'") || condition.includes('"succeeded"')) return 'success'
    if (condition.includes("'failed'") || condition.includes('"failed"')) return 'failure'
    if (condition.includes('.match(') || condition.includes('re.search')) return 'output_regex'
    if (condition.includes(' in ') || condition.includes('.contains')) return 'output_contains'
    return 'max_iterations'
  },
  set: (mode) => {
    if (selectedNode.value?.action_id !== 'loop.until') return
    const pattern = loopUntilPattern.value
    if (mode === 'success') selectedNode.value.config.condition = "result.status == 'succeeded'"
    else if (mode === 'failure') selectedNode.value.config.condition = "result.status == 'failed'"
    else if (mode === 'output_regex') selectedNode.value.config.condition = pattern ? `'${pattern}' in result.output` : "'' in result.output"
    else if (mode === 'output_contains') selectedNode.value.config.condition = pattern ? `'${pattern}' in result.output` : "'' in result.output"
    else if (mode === 'max_iterations') selectedNode.value.config.condition = 'False'
    else selectedNode.value.config.condition = 'False'
  }
})

const loopUntilPattern = computed<string>({
  get: () => {
    if (selectedNode.value?.action_id !== 'loop.until') return ''
    const condition = String(selectedNode.value.config.condition || '')
    const match = condition.match(/'([^']+)'\s+in\s+result\.output/) || condition.match(/"([^"]+)"\s+in\s+result\.output/)
    return match ? match[1] : ''
  },
  set: (pattern) => {
    if (selectedNode.value?.action_id !== 'loop.until') return
    const mode = loopUntilStopMode.value
    if (mode === 'output_contains' || mode === 'output_regex') {
      selectedNode.value.config.condition = pattern ? `'${pattern}' in result.output` : "'' in result.output"
    }
  }
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
    : { pattern: '', mode: 'match', group: 0, convert: 'string', trim: false }
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
function updateVariableExtractBoolean(key: string, event: Event): void {
  if (!selectedNode.value) return
  const extract = variableExtractConfig()
  extract[key] = (event.target as HTMLInputElement).checked
  selectedNode.value.config.extract = extract
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
const flowTestStatus = computed(() => {
  const status = String(flowTestTask.value?.status || '')
  if (!flowTestTask.value && flowTestError.value) return { label: '失败', tone: 'failed' }
  if (['completed', 'success', 'succeeded'].includes(status)) return { label: '已完成', tone: 'success' }
  if (['failed', 'cancelled'].includes(status)) return { label: status === 'cancelled' ? '已取消' : '失败', tone: 'failed' }
  if (status) {
    if (status === 'pending') return { label: '准备中', tone: 'running' }
    return { label: status === 'waiting_for_user' || status === 'waiting_for_decision' ? '等待输入' : '运行中', tone: 'running' }
  }
  return { label: '未运行', tone: 'idle' }
})
const flowTestTaskTerminal = computed(() => ['completed', 'success', 'succeeded', 'failed', 'cancelled'].includes(String(flowTestTask.value?.status || '')))
function flowTestStepStatusLabel(status: string): string {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'running' || normalized === 'resumed') return '执行中'
  if (normalized === 'success' || normalized === 'succeeded' || normalized === 'completed') return '已完成'
  if (normalized === 'failed') return '失败'
  if (normalized === 'cancelled') return '已取消'
  if (normalized === 'skipped') return '已跳过'
  if (normalized === 'waiting_for_user' || normalized === 'waiting_for_decision') return '等待输入'
  if (normalized === 'pending' || normalized === 'waiting' || !normalized) return '等待调度'
  return status
}
function normalizeFlowTestStepStatus(status: string): string {
  const normalized = String(status || '').toLowerCase()
  if (normalized === 'success' || normalized === 'succeeded' || normalized === 'completed') return 'success'
  if (normalized === 'failed' || normalized === 'cancelled') return 'failed'
  if (normalized === 'running' || normalized === 'resumed') return 'running'
  if (normalized === 'waiting_for_user' || normalized === 'waiting_for_decision') return 'waiting'
  if (normalized === 'skipped') return 'skipped'
  return 'pending'
}
const flowTestCurrentStep = computed(() => {
  const id = String(flowTestTask.value?.current_step_id || flowTestTask.value?.checkpoint?.current_step || '')
  if (!id) return ''
  const node = selected.value?.nodes?.find((item) => item.id === id)
  return node ? `${node.id} · ${actions.find((item) => item.id === node.action_id)?.label || node.action_id}` : id
})
const flowTestInputEntries = computed(() => (selected.value?.inputs || []).map((input) => ({
  name: input.name,
  type: input.type || 'string',
  value: workflowInputValues.value[input.name] ?? input.default ?? ''
})))
const flowTestOutputEntries = computed(() => {
  const task = flowTestTask.value
  const outputs = { ...(task?.checkpoint?.outputs || {}), ...(task?.result?.outputs || {}) }
  const definitions = selected.value?.outputs || []
  const resolveOutputValue = (reference: unknown): unknown => {
    if (typeof reference !== 'string') return reference
    const match = reference.trim().match(/^\$\{\s*([^}]+)\s*\}$/)
    if (!match) return reference
    const [root, ...path] = match[1].split('.').map((part) => part.trim()).filter(Boolean)
    let value: unknown = root === 'inputs' ? workflowInputValues.value : outputs[root]
    for (const part of path) {
      if (!value || typeof value !== 'object') return undefined
      value = (value as Record<string, unknown>)[part]
    }
    return value
  }
  const entries = definitions.map((output) => ({
    name: output.name,
    type: output.type || 'any',
    value: Object.prototype.hasOwnProperty.call(outputs, output.name)
      ? outputs[output.name]
      : resolveOutputValue(output.value)
  }))
  const definedNames = new Set(definitions.map((output) => output.name))
  for (const [name, value] of Object.entries(outputs)) {
    if (!definedNames.has(name)) entries.push({ name, type: 'any', value })
  }
  return entries.filter((item) => item.value !== undefined)
})
const flowTestExecutionOrder = computed(() => {
  const known = new Set<string>()
  const order: string[] = []
  const append = (id: string): void => {
    if (id && !known.has(id)) {
      known.add(id)
      order.push(id)
    }
  }
  for (const node of canvasNodes.value) append(node.id)
  for (const step of flowTestTask.value?.result?.steps || []) append(String(step.step_id || ''))
  for (const state of flowTestTask.value?.checkpoint?.step_states || []) append(String(state.step_id || ''))
  for (const state of flowTestTask.value?.workflow_view?.states || []) append(String(state.id || ''))
  return order
})
function flowTestValueText(value: unknown, prefix = ''): string {
  if (value === null || value === undefined) return prefix ? `${prefix}: 无内容` : ''
  if (Array.isArray(value)) {
    return value.map((item, index) => flowTestValueText(item, prefix ? `${prefix}[${index + 1}]` : `${index + 1}`)).filter(Boolean).join('\n')
  }
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => flowTestValueText(item, prefix ? `${prefix} · ${key}` : key))
      .filter(Boolean)
      .join('\n')
  }
  return prefix ? `${prefix}: ${String(value)}` : String(value)
}
function flowTestOutputText(value: string): string {
  const text = String(value || '').trim()
  if (!text) return ''
  if (text.startsWith('{') || text.startsWith('[')) {
    try { return flowTestValueText(JSON.parse(text)) || text } catch { /* preserve ordinary command output */ }
  }
  return text
}
function toggleFlowTestStep(stepId: string): void {
  expandedFlowTestStepIds.value = expandedFlowTestStepIds.value.includes(stepId)
    ? expandedFlowTestStepIds.value.filter((item) => item !== stepId)
    : [...expandedFlowTestStepIds.value, stepId]
}
const flowTestStepLogs = computed(() => {
  const task = flowTestTask.value
  const states = new Map<string, { status: string; output?: string; error?: string; payload?: Record<string, unknown> }>()
  for (const state of task?.checkpoint?.step_states || []) {
    const payload = state.result && typeof state.result === 'object' ? state.result as Record<string, unknown> : undefined
    states.set(state.step_id, {
      status: normalizeFlowTestStepStatus(String(state.status || 'pending')),
      output: state.result?.output || (state.result?.data ? JSON.stringify(state.result.data, null, 2) : ''),
      error: state.error?.message || state.result?.error?.message || '',
      payload
    })
  }
  for (const step of task?.result?.steps || []) {
    const payload = step && typeof step === 'object' ? step as Record<string, unknown> : undefined
    states.set(step.step_id, {
      status: normalizeFlowTestStepStatus(String(step.status || 'pending')),
      output: step.output || (step.data ? JSON.stringify(step.data, null, 2) : ''),
      error: step.message || step.error_code || '',
      payload
    })
  }
  const nodesById = new Map((selected.value?.nodes || []).map((node) => [node.id, node]))
  const completedSteps = new Set((task?.checkpoint?.completed_steps || []).map(String))
  const workflowOutputs = { ...(task?.checkpoint?.outputs || {}), ...(task?.result?.outputs || {}) }
  const terminalStatus = String(task?.status || '')
  const terminal = ['completed', 'success', 'succeeded', 'failed', 'cancelled'].includes(terminalStatus)
  const failedStepId = String(task?.checkpoint?.failed_step_id || task?.current_step_id || '')
  return flowTestExecutionOrder.value.map((nodeId) => {
    const node = nodesById.get(nodeId)
    if (!node) return null
    const state = states.get(node.id) || { status: 'pending', output: '', error: '' }
    const hasOutput = Object.prototype.hasOwnProperty.call(workflowOutputs, node.id)
    if (completedSteps.has(node.id) || hasOutput) state.status = 'success'
    else if (terminal && ['pending', 'running', 'waiting'].includes(state.status)) {
      state.status = terminalStatus === 'failed' && node.id === failedStepId ? 'failed' : 'skipped'
    }
    const payload = state.payload || {}
    let parsedOutput: Record<string, unknown> = {}
    if (typeof payload.output === 'string' && payload.output.trim().startsWith('{')) {
      try {
        const parsed = JSON.parse(payload.output)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) parsedOutput = parsed as Record<string, unknown>
      } catch { /* keep the raw terminal output */ }
    }
    const details = { ...payload, ...parsedOutput }
    const value = (keys: string[]): unknown => keys.map((key) => details[key]).find((item) => item !== undefined && item !== null && item !== '')
    const data = value(['data', 'facts', 'result']) ?? (hasOutput ? workflowOutputs[node.id] : undefined)
    return {
      id: node.id,
      actionId: node.action_id,
      label: actions.find((item) => item.id === node.action_id)?.label || node.action_id,
      command: node.action_id === 'device.command' ? String(node.config.command || '') : '',
      script: node.action_id === 'script.run' ? String(node.config.script_id ? `脚本资源：${node.config.script_id}` : '内联脚本') : '',
      stdout: String(value(['stdout', 'output']) || ''),
      stderr: String(value(['stderr']) || ''),
      exitCode: value(['exit_code', 'exitCode', 'returncode']),
      resultStatus: String(value(['status']) || ''),
      data: data && typeof data === 'object' ? data : undefined,
      dataText: data && typeof data === 'object' ? flowTestValueText(data) : '',
      ...state,
      output: typeof payload.output === 'string' ? payload.output : state.output
    }
  }).filter((item): item is NonNullable<typeof item> => Boolean(item)).filter((item) => item.status !== 'pending' || flowTestTask.value)
})
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
  normalizeLoopUntilNodes(item.nodes || [])
  selected.value = item
  flowTestRequestId += 1
  flowTestOpen.value = false
  flowTestRunning.value = false
  flowTestTask.value = null
  flowTestError.value = ''
  savedWorkflowSnapshot.value = workflowSnapshot(item)
  selectedNode.value = null
  rightRailMode.value = 'workflow'
  initializeWorkflowInputValues(item)
  issues.value = []
  runMessage.value = ''
  confirmedRisks.value = false
  const condition = item.nodes?.find((node) => node.action_id === 'utility.condition')
  if (condition && Array.isArray(condition.config.rules)) conditionRules.value = condition.config.rules as typeof conditionRules.value
  conditionLogicalOperator.value = condition?.config.logical_operator === 'OR' ? 'OR' : 'AND'
  void refreshPublishedVersions(item.id)
}

async function removePublishedVersion(version: PublishedVersionItem): Promise<void> {
  if (!selected.value || version.referenced) return
  if (!window.confirm(`确定删除 ${selected.value.name} 的 v${version.version} 吗？此操作不可撤销。`)) return
  try {
    await desktopApi.deleteWorkflowVersion(selected.value.id, version.version)
    await refreshPublishedVersions(selected.value.id)
    runMessage.value = `已删除发布版本 v${version.version}`
  } catch (cause) {
    versionError.value = cause instanceof Error ? cause.message : String(cause)
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

function openCreateDialog(blank = false): void {
  showCreateMenu.value = false
  createBlank.value = blank
  createTemplateId.value = blank ? '' : (workflowTemplates.value[0]?.id || '')
  const template = workflowTemplates.value.find((item) => item.id === createTemplateId.value)
  createName.value = blank ? '' : (template?.name || '')
  createDescription.value = blank ? '' : (template?.description || '')
  showCreateDialog.value = true
}

function openCreateDialogFromTemplate(templateId: string): void {
  openCreateDialog(false)
  chooseCreateTemplate(templateId)
}

function handleCreateMenuOutside(event: PointerEvent): void {
  if (!showCreateMenu.value) return
  const target = event.target as Node | null
  if (target && !createMenuRef.value?.contains(target)) showCreateMenu.value = false
}

function handleCreateMenuKeyDown(event: KeyboardEvent): void {
  if (event.key === 'Escape') showCreateMenu.value = false
}

function chooseCreateTemplate(templateId: string): void {
  createTemplateId.value = templateId
  createBlank.value = !templateId
  const template = workflowTemplates.value.find((item) => item.id === templateId)
  if (template) {
    createName.value = template.name
    createDescription.value = template.description || ''
  }
}

async function confirmCreate(): Promise<void> {
  const name = createName.value.trim()
  if (!name || creating.value) return
  creating.value = true
  error.value = ''
  try {
    const result = createTemplateId.value
      ? await desktopApi.instantiateWorkflowTemplate(createTemplateId.value, { name, description: createDescription.value.trim() })
      : await desktopApi.createWorkflowDefinition({ name, description: createDescription.value.trim(), inputs: [], outputs: [], nodes: [], edges: [] })
    showCreateDialog.value = false
    await refresh()
    selectWorkflow(result.workflow as WorkflowItem)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    creating.value = false
  }
}

async function saveCurrentAsTemplate(): Promise<void> {
  if (!selected.value) return
  if (!await persistCurrentWorkflow()) return
  try {
    await desktopApi.createWorkflowTemplate({ workflow_id: selected.value.id, name: selected.value.name, description: selected.value.description || '' })
    await loadWorkflowTemplates()
    runMessage.value = '当前流程已保存为模板。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function deleteWorkflowTemplate(template: WorkflowTemplate): Promise<void> {
  if (template.built_in || deletingTemplateId.value) return
  if (!window.confirm(`确定删除模板“${template.name}”吗？此操作不会删除已创建的流程。`)) return
  deletingTemplateId.value = template.id
  error.value = ''
  try {
    await desktopApi.deleteWorkflowTemplate(template.id)
    await loadWorkflowTemplates()
    if (createTemplateId.value === template.id) {
      chooseCreateTemplate(workflowTemplates.value[0]?.id || '')
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    deletingTemplateId.value = ''
  }
}

async function loadWorkflowTemplates(): Promise<void> {
  workflowTemplates.value = (await desktopApi.workflowTemplates()).templates as WorkflowTemplate[]
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
  const actionPreset = actions.find((item) => item.id === actionId)?.preset
  const actualActionId = actionPreset?.actionId || actionId
  const nodes = selected.value.nodes || []
  const insertEdge = position ? findInsertEdge(position) : null
  const node: NodeItem = {
    id: `${actualActionId.split('.').pop()}_${Date.now().toString(36)}`,
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
  if (actionId === 'device.connect') return { device_id: selectedDeviceId.value || '', timeout_seconds: 30 }
  if (actionId === 'device.info') return { fields: ['name', 'software_version', 'status'] }
  if (actionId === 'device.command') return { execution_mode: 'device', command: '', timeout_seconds: 30, retry_attempts: 1, retry_backoff_seconds: 0, failure_strategy: 'stop' }
  if (actionId === 'script.run') return { language: 'python', script_id: '', script: '', input_json: '{}', cwd: '', env: {}, timeout_seconds: 300, max_output_chars: 1_048_576, retry_attempts: 1, retry_backoff_seconds: 0 }
  if (actionId === 'file.upload') return { source: '', destination: '', overwrite: true }
  if (actionId === 'file.download') return { source: '', destination: '' }
  if (actionId === 'utility.wait') return { seconds: 1 }
  if (actionId === 'terminal.wait') return { mode: 'contains', pattern: '', timeout_seconds: 30, case_sensitive: false, send_enter: true }
  if (actionId === 'utility.confirm') return { prompt: '请确认是否继续执行后续步骤。', approve_label: '确认继续', reject_label: '取消流程' }
  if (actionId === 'utility.condition') return { expression: '', rules: [{ field: 'software_version', operator: '小于', value: '' }], logical_operator: 'AND', true_label: '满足条件', false_label: '不满足条件' }
  if (actionId === 'result.save') return { key: '检查结果' }
  if (actionId === 'variable.set') return { name: '', value: '' }
  if (actionId === 'expression.evaluate') return { expression: '', values: {} }
  if (actionId === 'loop.for_each') return { items: [], action_id: 'result.save', action_inputs: {} }
  if (actionId === 'loop.until') return { action_id: 'device.command', action_inputs: { command: 'display version' }, condition: "False", max_iterations: 10, interval_seconds: 2 }
  if (actionId === 'workflow.call') return { workflow_id: '', version: '', inputs: {} }
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

async function testFlowInEditor(): Promise<void> {
  if (!selected.value || !canStartFlowTest.value) return
  flowTestOpen.value = true
  flowTestError.value = ''
  flowTestTask.value = null
  expandedFlowTestStepIds.value = []
  runMessage.value = ''
  await validate()
  if (issues.value.length) {
    flowTestError.value = issueText(issues.value[0])
    showValidationProblem()
    return
  }
  if (!await persistCurrentWorkflow()) {
    flowTestError.value = runMessage.value || '流程保存失败，无法测试'
    return
  }
  flowTestRunning.value = true
  const requestId = ++flowTestRequestId
  try {
    const targets = selectedDeviceIds.value.length ? selectedDeviceIds.value : [selectedDeviceId.value]
    const targetSessionIds = targets
      .map((deviceId) => [deviceId, workspace.sessions.find((session) => session.device_id === deviceId && session.status === 'connected')?.id || ''] as const)
      .filter(([, sessionId]) => sessionId)
    const result = await desktopApi.runWorkflowDefinition(selected.value.id, {
      device_id: targets[0],
      device_ids: targets,
      session_ids: Object.fromEntries(targetSessionIds),
      protocol: 'simulated',
      inputs: workflowRuntimeInputs.value,
      draft: true,
      confirmed_risks: true
    })
    const task = result.tasks?.[0] || result.task
    if (!task) throw new Error('测试运行未返回任务记录')
    flowTestTask.value = task
    if (['failed', 'cancelled'].includes(String(task.status))) flowTestError.value = task.message || task.error_code || task.checkpoint?.error_message || ''
    workspace.tasks = [task, ...workspace.tasks.filter((item) => item.id !== task.id)]
    await monitorFlowTestTask(task.id, requestId)
  } catch (cause) {
    flowTestError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    flowTestRunning.value = false
  }
}

async function monitorFlowTestTask(taskId: string, requestId: number): Promise<void> {
  while (requestId === flowTestRequestId && !flowTestTaskTerminal.value) {
    await new Promise((resolve) => window.setTimeout(resolve, 500))
    if (requestId !== flowTestRequestId) return
    try {
      const latest = (await desktopApi.getTask(taskId)).task
      flowTestTask.value = latest
      flowTestError.value = ['failed', 'cancelled'].includes(String(latest.status))
        ? latest.message || latest.error_code || latest.checkpoint?.error_message || ''
        : ''
      workspace.tasks = [latest, ...workspace.tasks.filter((item) => item.id !== latest.id)]
    } catch (cause) {
      flowTestError.value = `读取任务进度失败：${cause instanceof Error ? cause.message : String(cause)}`
      break
    }
  }
}

async function resumeFlowTestMonitoring(): Promise<void> {
  if (!flowTestTask.value || flowTestRunning.value || flowTestTaskTerminal.value) return
  flowTestError.value = ''
  flowTestRunning.value = true
  const requestId = ++flowTestRequestId
  try {
    await monitorFlowTestTask(flowTestTask.value.id, requestId)
  } finally {
    flowTestRunning.value = false
  }
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

function showStepSettings(nodeId = ''): void {
  const node = selected.value?.nodes?.find((item) => item.id === nodeId)
  if (node) selectedNode.value = node
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
  restoreWorkflowCatalogWidth()
  cleanupShortcuts = useUndoRedoShortcuts(performUndo, performRedo)
  window.addEventListener('keydown', handleWorkflowKeyDown)
  window.addEventListener('pointerdown', handleCreateMenuOutside)
  window.addEventListener('keydown', handleCreateMenuKeyDown)
})
onUnmounted(() => {
  scriptTestRequestId += 1
  flowTestRequestId += 1
  finishWorkflowCatalogResize()
  finishWorkflowPropertiesResize()
  if (cleanupShortcuts) cleanupShortcuts()
  window.removeEventListener('keydown', handleWorkflowKeyDown)
  window.removeEventListener('pointerdown', handleCreateMenuOutside)
  window.removeEventListener('keydown', handleCreateMenuKeyDown)
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
  if (!selected.value) return false
  syncCurrentWorkflowState()
  const result = await desktopApi.validateWorkflowDefinition(selected.value.id, selected.value)
  const nameIssues: Issue[] = selected.value.name.trim()
    ? []
    : [{ code: 'missing_workflow_name', message: 'workflow name is required' }]
  issues.value = [
    ...nameIssues,
    ...(result.errors || []).map(e => ({ ...e, node_id: e.node_id || undefined }))
  ]
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
    savedWorkflowSnapshot.value = workflowSnapshot(saved)
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
  await refreshPublishedVersions(selected.value.id)
  publishedWorkflows.value = (await desktopApi.publishedWorkflowDefinitions()).workflows as PublishedVersionItem[]
}

async function remove(): Promise<void> {
  if (!selected.value) return
  if (hasUnsavedChanges.value && !window.confirm('当前流程有未保存修改，删除后无法恢复。确定继续吗？')) return
  if (!window.confirm(`确定删除流程“${selected.value.name}”吗？`)) return
  await desktopApi.deleteWorkflowDefinition(selected.value.id)
  selected.value = null
  selectedNode.value = null
  flowTestRequestId += 1
  flowTestOpen.value = false
  flowTestTask.value = null
  savedWorkflowSnapshot.value = ''
  await refresh()
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
  'loop.until': ['action_id', 'condition'],
  'workflow.call': ['workflow_id', 'version'],
  'terminal.wait': ['pattern'],
  'utility.confirm': ['prompt'],
  'utility.wait': ['seconds'],
  'variable.set': ['name']
}

async function importWorkflow(): Promise<void> {
  try {
    const filePath = await window.desktopApi.chooseWorkflowFile({ label: 'Workflow 文件', extensions: ['workflow.yaml', 'yaml', 'yml', 'json'] })
    if (!filePath) return
    importing.value = true
    importFilename.value = filePath.split(/[\\/]/).pop() || 'workflow.workflow.yaml'
    importContent.value = await window.desktopApi.readWorkflowFile(filePath)
    importPreview.value = await desktopApi.previewWorkflowImport(importFilename.value, importContent.value)
    showImportPreview.value = true
  } catch (cause) { error.value = String(cause) } finally { importing.value = false }
}

async function confirmImport(): Promise<void> {
  if (!importPreview.value || (importPreview.value.errors || []).length) return
  importing.value = true
  try {
    const result = await desktopApi.importWorkflowDefinition(importFilename.value, importContent.value, 'create_copy')
    showImportPreview.value = false
    importPreview.value = null
    await refresh()
    selectWorkflow(result.workflow as WorkflowItem)
  } catch (cause) { error.value = String(cause) } finally { importing.value = false }
}

async function exportWorkflow(format: 'yaml' | 'json'): Promise<void> {
  if (!selected.value) return
  try {
    const result = await desktopApi.exportWorkflowDefinition(selected.value.id, format)
    await window.desktopApi.saveWorkflowFile({ suggestedName: result.filename, content: result.content })
  } catch (cause) { error.value = String(cause) }
}

async function copyAiPrompt(): Promise<void> {
  if (!selected.value) return
  try {
    const exported = await desktopApi.exportWorkflowDefinition(selected.value.id, 'yaml')
    const prompt = `请生成一个 Device TUI Workflow 配置。要求：使用 device-tui.workflow 格式、schema_version: 1，只输出可导入的 YAML，不要解释。\n\n当前流程参考：\n${exported.content}`
    await window.desktopApi.writeClipboardText(prompt)
    runMessage.value = 'AI 提示词已复制到剪贴板'
  } catch (cause) { error.value = String(cause) }
}

function nodeSettings(node: NodeItem): Record<string, unknown> {
  return { ...node.config, ...(node.input_mapping || {}) }
}

function hasRequiredConfigValue(node: NodeItem, settings: Record<string, unknown>, key: string): boolean {
  let aliases = [key]
  if (node.action_id === 'script.run' && key === 'script') aliases = ['script', 'script_id']
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
const scriptPlaceholder = computed(() => String(selectedNode.value?.config.language || 'python') === 'python'
  ? '例如：\nimport json\nprint(json.dumps({"status": "ok"}))'
  : '输入要执行的脚本内容')
const selectedNodeScript = computed(() => {
  const scriptId = String(selectedNode.value?.config.script_id || '')
  return scripts.value.find((item) => item.id === scriptId) || null
})
function scriptNodeInputObject(): Record<string, unknown> {
  const raw = selectedNode.value?.config.input_json
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) return { ...(raw as Record<string, unknown>) }
  if (typeof raw === 'string' && raw.trim()) {
    try {
      const parsed = JSON.parse(raw)
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return { ...(parsed as Record<string, unknown>) }
    } catch {
      // Keep the invalid JSON visible in the advanced editor for correction.
    }
  }
  return {}
}
function scriptNodeInputText(parameter: WorkflowScriptInput): string {
  const value = scriptNodeInputObject()[parameter.name]
  if (value === undefined || value === null) return ''
  return typeof value === 'string' ? value : JSON.stringify(value)
}
function scriptNodeInputReference(parameterName: string): string {
  const value = scriptNodeInputObject()[parameterName]
  if (typeof value !== 'string') return ''
  return value.match(/^\$\{([^}]+)\}$/)?.[1] || ''
}
function updateScriptNodeInputReference(parameterName: string, reference: string): void {
  updateScriptNodeInput(parameterName, reference ? `\${${reference}}` : undefined)
}
function hasEmbeddedScriptReference(value: unknown): boolean {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed.includes('${') && !/^\$\{[^}]+\}$/.test(trimmed)
  }
  if (Array.isArray(value)) return value.some((item) => hasEmbeddedScriptReference(item))
  if (value && typeof value === 'object') return Object.values(value as Record<string, unknown>).some((item) => hasEmbeddedScriptReference(item))
  return false
}
function updateScriptNodeInput(name: string, value: unknown): void {
  if (!selectedNode.value) return
  if (hasEmbeddedScriptReference(value)) {
    runMessage.value = '脚本输入中的变量引用必须单独作为完整值，不能嵌在其他文字中。'
    return
  }
  const inputs = scriptNodeInputObject()
  if (value === '' || value === undefined) delete inputs[name]
  else inputs[name] = value
  selectedNode.value.config.input_json = JSON.stringify(inputs, null, 2)
}
function updateScriptNodeInputField(parameter: WorkflowScriptInput, event: Event): void {
  const raw = eventValue(event)
  if (parameter.type === 'number' && raw.trim() && !raw.trim().startsWith('${')) {
    const parsed = Number(raw)
    updateScriptNodeInput(parameter.name, Number.isFinite(parsed) ? parsed : raw)
    return
  }
  updateScriptNodeInput(parameter.name, raw)
}
function updateScriptNodeInputBoolean(parameter: WorkflowScriptInput, event: Event): void {
  updateScriptNodeInput(parameter.name, eventChecked(event))
}
function updateScriptNodeInputJson(parameter: WorkflowScriptInput, event: Event): void {
  const raw = eventValue(event)
  if (!raw.trim()) {
    updateScriptNodeInput(parameter.name, undefined)
    return
  }
  try {
    updateScriptNodeInput(parameter.name, JSON.parse(raw))
  } catch {
    runMessage.value = `参数“${parameter.name}”必须是有效 JSON`
  }
}
function updateScriptNodeInputJsonEditor(event: Event): void {
  if (!selectedNode.value) return
  const raw = eventValue(event)
  if (!raw.trim()) {
    selectedNode.value.config.input_json = '{}'
    return
  }
  try {
    const parsed = JSON.parse(raw)
    if (hasEmbeddedScriptReference(parsed)) {
      runMessage.value = '脚本输入中的变量引用必须单独作为完整值，不能嵌在其他文字中。'
      return
    }
    selectedNode.value.config.input_json = raw
  } catch {
    // Keep invalid JSON visible so the user can correct it before publishing.
    selectedNode.value.config.input_json = raw
  }
}
function updateConfigString(key: string, event: Event): void { if (selectedNode.value) selectedNode.value.config[key] = (event.target as HTMLInputElement | HTMLTextAreaElement).value }
function updateConfigJson(key: string, event: Event): void {
  if (!selectedNode.value) return
  try { selectedNode.value.config[key] = JSON.parse((event.target as HTMLTextAreaElement).value || (key === 'items' ? '[]' : '{}')) } catch { runMessage.value = `${key} 必须是有效 JSON` }
}

function openCustomActionDialog(): void {
  if (!selectedNode.value || selectedNode.value.action_id === 'utility.condition') return
  customActionWorkflowVersion.value = null
  customActionName.value = ''
  customActionDescription.value = ''
  showCustomActionDialog.value = true
}

function openWorkflowCustomActionDialog(version: PublishedVersionItem): void {
  customActionWorkflowVersion.value = version
  customActionName.value = version.name
  customActionDescription.value = version.description || ''
  showCustomActionDialog.value = true
}

async function saveCustomAction(): Promise<void> {
  if ((!selectedNode.value && !customActionWorkflowVersion.value) || !customActionName.value.trim()) return
  customActionSaving.value = true
  try {
    const sourceVersion = customActionWorkflowVersion.value
    const payload: Record<string, unknown> = {
      name: customActionName.value.trim(),
      description: customActionDescription.value.trim(),
    }
    if (sourceVersion) {
      payload.workflow_id = sourceVersion.id
      payload.version = sourceVersion.version
      payload.inputs = Object.fromEntries((sourceVersion.inputs || []).map((input) => [input.name, input.default ?? `\${inputs.${input.name}}`]))
    } else if (selectedNode.value) {
      payload.action_id = selectedNode.value.action_id
      payload.config = { ...selectedNode.value.config, ...(selectedNode.value.input_mapping || {}) }
    }
    await desktopApi.createWorkflowCustomAction(payload)
    await loadCustomActions()
    showCustomActionDialog.value = false
    customActionWorkflowVersion.value = null
    runMessage.value = '已保存为自定义 Action，可从节点库重复使用。'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    customActionSaving.value = false
  }
}

async function deleteCustomAction(action: ActionItem): Promise<void> {
  const customId = action.preset?.customActionId
  if (!customId) return
  try {
    await desktopApi.deleteWorkflowCustomAction(customId)
    await loadCustomActions()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function loadCustomActions(): Promise<void> {
  const result = await desktopApi.workflowCustomActions()
  for (let index = actions.length - 1; index >= 0; index -= 1) {
    if (actions[index].preset) actions.splice(index, 1)
  }
  for (const raw of result.actions) {
    const item = raw as { id?: string; name?: string; description?: string; action_id?: string; config?: Record<string, unknown>; output_schema?: unknown }
    if (!item.id || !item.action_id || !item.config) continue
    actions.push({
      id: `custom:${item.id}`,
      label: item.name || '自定义 Action',
      hint: item.description || '可复用动作',
      tone: 'teal',
      category: actionCategory(item.action_id),
      outputFields: outputFieldsFromSchema(item.output_schema).length ? outputFieldsFromSchema(item.output_schema) : defaultOutputFields(item.action_id),
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
    for (const raw of catalog.actions) {
      const item = raw as { id?: string; name?: string; category?: string; output_schema?: unknown }
      if (!item.id) continue
      const fields = outputFieldsFromSchema(item.output_schema)
      const existing = actions.find((action) => action.id === item.id)
      if (existing) {
        existing.label = item.name || existing.label
        existing.category = actionCategory(item.id, item.category)
        existing.outputFields = fields.length ? fields : existing.outputFields
      }
      else {
        actions.push({
          id: item.id,
          label: item.name || item.id,
          hint: '工作流动作',
          tone: 'blue',
          category: actionCategory(item.id, item.category),
          outputFields: fields.length ? fields : defaultOutputFields(item.id)
        })
      }
    }
    actionsRevision.value += 1
    await loadCustomActions()
  } catch (cause) { error.value = String(cause) }
  await refresh()
  if (workflows.value[0]) selectWorkflow(workflows.value[0])
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
        <select v-model="taskGoal" class="task-goal" aria-label="任务目标"><option>检查设备状态</option><option>批量执行操作</option><option>采集设备信息</option><option>上传文件</option><option>验证配置</option><option>执行实验流程</option><option>自定义流程</option></select>
      </div>
      <span class="toolbar-divider" aria-hidden="true"></span>
      <div class="toolbar-group toolbar-group-secondary">
        <button type="button" @click="importWorkflow" :disabled="importing"><Braces :size="14" />导入</button>
        <button type="button" :disabled="!selected" @click="duplicateWorkflow"><Copy :size="14" />复制</button>
        <button type="button" :disabled="!selected" @click="saveCurrentAsTemplate"><Save :size="14" />保存为模板</button>
        <button type="button" class="icon-toolbar-button" :disabled="!workflowHistory.canUndo.value" @click="performUndo" title="撤销 (Ctrl+Z)" aria-label="撤销"><Undo :size="14" /></button>
        <button type="button" class="icon-toolbar-button" :disabled="!workflowHistory.canRedo.value" @click="performRedo" title="重做 (Ctrl+Shift+Z)" aria-label="重做"><Redo :size="14" /></button>
        <button type="button" :disabled="!selected || !selected.nodes || selected.nodes.length === 0" @click="applyAutoLayout" title="自动布局"><GitBranch :size="14" />自动布局</button>
      </div>
      <div class="toolbar-group toolbar-group-export">
        <button type="button" class="icon-toolbar-button" :disabled="!selected" @click="exportWorkflow('yaml')" title="导出 YAML" aria-label="导出 YAML"><Download :size="14" /></button>
        <button type="button" class="icon-toolbar-button" :disabled="!selected" @click="exportWorkflow('json')" title="导出 JSON" aria-label="导出 JSON"><Braces :size="14" /></button>
        <button type="button" class="icon-toolbar-button" :disabled="!selected" @click="copyAiPrompt" title="复制 AI 提示词" aria-label="复制 AI 提示词"><Copy :size="14" /></button>
      </div>
      <span class="toolbar-divider" aria-hidden="true"></span>
      <div class="toolbar-group toolbar-group-commit">
        <button type="button" :disabled="!canSave" @click="save"><Save :size="14" />{{ saving ? '保存中…' : '保存草稿' }}</button>
        <button type="button" :disabled="!selected" @click="validate"><CheckCircle2 :size="14" />检查流程</button>
      </div>
      <label class="workflow-run-target"><span>执行目标</span><select v-model="selectedDeviceIds" multiple aria-label="测试运行目标设备"><option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">{{ deviceLabel(device) }}</option></select></label>
      <div class="toolbar-group toolbar-group-actions">
        <button class="flow-test-action" type="button" :disabled="!canStartFlowTest" @click="testFlowInEditor"><Play :size="14" />{{ flowTestRunning ? '测试运行中…' : '测试运行' }}</button>
        <button class="run-action" type="button" :disabled="!canStartRun" @click="requestRunPreview"><Play :size="14" />{{ running ? '启动中…' : '执行预览' }}</button>
        <button class="secondary-run-button" type="button" :disabled="!canRun" @click="runDraft">测试草稿</button>
        <button class="primary-action" type="button" :disabled="!canPublish" @click="publish"><Play :size="14" />发布</button>
        <button class="danger-action" type="button" :disabled="!selected" @click="remove"><Trash2 :size="14" />删除</button>
      </div>
    </div>
    <div v-if="showCreateDialog" class="workflow-modal-backdrop" @click.self="showCreateDialog = false">
      <form class="workflow-import-dialog workflow-create-dialog" role="dialog" aria-modal="true" aria-label="新建流程" @submit.prevent="confirmCreate">
        <header><strong>新建流程</strong><button type="button" title="关闭" @click="showCreateDialog = false"><X :size="16" /></button></header>
        <label>开始方式<select :value="createTemplateId" @change="chooseCreateTemplate(($event.target as HTMLSelectElement).value)"><option value="">空白流程</option><option v-for="item in workflowTemplates" :key="item.id" :value="item.id">{{ item.name }}{{ item.built_in ? ' · 内置' : '' }}</option></select></label>
        <section v-if="workflowTemplates.some((item) => !item.built_in)" class="workflow-template-manager" aria-label="我的流程模板">
          <strong>我的模板</strong>
          <div v-for="item in workflowTemplates.filter((template) => !template.built_in)" :key="item.id">
            <span>{{ item.name }}</span>
            <button type="button" :disabled="Boolean(deletingTemplateId)" :title="`删除模板 ${item.name}`" :aria-label="`删除模板 ${item.name}`" @click="deleteWorkflowTemplate(item)"><Trash2 :size="13" /></button>
          </div>
        </section>
        <label>流程名称<input v-model="createName" autofocus maxlength="120" placeholder="例如：路由器版本检查" /></label>
        <label>流程说明<textarea v-model="createDescription" rows="3" placeholder="说明这个流程的用途（可选）" /></label>
        <footer><button type="button" @click="showCreateDialog = false">取消</button><button type="submit" class="primary-action" :disabled="!createName.trim() || creating">{{ creating ? '创建中…' : '创建流程' }}</button></footer>
      </form>
    </div>
    <div v-if="showScriptTemplateDialog" class="workflow-modal-backdrop" @click.self="showScriptTemplateDialog = false">
      <form class="workflow-import-dialog workflow-create-dialog workflow-script-template-dialog" role="dialog" aria-modal="true" aria-label="新建脚本" @submit.prevent="confirmCreateWorkflowScript">
        <header><strong>新建脚本</strong><button type="button" title="关闭" @click="showScriptTemplateDialog = false"><X :size="16" /></button></header>
        <label>脚本名称<input v-model="scriptCreateName" autofocus maxlength="120" placeholder="例如：检查设备状态" /></label>
        <label>脚本说明<textarea v-model="scriptCreateDescription" rows="2" maxlength="400" placeholder="可选，说明脚本用途" /></label>
        <section class="workflow-script-template-grid" aria-label="脚本模板">
          <button v-for="template in scriptTemplates" :key="template.id" type="button" class="workflow-script-template-card" :class="{ active: selectedScriptTemplateId === template.id }" @click="selectedScriptTemplateId = template.id">
            <span class="workflow-script-template-icon"><Code2 :size="15" /></span>
            <span><strong>{{ template.name }}</strong><small>{{ template.description }}</small><em>{{ template.language }}</em></span>
          </button>
        </section>
        <div class="workflow-script-template-preview"><span>预置内容</span><code>{{ selectedScriptTemplate.script ? `${selectedScriptTemplate.script.split('\n').slice(0, 3).join('\n')}${selectedScriptTemplate.script.split('\n').length > 3 ? '\n…' : ''}` : '空白脚本' }}</code></div>
        <footer><button type="button" @click="showScriptTemplateDialog = false">取消</button><button type="submit" class="primary-action" :disabled="scriptCreating || !scriptCreateName.trim()">{{ scriptCreating ? '创建中…' : '使用模板创建' }}</button></footer>
      </form>
    </div>
    <div v-if="showImportPreview" class="workflow-modal-backdrop" @click.self="showImportPreview = false">
      <section class="workflow-import-dialog" role="dialog" aria-modal="true" aria-label="导入 Workflow 预览">
        <header><strong>导入预览</strong><button type="button" title="关闭" @click="showImportPreview = false"><X :size="16" /></button></header>
        <p class="field-hint">{{ importFilename }} · 将作为新草稿导入</p>
        <div v-if="importPreview?.workflow" class="workflow-import-summary">
          <strong>{{ importPreview.workflow.name || '未命名流程' }}</strong>
          <span>{{ Array.isArray(importPreview.workflow.steps) ? importPreview.workflow.steps.length : (Array.isArray(importPreview.workflow.nodes) ? importPreview.workflow.nodes.length : 0) }} 个步骤</span>
        </div>
        <p v-for="issue in importPreview?.errors || []" :key="issue.message" class="workflow-error">{{ issue.message }}</p>
        <p v-for="warning in importPreview?.warnings || []" :key="warning.message" class="workflow-run-message">{{ warning.message }}</p>
        <footer><button type="button" @click="showImportPreview = false">取消</button><button type="button" class="primary-action" :disabled="importing || Boolean(importPreview?.errors?.length)" @click="confirmImport">确认导入</button></footer>
      </section>
    </div>
    <div v-if="showCustomActionDialog" class="workflow-modal-backdrop" @click.self="showCustomActionDialog = false">
      <form class="workflow-import-dialog workflow-create-dialog" role="dialog" aria-modal="true" aria-label="保存自定义 Action" @submit.prevent="saveCustomAction">
        <header><strong>保存自定义 Action</strong><button type="button" title="关闭" @click="showCustomActionDialog = false"><X :size="16" /></button></header>
        <label>名称<input v-model="customActionName" autofocus maxlength="80" placeholder="例如：检查设备版本" /></label>
        <label>说明<textarea v-model="customActionDescription" rows="3" maxlength="400" placeholder="可选，说明这个命令的用途" /></label>
        <footer><button type="button" @click="showCustomActionDialog = false">取消</button><button type="submit" class="primary-action" :disabled="customActionSaving || !customActionName.trim()">{{ customActionSaving ? '保存中…' : '保存' }}</button></footer>
      </form>
    </div>
    <p v-if="error" class="workflow-error">{{ error }}</p>
    <p v-if="runMessage" class="workflow-run-message">{{ runMessage }}</p><p v-if="hasBranching" class="workflow-branch-notice"><GitBranch :size="14" />包含条件分支：运行时只执行匹配条件的一侧。</p>
    <div v-if="studioMode === 'scripts'" class="workflow-script-studio">
      <aside class="workflow-script-list">
        <div class="workflow-list-title"><span>脚本资源</span><small>{{ scripts.length }} 个</small></div>
        <div class="workflow-script-list-actions"><button type="button" class="primary-action" @click="createWorkflowScript"><Plus :size="13" />新建脚本</button><button type="button" class="icon-toolbar-button" :disabled="!selectedScript" title="复制脚本" aria-label="复制脚本" @click="duplicateWorkflowScript"><Copy :size="13" /></button></div>
        <button v-for="script in scripts" :key="script.id" type="button" class="workflow-script-list-item" :class="{ active: script.id === selectedScriptId }" @click="selectedScriptId = script.id">
          <span class="workflow-script-list-dot" :data-language="script.language"></span><span><strong>{{ script.name }}</strong><small>{{ script.language }} · {{ scriptSnapshot(script) !== savedScriptSnapshots[script.id] ? '未保存' : (script.updated_at ? new Date(script.updated_at).toLocaleDateString() : '未保存') }}</small></span>
        </button>
        <p v-if="!scripts.length" class="workflow-empty-list">还没有脚本<br /><span>新建后可单独编辑和测试</span></p>
      </aside>
      <main v-if="selectedScript" class="workflow-script-workspace">
        <section class="workflow-script-editor-panel">
          <header class="workflow-script-resource-header"><div><span class="workflow-section-kicker">脚本资源</span><input v-model="selectedScript.name" aria-label="脚本名称" maxlength="120" placeholder="输入脚本名称" /><small>{{ selectedScript.id }}<template v-if="hasUnsavedScriptChanges"> · 未保存</template></small><span v-if="scriptValidationMessage" class="workflow-script-validation">{{ scriptValidationMessage }}</span></div><div class="workflow-script-resource-actions"><button type="button" :disabled="scriptSaving || !hasUnsavedScriptChanges || Boolean(scriptValidationMessage)" @click="saveWorkflowScript"><Save :size="14" />{{ scriptSaving ? '保存中…' : '保存' }}</button><button type="button" class="icon-toolbar-button" title="删除脚本" aria-label="删除脚本" @click="deleteWorkflowScript"><Trash2 :size="14" /></button></div></header>
          <WorkflowScriptEditor v-model="selectedScript.script" :language="selectedScript.language" placeholder="输入脚本内容…" aria-label="独立脚本编辑器" />
          <section v-if="scriptTestResult" class="workflow-script-run-log" aria-label="脚本运行日志">
            <header><div><strong>运行日志</strong><small>{{ scriptTestResult.message || (scriptTesting ? '正在执行脚本…' : '测试完成') }}</small></div><code v-if="scriptTestResult.task?.id" :title="scriptTestResult.task.id">{{ scriptTestResult.task.id }}</code></header>
            <div v-if="scriptTestDetails" class="workflow-script-test-summary"><span>状态</span><b>{{ scriptTestDetails.status }}</b><span>退出码</span><b>{{ scriptTestDetails.exitCode !== '' ? scriptTestDetails.exitCode : '—' }}</b></div>
            <section v-if="scriptTestDetails?.stdout"><span>stdout</span><pre>{{ scriptTestDetails.stdout }}</pre></section>
            <section v-if="scriptTestDetails?.stderr"><span>stderr</span><pre>{{ scriptTestDetails.stderr }}</pre></section>
          </section>
        </section>
        <aside class="workflow-script-test-panel">
          <section class="workflow-script-config-section" aria-label="脚本配置">
            <div class="workflow-script-side-heading"><div><strong>配置</strong><small>脚本语言、说明和输入参数</small></div></div>
            <div class="workflow-script-resource-meta"><label>语言<select v-model="selectedScript.language"><option value="python">Python</option><option value="powershell">PowerShell</option><option value="bash">Bash</option></select></label><label>说明<input v-model="selectedScript.description" placeholder="脚本用途说明" /></label></div>
            <section class="workflow-script-parameters" aria-label="脚本输入参数">
              <header><div><strong>输入参数</strong><small v-if="selectedScript.entrypoint">由 {{ selectedScript.entrypoint }} 函数签名自动识别；保存脚本后会刷新</small><small v-else>脚本通过 DEVICE_TUI_INPUT_JSON 读取，测试时可直接填入参数</small></div><button v-if="!selectedScript.entrypoint" type="button" class="icon-toolbar-button" title="新增输入参数" aria-label="新增输入参数" @click="addScriptInput"><Plus :size="13" /></button></header>
              <p v-if="selectedScript.input_schema_error" class="workflow-script-validation">{{ selectedScript.input_schema_error }}；当前保留已有参数定义</p>
              <div v-if="selectedScript.input_schema.length" class="workflow-script-parameter-list">
                <article v-for="(parameter, index) in selectedScript.input_schema" :key="`${selectedScript.id}-${index}`" class="workflow-script-parameter-row">
                  <div class="workflow-script-parameter-main"><input :value="parameter.name" :disabled="Boolean(selectedScript.entrypoint)" aria-label="参数名" placeholder="参数名" @input="updateScriptInputField(index, 'name', eventValue($event))" /><select :value="parameter.type" :disabled="Boolean(selectedScript.entrypoint)" aria-label="参数类型" @change="updateScriptInputField(index, 'type', eventValue($event))"><option v-for="type in scriptInputTypes" :key="type" :value="type">{{ type }}</option></select><label class="workflow-script-required"><input :checked="Boolean(parameter.required)" :disabled="Boolean(selectedScript.entrypoint)" type="checkbox" @change="updateScriptInputField(index, 'required', eventChecked($event))" />必填</label><button v-if="!selectedScript.entrypoint" type="button" class="icon-toolbar-button" title="删除参数" :aria-label="`删除参数 ${parameter.name}`" @click="removeScriptInput(index)"><Trash2 :size="13" /></button></div>
                  <div class="workflow-script-parameter-details"><input :value="parameter.description || ''" :disabled="Boolean(selectedScript.entrypoint)" aria-label="参数说明" placeholder="参数说明（可选）" @input="updateScriptInputField(index, 'description', eventValue($event))" /><input v-if="parameter.type === 'string'" :value="scriptDefaultText(parameter)" :disabled="Boolean(selectedScript.entrypoint)" aria-label="默认值" placeholder="默认值（可选）" @input="updateScriptDefault(index, $event)" /><input v-else-if="parameter.type === 'number'" :value="scriptDefaultText(parameter)" :disabled="Boolean(selectedScript.entrypoint)" type="number" aria-label="默认值" placeholder="默认值" @input="updateScriptDefault(index, $event)" /><input v-else-if="parameter.type === 'boolean'" :checked="parameter.default === true" :disabled="Boolean(selectedScript.entrypoint)" type="checkbox" aria-label="默认值" @change="updateScriptDefault(index, $event)" /><input v-else :value="scriptDefaultText(parameter)" :disabled="Boolean(selectedScript.entrypoint)" aria-label="默认 JSON 值" placeholder="默认 JSON 值，例如 {} 或 []" @input="updateScriptDefault(index, $event)" /></div>
                </article>
              </div>
              <p v-else class="workflow-script-parameters-empty">暂无参数。新增参数后，独立测试会自动生成对应输入控件。</p>
            </section>
          </section>
          <section class="workflow-script-test-section" aria-label="脚本测试">
            <div class="workflow-script-side-heading"><div><strong>测试</strong><small>有修改时会先自动保存，再通过后端任务执行</small></div><span class="workflow-risk-chip"><AlertTriangle :size="12" />高风险</span></div>
            <label>目标设备<select v-model="selectedDeviceId"><option value="">选择设备</option><option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">{{ deviceLabel(device) }}</option></select></label>
            <div class="workflow-script-test-mode" role="tablist" aria-label="测试输入模式"><button type="button" :class="{ active: scriptTestMode === 'form' }" @click="scriptTestMode = 'form'">参数表单</button><button type="button" :class="{ active: scriptTestMode === 'json' }" @click="scriptTestMode = 'json'">JSON</button></div>
            <div v-if="scriptTestMode === 'form'" class="workflow-script-test-form">
              <div v-if="selectedScript.input_schema.length" v-for="parameter in selectedScript.input_schema" :key="`test-${parameter.name}`" class="workflow-script-test-field"><label :for="`script-test-${parameter.name}`">{{ parameter.name }}<span v-if="parameter.required">必填</span></label><small v-if="parameter.description">{{ parameter.description }}</small><input v-if="parameter.type === 'string'" :id="`script-test-${parameter.name}`" :value="scriptTestValueText(parameter)" :placeholder="parameter.required ? '请输入' : '留空表示不传入'" @input="updateScriptTestValue(parameter.name, eventValue($event))" /><input v-else-if="parameter.type === 'number'" :id="`script-test-${parameter.name}`" type="number" :value="scriptTestValueText(parameter)" placeholder="数字" @input="updateScriptTestValue(parameter.name, eventValue($event))" /><label v-else-if="parameter.type === 'boolean'" class="workflow-inline-toggle"><input :id="`script-test-${parameter.name}`" type="checkbox" :checked="scriptTestValues[parameter.name] === true" @change="updateScriptTestValue(parameter.name, eventChecked($event))" />启用</label><textarea v-else :id="`script-test-${parameter.name}`" rows="3" :value="scriptTestValueText(parameter)" :placeholder="parameter.type === 'array' ? '例如：[1, 2]' : '例如：{}'" @input="updateScriptTestValue(parameter.name, eventValue($event))" /></div>
              <p v-else class="workflow-script-parameters-empty">此脚本没有定义输入参数。</p>
            </div>
            <label v-else>输入 JSON<textarea v-model="scriptTestInputs" rows="8" placeholder='例如：{"mode":"check"}' /></label>
            <p v-if="scriptTestInputError" class="workflow-error">{{ scriptTestInputError }}</p>
            <label class="workflow-inline-toggle"><input v-model="scriptTestConfirmed" type="checkbox" />我已确认脚本将在后端主机执行</label>
            <button type="button" class="primary-action workflow-script-test-button" :disabled="scriptTesting || scriptSaving || !selectedDeviceId || !scriptTestConfirmed || Boolean(scriptValidationMessage)" @click="testWorkflowScript"><Play :size="14" />{{ scriptTesting ? '测试运行中…' : (hasUnsavedScriptChanges ? '保存并测试' : '测试脚本') }}</button>
            <p class="field-hint">测试会创建临时 Workflow 任务，不会修改当前 Flow。</p>
          </section>
        </aside>
      </main>
      <main v-else class="workflow-empty workflow-script-no-selection">选择或新建一个脚本</main>
    </div>
    <div v-else class="workflow-library-body">
      <aside class="workflow-list-pane">
        <div class="workflow-list-title"><span>我的流程</span><small>{{ workflows.length }} 个</small></div>
        <button v-for="item in workflows" :key="item.id" type="button" :class="{ active: selected?.id === item.id }" @click="selectWorkflow(item)">
          <strong>{{ item.name }}</strong><small>{{ item.description || '暂无描述' }}</small><em>v{{ item.version || '草稿' }}</em>
        </button>
        <p v-if="!loading && !workflows.length" class="workflow-empty-list">还没有流程<br /><span>点击“新建流程”开始</span></p>
        <section v-if="selected" class="workflow-version-manager" aria-label="发布版本管理">
          <div class="workflow-version-heading"><strong>发布版本</strong><small>{{ publishedVersions.length }} 个</small></div>
          <p v-if="versionsLoading" class="workflow-version-empty">加载版本中…</p>
          <p v-else-if="versionError" class="workflow-version-error">{{ versionError }}</p>
          <p v-else-if="!publishedVersions.length" class="workflow-version-empty">尚未发布版本</p>
          <div v-else class="workflow-version-list">
            <div v-for="version in publishedVersions" :key="`${version.id}-${version.version}`" class="workflow-version-row" :class="{ referenced: version.referenced }">
              <div class="workflow-version-info">
                <strong>v{{ version.version }}</strong>
                <small>{{ version.published_at ? new Date(version.published_at).toLocaleString() : '发布时间未知' }}</small>
                <span>{{ version.referenced ? '已被任务引用' : '未被引用，可删除' }}</span>
              </div>
              <div class="workflow-version-actions">
                <button type="button" class="icon-toolbar-button" title="运行此发布版本" :aria-label="`运行发布版本 v${version.version}`" @click.stop="emit('run-version', { workflowId: version.id, version: version.version })"><Play :size="13" /></button>
                <button type="button" class="icon-toolbar-button" title="导出此发布版本 YAML" :aria-label="`导出发布版本 v${version.version}`" @click.stop="exportPublishedVersion(version)"><Download :size="13" /></button>
                <button type="button" class="icon-toolbar-button" title="恢复为当前草稿" :aria-label="`恢复发布版本 v${version.version} 为草稿`" @click.stop="restorePublishedVersion(version)"><RotateCcw :size="13" /></button>
                <button type="button" class="icon-toolbar-button" title="保存为自定义 Action" :aria-label="`将发布版本 v${version.version} 保存为自定义 Action`" @click.stop="openWorkflowCustomActionDialog(version)"><Save :size="13" /></button>
                <button type="button" class="icon-toolbar-button workflow-version-delete" :disabled="version.referenced" :title="version.referenced ? '已被任务引用，不能删除' : '删除此发布版本'" :aria-label="version.referenced ? '已被任务引用，不能删除' : `删除发布版本 v${version.version}`" @click.stop="removePublishedVersion(version)"><Trash2 :size="13" /></button>
              </div>
            </div>
          </div>
        </section>
      </aside>
      <main v-if="selected" class="workflow-studio-grid" :class="{ 'flow-test-mode': flowTestOpen, 'step-settings-mode': rightRailMode === 'step' }" :style="{ '--workflow-catalog-width': `${workflowCatalogWidth}px`, '--workflow-properties-width': flowTestOpen ? 'min(46vw, 760px)' : `${workflowPropertiesWidth}px` }">
        <aside class="workflow-right-rail">
        <section v-if="flowTestOpen" class="workflow-flow-test-panel" aria-label="Flow 测试运行">
          <header class="workflow-flow-test-header">
            <div><span class="workflow-section-kicker">FLOW TEST</span><strong>测试运行</strong><small>{{ selected.name }}</small></div>
            <button type="button" class="icon-toolbar-button" title="返回步骤设置" aria-label="返回步骤设置" @click="closeFlowTestPanel"><X :size="14" /></button>
          </header>
          <div class="workflow-flow-test-status" :class="`status-${flowTestStatus.tone}`"><span class="workflow-flow-test-dot"></span><strong>{{ flowTestStatus.label }}</strong><small v-if="flowTestTask?.progress_percent != null">{{ Math.round(flowTestTask.progress_percent) }}%</small></div>
          <div v-if="flowTestCurrentStep" class="workflow-flow-test-current"><span>{{ flowTestTaskTerminal ? '最后执行步骤' : '当前步骤' }}</span><strong>{{ flowTestCurrentStep }}</strong></div>
          <p v-if="flowTestError" class="workflow-error workflow-flow-test-error">{{ flowTestError }}</p>
          <section class="workflow-flow-test-section workflow-test-data-section" aria-label="本次输入">
            <div class="workflow-flow-test-section-title"><strong>本次输入</strong><small>{{ flowTestInputEntries.length }} 个参数</small></div>
            <dl v-if="flowTestInputEntries.length" class="workflow-test-value-list"><div v-for="item in flowTestInputEntries" :key="item.name"><dt>{{ item.name }}<small>{{ item.type }}</small></dt><dd>{{ typeof item.value === 'object' ? JSON.stringify(item.value, null, 2) : String(item.value) }}</dd></div></dl>
            <p v-else class="workflow-test-empty">此流程没有定义输入参数。</p>
          </section>
          <section class="workflow-flow-test-section workflow-test-process-section"><div class="workflow-flow-test-section-title"><strong>执行过程</strong><small>{{ flowTestStepLogs.length }} 个步骤 · 展开查看详情</small></div><ol v-if="flowTestStepLogs.length" class="workflow-flow-test-log"><li v-for="item in flowTestStepLogs" :key="item.id" :class="`log-${item.status}`"><span class="workflow-flow-test-log-mark"></span><div class="workflow-flow-test-log-content"><button type="button" class="workflow-flow-step-toggle" :aria-expanded="expandedFlowTestStepIds.includes(item.id)" @click="toggleFlowTestStep(item.id)"><span class="workflow-flow-step-heading"><span class="workflow-flow-step-id">{{ item.id }}</span><strong class="workflow-flow-step-title">{{ item.label }}</strong></span><span class="workflow-flow-step-status">{{ flowTestStepStatusLabel(item.status) }}</span><ChevronDown :size="14" class="workflow-flow-step-chevron" :class="{ expanded: expandedFlowTestStepIds.includes(item.id) }" /></button><small v-if="item.status === 'pending'">等待任务调度</small><div v-if="expandedFlowTestStepIds.includes(item.id)" class="workflow-flow-step-details"><div v-if="item.command" class="workflow-flow-command"><span>执行命令</span><code>{{ item.command }}</code></div><div v-if="item.script" class="workflow-flow-command"><span>{{ item.script }}</span></div><div v-if="item.exitCode !== undefined || item.resultStatus" class="workflow-flow-step-metrics"><span v-if="item.resultStatus">状态 <b>{{ item.resultStatus }}</b></span><span v-if="item.exitCode !== undefined">退出码 <b>{{ item.exitCode }}</b></span></div><section v-if="item.stdout" class="workflow-flow-terminal-output"><header><span>标准输出</span></header><pre>{{ flowTestOutputText(item.stdout) }}</pre></section><section v-if="item.stderr" class="workflow-flow-terminal-output is-error"><header><span>错误输出</span></header><pre>{{ flowTestOutputText(item.stderr) }}</pre></section><section v-if="item.dataText" class="workflow-flow-terminal-output"><header><span>执行结果</span></header><pre>{{ item.dataText }}</pre></section><section v-if="item.output && !item.stdout && !item.dataText" class="workflow-flow-terminal-output"><header><span>执行输出</span></header><pre>{{ flowTestOutputText(item.output) }}</pre></section><p v-if="item.error && !item.stderr" class="workflow-flow-step-error">{{ item.error }}</p><small v-if="!item.stdout && !item.stderr && !item.dataText && !item.output && !item.error" class="workflow-flow-no-output">此步骤没有返回输出</small></div></div></li></ol><p v-else class="workflow-test-empty">测试开始后会逐步显示各步骤的状态与输出。</p></section>
          <section class="workflow-flow-test-section workflow-test-data-section workflow-test-outputs" aria-label="流程输出">
            <div class="workflow-flow-test-section-title"><strong>流程输出</strong><small>{{ flowTestOutputEntries.length }} 项</small></div>
            <dl v-if="flowTestOutputEntries.length" class="workflow-test-value-list"><div v-for="item in flowTestOutputEntries" :key="item.name"><dt>{{ item.name }}<small>{{ item.type }}</small></dt><dd>{{ typeof item.value === 'object' ? JSON.stringify(item.value, null, 2) : String(item.value) }}</dd></div></dl>
            <p v-else class="workflow-test-empty">{{ flowTestTaskTerminal ? '本次运行没有产生流程输出。' : '运行完成后，定义的输出会显示在这里。' }}</p>
          </section>
          <button v-if="flowTestTask && !flowTestRunning" type="button" class="connect-button workflow-flow-test-retry" @click="flowTestTaskTerminal ? testFlowInEditor() : resumeFlowTestMonitoring()"><Play :size="13" />{{ flowTestTaskTerminal ? '重新测试' : '继续监控' }}</button>
        </section>
        <template v-if="!flowTestOpen">
        <nav class="workflow-right-rail-switcher" aria-label="配置视图">
          <button type="button" :class="{ active: rightRailMode === 'workflow' }" @click="showWorkflowSettings"><Workflow :size="13" />流程设置</button>
          <button type="button" :disabled="!selectedNode" :class="{ active: rightRailMode === 'step' }" @click="showStepSettings()"><Braces :size="13" />步骤配置</button>
        </nav>
        <template v-if="rightRailMode === 'workflow'">
        <section class="workflow-metadata-editor" aria-label="流程基本信息">
          <div class="workflow-contract-heading"><span class="workflow-section-kicker">当前流程</span><strong>{{ selected.name || '未命名流程' }}</strong><span class="workflow-contract-status" :class="{ dirty: hasUnsavedChanges }">{{ hasUnsavedChanges ? '草稿有修改' : '已保存' }}</span></div>
          <label>流程名称<input v-model="selected.name" maxlength="120" placeholder="请输入流程名称" /></label>
          <label>流程说明<input v-model="selected.description" maxlength="500" placeholder="说明这个流程的用途（可选）" /></label>
          <small v-if="!selected.name.trim()">流程名称不能为空</small>
        </section>
        <section class="workflow-input-editor workflow-input-compact" :class="{ expanded: workflowInputsExpanded }" aria-label="流程输入定义">
          <div class="panel-heading"><button type="button" class="workflow-section-toggle" :aria-expanded="workflowInputsExpanded" @click="workflowInputsExpanded = !workflowInputsExpanded"><strong>流程输入</strong><small>{{ selected.inputs?.length || 0 }} 个参数</small><span>{{ workflowInputsExpanded ? '收起' : '展开' }}</span></button><button type="button" class="icon-toolbar-button" title="添加流程输入" aria-label="添加流程输入" @click="addWorkflowInput(); workflowInputsExpanded = true"><Plus :size="14" /></button></div>
          <div v-if="workflowInputsExpanded && selected.inputs?.length" class="workflow-input-definitions">
            <div v-for="(input, index) in selected.inputs" :key="`${index}-${input.name}`" class="workflow-input-definition">
              <label>名称<input :value="input.name" placeholder="例如：package_path" @input="updateWorkflowInputDefinition(index, 'name', ($event.target as HTMLInputElement).value)" /></label>
              <label>类型<select :value="input.type || 'string'" @change="updateWorkflowInputDefinition(index, 'type', ($event.target as HTMLSelectElement).value)"><option value="string">文本</option><option value="file">本地文件</option><option value="number">数字</option><option value="integer">整数</option><option value="boolean">布尔值</option><option value="array">数组</option><option value="object">对象</option></select></label>
              <label class="workflow-input-required"><input type="checkbox" :checked="input.required === true" @change="updateWorkflowInputDefinition(index, 'required', ($event.target as HTMLInputElement).checked)" />必填</label>
              <label>默认值<input :value="input.default == null ? '' : String(input.default)" placeholder="可选" @input="updateWorkflowInputDefinition(index, 'default', ($event.target as HTMLInputElement).value)" /></label>
              <label class="workflow-input-description">说明<input :value="input.description || ''" placeholder="给执行者的提示" @input="updateWorkflowInputDefinition(index, 'description', ($event.target as HTMLInputElement).value)" /></label>
              <button type="button" class="icon-toolbar-button workflow-input-delete" title="删除流程输入" aria-label="删除流程输入" @click="removeWorkflowInput(index)"><Trash2 :size="14" /></button>
            </div>
          </div>
          <p v-else-if="workflowInputsExpanded" class="field-hint">尚未定义输入。点击右上角加号后，执行时会出现运行参数。</p>
        </section>
        <section class="workflow-input-editor workflow-output-editor workflow-input-compact" :class="{ expanded: workflowOutputsExpanded }" aria-label="流程输出定义">
          <div class="panel-heading"><button type="button" class="workflow-section-toggle" :aria-expanded="workflowOutputsExpanded" @click="workflowOutputsExpanded = !workflowOutputsExpanded"><strong>流程输出</strong><small>{{ selected.outputs?.length || 0 }} 个结果</small><span>{{ workflowOutputsExpanded ? '收起' : '展开' }}</span></button><button type="button" class="icon-toolbar-button" title="添加流程输出" aria-label="添加流程输出" @click="addWorkflowOutput(); workflowOutputsExpanded = true"><Plus :size="14" /></button></div>
          <div v-if="workflowOutputsExpanded && selected.outputs?.length" class="workflow-input-definitions">
            <div v-for="(output, index) in selected.outputs" :key="`${index}-${output.name}`" class="workflow-input-definition workflow-output-definition">
              <label>名称<input :value="output.name" placeholder="例如：software_version" @input="updateWorkflowOutput(index, 'name', ($event.target as HTMLInputElement).value)" /></label>
              <label>类型<select :value="output.type || 'any'" @change="updateWorkflowOutput(index, 'type', ($event.target as HTMLSelectElement).value)"><option value="any">任意</option><option value="string">文本</option><option value="number">数字</option><option value="integer">整数</option><option value="boolean">布尔值</option><option value="array">数组</option><option value="object">对象</option></select></label>
              <label class="workflow-output-value">值或引用<input :value="String(output.value ?? '')" placeholder="例如：${probe.software_version}" @input="updateWorkflowOutput(index, 'value', ($event.target as HTMLInputElement).value)" /></label>
              <label class="workflow-input-description">说明<input :value="output.description || ''" placeholder="供调用者理解此输出" @input="updateWorkflowOutput(index, 'description', ($event.target as HTMLInputElement).value)" /></label>
              <button type="button" class="icon-toolbar-button workflow-input-delete" title="删除流程输出" aria-label="删除流程输出" @click="removeWorkflowOutput(index)"><Trash2 :size="14" /></button>
            </div>
          </div>
          <p v-else-if="workflowOutputsExpanded" class="field-hint">尚未定义输出。发布后作为子流程使用时，显式输出会出现在调用节点上。</p>
        </section>
        <section v-if="selected.inputs?.length" class="workflow-runtime-inputs workflow-input-compact" :class="{ expanded: workflowRuntimeInputsExpanded }" aria-label="运行参数">
          <div class="panel-heading"><button type="button" class="workflow-section-toggle" :aria-expanded="workflowRuntimeInputsExpanded" @click="workflowRuntimeInputsExpanded = !workflowRuntimeInputsExpanded"><strong>运行参数</strong><small>{{ selected.inputs.length }} 个参数</small><span>{{ workflowRuntimeInputsExpanded ? '收起' : '展开' }}</span></button></div>
          <div v-if="workflowRuntimeInputsExpanded" class="workflow-input-values">
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
              <div v-else class="workflow-runtime-input-row">
                <input
                  :data-workflow-input-name="input.name"
                  :type="input.type === 'boolean' ? 'checkbox' : input.type === 'number' || input.type === 'integer' ? 'number' : 'text'"
                  :step="input.type === 'integer' ? '1' : 'any'"
                  :checked="input.type === 'boolean' ? workflowInputValues[input.name] === true : undefined"
                  :value="input.type === 'boolean' ? undefined : workflowInputDisplay(input)"
                  :placeholder="isWorkflowFileInput(input) ? '选择本机文件，或填写路径' : input.default === undefined || input.default === null ? `请输入${input.name}` : ''"
                  @input="updateWorkflowInput(input.name, $event)"
                  @change="updateWorkflowInput(input.name, $event)"
                />
                <button v-if="isWorkflowFileInput(input)" type="button" class="workflow-file-button" @click="chooseWorkflowRuntimeFile(input)"><FileUp :size="14" />选择文件</button>
              </div>
              <small v-if="isWorkflowFileInput(input)" class="field-hint workflow-shared-root-hint">
                这是本机源文件输入；执行上传时会自动暂存到共享目录，用户无需关心暂存目录，不要把设备目标路径填在这里。
                <button v-if="!workspace.transferSettings?.root" type="button" class="text-button" @click="workspace.transferPanelOpen = true">打开设置</button>
              </small>
            </label>
          </div>
        </section>
        </template>
        </template>
        </aside>
        <section class="workflow-action-catalog">
          <div class="panel-heading"><div><strong>节点库</strong><small>拖入画布或点击添加</small></div><span class="catalog-count">{{ filteredActions.length }}</span></div>
          <label class="workflow-search"><Search :size="13" /><input v-model="searchQuery" placeholder="搜索动作" aria-label="搜索动作" /></label>
          <div v-for="group in groupedActions" :key="group.category" class="action-category-group">
            <div class="action-category-heading"><span>{{ group.label }}</span><small>{{ group.actions.length }}</small></div>
            <button v-for="action in group.actions" :key="action.id" type="button" draggable="true" :class="`action-tile tone-${action.tone}`" @dragstart="startActionDrag($event, action.id)" @click="addNode(action.id)"><span class="action-icon"><Plus :size="12" /></span><span><b>{{ action.label }}</b><small>{{ action.hint }}</small></span><Trash2 v-if="action.preset" :size="12" class="custom-action-delete" title="删除自定义 Action" @click.stop="deleteCustomAction(action)" /></button>
          </div>
          <p v-if="!filteredActions.length" class="catalog-empty">没有匹配的动作</p>
          <p class="node-library-hint">拖动节点到画布创建步骤；点击节点端口可以重新组织流程。</p>
        </section>
        <div
          class="workflow-catalog-resizer"
          :class="{ active: resizingWorkflowCatalog }"
          role="separator"
          aria-orientation="vertical"
          aria-label="调整节点库宽度"
          title="拖动调整节点库宽度"
          @pointerdown="startWorkflowCatalogResize"
        ><GripVertical :size="14" /></div>
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
              <span class="canvas-toolbar-hint">左键拖动节点 · 中键平移 · 从端口拉线</span>
            </div>
          </div>
          <div class="workflow-canvas-container">
            <WorkflowCanvas
              :workflow="selected"
              :issues="issues"
              :interactive="canvasInteractive"
              @node-select="showStepSettings"
              @connect="({ source, target, sourceHandle }) => addEdge(source, target, sourceHandle)"
              @node-add="addNode"
              @disconnect="(edgeId) => { const edge = (selected?.edges || []).find((item) => `${item.source}-${item.source_handle || 'default'}-${item.target}` === edgeId); if (edge && selected) selected.edges = (selected.edges || []).filter((item) => item !== edge) }"
              @node-position-change="handleNodePositionChange"
            />
          </div>
        </section>
        <div
          class="workflow-properties-resizer"
          :class="{ active: resizingWorkflowProperties }"
          role="separator"
          aria-orientation="vertical"
          aria-label="调整配置栏宽度"
          title="拖动调整配置栏宽度"
          @pointerdown="startWorkflowPropertiesResize"
        ><GripVertical :size="14" /></div>
        <section v-if="selectedNode && !flowTestOpen && rightRailMode === 'step'" class="workflow-properties" aria-label="步骤设置">
          <div class="panel-heading"><div><strong>{{ selectedNode.action_id === 'variable.set' ? '设置变量' : '步骤设置' }}</strong><small v-if="selectedNode.action_id !== 'variable.set'">{{ selectedAction?.label }}</small></div><span class="properties-node-index">{{ selectedNode.id }}</span></div>
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
            <label>运行位置<select v-model="selectedNode.config.execution_mode"><option value="device">设备终端 / SSH</option><option value="shell">本机 Shell</option><option value="bash">Bash</option></select></label>
            <div class="workflow-command-label-row"><span>要执行的命令</span><button class="workflow-command-insert" type="button" :aria-expanded="showCommandReferenceMenu" title="在光标位置插入变量" @mousedown.prevent @click="showCommandReferenceMenu = !showCommandReferenceMenu"><Braces :size="13" />插入变量</button></div>
            <textarea ref="commandEditor" :value="configString('command')" rows="3" placeholder="例如：display version" @input="updateConfigString('command', $event)" />
            <div v-if="showCommandReferenceMenu" class="workflow-command-reference-menu" role="menu" aria-label="选择要插入的变量">
              <small class="workflow-command-reference-title">选择引用，插入到当前光标位置</small>
              <button v-for="item in commandReferences" :key="item.reference" type="button" role="menuitem" @mousedown.prevent @click="insertCommandReference(item.reference)"><span><strong>{{ item.label }}</strong><small>{{ item.hint }}</small></span><code>${{ '{' }}{{ item.reference }}{{ '}' }}</code></button>
              <small v-if="!commandReferences.length" class="workflow-command-reference-empty">暂无可用变量；请先连接上游步骤或定义流程输入。</small>
            </div>
            <div class="workflow-command-preview" :class="{ 'is-runtime': commandPreview.runtimeOnly }"><span>实际命令预览</span><code>{{ commandPreview.text }}</code><small>{{ commandPreview.runtimeOnly ? '运行时解析' : '当前值已解析' }}</small></div>
            <label>超时时间（秒）<input v-model.number="selectedNode.config.timeout_seconds" type="number" min="1" max="86400" /></label>
            <div class="workflow-command-grid" v-if="selectedNode.config.execution_mode !== 'device'"><label>工作目录<input :value="configString('cwd')" placeholder="可选，例如 D:/scripts" @input="updateConfigString('cwd', $event)" /></label><label>环境变量 JSON<textarea :value="JSON.stringify(selectedNode.config.env || {})" rows="2" placeholder="可选，例如 {&quot;MODE&quot;:&quot;prod&quot;}" @change="updateConfigJson('env', $event)" /></label></div>
            <div class="workflow-command-result-contract"><span>输出</span><code>stdout</code><code>stderr</code><code>exitCode</code><code>status</code><code>duration</code></div>
            <button type="button" class="connect-button" @click="openCustomActionDialog"><Save :size="13" />保存为自定义 Action</button>
            <small class="field-hint">可直接输入文本，也可用“插入变量”生成 `${变量名}`。</small>
          </div>
          <div v-if="selectedNode.action_id === 'script.run'" class="workflow-script-field">
            <div class="workflow-script-heading">
              <div><strong>本机脚本</strong><small>在后端主机执行，不会在设备终端运行</small></div>
              <span class="workflow-risk-chip"><AlertTriangle :size="12" />高风险</span>
            </div>
            <label>脚本资源<select :value="String(selectedNode.config.script_id || '')" @change="selectScriptForNode(($event.target as HTMLSelectElement).value)"><option value="">兼容模式：使用节点内联脚本</option><option v-for="script in scripts" :key="script.id" :value="script.id">{{ script.name }} · {{ script.language }}</option></select></label>
            <label v-if="!selectedNode.config.script_id">脚本语言<select v-model="selectedNode.config.language"><option value="python">Python</option><option value="powershell">PowerShell</option><option value="bash">Bash</option></select></label>
            <div v-if="selectedNode.config.script_id" class="workflow-script-reference-notice">
              <span><Code2 :size="14" />引用脚本资源</span>
              <strong>{{ selectedNodeScript?.name || selectedNode.config.script_id }}</strong>
              <small>参数名和类型由脚本函数签名决定；修改脚本代码后需单独保存脚本资源。</small>
              <div class="workflow-script-resource-actions-inline">
                <button type="button" class="secondary-button" @click="openScriptStudio(String(selectedNode.config.script_id))"><Code2 :size="13" />打开脚本工作区</button>
                <button v-if="selectedNodeScript && scriptSnapshot(selectedNodeScript) !== savedScriptSnapshots[selectedNodeScript.id]" type="button" class="primary-action" :disabled="scriptSaving" @click="saveNodeScriptResource"><Save :size="13" />{{ scriptSaving ? '保存中…' : '保存脚本' }}</button>
              </div>
            </div>
            <WorkflowScriptEditor
              :model-value="selectedNodeScript?.script || configString('script')"
              :language="String(selectedNode.config.language || selectedNodeScript?.language || 'python')"
              :placeholder="scriptPlaceholder"
              aria-label="步骤脚本编辑器"
              @update:model-value="(value) => { if (selectedNode) { selectedNode.config.script = value; if (selectedNode.config.script_id) { const script = scripts.find((item) => item.id === selectedNode?.config.script_id); if (script) script.script = value } } }"
            />
            <small class="field-hint">脚本在后端主机执行；引用资源时，编辑内容会同步到对应脚本资源。</small>
            <div v-if="selectedNodeScript?.input_schema?.length" class="workflow-script-node-inputs">
              <div class="workflow-script-node-input-heading">
                <div><strong>脚本输入</strong><small>按脚本定义配置参数</small></div>
                <div class="workflow-script-test-mode" role="tablist" aria-label="脚本输入模式">
                  <button type="button" :class="{ active: scriptNodeInputMode === 'form' }" @click="scriptNodeInputMode = 'form'">参数表单</button>
                  <button type="button" :class="{ active: scriptNodeInputMode === 'json' }" @click="scriptNodeInputMode = 'json'"><Braces :size="13" />JSON</button>
                </div>
              </div>
              <div v-if="scriptNodeInputMode === 'form'" class="workflow-script-node-input-form">
                <div v-for="parameter in selectedNodeScript.input_schema" :key="`node-input-${parameter.name}`" class="workflow-script-node-input-field">
                  <label :for="`node-input-${parameter.name}`"><span>{{ parameter.name }}</span><em v-if="parameter.required">必填</em></label>
                  <template v-if="parameter.type === 'string' || parameter.type === 'number'">
                  <input
                    :id="`node-input-${parameter.name}`"
                    type="text"
                    :inputmode="parameter.type === 'number' ? 'decimal' : 'text'"
                    :value="scriptNodeInputText(parameter)"
                    :placeholder="parameter.required ? '必填值或 ${inputs.name}' : '可选值或 ${inputs.name}'"
                    @input="updateScriptNodeInputField(parameter, $event)"
                  />
                  </template>
                  <label v-else-if="parameter.type === 'boolean'" class="workflow-inline-toggle" :for="`node-input-${parameter.name}`">
                    <input :id="`node-input-${parameter.name}`" type="checkbox" :checked="scriptNodeInputObject()[parameter.name] === true" @change="updateScriptNodeInputBoolean(parameter, $event)" />
                    启用
                  </label>
                  <textarea
                    v-else
                    :id="`node-input-${parameter.name}`"
                    :value="scriptNodeInputText(parameter)"
                    rows="3"
                    :placeholder="parameter.type === 'array' ? 'JSON 数组或 ${inputs.name}' : 'JSON 对象或 ${inputs.name}'"
                    @change="updateScriptNodeInputJson(parameter, $event)"
                  />
                  <select
                    class="workflow-script-node-input-reference"
                    :value="scriptNodeInputReference(parameter.name)"
                    :aria-label="`选择 ${parameter.name} 的引用来源`"
                    @change="updateScriptNodeInputReference(parameter.name, eventValue($event))"
                  >
                    <option value="">固定值 / 手动填写</option>
                    <option v-for="item in commandReferences" :key="`script-ref-${parameter.name}-${item.reference}`" :value="item.reference">{{ item.label }} · {{ item.reference }}</option>
                  </select>
                  <small v-if="parameter.description" class="field-hint">{{ parameter.description }}</small>
                </div>
              </div>
              <label v-else>输入 JSON<textarea :value="typeof selectedNode.config.input_json === 'string' ? String(selectedNode.config.input_json) : JSON.stringify(selectedNode.config.input_json || {}, null, 2)" rows="6" placeholder='例如：{"mode":"check"}' @change="updateScriptNodeInputJsonEditor($event)" /></label>
              <small class="field-hint">参数会以 JSON 写入 <code>DEVICE_TUI_INPUT_JSON</code>；支持使用 <code>${inputs.xxx}</code> 引用流程输入。</small>
            </div>
            <label v-else>输入 JSON<textarea :value="typeof selectedNode.config.input_json === 'string' ? String(selectedNode.config.input_json) : JSON.stringify(selectedNode.config.input_json || {})" rows="3" placeholder='例如：{"device_id":"router-1"}' @change="updateScriptNodeInputJsonEditor($event)" /><small class="field-hint">脚本通过环境变量 <code>DEVICE_TUI_INPUT_JSON</code> 读取；变量引用必须单独作为完整值。</small></label>
            <div class="workflow-command-grid">
              <label>工作目录<input :value="configString('cwd')" placeholder="可选，例如 D:/scripts" @input="updateConfigString('cwd', $event)" /></label>
              <label>环境变量 JSON<textarea :value="JSON.stringify(selectedNode.config.env || {})" rows="3" placeholder='例如：{"MODE":"prod"}' @change="updateConfigJson('env', $event)" /></label>
            </div>
            <div class="workflow-command-grid">
              <label>超时时间（秒）<input v-model.number="selectedNode.config.timeout_seconds" type="number" min="1" max="86400" /></label>
              <label>最大输出长度<input v-model.number="selectedNode.config.max_output_chars" type="number" min="1024" max="16777216" step="1024" /><small class="field-hint">stdout 和 stderr 分别保留，避免日志失控。</small></label>
            </div>
            <div class="workflow-command-result-contract"><span>输出</span><code>stdout</code><code>stderr</code><code>result</code><code>exit_code</code><code>status</code></div>
            <small class="field-hint">脚本 stdout 最后一行若是 JSON，会解析为 <code>result</code>；退出码非 0 时步骤失败。</small>
          </div>
          <template v-if="selectedNode.action_id === 'workflow.call'">
            <label>已发布流程<select :value="String(selectedNode.config.workflow_id || '')" @change="selectSubworkflow(($event.target as HTMLSelectElement).value)"><option value="">选择流程</option><option v-for="item in publishedWorkflows.filter((workflow) => workflow.id !== selected?.id)" :key="item.id" :value="item.id">{{ item.name }}</option></select></label>
            <label>固定版本<select :value="String(selectedNode.config.version || '')" @change="selectSubworkflowVersion(($event.target as HTMLSelectElement).value)"><option value="">选择版本</option><option v-for="item in subworkflowVersions" :key="`${item.id}-${item.version}`" :value="String(item.version)">v{{ item.version }} · {{ item.step_count || 0 }} 步</option></select></label>
            <div v-if="selectedSubworkflow?.inputs?.length" class="workflow-subflow-contract"><strong>输入映射</strong><label v-for="input in selectedSubworkflow.inputs" :key="input.name">{{ input.name }}<input :value="String((selectedNode.config.inputs as Record<string, unknown> | undefined)?.[input.name] ?? '')" :placeholder="input.required ? '必填值或 ${inputs.name}' : '可选'" @input="updateSubworkflowInput(input.name, ($event.target as HTMLInputElement).value)" /></label></div>
            <div v-if="selectedSubworkflow?.outputs?.length" class="workflow-command-result-contract"><span>输出</span><code v-for="output in selectedSubworkflow.outputs" :key="output.name">{{ output.name }}</code></div>
            <small class="field-hint">运行时展开固定发布版本；下游可使用 <code>{{ '${' + selectedNode.id + '.输出名}' }}</code>。</small>
          </template>
          <template v-if="selectedNode.action_id === 'terminal.wait'"><label>匹配方式<select v-model="selectedNode.config.mode"><option value="contains">包含文本</option><option value="regex">正则表达式</option></select></label><label>等待文本<textarea :value="configString('pattern')" rows="2" placeholder="例如：Huawei、Password: 或 completed" @input="updateConfigString('pattern', $event)" /></label><label>等待超时（秒）<input v-model.number="selectedNode.config.timeout_seconds" type="number" min="1" max="86400" /></label><label class="workflow-input-required"><input v-model="selectedNode.config.send_enter" type="checkbox" />开始等待时发送回车</label><label class="workflow-input-required"><input v-model="selectedNode.config.case_sensitive" type="checkbox" />区分大小写</label><small class="field-hint">开始等待时会自动唤醒终端提示符，再监听后续输出；支持跨数据块匹配。</small></template>
          <template v-if="selectedNode.action_id === 'variable.set'">
            <label>变量名<input :value="configString('name')" @input="updateConfigString('name', $event)" /></label>
            <label>变量值<input :value="configString('value')" placeholder="固定值或支持 ${node.field}" @input="updateConfigString('value', $event)" /><details class="workflow-variable-reference"><summary>插入上游引用</summary><select :value="variableValueSourceId && variableValueField ? `${variableValueSourceId}.${variableValueField}` : variableValueSourceId" aria-label="选择上游输出" @change="setVariableValueReference(($event.target as HTMLSelectElement).value)"><option value="">选择步骤或字段</option><template v-for="source in resultSources" :key="`${source.id}-fields`"><option :value="`${source.id}`">{{ source.label }} · 完整结果</option><option v-for="field in source.fields" :key="`${source.id}-${field.name}`" :value="`${source.id}.${field.name}`">{{ source.label }} · {{ fieldLabel(field.name) }}</option></template></select></details></label>
            <label class="workflow-inline-toggle"><input :checked="variableExtractEnabled" type="checkbox" @change="toggleVariableExtract(($event.target as HTMLInputElement).checked)" /><span>提取匹配</span></label>
            <div v-if="variableExtractEnabled" class="workflow-variable-extract">
              <label>匹配规则<textarea :value="variableExtractString('pattern')" rows="2" placeholder="例如：flash:/\\S*cc\\S*" @input="updateVariableExtractString('pattern', $event)" /></label>
              <label>保存方式<select :value="variableExtractString('mode') || 'match'" @change="updateVariableExtractMode"><option value="match">匹配内容</option><option value="line">匹配所在整行</option></select></label>
              <label>捕获组<input :value="variableExtractString('group') || '0'" type="number" min="0" step="1" @input="updateVariableExtractNumber('group', $event)" /></label>
              <label>转换为<select :value="variableExtractString('convert') || 'string'" @change="updateVariableExtractString('convert', $event)"><option value="string">文本</option><option value="integer">整数</option><option value="number">数字</option><option value="boolean">布尔值</option><option value="json">JSON</option></select></label>
              <label class="workflow-inline-toggle"><input :checked="Boolean(variableExtractConfig().trim)" type="checkbox" @change="updateVariableExtractBoolean('trim', $event)" /><span>去除首尾空白</span></label>
              <small class="field-hint">保存第一个匹配并按需转换；无匹配时变量为空。</small>
            </div>
          </template>
          <template v-if="selectedNode.action_id === 'expression.evaluate'"><label>表达式<textarea :value="configString('expression')" rows="2" placeholder="例如：inputs.version &lt; 10" @input="updateConfigString('expression', $event)" /></label><label>表达式上下文 JSON<textarea :value="JSON.stringify(selectedNode.config.values || {})" rows="2" @change="updateConfigJson('values', $event)" /></label></template>
          <template v-if="selectedNode.action_id === 'loop.for_each'"><label>列表来源<select v-model="loopItemsMode"><option value="manual">手动输入列表</option><option value="reference">引用前置步骤输出</option></select></label><label v-if="loopItemsMode === 'manual'">遍历列表 JSON<textarea :value="JSON.stringify(selectedNode.config.items || [])" rows="2" @change="updateConfigJson('items', $event)" /></label><template v-else><label>列表来源步骤<select :value="loopItemsSourceId" @change="setLoopItemsSource(($event.target as HTMLSelectElement).value)"><option value="">选择步骤</option><option v-for="source in resultSources" :key="source.id" :value="source.id">{{ source.label }}</option></select></label><label>输出字段<select :value="loopItemsField" @change="setLoopItemsField(($event.target as HTMLSelectElement).value)"><option value="">完整输出</option><option v-for="field in loopItemsSourceFields" :key="`loop-${loopItemsSourceId}-${field.name}`" :value="field.name">{{ fieldLabel(field.name) }}</option></select><small class="field-hint">引用会在运行时解析为列表；适合消费采集、表达式或保存结果步骤的输出。</small></label></template><label>循环动作<select v-model="selectedNode.config.action_id"><option v-for="action in loopChildActions" :key="action.id" :value="action.id">{{ action.label }}</option></select></label><label>动作参数 JSON<textarea :value="JSON.stringify(selectedNode.config.action_inputs || {})" rows="2" @change="updateConfigJson('action_inputs', $event)" /></label></template>
          <template v-if="selectedNode.action_id === 'loop.until'">
            <label>循环执行什么？<select v-model="selectedNode.config.action_id"><option v-for="action in loopChildActions" :key="action.id" :value="action.id">{{ action.label }}</option></select></label>
            <div v-if="selectedNode.config.action_id === 'device.command'" class="workflow-command-field">
              <div class="workflow-command-label-row"><span>命令内容</span></div>
              <textarea :value="String((selectedNode.config.action_inputs as Record<string, unknown> | undefined)?.command || '')" rows="2" placeholder="例如：display version" @input="(e) => { const node = selectedNode; if (!node) return; if (!node.config.action_inputs || typeof node.config.action_inputs !== 'object') node.config.action_inputs = {}; (node.config.action_inputs as Record<string, unknown>).command = (e.target as HTMLTextAreaElement).value }" />
            </div>
            <label>何时停止？<select v-model="loopUntilStopMode">
              <option value="output_contains">输出包含文本</option>
              <option value="output_regex">输出匹配正则</option>
              <option value="success">命令成功</option>
              <option value="failure">命令失败</option>
              <option value="max_iterations">达到最大次数</option>
            </select></label>
            <label v-if="loopUntilStopMode === 'output_contains' || loopUntilStopMode === 'output_regex'">
              {{ loopUntilStopMode === 'output_contains' ? '目标文本' : '正则表达式' }}
              <input v-model="loopUntilPattern" :placeholder="loopUntilStopMode === 'output_contains' ? '例如：READY' : '例如：V\\d+R\\d+'" />
            </label>
            <label>最多执行<input v-model.number="selectedNode.config.max_iterations" type="number" min="1" max="100" /> 次</label>
            <label>每次间隔<input v-model.number="selectedNode.config.interval_seconds" type="number" min="0" max="86400" step="0.1" /> 秒</label>
            <small class="field-hint">{{ loopUntilStopMode === 'max_iterations' ? '每轮执行一次动作，达到最大次数后停止。' : '每轮执行一次动作并检查停止条件，满足条件或达到最大次数时停止。' }}</small>
          </template>
          <template v-if="selectedNode.action_id === 'utility.confirm'"><label>确认提示<textarea :value="configString('prompt')" rows="3" placeholder="例如：请确认设备已备份配置" @input="updateConfigString('prompt', $event)" /></label><label>同意按钮文字<input :value="configString('approve_label')" @input="updateConfigString('approve_label', $event)" /></label><label>拒绝按钮文字<input :value="configString('reject_label')" @input="updateConfigString('reject_label', $event)" /></label><small class="field-hint">执行到此步骤会暂停，任务页会显示确认或取消选项。</small></template>
          <label v-if="selectedNode.action_id !== 'variable.set' && selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.wait' && selectedNode.action_id !== 'utility.confirm'">失败重试次数<input v-model.number="selectedNode.config.retry_attempts" type="number" min="1" max="5" placeholder="1" /><small class="field-hint">失败后自动重试，最多 5 次。</small></label>
          <label v-if="selectedNode.action_id !== 'variable.set' && selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.wait' && selectedNode.action_id !== 'utility.confirm'">失败重试间隔（秒）<input v-model.number="selectedNode.config.retry_backoff_seconds" type="number" min="0" max="60" step="0.1" placeholder="0" /><small class="field-hint">两次重试之间等待的时间，最多 60 秒。</small></label>
          <label v-if="selectedNode.action_id === 'device.command'">失败后的处理<select v-model="selectedNode.config.failure_strategy"><option value="stop">停止流程</option><option value="continue">继续后续节点</option></select></label>
          <label v-if="selectedNode.action_id !== 'variable.set' && selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.confirm'">并行组（可选）<input :value="configString('parallel_group')" placeholder="例如：信息采集" @input="updateConfigString('parallel_group', $event)" /><small class="field-hint">同一组中互相独立的步骤可并行执行；留空表示按顺序执行。</small></label>
          <label v-if="selectedNode.action_id !== 'variable.set' && selectedNode.action_id !== 'utility.condition' && selectedNode.action_id !== 'utility.confirm'">重复执行次数<input v-model.number="selectedNode.config.repeat_count" type="number" min="1" max="20" placeholder="1" /><small class="field-hint">将此步骤最多执行 20 次，适合重复探测和轮询。</small></label>
          <template v-if="selectedNode.action_id === 'file.upload'">
            <label>本机文件绝对路径<div class="workflow-file-input"><input :value="configString('source')" placeholder="例如：D:/packages/image.cc" @input="updateConfigString('source', $event)" /><button type="button" class="workflow-file-button workflow-upload-picker" @click="chooseUploadSource"><FileUp :size="14" />选择文件</button></div><small class="field-hint">填写或选择本机文件绝对路径；执行时会自动暂存并上传。</small></label>
            <label>设备目标路径（可选）<input :value="configString('destination')" placeholder="留空自动使用 flash:/文件名" @input="updateConfigString('destination', $event)" /><small class="field-hint">留空时默认上传到设备 flash:/ 目录，也可手动指定完整路径。</small></label>
            <label class="workflow-inline-toggle"><input v-model="selectedNode.config.overwrite" type="checkbox" />文件已存在时覆盖</label>
          </template>
          <template v-else-if="selectedNode.action_id === 'file.download'">
            <label>设备源路径<input :value="configString('source')" placeholder="例如：flash:/image.cc" @input="updateConfigString('source', $event)" /></label>
            <label>本地保存位置<input :value="configString('destination')" placeholder="共享目录中的相对路径" @input="updateConfigString('destination', $event)" /></label>
          </template>
          <label v-if="selectedNode.action_id === 'utility.wait'">等待秒数<input v-model.number="selectedNode.config.seconds" type="number" min="1" max="3600" /></label>
          <div v-else-if="selectedNode.action_id === 'utility.condition'" class="condition-builder"><strong>如果</strong><label>多个条件<select v-model="conditionLogicalOperator"><option value="AND">全部满足（AND）</option><option value="OR">任一满足（OR）</option></select></label><div v-for="(rule, index) in conditionRules" :key="index" class="condition-row"><select v-model="rule.field"><option value="software_version">软件版本</option><option value="status">状态</option><option value="name">名称</option><option value="stdout">标准输出</option><option value="stderr">错误输出</option><option value="exitCode">退出码</option><option value="duration">执行耗时</option></select><select v-model="rule.operator"><option>等于</option><option>不等于</option><option>包含</option><option>不包含</option><option>正则匹配</option><option>大于</option><option>小于</option><option>是否为空</option></select><input v-model="rule.value" placeholder="比较值或正则表达式" /></div><button type="button" class="connect-button" @click="conditionRules.push({ field: 'status', operator: '等于', value: '' })">+ 添加条件</button><label>满足条件时<select :value="conditionTargets.trueTarget" @change="setConditionTarget('true', $event)"><option value="">选择真分支步骤</option><option v-for="node in (selected.nodes || []).filter((item) => item.id !== selectedNode?.id)" :key="node.id" :value="node.id">{{ actions.find((action) => action.id === node.action_id)?.label || node.id }}</option></select></label><label>不满足时<select :value="conditionTargets.falseTarget" @change="setConditionTarget('false', $event)"><option value="">选择假分支步骤</option><option v-for="node in (selected.nodes || []).filter((item) => item.id !== selectedNode?.id)" :key="node.id" :value="node.id">{{ actions.find((action) => action.id === node.action_id)?.label || node.id }}</option></select></label><small>运行时只会执行其中一条分支，后续步骤会沿用分支条件。</small></div>
          <label v-else-if="selectedNode.action_id === 'result.save'">结果名称<input v-model="selectedNode.config.key" placeholder="例如：版本检查结果" /><span class="field-hint">保存哪个数据</span><select :value="String(selectedNode.config.value || '')" @change="onResultFieldChange"><option value="">上一步完整结果</option><template v-for="source in resultSources" :key="`${source.id}-result-fields`"><option :value="`${source.id}`">{{ source.label }} · 完整结果</option><option v-for="field in source.fields" :key="`${source.id}-${field.name}`" :value="`${source.id}.${field.name}`">{{ source.label }} · {{ fieldLabel(field.name) }}</option></template></select><small class="field-hint">通过选择器传递上一步数据，无需填写表达式。</small></label>
          <button v-if="selectedNode.action_id !== 'device.command' && selectedNode.action_id !== 'utility.condition'" type="button" class="connect-button" @click="openCustomActionDialog"><Save :size="13" />保存为自定义 Action</button>
          <button class="remove-node-button" type="button" @click="removeNode"><Trash2 :size="13" />删除步骤</button>
          <button v-if="selectedNode.action_id !== 'variable.set'" class="connect-button" type="button" @click="testSelectedStep">测试此步骤</button>
        </section>
        <section v-else-if="!flowTestOpen && rightRailMode === 'step'" class="workflow-properties workflow-empty">选择一个步骤编辑参数</section>
      </main>
      <main v-else class="workflow-empty">选择一个 Workflow 开始编辑</main>
    </div>
    <div v-if="showRunPreview" class="workflow-preview-backdrop"><div class="workflow-preview"><h3>执行预览</h3><p><b>流程名称：</b>{{ selected?.name }}</p><p><b>目标数量：</b>{{ selectedDeviceIds.length || 1 }} 台</p><p><b>步骤数量：</b>{{ selected?.nodes?.length || 0 }} 步</p><p><b>任务目标：</b>{{ taskGoal }}</p><p v-if="previewParallelGroups.length" class="preview-parallel-summary"><b>并行执行：</b>{{ previewParallelGroups.join('；') }}</p><ol class="preview-step-list"><li v-for="(step, index) in previewSteps" :key="`${step.label}-${index}`">{{ index + 1 }}. {{ step.label }}<small v-if="step.detail">{{ step.detail }}</small></li></ol><p class="preview-check">✓ 目标设备已选择　✓ 必填字段已填写　✓ 条件配置完整</p><p v-if="previewHasRisk" class="preview-risk-warning"><AlertTriangle :size="14" />包含脚本执行、重启或文件传输操作，请确认影响后继续。</p><label v-if="previewHasRisk" class="preview-risk-confirm"><input v-model="confirmedRisks" type="checkbox" />我已确认高风险操作的影响</label><div class="preview-actions"><button type="button" @click="showRunPreview = false">取消</button><button type="button" :disabled="dryRunning" @click="dryRunWorkflow">模拟运行</button><button class="primary-action" type="button" :disabled="previewHasRisk && !confirmedRisks" @click="confirmRunFromPreview">确认开始</button></div></div></div>
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
  color: var(--workflow-muted);
  font-size: 11px;
}
.workflow-run-target select,
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
.workflow-flow-test-panel { display: grid; grid-template-rows: auto auto auto minmax(0, 1fr) auto auto; align-content: start; gap: 12px; min-width: 0; min-height: 100%; padding: 16px 14px 20px; background: var(--workflow-surface-muted); }
.workflow-flow-test-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; padding-bottom: 12px; border-bottom: 1px solid var(--workflow-border); }
.workflow-flow-test-header > div { min-width: 0; display: grid; gap: 3px; }
.workflow-flow-test-header strong { color: var(--workflow-text); font-size: 15px; }
.workflow-flow-test-header small { overflow: hidden; color: var(--workflow-muted); text-overflow: ellipsis; white-space: nowrap; font-size: 10px; }
.workflow-flow-test-status { display: flex; align-items: center; gap: 7px; min-height: 32px; padding: 0 10px; border: 1px solid var(--workflow-border); border-radius: 6px; color: var(--workflow-muted); background: var(--workflow-surface); }
.workflow-flow-test-status strong { font-size: 11px; }
.workflow-flow-test-status small { margin-left: auto; font: 600 10px ui-monospace, SFMono-Regular, Consolas, monospace; }
.workflow-flow-test-status.status-running { color: #fcd34d; border-color: rgba(245, 158, 11, .34); }
.workflow-flow-test-status.status-success { color: #86efac; border-color: rgba(34, 197, 94, .34); }
.workflow-flow-test-status.status-failed { color: #fca5a5; border-color: rgba(248, 113, 113, .38); }
.workflow-flow-test-dot { width: 7px; height: 7px; flex: 0 0 auto; border-radius: 50%; background: currentColor; }
.status-running .workflow-flow-test-dot { box-shadow: 0 0 0 4px rgba(245, 158, 11, .12); animation: workflow-test-pulse 1.4s ease-in-out infinite; }
@keyframes workflow-test-pulse { 50% { opacity: .45; transform: scale(.75); } }
.workflow-flow-test-current { display: grid; gap: 4px; padding: 9px 10px; border-left: 2px solid #60a5fa; background: rgba(37, 99, 235, .1); }
.workflow-flow-test-current span, .workflow-flow-test-section-title small { color: var(--workflow-muted); font-size: 10px; }
.workflow-flow-test-current strong { overflow-wrap: anywhere; color: var(--workflow-text); font-size: 11px; }
.workflow-flow-test-error { margin: 0; }
.workflow-flow-test-section { display: grid; gap: 9px; min-width: 0; }
.workflow-test-data-section { gap: 7px; padding-bottom: 11px; border-bottom: 1px solid var(--workflow-border); }
.workflow-test-process-section { min-height: 150px; align-content: start; }
.workflow-test-outputs { padding-top: 1px; border-bottom: 0; }
.workflow-test-value-list { display: grid; gap: 5px; min-width: 0; margin: 0; }
.workflow-test-value-list > div { display: grid; grid-template-columns: minmax(82px, .7fr) minmax(0, 1.5fr); gap: 8px; align-items: start; padding: 6px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface); }
.workflow-test-value-list dt { display: grid; gap: 3px; min-width: 0; color: var(--workflow-text); font: 600 10px ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
.workflow-test-value-list dt small { color: var(--workflow-muted); font: 9px ui-sans-serif, system-ui, sans-serif; }
.workflow-test-value-list dd { min-width: 0; max-height: 96px; margin: 0; overflow: auto; color: var(--workflow-text); font: 10px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.workflow-test-empty { margin: 0; color: var(--workflow-muted); font-size: 10px; line-height: 1.5; }
.workflow-flow-test-section-title { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.workflow-flow-test-section-title strong { color: var(--workflow-text); font-size: 12px; }
.workflow-flow-test-log { position: relative; display: grid; gap: 6px; margin: 0; padding: 0; list-style: none; }
.workflow-flow-test-log::before { content: ''; position: absolute; top: 11px; bottom: 11px; left: 12px; width: 1px; background: var(--workflow-border); }
.workflow-flow-test-log li { position: relative; display: grid; grid-template-columns: 9px minmax(0, 1fr); gap: 9px; min-width: 0; padding: 8px 9px 8px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface); }
.workflow-flow-test-log-mark { position: relative; z-index: 1; width: 7px; height: 7px; margin-top: 4px; border: 2px solid var(--workflow-surface); border-radius: 50%; background: #64748b; box-shadow: 0 0 0 1px #64748b; }
.workflow-flow-test-log li.log-running .workflow-flow-test-log-mark { background: #f59e0b; }
.workflow-flow-test-log li.log-success .workflow-flow-test-log-mark, .workflow-flow-test-log li.log-completed .workflow-flow-test-log-mark { background: #22c55e; }
.workflow-flow-test-log li.log-failed .workflow-flow-test-log-mark { background: #ef4444; }
.workflow-flow-test-log li > div { min-width: 0; display: grid; gap: 4px; }
.workflow-flow-test-log li header { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
.workflow-flow-test-log li header strong { overflow: hidden; color: var(--workflow-text); text-overflow: ellipsis; white-space: nowrap; font-size: 11px; }
.workflow-flow-test-log li header span { flex: 0 0 auto; color: var(--workflow-muted); font-size: 10px; }
.workflow-flow-test-log li.log-running header span { color: #f59e0b; }
.workflow-flow-test-log li.log-success header span { color: #22c55e; }
.workflow-flow-test-log li.log-failed header span { color: #ef4444; }
.workflow-flow-test-log li small { color: var(--workflow-muted); font: 10px ui-monospace, SFMono-Regular, Consolas, monospace; }
.workflow-flow-test-log pre, .workflow-flow-test-output { max-height: 160px; margin: 2px 0 0; padding: 8px; overflow: auto; color: var(--workflow-text); border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface-input); font: 10px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.workflow-flow-test-output { max-height: 240px; margin: 0; }
.workflow-flow-test-retry { justify-content: center; }
.workflow-right-rail-switcher { display: flex; align-items: center; gap: 4px; grid-column: 3; grid-row: 1; min-width: 0; margin: 0; padding: 10px 12px; border-bottom: 1px solid var(--workflow-border); background: var(--workflow-surface); }
.workflow-right-rail-switcher button { display: inline-flex; align-items: center; justify-content: center; gap: 5px; min-width: 0; flex: 1; min-height: 30px; padding: 0 8px; color: var(--workflow-muted); border: 1px solid transparent; border-radius: 5px; background: transparent; cursor: pointer; font-size: 11px; }
.workflow-right-rail-switcher button:hover:not(:disabled) { color: var(--workflow-text); background: color-mix(in srgb, var(--workflow-focus) 8%, transparent); }
.workflow-right-rail-switcher button.active { color: var(--workflow-focus); border-color: color-mix(in srgb, var(--workflow-focus) 34%, var(--workflow-border)); background: color-mix(in srgb, var(--workflow-focus) 12%, transparent); font-weight: 650; }
.workflow-right-rail-switcher button:disabled { opacity: .4; cursor: default; }
.workflow-studio-grid.step-settings-mode > .workflow-properties { grid-row: 2 / -1; }
.workflow-studio-grid:not(.flow-test-mode) > .workflow-right-rail > .workflow-metadata-editor { grid-row: 2; }
.workflow-studio-grid:not(.flow-test-mode) > .workflow-right-rail > .workflow-input-editor:not(.workflow-output-editor) { grid-row: 3; }
.workflow-studio-grid:not(.flow-test-mode) > .workflow-right-rail > .workflow-output-editor { grid-row: 4; }
.workflow-studio-grid:not(.flow-test-mode) > .workflow-right-rail > .workflow-runtime-inputs { grid-row: 5; }
@media (max-width: 980px) {
  .workflow-right-rail-switcher { grid-column: 1 / -1; grid-row: 1; }
  .workflow-studio-grid.step-settings-mode > .workflow-properties { grid-column: 1 / -1; grid-row: 6; }
}
@media (max-width: 720px) {
  .workflow-studio-grid.step-settings-mode > .workflow-properties { grid-row: 7; }
}
.workflow-flow-test-log-content { min-width: 0; display: grid; gap: 7px; }
.workflow-flow-test-log-content > header { margin: 0; }
.workflow-flow-step-toggle { display: grid; grid-template-columns: minmax(0, 1fr) auto 14px; align-items: center; gap: 12px; width: 100%; padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer; text-align: left; }
.workflow-flow-step-toggle:hover .workflow-flow-step-title { color: var(--workflow-focus); }
.workflow-flow-step-heading { display: grid; gap: 5px; min-width: 0; }
.workflow-flow-step-chevron { justify-self: end; color: var(--workflow-muted); transition: transform 120ms ease; }
.workflow-flow-step-chevron.expanded { transform: rotate(180deg); }
.workflow-flow-step-details { display: grid; gap: 8px; padding-top: 8px; }
.workflow-flow-no-output { color: var(--workflow-muted); font-size: 10px; }
.workflow-flow-step-id { min-width: 0; overflow: hidden; color: var(--workflow-muted); text-overflow: ellipsis; white-space: nowrap; font: 10px ui-monospace, SFMono-Regular, Consolas, monospace; }
.workflow-flow-step-status { justify-self: end; padding: 2px 6px; border-radius: 999px; color: var(--workflow-muted); background: color-mix(in srgb, var(--workflow-muted) 10%, transparent); font-size: 9px; }
.log-running .workflow-flow-step-status { color: #f59e0b; background: rgba(245, 158, 11, .12); }
.log-success .workflow-flow-step-status { color: #22c55e; background: rgba(34, 197, 94, .12); }
.log-failed .workflow-flow-step-status { color: #ef4444; background: rgba(239, 68, 68, .12); }
.workflow-flow-step-title { color: var(--workflow-text); font-size: 12px; }
.workflow-flow-command { display: grid; gap: 4px; min-width: 0; padding: 7px 8px; border-left: 2px solid #60a5fa; background: rgba(37, 99, 235, .08); }
.workflow-flow-command span { color: var(--workflow-muted); font-size: 9px; }
.workflow-flow-command code { overflow-x: auto; color: var(--workflow-text); font: 10px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.workflow-flow-step-metrics { display: flex; flex-wrap: wrap; gap: 6px; }
.workflow-flow-step-metrics span { padding: 3px 6px; color: var(--workflow-muted); border: 1px solid var(--workflow-border); border-radius: 4px; font-size: 9px; }
.workflow-flow-step-metrics b { margin-left: 3px; color: var(--workflow-text); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.workflow-flow-terminal-output { display: grid; gap: 4px; min-width: 0; }
.workflow-flow-terminal-output header { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #86efac; font-size: 10px; }
.workflow-flow-terminal-output header small { color: var(--workflow-muted); font: 9px ui-monospace, SFMono-Regular, Consolas, monospace; }
.workflow-flow-terminal-output.is-error header { color: #fca5a5; }
.workflow-flow-terminal-output pre, .workflow-flow-raw-result pre, .workflow-flow-result-item pre, .workflow-flow-raw-json pre { max-height: 170px; margin: 0; padding: 8px; overflow: auto; color: var(--workflow-text); border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface-input); font: 10px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.workflow-flow-terminal-output pre { border-color: rgba(34, 197, 94, .22); }
.workflow-flow-terminal-output.is-error pre { border-color: rgba(239, 68, 68, .28); }
.workflow-flow-raw-result, .workflow-flow-raw-json { min-width: 0; }
.workflow-flow-raw-result summary, .workflow-flow-raw-json summary { color: var(--workflow-focus); cursor: pointer; font-size: 10px; }
.workflow-flow-raw-result pre, .workflow-flow-raw-json pre { margin-top: 6px; }
.workflow-flow-step-error { margin: 0; color: #fca5a5; font-size: 10px; }
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
:global(:root[data-theme="light"]) .workflow-flow-command { background: #eff6ff; }
:global(:root[data-theme="light"]) .workflow-flow-result-item { background: #ffffff; }
.workflow-studio-grid.flow-test-mode > .workflow-right-rail { display: block; grid-column: 3; grid-row: 1; min-width: 0; min-height: 0; overflow-x: hidden; overflow-y: auto; border-left: 1px solid var(--workflow-border); background: var(--workflow-surface-muted); }
.workflow-studio-grid.flow-test-mode > .workflow-right-rail > .workflow-flow-test-panel { min-height: 100%; box-sizing: border-box; }
:global(:root[data-theme="light"]) .workflow-flow-test-current { background: #eff6ff; }
:global(:root[data-theme="light"]) .workflow-test-value-list > div { background: #fff; }
:global(:root[data-theme="light"]) .flow-test-action { color: #1d4ed8; background: #eff6ff; border-color: #93c5fd; }
:global(:root[data-theme="light"]) .workflow-flow-test-panel { background: #f1f5f9; }
:global(:root[data-theme="light"]) .workflow-flow-test-status,
:global(:root[data-theme="light"]) .workflow-flow-test-log li { background: #ffffff; }
.workflow-input-editor { grid-column: 1 / -1; display: grid; gap: 8px; padding: 12px 16px; border-bottom: 1px solid var(--workflow-border); background: var(--workflow-surface-muted); }
.workflow-metadata-editor { grid-column: 1 / -1; display: grid; grid-template-columns: minmax(180px, .8fr) minmax(260px, 1.4fr); gap: 8px 14px; padding: 12px 16px; border-bottom: 1px solid var(--workflow-border); background: var(--workflow-surface); }
.workflow-metadata-editor label { min-width: 0; margin: 0; color: var(--workflow-muted); font-size: 10px; }
.workflow-metadata-editor input { margin-top: 4px; }
.workflow-metadata-editor small { grid-column: 1 / -1; color: #fca5a5; font-size: 10px; }
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
.workflow-run-target select[multiple] { min-height: 68px; }
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
.workflow-version-manager { margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(100, 116, 139, .28); }
.workflow-version-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; margin-bottom: 7px; color: #e2e8f0; font-size: 12px; }
.workflow-version-heading small, .workflow-version-empty { color: rgba(226, 232, 240, .5); font-size: 10px; }
.workflow-version-list { display: grid; gap: 5px; }
.workflow-version-row { display: flex; align-items: center; justify-content: space-between; gap: 7px; padding: 7px 6px; border: 1px solid rgba(100, 116, 139, .25); border-radius: 5px; background: rgba(15, 23, 42, .42); }
.workflow-version-info { min-width: 0; display: grid; gap: 2px; }
.workflow-version-info strong { color: #bfdbfe; font-size: 11px; }
.workflow-version-info small, .workflow-version-info span { overflow: hidden; color: rgba(226, 232, 240, .52); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.workflow-version-info span { color: #86efac; }
.workflow-version-row.referenced .workflow-version-info span { color: #fcd34d; }
.workflow-version-actions { display: inline-flex; flex: 0 0 auto; align-items: center; gap: 2px; }
.workflow-version-actions .icon-toolbar-button { width: 25px; height: 25px; }
.workflow-run-header-button { display: inline-flex; align-items: center; gap: 5px; padding: 5px 8px; border: 1px solid rgba(96, 165, 250, .45); border-radius: 5px; color: #bfdbfe; background: rgba(37, 99, 235, .16); font-size: 11px; cursor: pointer; }
.workflow-run-header-button:hover { border-color: rgba(147, 197, 253, .75); background: rgba(37, 99, 235, .28); }
.workflow-dirty-state { color: #fcd34d; font-size: 10px; white-space: nowrap; }
.workflow-version-error { margin: 0; color: #fca5a5; font-size: 10px; line-height: 1.4; }
.workflow-modal-backdrop { position: fixed; inset: 0; z-index: 30; display: grid; place-items: center; background: rgba(2,6,23,.62); }
.workflow-modal-backdrop { pointer-events: auto; }
.workflow-modal-backdrop .workflow-create-dialog { position: relative; z-index: 31; pointer-events: auto; }
.workflow-import-dialog { width: min(520px, calc(100vw - 32px)); padding: 18px; border: 1px solid var(--workflow-border); border-radius: 8px; background: #172033; box-shadow: 0 16px 48px rgba(0,0,0,.35); }
.workflow-import-dialog header, .workflow-import-dialog footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.workflow-import-dialog footer { justify-content: flex-end; margin-top: 16px; }
.workflow-create-dialog { display: grid; gap: 12px; }
.workflow-create-dialog label { display: grid; gap: 5px; margin: 0; color: var(--workflow-muted); font-size: 11px; }
.workflow-create-dialog input, .workflow-create-dialog textarea { box-sizing: border-box; width: 100%; padding: 8px; border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface-input); color: inherit; font: inherit; }
.workflow-create-dialog button { padding: 7px 10px; border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface-muted); color: inherit; cursor: pointer; }
.workflow-create-dialog .primary-action { color: #fff; background: #2563eb; border-color: #3b82f6; }
.workflow-create-dialog button:disabled { opacity: .45; cursor: default; }
.workflow-script-template-dialog { width: min(720px, calc(100vw - 32px)); max-height: min(760px, calc(100vh - 32px)); overflow-y: auto; scrollbar-gutter: stable; scrollbar-width: thin; }
.workflow-script-template-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.workflow-script-template-card { display: grid; grid-template-columns: 30px minmax(0, 1fr); align-items: start; gap: 10px; min-width: 0; min-height: 76px; padding: 11px; border: 1px solid var(--workflow-border); border-radius: 6px; color: inherit; background: var(--workflow-surface-muted); text-align: left; }
.workflow-script-template-card:hover, .workflow-script-template-card.active { border-color: rgba(79, 156, 249, .7); background: rgba(37, 99, 235, .14); }
.workflow-script-template-card.active { box-shadow: inset 3px 0 0 #3b82f6; }
.workflow-script-template-card > span:last-child { display: grid; gap: 4px; min-width: 0; }
.workflow-script-template-card strong { color: var(--workflow-text); font-size: 12px; }
.workflow-script-template-card small { color: var(--workflow-muted); font-size: 10px; line-height: 1.4; }
.workflow-script-template-card em { width: fit-content; padding: 2px 5px; border: 1px solid var(--workflow-border); border-radius: 3px; color: var(--workflow-muted); font-size: 9px; font-style: normal; text-transform: uppercase; }
.workflow-script-template-icon { display: inline-grid; width: 30px; height: 30px; place-items: center; border: 1px solid rgba(45, 212, 191, .36); border-radius: 5px; color: #5eead4; background: rgba(13, 148, 136, .16); }
.workflow-script-template-card.active .workflow-script-template-icon { border-color: rgba(96, 165, 250, .58); color: #bfdbfe; background: rgba(37, 99, 235, .25); }
.workflow-script-template-preview { display: grid; gap: 6px; min-width: 0; padding: 10px; border: 1px solid var(--workflow-border); border-radius: 6px; background: rgba(15, 23, 42, .36); }
.workflow-script-template-preview > span { color: var(--workflow-muted); font-size: 10px; }
.workflow-script-template-preview code { display: block; max-height: 86px; overflow: auto; color: #bfdbfe; font: 10px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; scrollbar-width: thin; }
.workflow-template-manager { display: grid; gap: 5px; padding: 9px 0; border-top: 1px solid var(--workflow-border); border-bottom: 1px solid var(--workflow-border); }
.workflow-template-manager > strong { color: var(--workflow-muted); font-size: 11px; font-weight: 500; }
.workflow-template-manager > div { display: grid; grid-template-columns: minmax(0, 1fr) 30px; align-items: center; gap: 8px; min-height: 30px; }
.workflow-template-manager span { overflow: hidden; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.workflow-template-manager button { display: inline-grid; width: 30px; height: 30px; padding: 0; place-items: center; color: #fca5a5; }
.workflow-import-summary { display: flex; justify-content: space-between; padding: 12px; margin-top: 12px; border-radius: 6px; background: rgba(15,23,42,.62); }
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
  .workflow-script-studio { grid-template-columns: 180px minmax(0, 1fr); }
  .workflow-script-workspace { grid-template-columns: 1fr; overflow: auto; }
  .workflow-script-editor-panel { min-height: 520px; }
  .workflow-script-test-panel { min-height: 280px; border-top: 1px solid var(--workflow-border); border-left: 0; }
}
@media (max-width: 560px) {
  .workflow-script-template-dialog { width: min(calc(100vw - 20px), 720px); max-height: calc(100vh - 20px); padding: 14px; }
  .workflow-script-template-grid { grid-template-columns: 1fr; }
}
@media (max-width: 980px) {
  .workflow-studio-grid { height: auto; }
}

:global(:root[data-theme="light"]) .workflow-create-menu,
:global(:root[data-theme="light"]) .workflow-import-dialog,
:global(:root[data-theme="light"]) .workflow-preview { color: var(--workflow-text); background: var(--workflow-surface); }
:global(:root[data-theme="light"]) .workflow-script-template-card { background: #f8fafc; }
:global(:root[data-theme="light"]) .workflow-script-template-card:hover,
:global(:root[data-theme="light"]) .workflow-script-template-card.active { background: #eff6ff; }
:global(:root[data-theme="light"]) .workflow-script-template-card strong { color: #172033; }
:global(:root[data-theme="light"]) .workflow-script-template-card small,
:global(:root[data-theme="light"]) .workflow-script-template-card em,
:global(:root[data-theme="light"]) .workflow-script-template-preview > span { color: #475569; }
:global(:root[data-theme="light"]) .workflow-script-template-icon { color: #0f766e; background: #ccfbf1; border-color: #99f6e4; }
:global(:root[data-theme="light"]) .workflow-script-template-card.active .workflow-script-template-icon { color: #1d4ed8; background: #dbeafe; border-color: #93c5fd; }
:global(:root[data-theme="light"]) .workflow-script-template-preview { background: #f1f5f9; }
:global(:root[data-theme="light"]) .workflow-script-template-preview code { color: #1e3a8a; }
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
:global(:root[data-theme="light"]) .workflow-version-heading,
:global(:root[data-theme="light"]) .workflow-input-definition label,
:global(:root[data-theme="light"]) .workflow-input-label { color: #334155; }
:global(:root[data-theme="light"]) .workflow-version-heading small,
:global(:root[data-theme="light"]) .workflow-version-empty,
:global(:root[data-theme="light"]) .workflow-version-info small,
:global(:root[data-theme="light"]) .workflow-version-info span { color: #64748b; }
:global(:root[data-theme="light"]) .workflow-run-header-button { color: #1d4ed8; background: #eff6ff; border-color: #93c5fd; }
:global(:root[data-theme="light"]) .workflow-dirty-state { color: #92400e; }
:global(:root[data-theme="light"]) .workflow-version-row.referenced .workflow-version-info span { color: #92400e; }
:global(:root[data-theme="light"]) .workflow-version-delete { color: #b91c1c; }
:global(:root[data-theme="light"]) .workflow-preview .preview-step-list { color: #334155; }
:global(:root[data-theme="light"]) .workflow-branch-notice { color: #92400e; background: #fffbeb; }
:global(:root[data-theme="light"]) .canvas-toolbar-title strong { color: #172033; }
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
.workflow-script-studio { display: grid; grid-template-columns: 248px minmax(0, 1fr); min-height: 0; flex: 1; overflow: hidden; border-top: 1px solid var(--workflow-border); }
.workflow-script-list { min-height: 0; overflow: auto; padding: 14px 10px 24px; border-right: 1px solid var(--workflow-border); background: color-mix(in srgb, var(--workflow-surface-muted) 86%, var(--workflow-bg)); scrollbar-gutter: stable; scrollbar-width: thin; }
.workflow-script-list-actions { display: flex; gap: 6px; padding: 0 7px 10px; }
.workflow-script-list-actions .primary-action { flex: 1; justify-content: center; }
.workflow-script-list-item { display: grid; grid-template-columns: 8px minmax(0, 1fr); align-items: center; gap: 9px; width: 100%; padding: 9px 8px; border: 1px solid transparent; border-radius: 6px; color: inherit; background: transparent; text-align: left; cursor: pointer; }
.workflow-script-list-item:hover, .workflow-script-list-item.active { border-color: rgba(79,156,249,.34); background: rgba(37,99,235,.14); }
.workflow-script-list-item span:last-child { min-width: 0; }
.workflow-script-list-item strong, .workflow-script-list-item small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-script-list-item strong { font-size: 12px; }
.workflow-script-list-item small { margin-top: 3px; color: var(--workflow-muted); font-size: 9px; }
.workflow-script-list-dot { width: 7px; height: 7px; border-radius: 50%; background: #2dd4bf; }
.workflow-script-list-dot[data-language='powershell'] { background: #60a5fa; }
.workflow-script-list-dot[data-language='bash'] { background: #a3e635; }
.workflow-script-workspace { display: grid; grid-template-columns: minmax(460px, 1fr) 340px; min-width: 0; min-height: 0; overflow: hidden; }
.workflow-script-editor-panel { display: grid; grid-template-rows: auto minmax(260px, 1fr) minmax(150px, .42fr); gap: 10px; min-width: 0; min-height: 0; padding: 16px; overflow: hidden; }
.workflow-script-resource-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding-bottom: 12px; }
.workflow-script-resource-header > div:first-child { display: grid; min-width: 0; gap: 3px; }
.workflow-script-resource-header input { min-width: 0; padding: 0; border: 0; color: var(--workflow-text); background: transparent; font-size: 18px; font-weight: 700; outline: 0; }
.workflow-script-resource-header input:focus { border-bottom: 1px solid var(--workflow-focus); }
.workflow-script-resource-header small { color: var(--workflow-muted); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 9px; }
.workflow-script-validation { color: #fca5a5; font-size: 10px; }
.workflow-script-resource-actions { display: flex; gap: 6px; }
.workflow-script-resource-actions button { display: inline-flex; align-items: center; gap: 5px; min-height: 32px; padding: 6px 9px; border: 1px solid var(--workflow-border); border-radius: 5px; color: inherit; background: var(--workflow-surface-muted); cursor: pointer; }
.workflow-script-resource-meta { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 10px; padding-bottom: 12px; }
.workflow-script-resource-meta label, .workflow-script-test-panel label { display: grid; gap: 5px; color: var(--workflow-muted); font-size: 10px; }
.workflow-script-resource-meta input, .workflow-script-resource-meta select, .workflow-script-test-panel select, .workflow-script-test-panel textarea { box-sizing: border-box; width: 100%; padding: 7px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; color: inherit; background: var(--workflow-surface-input); }
.workflow-script-parameters { min-height: 0; max-height: 238px; margin-bottom: 12px; padding: 10px; overflow: auto; border: 1px solid var(--workflow-border); border-radius: 6px; background: var(--workflow-surface-muted); scrollbar-gutter: stable; scrollbar-width: thin; }
.workflow-script-parameters > header, .workflow-script-test-mode { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.workflow-script-parameters > header { margin-bottom: 8px; }
.workflow-script-parameters > header strong { display: block; color: var(--workflow-text); font-size: 12px; }
.workflow-script-parameters > header small { display: block; margin-top: 3px; color: var(--workflow-muted); font-size: 9px; }
.workflow-script-parameter-list { display: grid; gap: 7px; }
.workflow-script-parameter-row { display: grid; gap: 6px; padding: 8px; border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface); }
.workflow-script-parameter-main, .workflow-script-parameter-details { display: grid; grid-template-columns: minmax(100px, 1.1fr) 100px auto 28px; align-items: center; gap: 6px; }
.workflow-script-parameter-details { grid-template-columns: minmax(0, 1fr) minmax(110px, .8fr); }
.workflow-script-parameter-row input, .workflow-script-parameter-row select { box-sizing: border-box; width: 100%; min-width: 0; padding: 5px 6px; border: 1px solid var(--workflow-border); border-radius: 4px; color: inherit; background: var(--workflow-surface-input); font-size: 10px; }
.workflow-script-required, .workflow-inline-toggle { display: inline-flex !important; align-items: center; gap: 5px; white-space: nowrap; }
.workflow-script-required { color: var(--workflow-muted); font-size: 10px; }
.workflow-script-required input, .workflow-inline-toggle input { width: 13px !important; height: 13px; }
.workflow-script-parameters-empty { margin: 2px 0; color: var(--workflow-muted); font-size: 10px; }
.workflow-script-editor-panel :deep(.workflow-script-editor) { position: relative; z-index: 1; min-height: 0; height: 100%; pointer-events: auto; }
.workflow-script-run-log { display: grid; gap: 8px; min-height: 0; padding: 10px; overflow: auto; border: 1px solid var(--workflow-border); border-radius: 6px; color: var(--workflow-text); background: var(--workflow-surface-muted); scrollbar-gutter: stable; scrollbar-width: thin; }
.workflow-script-run-log header, .workflow-script-side-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.workflow-script-run-log header > div, .workflow-script-side-heading > div { display: grid; gap: 3px; min-width: 0; }
.workflow-script-run-log header strong, .workflow-script-side-heading strong { color: var(--workflow-text); font-size: 12px; }
.workflow-script-run-log header small, .workflow-script-side-heading small { color: var(--workflow-muted); font-size: 9px; }
.workflow-script-run-log header code { max-width: 46%; overflow: hidden; color: var(--workflow-muted); font: 9px ui-monospace, SFMono-Regular, Consolas, monospace; text-overflow: ellipsis; white-space: nowrap; }
.workflow-script-run-log .workflow-script-test-summary { padding-top: 7px; }
.workflow-script-run-log section { display: grid; gap: 4px; min-width: 0; }
.workflow-script-run-log section > span { color: var(--workflow-muted); font-size: 9px; }
.workflow-script-run-log pre { box-sizing: border-box; max-height: 150px; margin: 0; padding: 8px; overflow: auto; border: 1px solid var(--workflow-border); border-radius: 4px; color: var(--workflow-text); background: var(--workflow-surface-input); font: 10px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.workflow-script-test-panel { display: grid; align-content: start; gap: 14px; min-height: 0; overflow: auto; padding: 16px; border-left: 1px solid var(--workflow-border); background: var(--workflow-surface-muted); scrollbar-gutter: stable; scrollbar-width: thin; }
.workflow-script-config-section, .workflow-script-test-section { display: grid; gap: 10px; min-width: 0; padding-bottom: 14px; border-bottom: 1px solid var(--workflow-border); }
.workflow-script-test-section { border-bottom: 0; padding-bottom: 0; }
.workflow-script-config-section .workflow-script-resource-meta { grid-template-columns: 1fr; gap: 8px; padding-bottom: 0; }
.workflow-script-config-section .workflow-script-parameters { max-height: 300px; margin-bottom: 0; }
.workflow-script-test-panel .panel-heading { margin-bottom: 18px; }
.workflow-script-test-panel label { margin-bottom: 14px; }
.workflow-script-test-panel textarea { resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.workflow-script-test-mode { justify-content: flex-start; margin: 0 0 12px; padding: 2px; border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface-input); }
.workflow-script-test-mode button { flex: 1; min-height: 27px; border: 0; border-radius: 3px; color: var(--workflow-muted); background: transparent; font-size: 10px; cursor: pointer; }
.workflow-script-test-mode button.active { color: var(--workflow-text); background: var(--workflow-surface); box-shadow: 0 1px 2px rgba(15, 23, 42, .18); }
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
.workflow-script-test-form { display: grid; gap: 11px; margin-bottom: 2px; }
.workflow-script-test-field { display: grid; gap: 4px; }
.workflow-script-test-field > label:first-child { display: flex; align-items: baseline; justify-content: space-between; margin: 0; color: var(--workflow-text); font-size: 10px; }
.workflow-script-test-field > label:first-child span { color: #f59e0b; font-size: 9px; }
.workflow-script-test-field > small { color: var(--workflow-muted); font-size: 9px; }
.workflow-script-test-field > input, .workflow-script-test-field > textarea { box-sizing: border-box; width: 100%; padding: 7px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; color: inherit; background: var(--workflow-surface-input); }
.workflow-script-test-field > textarea { resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.workflow-script-test-button { display: inline-flex; align-items: center; justify-content: center; gap: 6px; width: 100%; min-height: 36px; cursor: pointer; }
.workflow-script-test-button:disabled { opacity: .45; cursor: default; }
.workflow-script-test-result { display: grid; gap: 8px; margin-top: 14px; padding: 10px; border: 1px solid rgba(45,212,163,.28); border-radius: 6px; color: #99f6e4; background: rgba(13,148,136,.1); font-size: 11px; }
.workflow-script-test-result.status-failed, .workflow-script-test-result.status-cancelled { border-color: rgba(248,113,113,.36); color: #fecaca; background: rgba(127,29,29,.16); }
.workflow-script-test-result code { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-script-test-summary { display: grid; grid-template-columns: 54px minmax(0, 1fr); gap: 5px 8px; padding-top: 7px; border-top: 1px solid currentColor; }
.workflow-script-test-summary span, .workflow-script-test-result section > span { opacity: .72; }
.workflow-script-test-summary b { overflow-wrap: anywhere; font-weight: 650; }
.workflow-script-test-result section { display: grid; gap: 4px; min-width: 0; }
.workflow-script-test-result pre { box-sizing: border-box; max-height: 220px; margin: 0; padding: 8px; overflow: auto; border: 1px solid rgba(148,163,184,.18); border-radius: 4px; color: #dbeafe; background: rgba(2,6,23,.58); font: 10px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; scrollbar-gutter: stable; }
.workflow-script-no-selection { display: grid; place-items: center; color: var(--workflow-muted); }
.workflow-new-button { color: #eff6ff !important; background: #2563eb !important; border-color: #3b82f6 !important; box-shadow: 0 3px 10px rgba(37,99,235,.22); }
.workflow-new-button:hover { background: #1d4ed8 !important; }
.toolbar-group-secondary { padding-left: 2px; }
.toolbar-group-secondary > button:not(.icon-toolbar-button), .toolbar-group-commit > button:not(.primary-action) { color: var(--workflow-muted); background: transparent; border-color: transparent; }
.toolbar-group-secondary > button:hover, .toolbar-group-commit > button:hover:not(:disabled) { color: var(--workflow-text); background: var(--workflow-surface-muted); border-color: var(--workflow-border); }
.toolbar-group-export { margin-left: auto; padding: 0 2px; }
.toolbar-group-export .icon-toolbar-button { color: var(--workflow-muted); background: transparent; border-color: transparent; }
.toolbar-group-export .icon-toolbar-button:hover:not(:disabled) { color: var(--workflow-focus); background: rgba(79,156,249,.1); border-color: rgba(79,156,249,.3); }
.secondary-run-button { color: #99f6e4 !important; background: rgba(13,148,136,.12) !important; border-color: rgba(45,212,191,.28) !important; }
.secondary-run-button:hover:not(:disabled) { background: rgba(13,148,136,.22) !important; }
.workflow-run-target { padding-left: 8px; }
.workflow-run-target select { max-width: 190px; min-height: 30px; }
.workflow-library-body { grid-template-columns: 232px minmax(0, 1fr); }
.workflow-library-body > aside { padding: 14px 10px; background: color-mix(in srgb, var(--workflow-surface-muted) 86%, var(--workflow-bg)); }
.workflow-list-title { padding: 0 8px 10px; }
.workflow-list-title span { color: var(--workflow-text); font-size: 12px; font-weight: 650; }
.workflow-list-title small { color: var(--workflow-muted); font-size: 10px; }
.workflow-library-body aside button { margin: 2px 0; border: 1px solid transparent; border-radius: 7px; }
.workflow-library-body aside button.active { border-color: rgba(79,156,249,.34); background: rgba(37,99,235,.14); box-shadow: inset 3px 0 0 var(--workflow-focus); }
.workflow-library-body aside button strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-library-body aside button small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-studio-grid { grid-template-columns: var(--workflow-catalog-width, 224px) minmax(0, 1fr) 312px; grid-template-rows: auto auto auto auto minmax(0, 1fr); gap: 0; min-width: 0; min-height: 0; height: 100%; overflow: hidden; background: var(--workflow-bg); }
.workflow-metadata-editor, .workflow-input-editor, .workflow-runtime-inputs { min-width: 0; background: var(--workflow-surface); border-bottom: 1px solid var(--workflow-border); }
.workflow-metadata-editor { grid-column: 1 / -1; grid-row: 1; grid-template-columns: minmax(220px,.75fr) minmax(280px,1.25fr); gap: 8px 16px; padding: 10px 18px; }
.workflow-contract-heading { grid-column: 1 / -1; display: flex; align-items: center; gap: 9px; min-width: 0; }
.workflow-section-kicker { color: var(--workflow-focus); font-size: 10px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; }
.workflow-contract-heading strong { overflow: hidden; min-width: 0; color: var(--workflow-text); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.workflow-contract-status { margin-left: auto; padding: 3px 7px; border: 1px solid rgba(45,212,163,.26); border-radius: 999px; color: #86efac; background: rgba(16,185,129,.1); font-size: 10px; white-space: nowrap; }
.workflow-contract-status.dirty { border-color: rgba(240,180,77,.34); color: #fcd34d; background: rgba(180,83,9,.12); }
.workflow-metadata-editor label { font-size: 10px; }
.workflow-metadata-editor input { min-height: 30px; }
.workflow-input-editor { grid-column: 1 / -1; padding: 9px 16px; overflow: auto; }
.workflow-input-editor .panel-heading { min-height: 26px; }
.workflow-input-definitions { gap: 6px; }
.workflow-input-definition { gap: 6px; padding: 6px; border-radius: 6px; }
.workflow-input-definition input:not([type='checkbox']), .workflow-input-definition select { min-height: 28px; padding: 5px 6px; }
.workflow-runtime-inputs { grid-column: 1 / -1; padding: 9px 16px; overflow: auto; }
.workflow-runtime-inputs .workflow-input-values { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px 12px; }
.workflow-runtime-inputs .workflow-input-values > label { min-width: 0; margin: 0; }
.workflow-action-catalog, .workflow-properties { min-height: 0; overflow: auto; border: 0; border-radius: 0; background: var(--workflow-surface-muted); }
.workflow-action-catalog { position: relative; grid-column: 1; grid-row: 5; padding: 14px 12px; border-right: 1px solid var(--workflow-border); }
.workflow-properties { grid-column: 3; grid-row: 5; padding: 14px 16px 22px; border-left: 1px solid var(--workflow-border); }
.workflow-properties.workflow-empty { display: grid; place-items: center; color: var(--workflow-muted); text-align: center; }
.workflow-canvas { grid-column: 2; grid-row: 5; min-width: 0; min-height: 0; padding: 12px 14px 14px; background: var(--workflow-bg); }
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

@media (max-width: 1180px) {
  .workflow-studio-grid { grid-template-columns: var(--workflow-catalog-width, 200px) minmax(300px, 1fr) var(--workflow-properties-width, 312px); }
  .workflow-library-toolbar { padding-left: 14px; padding-right: 14px; }
  .workflow-library-toolbar .toolbar-group-secondary > button:not(.icon-toolbar-button) { font-size: 0; gap: 0; }
  .workflow-library-toolbar .toolbar-group-secondary > button:not(.icon-toolbar-button) svg { width: 15px; height: 15px; }
}
@media (max-width: 980px) {
  .workflow-library-body { grid-template-columns: 190px minmax(0, 1fr); }
  .workflow-studio-grid { grid-template-columns: minmax(170px, var(--workflow-catalog-width, 220px)) minmax(0, 1fr); grid-template-rows: auto auto auto auto minmax(420px, 1fr) auto; overflow: auto; }
  .workflow-action-catalog { grid-column: 1; grid-row: 5; }
  .workflow-canvas { grid-column: 2; grid-row: 5; min-height: 420px; }
  .workflow-properties { grid-column: 1 / -1; grid-row: 6; min-height: 240px; max-height: none; border-top: 1px solid var(--workflow-border); border-left: 0; }
  .workflow-properties-resizer { display: none; }
  .workflow-library-toolbar { align-items: center; }
  .workflow-run-target { order: 9; }
  .toolbar-group-actions { margin-left: auto; }
}
@media (max-width: 720px) {
  .workflow-library { min-width: 0; }
  .workflow-library-header { padding: 10px 14px; }
  .workflow-library-toolbar { gap: 5px; padding: 8px 12px; }
  .workflow-library-toolbar .toolbar-divider, .toolbar-group-secondary, .toolbar-group-export { display: none; }
  .workflow-library-body { grid-template-columns: 1fr; }
  .workflow-library-body > aside { max-height: 150px; border-right: 0; border-bottom: 1px solid var(--workflow-border); }
  .workflow-studio-grid { grid-template-columns: 1fr; grid-template-rows: auto auto auto auto 420px auto; }
  .workflow-action-catalog, .workflow-canvas, .workflow-properties { grid-column: 1; }
  .workflow-action-catalog { grid-row: 5; }
  .workflow-canvas { grid-row: 6; min-height: 420px; }
  .workflow-properties { grid-row: 7; }
  .workflow-metadata-editor { grid-template-columns: 1fr; }
  .workflow-input-definition, .workflow-output-definition { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .workflow-input-definition .workflow-input-description, .workflow-output-definition .workflow-input-description { grid-column: 1 / -1; }
  .workflow-run-target { width: 100%; margin-left: 0; }
  .workflow-run-target select { flex: 1; max-width: none; }
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



/* Restore intentional scroll regions after the compact studio layout. */
.workflow-library-body,
.workflow-studio-grid { min-height: 0; }
.workflow-studio-grid {
  height: 100%;
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: #475569 rgba(15, 23, 42, .35);
}
.workflow-studio-grid::-webkit-scrollbar,
.workflow-action-catalog::-webkit-scrollbar,
.workflow-properties::-webkit-scrollbar,
.workflow-input-editor::-webkit-scrollbar,
.workflow-runtime-inputs::-webkit-scrollbar,
.workflow-script-template-dialog::-webkit-scrollbar,
.workflow-script-template-preview code::-webkit-scrollbar { width: 9px; height: 9px; }
.workflow-studio-grid::-webkit-scrollbar-track,
.workflow-action-catalog::-webkit-scrollbar-track,
.workflow-properties::-webkit-scrollbar-track,
.workflow-input-editor::-webkit-scrollbar-track,
.workflow-runtime-inputs::-webkit-scrollbar-track,
.workflow-script-template-dialog::-webkit-scrollbar-track,
.workflow-script-template-preview code::-webkit-scrollbar-track { background: rgba(15, 23, 42, .28); }
.workflow-studio-grid::-webkit-scrollbar-thumb,
.workflow-action-catalog::-webkit-scrollbar-thumb,
.workflow-properties::-webkit-scrollbar-thumb,
.workflow-input-editor::-webkit-scrollbar-thumb,
.workflow-runtime-inputs::-webkit-scrollbar-thumb,
.workflow-script-template-dialog::-webkit-scrollbar-thumb,
.workflow-script-template-preview code::-webkit-scrollbar-thumb { border: 2px solid transparent; border-radius: 999px; background: #475569; background-clip: padding-box; }
.workflow-studio-grid::-webkit-scrollbar-thumb:hover,
.workflow-action-catalog::-webkit-scrollbar-thumb:hover,
.workflow-properties::-webkit-scrollbar-thumb:hover,
.workflow-input-editor::-webkit-scrollbar-thumb:hover,
.workflow-runtime-inputs::-webkit-scrollbar-thumb:hover,
.workflow-script-template-dialog::-webkit-scrollbar-thumb:hover,
.workflow-script-template-preview code::-webkit-scrollbar-thumb:hover { background: #64748b; background-clip: padding-box; }
.workflow-action-catalog,
.workflow-properties { scrollbar-gutter: stable; scrollbar-width: thin; scrollbar-color: #475569 rgba(15, 23, 42, .28); }
.workflow-input-editor,
.workflow-runtime-inputs { scrollbar-gutter: stable; scrollbar-width: thin; }
:global(:root[data-theme="light"]) .workflow-studio-grid { scrollbar-color: #94a3b8 #e2e8f0; }
:global(:root[data-theme="light"]) .workflow-studio-grid::-webkit-scrollbar-track,
:global(:root[data-theme="light"]) .workflow-action-catalog::-webkit-scrollbar-track,
:global(:root[data-theme="light"]) .workflow-properties::-webkit-scrollbar-track,
:global(:root[data-theme="light"]) .workflow-input-editor::-webkit-scrollbar-track,
:global(:root[data-theme="light"]) .workflow-runtime-inputs::-webkit-scrollbar-track { background: #e2e8f0; }
:global(:root[data-theme="light"]) .workflow-studio-grid::-webkit-scrollbar-thumb,
:global(:root[data-theme="light"]) .workflow-action-catalog::-webkit-scrollbar-thumb,
:global(:root[data-theme="light"]) .workflow-properties::-webkit-scrollbar-thumb,
:global(:root[data-theme="light"]) .workflow-input-editor::-webkit-scrollbar-thumb,
:global(:root[data-theme="light"]) .workflow-runtime-inputs::-webkit-scrollbar-thumb { background: #94a3b8; background-clip: padding-box; }

.workflow-library-body > main.workflow-studio-grid {
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow: hidden;
}

.workflow-action-catalog,
.workflow-properties {
  min-width: 0;
  min-height: 0;
  height: auto;
  max-height: 100%;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
}

/* Keep the canvas full height; workflow contract editors live in the scrollable right rail. */
.workflow-studio-grid {
  grid-template-columns: var(--workflow-catalog-width, 224px) minmax(0, 1fr) var(--workflow-properties-width, 312px);
  grid-template-rows: minmax(0, 1fr);
}
.workflow-right-rail {
  grid-column: 3;
  grid-row: 1;
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  border-left: 1px solid var(--workflow-border);
  background: var(--workflow-surface-muted);
  scrollbar-gutter: stable;
  scrollbar-width: thin;
}
.workflow-right-rail > .workflow-metadata-editor,
.workflow-right-rail > .workflow-input-editor,
.workflow-right-rail > .workflow-runtime-inputs,
.workflow-right-rail > .workflow-properties {
  position: static;
  width: auto;
  max-height: none;
  box-sizing: border-box;
}
.workflow-metadata-editor,
.workflow-input-editor,
.workflow-runtime-inputs {
  display: grid;
  grid-column: auto;
  grid-row: auto;
  overflow: visible;
  border-left: 0;
}
.workflow-metadata-editor {
  display: grid;
  grid-template-columns: 1fr;
  gap: 8px;
  padding: 14px 16px 10px;
}
.workflow-input-editor,
.workflow-runtime-inputs {
  padding: 9px 16px;
}
.workflow-action-catalog,
.workflow-canvas,
.workflow-properties {
  grid-row: 1;
}
.workflow-canvas {
  grid-column: 2;
}
.workflow-properties {
  display: grid;
  grid-column: auto;
  grid-row: auto;
  max-height: none;
  overflow: visible;
  border-left: 0;
}
.workflow-properties-resizer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 8;
  display: grid;
  width: 12px;
  place-items: center;
  color: rgba(148, 163, 184, .42);
  background: transparent;
  cursor: col-resize;
  touch-action: none;
}
.workflow-properties-resizer:hover,
.workflow-properties-resizer.active { color: #60a5fa; }
.workflow-properties-resizer::before { content: ''; position: absolute; inset: 0 5px; border-left: 1px solid transparent; }
.workflow-properties-resizer:hover::before,
.workflow-properties-resizer.active::before { border-color: rgba(96, 165, 250, .7); }

/* Final studio layout: three columns, one scrollable inspector rail. */
.workflow-library-body > main.workflow-studio-grid {
  position: relative;
  display: grid;
  grid-template-columns: var(--workflow-catalog-width, 224px) minmax(0, 1fr) var(--workflow-properties-width, 312px);
  grid-template-rows: minmax(0, 1fr);
  height: 100%;
  overflow: hidden;
}
.workflow-studio-grid {
  grid-template-columns: var(--workflow-catalog-width, 224px) minmax(320px, 1fr) var(--workflow-properties-width, 312px);
  grid-template-areas: 'catalog canvas inspector';
}
.workflow-studio-grid > .workflow-action-catalog {
  grid-area: catalog;
  grid-column: 1;
  grid-row: 1;
  min-height: 0;
  overflow-y: auto;
}
.workflow-studio-grid > .workflow-canvas {
  grid-area: canvas;
  grid-column: 2;
  grid-row: 1;
  min-height: 0;
  overflow: hidden;
}
.workflow-studio-grid > .workflow-right-rail {
  grid-area: inspector;
  grid-column: 3;
  grid-row: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  position: relative;
  border-left: 1px solid var(--workflow-border);
  background: var(--workflow-surface-muted);
}
.workflow-studio-grid > .workflow-properties,
.workflow-studio-grid > .workflow-properties.workflow-empty {
  position: static;
  grid-column: 3;
  grid-row: 1;
  width: auto;
  max-width: none;
  z-index: auto;
  overflow: visible;
  pointer-events: auto;
  opacity: 1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  border-left: 1px solid var(--workflow-border);
  background: var(--workflow-surface-muted);
}
.workflow-right-rail > .workflow-metadata-editor,
.workflow-right-rail > .workflow-input-editor,
.workflow-right-rail > .workflow-runtime-inputs,
.workflow-right-rail > .workflow-properties,
.workflow-right-rail > .workflow-properties.workflow-empty {
  position: static;
  display: grid;
  flex: 0 0 auto;
  width: auto;
  max-height: none;
  min-height: auto;
  overflow: visible;
  border-left: 0;
  border-right: 0;
}
.workflow-right-rail > .workflow-metadata-editor { grid-template-columns: 1fr; }
.workflow-right-rail > .workflow-properties { order: 10; }
.workflow-right-rail > .workflow-properties-resizer {
  position: absolute;
  top: 0;
  left: -7px;
  bottom: 0;
  z-index: 20;
}
.workflow-right-rail > .workflow-metadata-editor,
.workflow-right-rail > .workflow-input-editor,
.workflow-right-rail > .workflow-runtime-inputs,
.workflow-right-rail > .workflow-properties {
  margin: 0;
  padding: 16px;
  border-bottom: 1px solid color-mix(in srgb, var(--workflow-border) 78%, transparent);
  background: transparent;
}
.workflow-right-rail > .workflow-metadata-editor { padding-top: 18px; }
.workflow-right-rail > .workflow-properties { padding-bottom: 24px; }
.workflow-right-rail .panel-heading {
  position: static;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  margin: 0 0 12px;
  padding: 0;
  background: transparent;
}
.workflow-right-rail .panel-heading > div { min-width: 0; }
.workflow-input-compact { min-height: 48px; }
.workflow-input-compact.expanded { min-height: 0; }
.workflow-section-toggle { display: inline-flex; align-items: center; gap: 8px; min-width: 0; padding: 0; border: 0; color: inherit; background: transparent; cursor: pointer; text-align: left; }
.workflow-section-toggle strong { color: var(--workflow-text); font-size: 12px; }
.workflow-section-toggle small { color: var(--workflow-muted); font-size: 10px; }
.workflow-section-toggle span { color: var(--workflow-focus); font-size: 10px; }
.workflow-right-rail .panel-heading strong { color: var(--workflow-text); font-size: 12px; }
.workflow-right-rail .panel-heading small { color: var(--workflow-muted); font-size: 10px; }
.workflow-right-rail label { min-width: 0; }
.workflow-right-rail input:not([type='checkbox']),
.workflow-right-rail select,
.workflow-right-rail textarea { box-sizing: border-box; width: 100%; max-width: none; }
.workflow-right-rail .workflow-input-definition {
  grid-template-columns: minmax(0, 1fr) minmax(90px, .7fr) auto;
  gap: 8px;
}
.workflow-right-rail .workflow-input-definition .workflow-input-description,
.workflow-right-rail .workflow-output-definition .workflow-input-description,
.workflow-right-rail .workflow-output-value { grid-column: 1 / -1; }
.workflow-right-rail .workflow-output-definition { grid-template-columns: minmax(0, 1fr) minmax(90px, .7fr) auto; }
.workflow-right-rail .workflow-runtime-inputs .workflow-input-values { grid-template-columns: 1fr; gap: 10px; }
.workflow-right-rail .workflow-script-field { margin: 0; }
.workflow-right-rail .remove-node-button,
.workflow-right-rail .connect-button,
.workflow-right-rail .workflow-script-test-button { min-height: 34px; }
.workflow-studio-grid > .workflow-catalog-resizer {
  position: absolute;
  left: var(--workflow-catalog-width, 224px);
  right: auto;
}
.workflow-studio-grid > .workflow-properties-resizer {
  position: absolute;
  left: calc(100% - var(--workflow-properties-width, 312px));
  right: auto;
}

/* Resolve the inspector as a real third grid column; never paint it over the canvas. */
.workflow-library-body > main.workflow-studio-grid {
  grid-template-columns: var(--workflow-catalog-width, 224px) minmax(320px, 1fr) var(--workflow-properties-width, 312px);
  grid-template-rows: auto auto auto auto minmax(0, 1fr);
  grid-template-areas: none;
  overflow: hidden;
}
.workflow-studio-grid > .workflow-right-rail {
  display: contents;
}
.workflow-studio-grid > .workflow-right-rail > .workflow-metadata-editor,
.workflow-studio-grid > .workflow-right-rail > .workflow-input-editor,
.workflow-studio-grid > .workflow-right-rail > .workflow-runtime-inputs {
  grid-column: 3;
  min-width: 0;
  max-height: none;
  overflow: visible;
}
.workflow-studio-grid > .workflow-right-rail > .workflow-metadata-editor { grid-row: 1; }
.workflow-studio-grid > .workflow-right-rail > .workflow-input-editor:not(.workflow-output-editor) { grid-row: 2; }
.workflow-studio-grid > .workflow-right-rail > .workflow-output-editor { grid-row: 3; }
.workflow-studio-grid > .workflow-right-rail > .workflow-runtime-inputs { grid-row: 4; }
.workflow-studio-grid > .workflow-action-catalog {
  grid-column: 1;
  grid-row: 1 / -1;
  min-height: 0;
  overflow-y: auto;
}
.workflow-studio-grid > .workflow-canvas {
  grid-column: 2;
  grid-row: 1 / -1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
.workflow-studio-grid > .workflow-properties,
.workflow-studio-grid > .workflow-properties.workflow-empty {
  position: static;
  grid-column: 3;
  grid-row: 5;
  width: auto;
  max-width: none;
  min-width: 0;
  min-height: 0;
  max-height: none;
  overflow-x: hidden;
  overflow-y: auto;
  pointer-events: auto;
  opacity: 1;
  border-left: 0;
  background: var(--workflow-surface-muted);
}
.workflow-studio-grid > .workflow-properties-resizer {
  position: absolute;
  left: calc(100% - var(--workflow-properties-width, 312px));
  right: auto;
  top: 0;
  bottom: 0;
}

.workflow-catalog-resizer {
  position: absolute;
  top: 0;
  right: -6px;
  bottom: 0;
  z-index: 8;
  display: grid;
  width: 12px;
  place-items: center;
  border: 0;
  color: rgba(148, 163, 184, .42);
  background: transparent;
  cursor: col-resize;
  touch-action: none;
}
.workflow-catalog-resizer:hover,
.workflow-catalog-resizer.active { color: #60a5fa; }
.workflow-catalog-resizer::before { content: ''; position: absolute; inset: 0 5px; border-right: 1px solid transparent; }
.workflow-catalog-resizer:hover::before,
.workflow-catalog-resizer.active::before { border-color: rgba(96, 165, 250, .7); }

@media (max-width: 720px) {
  .workflow-catalog-resizer,
  .workflow-properties-resizer { display: none; }
}

/* Context switch: keep workflow contract and step settings in separate views. */
.workflow-right-rail-switcher {
  display: flex;
  align-items: center;
  gap: 4px;
  grid-column: 3;
  grid-row: 1;
  min-width: 0;
  margin: 0;
  padding: 10px 12px;
  border-bottom: 1px solid var(--workflow-border);
  background: var(--workflow-surface);
}
.workflow-right-rail-switcher button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-width: 0;
  flex: 1;
  min-height: 30px;
  padding: 0 8px;
  color: var(--workflow-muted);
  border: 1px solid transparent;
  border-radius: 5px;
  background: transparent;
  cursor: pointer;
  font-size: 11px;
}
.workflow-right-rail-switcher button:hover:not(:disabled) { color: var(--workflow-text); background: color-mix(in srgb, var(--workflow-focus) 8%, transparent); }
.workflow-right-rail-switcher button.active { color: var(--workflow-focus); border-color: color-mix(in srgb, var(--workflow-focus) 34%, var(--workflow-border)); background: color-mix(in srgb, var(--workflow-focus) 12%, transparent); font-weight: 650; }
.workflow-right-rail-switcher button:disabled { opacity: .4; cursor: default; }
.workflow-studio-grid.step-settings-mode > .workflow-properties { grid-row: 2 / -1; }
.workflow-studio-grid:not(.flow-test-mode) > .workflow-right-rail > .workflow-metadata-editor { grid-row: 2; }
.workflow-studio-grid:not(.flow-test-mode) > .workflow-right-rail > .workflow-input-editor:not(.workflow-output-editor) { grid-row: 3; }
.workflow-studio-grid:not(.flow-test-mode) > .workflow-right-rail > .workflow-output-editor { grid-row: 4; }
.workflow-studio-grid:not(.flow-test-mode) > .workflow-right-rail > .workflow-runtime-inputs { grid-row: 5; }
.workflow-studio-grid.step-settings-mode > .workflow-right-rail {
  display: flex;
  flex-direction: column;
  grid-column: 3;
  grid-row: 1 / -1;
  min-height: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: #64748b rgba(15, 23, 42, .28);
}
.workflow-studio-grid.step-settings-mode > .workflow-right-rail > .workflow-right-rail-switcher {
  position: sticky;
  top: 0;
  z-index: 3;
  flex: 0 0 auto;
}
.workflow-studio-grid.step-settings-mode > .workflow-right-rail > .workflow-properties {
  display: grid;
  grid-column: auto;
  grid-row: auto;
  box-sizing: border-box;
  width: auto;
  height: auto;
  flex: 0 0 auto;
  min-height: max-content;
  max-height: none;
  overflow: visible;
}
:global(:root[data-theme="light"]) .workflow-studio-grid.step-settings-mode > .workflow-right-rail { scrollbar-color: #94a3b8 #e2e8f0; }
</style>
