import { computed, type Ref } from 'vue'
import { desktopApi } from '../transport/api'

export interface WorkflowConfigNode {
  id: string
  action_id: string
  config: Record<string, unknown>
}

export interface WorkflowConfigEdge { source: string; target: string; source_handle?: string }
export interface WorkflowConfigInput { name: string; default?: unknown }
export interface WorkflowConfigOutput { name: string }
export interface WorkflowConfigVersion {
  id: string
  name: string
  version: string | number
  inputs?: WorkflowConfigInput[]
  outputs?: WorkflowConfigOutput[]
}
export interface WorkflowConfigAction {
  id: string
  label: string
  outputFields?: Array<{ name: string; label: string }>
}

interface NodeConfigContext {
  selected: Ref<{ inputs?: WorkflowConfigInput[]; nodes?: WorkflowConfigNode[]; edges?: WorkflowConfigEdge[] } | null>
  selectedNode: Ref<WorkflowConfigNode | null>
  actions: WorkflowConfigAction[]
  actionsRevision: Ref<number>
  publishedWorkflows: Ref<WorkflowConfigVersion[]>
  subworkflowVersions: Ref<WorkflowConfigVersion[]>
  fieldLabel: (name: string) => string
}

export function useWorkflowNodeConfig(context: NodeConfigContext) {
  const loopItemsMode = computed<'manual' | 'reference'>({
    get: () => context.selectedNode.value?.action_id === 'loop.for_each' && typeof context.selectedNode.value.config.items === 'string' ? 'reference' : 'manual',
    set: (mode) => {
      const node = context.selectedNode.value
      if (node?.action_id !== 'loop.for_each') return
      if (mode === 'reference') node.config.items = typeof node.config.items === 'string' ? node.config.items : ''
      else if (!Array.isArray(node.config.items)) node.config.items = []
    }
  })

  const loopItemsReference = computed<string>({
    get: () => context.selectedNode.value?.action_id === 'loop.for_each' && typeof context.selectedNode.value.config.items === 'string' ? context.selectedNode.value.config.items : '',
    set: (reference) => {
      if (context.selectedNode.value?.action_id === 'loop.for_each') context.selectedNode.value.config.items = reference
    }
  })

  function outputFieldsForAction(actionId: string): Array<{ name: string; label: string }> {
    return context.actions.find((action) => action.id === actionId)?.outputFields || []
  }

  function outputFieldsForNode(node: WorkflowConfigNode): Array<{ name: string; label: string }> {
    if (node.action_id !== 'workflow.call') return outputFieldsForAction(node.action_id)
    const workflowId = String(node.config.workflow_id || '')
    const version = String(node.config.version || '')
    const published = [...context.subworkflowVersions.value, ...context.publishedWorkflows.value]
      .find((item) => item.id === workflowId && String(item.version) === version)
    return (published?.outputs || []).map((item) => ({ name: item.name, label: context.fieldLabel(item.name) }))
  }

  const resultSources = computed(() => {
    void context.actionsRevision.value
    const workflow = context.selected.value
    const currentNode = context.selectedNode.value
    if (!workflow || !currentNode) return []
    const edges = workflow.edges || []
    const sourceIds = new Set<string>()
    const pending = edges.filter((edge) => edge.target === currentNode.id).map((edge) => edge.source)
    while (pending.length) {
      const sourceId = pending.pop()
      if (!sourceId || sourceIds.has(sourceId)) continue
      sourceIds.add(sourceId)
      pending.push(...edges.filter((edge) => edge.target === sourceId).map((edge) => edge.source))
    }
    return (workflow.nodes || [])
      .filter((item) => sourceIds.has(item.id) && item.action_id !== 'utility.condition')
      .map((item) => ({
        id: item.id,
        actionId: item.action_id,
        label: context.actions.find((action) => action.id === item.action_id)?.label || item.id,
        fields: outputFieldsForNode(item)
      }))
  })

  // Resolve loop scope from the graph itself. A transitive upstream loop is
  // not necessarily the owner of the selected node, so resultSources alone
  // cannot determine whether a connection should use the current iteration.
  const deviceLoopId = computed(() => {
    const workflow = context.selected.value
    const selectedNode = context.selectedNode.value
    if (!workflow || !selectedNode) return ''
    const nodes = new Map((workflow.nodes || []).map((node) => [node.id, node]))
    const outgoing = new Map<string, string[]>()
    const incoming = new Map<string, string[]>()
    for (const edge of workflow.edges || []) {
      if (!nodes.has(edge.source) || !nodes.has(edge.target)) continue
      outgoing.set(edge.source, [...(outgoing.get(edge.source) || []), edge.target])
      incoming.set(edge.target, [...(incoming.get(edge.target) || []), edge.source])
    }
    for (const loop of workflow.nodes || []) {
      if (loop.action_id !== 'device.for_each') continue
      const mode = String(loop.config.body_mode || '')
      const actionInputs = loop.config.action_inputs
      const hasActionInputs = Boolean(actionInputs && typeof actionInputs === 'object' && !Array.isArray(actionInputs) && Object.keys(actionInputs as Record<string, unknown>).length)
      if (mode === 'action' || (mode !== 'downstream' && mode !== 'bounded' && hasActionInputs)) continue
      const explicitEnd = String(loop.config.body_end || loop.config.loop_end || loop.config.loop_body_end || '')
      const explicitStart = String(loop.config.body_start || loop.config.loop_start || '')
      const loopEdges = (workflow.edges || []).filter((edge) => edge.source === loop.id)
      const bodyEdges = loopEdges.filter((edge) => ['body', 'loop-body', 'loop_body'].includes(String(edge.source_handle || '').toLowerCase()))
      const inferredBody = bodyEdges.length ? bodyEdges : loopEdges.filter((edge) => !['exit', 'loop-exit', 'loop_exit'].includes(String(edge.source_handle || '').toLowerCase()))
      let current = explicitStart || (inferredBody.length === 1 ? inferredBody[0].target : '')
      if (!current || (loopEdges.some((edge) => ['exit', 'loop-exit', 'loop_exit'].includes(String(edge.source_handle || '').toLowerCase())) && !explicitEnd)) continue
      const visited = new Set<string>()
      while (current) {
        if (current === selectedNode.id) return loop.id
        if (explicitEnd && current === explicitEnd) break
        const next = outgoing.get(current) || []
        if (next.length !== 1) break
        const childId = next[0]
        if (visited.has(childId) || (incoming.get(childId) || []).length > 1) break
        visited.add(childId)
        const child = nodes.get(childId)
        if (!child || ['device.for_each', 'loop.for_each', 'loop.until', 'utility.condition', 'utility.confirm', 'workflow.call'].includes(child.action_id)) break
        current = childId
      }
    }
    return ''
  })

  const loopItemsSourceId = computed(() => {
    const reference = loopItemsReference.value
    return resultSources.value.find((source) => reference === source.id || reference.startsWith(`${source.id}.`))?.id || ''
  })
  const loopItemsField = computed(() => {
    const source = loopItemsSourceId.value
    return source && loopItemsReference.value.startsWith(`${source}.`) ? loopItemsReference.value.slice(source.length + 1) : ''
  })
  const loopItemsSourceFields = computed(() => resultSources.value.find((source) => source.id === loopItemsSourceId.value)?.fields || [])
  function setLoopItemsSource(sourceId: string): void {
    loopItemsReference.value = sourceId ? `${sourceId}${loopItemsField.value ? `.${loopItemsField.value}` : ''}` : ''
  }
  function setLoopItemsField(field: string): void {
    loopItemsReference.value = loopItemsSourceId.value ? `${loopItemsSourceId.value}${field ? `.${field}` : ''}` : ''
  }

  const selectedSubworkflow = computed(() => {
    const node = context.selectedNode.value
    if (node?.action_id !== 'workflow.call') return null
    const workflowId = String(node.config.workflow_id || '')
    const version = String(node.config.version || '')
    return [...context.subworkflowVersions.value, ...context.publishedWorkflows.value]
      .find((item) => item.id === workflowId && String(item.version) === version) || null
  })

  async function selectSubworkflow(workflowId: string): Promise<void> {
    const node = context.selectedNode.value
    if (node?.action_id !== 'workflow.call') return
    node.config.workflow_id = workflowId
    context.subworkflowVersions.value = workflowId
      ? (await desktopApi.workflowVersions(workflowId)).versions as WorkflowConfigVersion[]
      : []
    applySubworkflowVersion(context.subworkflowVersions.value[0])
  }

  function applySubworkflowVersion(version?: WorkflowConfigVersion): void {
    const node = context.selectedNode.value
    if (node?.action_id !== 'workflow.call') return
    node.config.version = version?.version ?? ''
    node.config.inputs = Object.fromEntries((version?.inputs || []).map((input) => [input.name, input.default ?? '']))
  }

  function selectSubworkflowVersion(version: string): void {
    applySubworkflowVersion(context.subworkflowVersions.value.find((candidate) => String(candidate.version) === version))
  }

  function updateSubworkflowInput(name: string, value: string): void {
    const node = context.selectedNode.value
    if (!node) return
    const inputs = node.config.inputs
    node.config.inputs = { ...(inputs && typeof inputs === 'object' ? inputs as Record<string, unknown> : {}), [name]: value }
  }

  const commandReferences = computed(() => {
    const references: Array<{ reference: string; label: string; hint: string }> = []
    const seen = new Set<string>()
    const add = (reference: string, label: string, hint: string): void => {
      if (!reference || seen.has(reference)) return
      seen.add(reference)
      references.push({ reference, label, hint })
    }
    for (const input of context.selected.value?.inputs || []) {
      const name = String(input.name || '').trim()
      if (name) add(`inputs.${name}`, `流程输入 · ${name}`, '执行流程时提供')
    }
    const sourceIds = new Set(resultSources.value.map((source) => source.id))
    if (deviceLoopId.value) {
      add('device_id', '当前遍历设备', deviceLoopId.value)
      add('device.id', '当前设备 ID', deviceLoopId.value)
      add('index', '遍历序号', deviceLoopId.value)
    }
    for (const node of context.selected.value?.nodes || []) {
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

  const loopUntilPattern = computed<string>({
    get: () => {
      const node = context.selectedNode.value
      if (node?.action_id !== 'loop.until') return ''
      const condition = String(node.config.condition || '')
      return (condition.match(/'([^']+)'\s+in\s+result\.output/) || condition.match(/"([^"]+)"\s+in\s+result\.output/))?.[1] || ''
    },
    set: (pattern) => {
      const node = context.selectedNode.value
      if (node?.action_id !== 'loop.until' || !['output_contains', 'output_regex'].includes(loopUntilStopMode.value)) return
      node.config.condition = pattern ? `'${pattern}' in result.output` : "'' in result.output"
    }
  })

  const loopUntilStopMode = computed<'output_contains' | 'output_regex' | 'success' | 'failure' | 'max_iterations'>({
    get: () => {
      const node = context.selectedNode.value
      if (node?.action_id !== 'loop.until') return 'max_iterations'
      const condition = String(node.config.condition || '')
      if (condition === 'False' || condition === 'false' || condition === '0' || !condition.trim()) return 'max_iterations'
      if (condition.includes("'succeeded'") || condition.includes('"succeeded"')) return 'success'
      if (condition.includes("'failed'") || condition.includes('"failed"')) return 'failure'
      if (condition.includes('.match(') || condition.includes('re.search')) return 'output_regex'
      return condition.includes(' in ') || condition.includes('.contains') ? 'output_contains' : 'max_iterations'
    },
    set: (mode) => {
      const node = context.selectedNode.value
      if (node?.action_id !== 'loop.until') return
      if (mode === 'success') node.config.condition = "result.status == 'succeeded'"
      else if (mode === 'failure') node.config.condition = "result.status == 'failed'"
      else if (mode === 'output_regex' || mode === 'output_contains') node.config.condition = loopUntilPattern.value ? `'${loopUntilPattern.value}' in result.output` : "'' in result.output"
      else node.config.condition = 'False'
    }
  })

  function configString(key: string): string { return String(context.selectedNode.value?.config?.[key] ?? '') }
  const variableValueSourceId = computed(() => {
    const reference = configString('value').match(/^\$\{([^}]+)\}$/)?.[1] || ''
    return resultSources.value.find((source) => reference === source.id || reference.startsWith(`${source.id}.`))?.id || ''
  })
  const variableValueField = computed(() => {
    const source = variableValueSourceId.value
    const reference = configString('value').match(/^\$\{([^}]+)\}$/)?.[1] || ''
    return source && reference.startsWith(`${source}.`) ? reference.slice(source.length + 1) : ''
  })
  const variableExtractEnabled = computed(() => isObject(context.selectedNode.value?.config.extract))
  function setResultField(source: string, field: string): void {
    if (context.selectedNode.value) context.selectedNode.value.config.value = source && field ? `\${${source}.${field}}` : ''
  }
  function onResultFieldChange(event: Event): void {
    const parts = String((event.target as HTMLSelectElement).value || '').split('.')
    setResultField(parts.shift() || '', parts.join('.'))
  }
  function setVariableValueReference(reference: string): void {
    const node = context.selectedNode.value
    if (!node) return
    node.config.value = reference ? `\${${reference}}` : ''
  }
  function variableExtractConfig(): Record<string, unknown> {
    const extract = context.selectedNode.value?.config.extract
    return isObject(extract) ? extract : {}
  }
  function toggleVariableExtract(enabled: boolean): void {
    const node = context.selectedNode.value
    if (!node) return
    if (!enabled) delete node.config.extract
    else if (!isObject(node.config.extract)) node.config.extract = { pattern: '', mode: 'match', group: 0, convert: 'string', trim: false }
  }
  function updateExtract(key: string, value: unknown): void {
    const node = context.selectedNode.value
    if (!node) return
    node.config.extract = { ...variableExtractConfig(), [key]: value }
  }
  function variableExtractString(key: string): string { return String(variableExtractConfig()[key] ?? '') }
  function updateVariableExtractString(key: string, event: Event): void { updateExtract(key, (event.target as HTMLInputElement | HTMLTextAreaElement).value) }
  function updateVariableExtractNumber(key: string, event: Event): void {
    const value = Number((event.target as HTMLInputElement).value)
    updateExtract(key, Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0)
  }
  function updateVariableExtractMode(event: Event): void { updateExtract('mode', (event.target as HTMLSelectElement).value) }
  function updateVariableExtractBoolean(key: string, event: Event): void { updateExtract(key, (event.target as HTMLInputElement).checked) }

  return {
    loopItemsMode, loopItemsReference, loopItemsSourceId, loopItemsField, loopItemsSourceFields,
    setLoopItemsSource, setLoopItemsField, outputFieldsForAction, outputFieldsForNode,
    selectedSubworkflow, selectSubworkflow, selectSubworkflowVersion, updateSubworkflowInput,
    resultSources, deviceLoopId, commandReferences, loopUntilStopMode, loopUntilPattern,
    setResultField, onResultFieldChange, variableValueSourceId, variableValueField,
    variableExtractEnabled, setVariableValueReference, toggleVariableExtract,
    variableExtractConfig, variableExtractString, updateVariableExtractString,
    updateVariableExtractNumber, updateVariableExtractMode, updateVariableExtractBoolean
  }
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}
