import { computed, ref, watch, type Ref } from 'vue'
import { desktopApi } from '../transport/api'
import type { TaskRecord, WorkflowScript, WorkflowScriptInput, WorkflowScriptInputType } from '../types'

export type WorkflowScriptTemplate = {
  id: string
  name: string
  description: string
  language: WorkflowScript['language']
  script: string
  input_schema: WorkflowScriptInput[]
}

export type WorkflowScriptTestResult = { task?: TaskRecord; message?: string }

export const workflowScriptInputTypes: WorkflowScriptInputType[] = ['string', 'number', 'boolean', 'object', 'array']

export const workflowScriptTemplates: WorkflowScriptTemplate[] = [
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

export function workflowScriptSnapshot(script: WorkflowScript): string {
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
      type: workflowScriptInputTypes.includes(item?.type) ? item.type : 'string',
      ...(item?.required ? { required: true } : {}),
      ...(Object.prototype.hasOwnProperty.call(item || {}, 'default') ? { default: item.default } : {}),
      ...(item?.description ? { description: String(item.description) } : {})
    }))
  }
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

export function useWorkflowScripts(options: {
  selectedDeviceId: Ref<string>
  studioMode: Ref<'flow' | 'scripts'>
  setError: (message: string) => void
  setRunMessage: (message: string) => void
}) {
  const scripts = ref<WorkflowScript[]>([])
  const selectedScriptId = ref('')
  const scriptSaving = ref(false)
  const scriptTesting = ref(false)
  const scriptTestConfirmed = ref(false)
  const scriptTestInputs = ref('{}')
  const scriptTestMode = ref<'form' | 'json'>('form')
  const scriptTestValues = ref<Record<string, unknown>>({})
  const scriptTestInputError = ref('')
  const scriptTestResult = ref<WorkflowScriptTestResult | null>(null)
  const savedScriptSnapshots = ref<Record<string, string>>({})
  const showScriptTemplateDialog = ref(false)
  const selectedScriptTemplateId = ref('python-main')
  const scriptCreateName = ref('')
  const scriptCreateDescription = ref('')
  const scriptCreating = ref(false)
  let scriptTestRequestId = 0

  const selectedScript = computed(() => scripts.value.find((item) => item.id === selectedScriptId.value) || null)
  const selectedScriptTemplate = computed(() => workflowScriptTemplates.find((item) => item.id === selectedScriptTemplateId.value) || workflowScriptTemplates[0])
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
      if (!workflowScriptInputTypes.includes(parameter.type)) return `参数“${name}”的类型无效`
    }
    return ''
  })
  const hasUnsavedScriptChanges = computed(() => Boolean(
    selectedScript.value && workflowScriptSnapshot(selectedScript.value) !== savedScriptSnapshots.value[selectedScript.value.id]
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

  async function loadWorkflowScripts(preferredId = ''): Promise<void> {
    const result = await desktopApi.workflowScripts()
    scripts.value = result.scripts.map(normalizeWorkflowScript)
    savedScriptSnapshots.value = Object.fromEntries(result.scripts.map((item) => [item.id, workflowScriptSnapshot(item)]))
    const nextId = preferredId || selectedScriptId.value
    selectedScriptId.value = scripts.value.some((item) => item.id === nextId) ? nextId : (scripts.value[0]?.id || '')
    synchronizeScriptTestValues()
  }

  function openScriptStudio(scriptId = selectedScriptId.value): void {
    options.studioMode.value = 'scripts'
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
      savedScriptSnapshots.value[result.script.id] = workflowScriptSnapshot(result.script)
      selectedScriptId.value = result.script.id
      synchronizeScriptTestValues()
      showScriptTemplateDialog.value = false
      options.studioMode.value = 'scripts'
    } catch (cause) {
      options.setError(cause instanceof Error ? cause.message : String(cause))
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
      savedScriptSnapshots.value[result.script.id] = workflowScriptSnapshot(result.script)
      selectedScriptId.value = result.script.id
      synchronizeScriptTestValues()
    } catch (cause) {
      options.setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  async function saveScriptResource(script: WorkflowScript): Promise<boolean> {
    const invalidParameter = script.input_schema.some((parameter) => !String(parameter.name || '').trim())
    const validationMessage = !script.name.trim() ? '脚本名称不能为空' : invalidParameter ? '每个输入参数都需要名称' : ''
    if (validationMessage) {
      options.setError(validationMessage)
      return false
    }
    scriptSaving.value = true
    try {
      const result = await desktopApi.saveWorkflowScript(script.id, script)
      const index = scripts.value.findIndex((item) => item.id === result.script.id)
      if (index >= 0) scripts.value[index] = normalizeWorkflowScript(result.script)
      savedScriptSnapshots.value[result.script.id] = workflowScriptSnapshot(result.script)
      options.setRunMessage('脚本已保存。')
      return true
    } catch (cause) {
      options.setError(cause instanceof Error ? cause.message : String(cause))
      return false
    } finally {
      scriptSaving.value = false
    }
  }

  async function saveWorkflowScript(): Promise<boolean> {
    if (!selectedScript.value || scriptValidationMessage.value) {
      if (scriptValidationMessage.value) options.setError(scriptValidationMessage.value)
      return false
    }
    return saveScriptResource(selectedScript.value)
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
      options.setError(cause instanceof Error ? cause.message : String(cause))
    }
  }

  async function testWorkflowScript(): Promise<void> {
    if (!selectedScript.value || !options.selectedDeviceId.value || !scriptTestConfirmed.value) return
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
        device_id: options.selectedDeviceId.value,
        protocol: 'simulated',
        inputs,
        confirmed_risks: true
      })
      scriptTestResult.value = result
      if (!result.task?.id) {
        options.setRunMessage('脚本测试已提交。')
        return
      }
      options.setRunMessage(`脚本测试任务已创建：${result.task.id}`)
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

  function cancelScriptTaskMonitoring(): void {
    scriptTestRequestId += 1
  }

  return {
    scripts,
    selectedScriptId,
    selectedScript,
    scriptSaving,
    scriptTesting,
    scriptTestConfirmed,
    scriptTestInputs,
    scriptTestMode,
    scriptTestValues,
    scriptTestInputError,
    scriptTestResult,
    scriptTestDetails,
    savedScriptSnapshots,
    showScriptTemplateDialog,
    selectedScriptTemplateId,
    selectedScriptTemplate,
    scriptCreateName,
    scriptCreateDescription,
    scriptCreating,
    scriptValidationMessage,
    hasUnsavedScriptChanges,
    loadWorkflowScripts,
    openScriptStudio,
    createWorkflowScript,
    confirmCreateWorkflowScript,
    duplicateWorkflowScript,
    saveScriptResource,
    saveWorkflowScript,
    deleteWorkflowScript,
    testWorkflowScript,
    cancelScriptTaskMonitoring,
    scriptTestValueText,
    scriptDefaultText,
    updateScriptInputField,
    updateScriptDefault,
    updateScriptTestValue,
    addScriptInput,
    removeScriptInput,
    eventValue,
    eventChecked
  }
}
