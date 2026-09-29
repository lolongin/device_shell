import type { WorkflowActionCatalogEntry } from '../../types'
import type { ActionItem } from './types'

export type WorkflowActionPresentationCategory = 'flow-control' | 'device' | 'transfer' | 'data' | 'workflow' | 'script'

export const fieldLabels: Record<string, string> = {
  count: '数量',
  approved: '是否批准',
  cli_status: '终端状态',
  data: '结构化数据',
  device_id: '设备',
  error: '错误',
  evidence: '校验证据',
  exit_code: '退出码',
  execution_id: '执行 ID',
  host: '主机',
  iterations: '循环次数',
  items: '列表',
  key: '结果名称',
  matched: '是否匹配',
  operation_id: '操作 ID',
  option_id: '选项 ID',
  output: '输出',
  port: '端口',
  reason: '原因',
  requested_fields: '请求字段',
  address: '地址',
  model: '型号',
  name: '名称',
  result: '当前结果',
  returncode: '返回码',
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
  verified: '已校验',
}

export const inputFieldLabels: Record<string, string> = {
  devices: '设备列表',
  source: '源文件路径',
  destination: '目标路径',
  overwrite: '覆盖已有文件',
  command: '命令',
  execution_mode: '执行方式',
  timeout_seconds: '超时时间',
  cwd: '工作目录',
  env: '环境变量',
  retry_attempts: '重试次数',
  retry_backoff_seconds: '重试间隔',
  failure_strategy: '失败处理',
  script: '脚本',
  language: '脚本语言',
  input_json: '脚本输入',
  max_output_chars: '输出长度上限',
  seconds: '等待秒数',
  pattern: '匹配内容',
  mode: '匹配模式',
  case_sensitive: '区分大小写',
  send_enter: '发送回车',
  after_sequence: '起始序号',
  device_id: '设备',
  host: '主机地址',
  port: '端口',
  fields: '采集字段',
  rules: '条件规则',
  logical_operator: '规则关系',
  prompt: '确认提示',
  approve_label: '同意按钮文字',
  reject_label: '拒绝按钮文字',
  name: '变量名',
  value: '变量值',
  extract: '提取规则',
  expression: '表达式',
  values: '表达式变量',
  items: '列表',
  action_id: '循环动作',
  action_inputs: '循环动作输入',
  condition: '停止条件',
  max_iterations: '最大循环次数',
  interval_seconds: '循环间隔',
  key: '结果名称',
  workflow_id: '子流程',
  version: '版本',
  inputs: '子流程输入',
}

export function requiredInputLabels(schema: Record<string, unknown>): string[] {
  const required = Array.isArray(schema.required) ? schema.required : []
  return required.map((name) => inputFieldLabels[String(name)] || String(name))
}

function presentationCategory(entry: WorkflowActionCatalogEntry): WorkflowActionPresentationCategory {
  if (entry.id === 'variable.set' || entry.id === 'expression.evaluate' || entry.category === 'result') return 'data'
  if (entry.id.startsWith('loop.') || entry.category === 'control') return 'flow-control'
  if (entry.id.startsWith('file.') || entry.category === 'transfer') return 'transfer'
  if (entry.id === 'workflow.call' || entry.category === 'workflow') return 'workflow'
  if (entry.id === 'script.run' || entry.category === 'script') return 'script'
  return 'device'
}

function presentationTone(category: WorkflowActionPresentationCategory, risk: string): string {
  if (risk === 'high') return 'red'
  if (category === 'flow-control') return 'purple'
  if (category === 'transfer') return 'amber'
  if (category === 'data') return 'green'
  if (category === 'workflow' || category === 'script') return 'teal'
  return 'blue'
}

export function outputFieldsFromSchema(schema: unknown): Array<{ name: string; label: string }> {
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) return []
  const properties = (schema as Record<string, unknown>).properties
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return []
  return Object.keys(properties as Record<string, unknown>).map((name) => ({ name, label: fieldLabels[name] || name }))
}

export function actionItemFromCatalog(entry: WorkflowActionCatalogEntry): ActionItem {
  const category = presentationCategory(entry)
  const inputSchema = entry.input_schema || {}
  const outputSchema = entry.output_schema || {}
  const requiredLabels = requiredInputLabels(inputSchema)
  const outputFields = outputFieldsFromSchema(outputSchema)
  return {
    id: entry.id,
    label: entry.name || entry.id,
    hint: '必填：' + (requiredLabels.join('、') || '无') + ' · 输出：' + outputFields.length + ' 项',
    tone: presentationTone(category, entry.risk),
    category,
    inputSchema,
    outputSchema,
    risk: entry.risk || 'low',
    outputFields,
  }
}

export function actionItemsFromCatalog(entries: WorkflowActionCatalogEntry[]): ActionItem[] {
  return entries
    .filter((entry) => Boolean(entry?.id))
    .map(actionItemFromCatalog)
}
