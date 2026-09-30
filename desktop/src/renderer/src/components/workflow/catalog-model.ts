import type { ActionItem } from '../workflow-config/types'

export const ACTION_CATEGORY_LABELS: Record<string, string> = {
  'flow-control': '基础流程控制', device: '设备操作', transfer: '文件传输',
  data: '变量与结果', workflow: '子流程', script: '脚本执行'
}
export const ACTION_CATEGORY_ORDER = ['flow-control', 'device', 'transfer', 'script', 'data', 'workflow']
export const NON_EXECUTABLE_LOOP_ACTIONS = new Set(['loop.for_each', 'device.for_each', 'loop.until', 'utility.condition', 'utility.confirm', 'workflow.call'])

export function filterWorkflowActions(actions: ActionItem[], query: string): ActionItem[] {
  const normalized = query.trim().toLowerCase()
  if (!normalized) return actions
  return actions.filter((item) => `${item.id} ${item.label} ${item.hint}`.toLowerCase().includes(normalized))
}

export function groupWorkflowActions(actions: ActionItem[]): Array<{ category: string; label: string; actions: ActionItem[] }> {
  return ACTION_CATEGORY_ORDER.map((category) => ({ category, label: ACTION_CATEGORY_LABELS[category], actions: actions.filter((item) => item.category === category) })).filter((group) => group.actions.length)
}

export function loopChildWorkflowActions(actions: ActionItem[]): ActionItem[] {
  return actions.filter((item) => !NON_EXECUTABLE_LOOP_ACTIONS.has(item.id))
}
