export interface WorkflowInputDefinition {
  name: string
  type?: string
  default?: unknown
}

export function normalizeStructuredInputValue(value: unknown, type?: string): unknown {
  if ((type !== 'array' && type !== 'object') || typeof value !== 'string') return value
  let current: unknown = value
  for (let attempt = 0; attempt < 3 && typeof current === 'string'; attempt += 1) {
    const text = current.trim()
    if (!text || (!text.startsWith('[') && !text.startsWith('{') && !text.startsWith('"'))) break
    try { current = JSON.parse(current) } catch { break }
  }
  return current
}

export function defaultWorkflowInputValue(input: WorkflowInputDefinition): unknown {
  if (input.default !== undefined && input.default !== null) return normalizeStructuredInputValue(input.default, input.type)
  if (input.type === 'boolean') return false
  return ''
}

export function workflowSnapshot(workflow: unknown): string {
  return workflow ? JSON.stringify(workflow) : ''
}
