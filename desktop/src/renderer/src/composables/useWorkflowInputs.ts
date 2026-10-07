import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { defaultWorkflowInputValue, normalizeStructuredInputValue } from '../components/workflow/workflow-inputs'

export type WorkflowInputDefinition = { name: string; type?: string; control?: string | { id: string; props?: Record<string, unknown> }; required?: boolean; default?: unknown; description?: string }
export type WorkflowOutputDefinition = { name: string; value?: unknown; type?: string; primitiveType?: string; presentation?: string; semanticType?: string; description?: string }
export type WorkflowNodeDefinition = { action_id: string; config: Record<string, unknown>; input_mapping?: Record<string, unknown> }
export type WorkflowInputWorkflow = { inputs?: WorkflowInputDefinition[]; outputs?: WorkflowOutputDefinition[]; nodes?: WorkflowNodeDefinition[] }
export type WorkflowInputIssue = { code: string; message: string }

interface WorkflowInputContext {
  selected: Ref<WorkflowInputWorkflow | null>
  selectedNode: Ref<{ action_id: string; config: Record<string, unknown> } | null>
  issues: Ref<WorkflowInputIssue[]>
  error: Ref<string>
  runMessage: Ref<string>
  transferRoot: ComputedRef<string>
}

export function useWorkflowInputs(context: WorkflowInputContext) {
  const { selected, selectedNode, issues, error, runMessage, transferRoot } = context
  const workflowInputValues = ref<Record<string, unknown>>({})
  const workflowInputTouched = ref(new Set<string>())

  function initializeWorkflowInputValues(workflow: WorkflowInputWorkflow | null): void {
    const values: Record<string, unknown> = {}
    for (const input of workflow?.inputs || []) {
      const name = String(input.name || '').trim()
      if (name) values[name] = defaultWorkflowInputValue(input)
    }
    workflowInputValues.value = values
    workflowInputTouched.value = new Set()
  }

  function addWorkflowInput(): void {
    if (!selected.value) return
    const inputs = selected.value.inputs || []
    const names = new Set(inputs.map((input) => String(input.name || '').trim()))
    let index = inputs.length + 1
    while (names.has(`input_${index}`)) index += 1
    selected.value.inputs = [...inputs, { name: `input_${index}`, type: 'string', required: false, description: '' }]
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
    selected.value.outputs = [...outputs, { name: `output_${index}`, value: '', type: 'any', description: '' }]
    invalidateOutputValidation()
  }

  function removeWorkflowOutput(index: number): void {
    if (!selected.value) return
    selected.value.outputs = (selected.value.outputs || []).filter((_, itemIndex) => itemIndex !== index)
    invalidateOutputValidation()
  }

  function invalidateOutputValidation(): void {
    // Diagnostics describe the previous snapshot; execution validates again.
    issues.value = []
    error.value = ''
    runMessage.value = ''
  }

  function updateWorkflowOutput(index: number, field: keyof WorkflowOutputDefinition, value: unknown): void {
    if (!selected.value?.outputs?.[index]) return
    const outputs = [...selected.value.outputs]
    outputs[index] = { ...outputs[index], [field]: value }
    if (field === 'type') outputs[index].primitiveType = String(value)
    if (field === 'presentation') outputs[index].semanticType = value === 'download' ? 'file' : value === 'json' || value === 'table' ? 'json' : 'text'
    selected.value.outputs = outputs
    invalidateOutputValidation()
  }

  function updateWorkflowInputDefinition(index: number, field: keyof WorkflowInputDefinition, value: unknown): void {
    if (!selected.value?.inputs?.[index]) return
    const inputs = [...selected.value.inputs]
    inputs[index] = { ...inputs[index], [field]: value }
    selected.value.inputs = inputs
    if (field === 'name') initializeWorkflowInputValues(selected.value)
  }

  const workflowRuntimeInputs = computed<Record<string, unknown>>(() => {
    const inputs = selected.value?.inputs || []
    return Object.fromEntries(inputs.filter((input) => String(input.name || '').trim()).filter((input) => {
      const value = workflowInputValues.value[input.name]
      return (value !== undefined && value !== null && value !== '') || input.required || (input.default !== undefined && input.default !== null) || workflowInputTouched.value.has(input.name)
    }).map((input) => [input.name, workflowInputValues.value[input.name] ?? '']))
  })

  function isWorkflowFileInput(input: WorkflowInputDefinition): boolean {
    if (input.control === 'file' || input.type === 'file' || input.name === 'package_path') return true
    const references = [`${'${inputs.'}${input.name}}`, `${'${'}${input.name}}`]
    return (selected.value?.nodes || []).some((node) => node.action_id === 'file.upload' && references.includes(String(node.input_mapping?.source ?? node.input_mapping?.source_path ?? node.config.source ?? node.config.source_path ?? '')))
  }

  function normalizeWorkflowPath(value: string): string {
    let normalized = value.trim().replace(/\\/g, '/')
    while (normalized.startsWith('./')) normalized = normalized.slice(2)
    return normalized
  }

  function workflowInputDisplay(input: WorkflowInputDefinition): string {
    const value = workflowInputValues.value[input.name]
    if (input.type === 'object' || input.type === 'array') {
      if (value === '' || value === undefined || value === null) return ''
      return typeof value === 'string' ? String(normalizeStructuredInputValue(value, input.type)) : JSON.stringify(value)
    }
    return String(value ?? '')
  }

  function updateWorkflowInput(name: string, event: Event): void {
    const input = selected.value?.inputs?.find((item) => item.name === name)
    if (!input) return
    const target = event.target as HTMLInputElement | HTMLTextAreaElement
    const rawValue = input.type === 'boolean' ? (target as HTMLInputElement).checked : target.value
    let value: unknown = rawValue
    if (typeof rawValue === 'string' && isWorkflowFileInput(input)) value = normalizeWorkflowPath(rawValue)
    if (input.type === 'number' || input.type === 'integer') value = target.value === '' ? '' : Number(target.value)
    workflowInputValues.value = { ...workflowInputValues.value, [name]: value }
    workflowInputTouched.value = new Set([...workflowInputTouched.value, name])
  }

  function normalizeWorkflowInputJson(name: string): void {
    const input = selected.value?.inputs?.find((item) => item.name === name)
    const current = workflowInputValues.value[name]
    if (!input || (input.type !== 'object' && input.type !== 'array') || typeof current !== 'string' || current.trim() === '') return
    try { workflowInputValues.value = { ...workflowInputValues.value, [name]: normalizeStructuredInputValue(current, input.type) } } catch { /* preserve invalid JSON for correction */ }
  }

  async function chooseWorkflowRuntimeFile(input: WorkflowInputDefinition): Promise<void> {
    try {
      const selectedPath = await window.desktopApi.chooseWorkflowFile({ defaultPath: transferRoot.value, label: input.name === 'package_path' ? '软件包' : 'Workflow 文件', extensions: input.name === 'package_path' ? ['cc'] : [] })
      if (!selectedPath) return
      workflowInputValues.value = { ...workflowInputValues.value, [input.name]: normalizeWorkflowPath(selectedPath) }
      workflowInputTouched.value = new Set([...workflowInputTouched.value, input.name])
      runMessage.value = `已选择文件：${selectedPath}`
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  }

  function workflowInputHasIssue(name: string): boolean {
    return issues.value.some((issue) => (issue.code === 'missing_workflow_input' || issue.code === 'invalid_workflow_input_type') && issue.message.includes(name))
  }

  return {
    workflowInputValues, workflowInputTouched, workflowRuntimeInputs,
    initializeWorkflowInputValues, addWorkflowInput, removeWorkflowInput, addWorkflowOutput,
    removeWorkflowOutput, updateWorkflowOutput, updateWorkflowInputDefinition,
    workflowInputDisplay, isWorkflowFileInput, updateWorkflowInput, normalizeWorkflowInputJson,
    chooseWorkflowRuntimeFile, workflowInputHasIssue, normalizeWorkflowPath
  }
}
