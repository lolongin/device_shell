import type { ActionItem, CommandReference, ResultSource, WorkflowValueReference } from '../components/workflow-config/types'

export type BindingSchema = Record<string, unknown>

export function schemaTypes(schema: BindingSchema): string[] {
  const raw = schema.type
  return (Array.isArray(raw) ? raw : raw ? [raw] : []).map(String).filter(type => type !== 'null')
}

export function valueType(value: unknown): string {
  if (value === null || value === undefined) return 'any'
  if (Array.isArray(value)) return 'array'
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number'
  return typeof value
}

export function referenceCompatible(schema: BindingSchema, reference: WorkflowValueReference, template = false): boolean {
  const binding = schema.binding as { mode?: string; reference_types?: string[] } | undefined
  if (binding?.mode === 'static') return false
  const expected = binding?.reference_types?.length ? binding.reference_types : schemaTypes(schema)
  const normalize = (type: string): string => ({ devices: 'array', device: 'string', file: 'string', file_path: 'string' }[type] || type)
  const actual = normalize(reference.type)
  if (actual === 'any' || !expected.length) return true
  if (template && ['string', 'number', 'integer', 'boolean'].includes(actual)) return true
  return expected.map(normalize).some(type => type === actual || (type === 'number' && actual === 'integer'))
}

export function buildWorkflowReferences(context: {
  workflowInputs?: Array<{ name: string; type?: string; primitive_type?: string; semantic_type?: string; default?: unknown }>
  resultSources?: ResultSource[]
  commandReferences?: CommandReference[]
  actions?: ActionItem[]
  deviceLoopId?: string
}): WorkflowValueReference[] {
  const references: WorkflowValueReference[] = []
  const add = (reference: WorkflowValueReference): void => {
    if (!references.some(item => item.reference === reference.reference)) references.push(reference)
  }
  const expand = (path: string, label: string, schema: BindingSchema, source: WorkflowValueReference['source'], scope: string, depth = 0): void => {
    const types = schemaTypes(schema)
    add({ reference: path, label, source, type: types[0] || 'any', scope })
    if (depth >= 5) return
    const properties = schema.properties
    if (properties && typeof properties === 'object' && !Array.isArray(properties)) {
      for (const [key, definition] of Object.entries(properties)) {
        if (definition && typeof definition === 'object' && !Array.isArray(definition)) expand(`${path}.${key}`, `${label} · ${key}`, definition as BindingSchema, source, scope, depth + 1)
      }
    }
    if (types.includes('array') && schema.items && typeof schema.items === 'object' && !Array.isArray(schema.items)) {
      expand(`${path}.0`, `${label} · [0]`, schema.items as BindingSchema, source, scope, depth + 1)
    }
  }
  for (const input of context.workflowInputs || []) {
    const type = input.primitive_type || input.type || 'string'
    expand(`inputs.${input.name}`, input.name, { type: input.semantic_type === 'device_list' ? 'array' : type }, 'input', '整个流程')
    if (input.default && typeof input.default === 'object' && !Array.isArray(input.default)) {
      for (const [key, value] of Object.entries(input.default)) expand(`inputs.${input.name}.${key}`, `${input.name} · ${key}`, { type: valueType(value) }, 'input', '整个流程')
    }
  }
  for (const source of context.resultSources || []) {
    add({ reference: source.id, label: `${source.label} · 完整结果`, source: 'node', type: 'object', scope: source.id })
    const action = context.actions?.find(item => item.id === source.actionId)
    const properties = action?.outputSchema.properties as Record<string, BindingSchema> | undefined
    for (const field of source.fields) expand(`${source.id}.${field.name}`, `${source.label} · ${field.label}`, field.schema || properties?.[field.name] || {}, 'node', source.id)
  }
  for (const reference of context.commandReferences || []) {
    if (references.some(item => item.reference === reference.reference)) continue
    const isLocal = ['device_id', 'device.id', 'device', 'index', 'item', 'iteration', 'result'].includes(reference.reference)
    if (reference.reference.startsWith('inputs.')) continue
    if (!isLocal && reference.reference.includes('.')) continue
    add({ ...reference, source: isLocal ? 'loop' : 'variable', type: reference.type || (['index', 'iteration'].includes(reference.reference) ? 'integer' : reference.reference === 'device_id' || reference.reference === 'device.id' ? 'string' : 'any'), scope: reference.hint })
  }
  if (context.deviceLoopId) {
    for (const [reference, label, type] of [['device_id', '当前设备 ID', 'string'], ['device', '当前设备', 'object'], ['device.id', '当前设备 ID', 'string'], ['index', '遍历序号', 'integer']]) add({ reference, label, type, source: 'loop', scope: context.deviceLoopId })
  }
  return references
}

export function loopReferences(actionId: string): WorkflowValueReference[] {
  const locals = actionId === 'device.for_each'
    ? [['device_id', '当前设备 ID', 'string'], ['device', '当前设备', 'object'], ['device.id', '当前设备 ID', 'string'], ['index', '遍历序号', 'integer']]
    : actionId === 'loop.until'
      ? [['iteration', '迭代次数', 'integer'], ['result', '上次结果', 'object'], ['result.output', '上次输出', 'string'], ['result.status', '上次状态', 'string'], ['outputs', '上次结果', 'object']]
      : [['item', '当前项', 'any'], ['index', '遍历序号', 'integer']]
  return locals.map(([reference, label, type]) => ({ reference, label, type, source: 'loop', scope: '当前循环' }))
}
