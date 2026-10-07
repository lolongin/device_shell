// 共享类型定义
export type NodeItem = {
  id: string
  action_id: string
  config: Record<string, unknown>
  input_mapping?: Record<string, unknown>
  position?: { x: number; y: number }
}

export type DeviceSummary = {
  id: string
  row_id?: string
  name: string
  address?: string
  model?: string
  software_version?: string
  status?: string
}

export type CommandReference = {
  reference: string
  label: string
  hint: string
}

export type ResultSource = {
  id: string
  actionId?: string
  label: string
  fields: Array<{ name: string; label: string }>
}

export type ActionItem = {
  id: string
  label: string
  hint: string
  tone: string
  category: string
  inputSchema: Record<string, unknown>
  outputSchema: Record<string, unknown>
  risk: string
  outputFields: Array<{ name: string; label: string }>
  preset?: {
    actionId: string
    config: Record<string, unknown>
    customActionId: string
  }
}

export type WorkflowScript = {
  id: string
  name: string
  description?: string
  language: 'python' | 'powershell' | 'bash' | string
  script: string
  entrypoint?: string
  input_schema: Array<{
    name: string
    type: 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object'
    required?: boolean
    default?: unknown
    description?: string
  }>
  input_schema_source?: 'function' | 'manual' | string
  input_schema_error?: string
  updated_at?: string
}

// Props 定义
export interface NodeConfigProps {
  node: NodeItem
  deviceLoopId?: string
  availableDevices?: DeviceSummary[]
  workflowInputs?: Array<{ name: string; type?: string; description?: string }>
  commandReferences?: CommandReference[]
  resultSources?: ResultSource[]
  scripts?: WorkflowScript[]
  actions?: ActionItem[]
}

// Emits 定义
export interface NodeConfigEmits {
  update: [node: NodeItem]
  remove: []
  test: []
  'save-as-action': []
}
