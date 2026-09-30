import { computed, type Ref } from 'vue'
import type { TaskRecord } from '../../types'
import type { ActionItem } from '../workflow-config/types'
import { flowTestOutputText, flowTestValueText } from './flow-test-output'
import { flowTestStepStatusLabel, normalizeFlowTestStepStatus } from './flow-test-status'

type WorkflowInput = { name: string; type?: string; default?: unknown }
type WorkflowNode = { id: string; action_id: string; config: Record<string, unknown> }
type WorkflowLike = { inputs?: WorkflowInput[]; nodes?: WorkflowNode[] }

export function useWorkflowFlowTestView(options: {
  selected: Ref<WorkflowLike | null>
  canvasNodes: Ref<WorkflowNode[]>
  actions: ActionItem[]
  task: Ref<TaskRecord | null>
  error: Ref<string>
  inputValues: Ref<Record<string, unknown>>
  expandedStepIds: Ref<string[]>
}) {
  const status = computed(() => {
    const taskStatus = String(options.task.value?.status || '')
    if (!options.task.value && options.error.value) return { label: '失败', tone: 'failed' }
    if (['completed', 'success', 'succeeded'].includes(taskStatus)) return { label: '已完成', tone: 'success' }
    if (['failed', 'cancelled'].includes(taskStatus)) return { label: taskStatus === 'cancelled' ? '已取消' : '失败', tone: 'failed' }
    if (taskStatus) {
      if (taskStatus === 'pending') return { label: '准备中', tone: 'running' }
      return { label: taskStatus === 'waiting_for_user' || taskStatus === 'waiting_for_decision' ? '等待输入' : '运行中', tone: 'running' }
    }
    return { label: '未运行', tone: 'idle' }
  })

  const currentStep = computed(() => {
    const id = String(options.task.value?.current_step_id || options.task.value?.checkpoint?.current_step || '')
    if (!id) return ''
    const node = options.selected.value?.nodes?.find((item) => item.id === id)
    return node ? `${node.id} · ${options.actions.find((item) => item.id === node.action_id)?.label || node.action_id}` : id
  })

  const inputEntries = computed(() => (options.selected.value?.inputs || []).map((input) => ({
    name: input.name,
    type: input.type || 'string',
    value: options.inputValues.value[input.name] ?? input.default ?? ''
  })))

  const executionOrder = computed(() => {
    const known = new Set<string>()
    const order: string[] = []
    const append = (id: string): void => {
      if (id && !known.has(id)) {
        known.add(id)
        order.push(id)
      }
    }
    for (const node of options.canvasNodes.value) append(node.id)
    for (const step of options.task.value?.result?.steps || []) append(String(step.step_id || ''))
    for (const state of options.task.value?.checkpoint?.step_states || []) append(String(state.step_id || ''))
    for (const state of options.task.value?.workflow_view?.states || []) append(String(state.id || ''))
    return order
  })

  function toggleStep(stepId: string): void {
    options.expandedStepIds.value = options.expandedStepIds.value.includes(stepId)
      ? options.expandedStepIds.value.filter((item) => item !== stepId)
      : [...options.expandedStepIds.value, stepId]
  }

  const stepLogs = computed(() => {
    const task = options.task.value
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
      const payload = step && typeof step === 'object' ? step as unknown as Record<string, unknown> : undefined
      states.set(step.step_id, {
        status: normalizeFlowTestStepStatus(String(step.status || 'pending')),
        output: step.output || (step.data ? JSON.stringify(step.data, null, 2) : ''),
        error: step.message || step.error_code || '',
        payload
      })
    }
    const nodesById = new Map((options.selected.value?.nodes || []).map((node) => [node.id, node]))
    const completedSteps = new Set((task?.checkpoint?.completed_steps || []).map(String))
    const workflowOutputs = { ...(task?.checkpoint?.outputs || {}), ...(task?.result?.outputs || {}) }
    const terminalStatus = String(task?.status || '')
    const terminal = ['completed', 'success', 'succeeded', 'failed', 'cancelled'].includes(terminalStatus)
    const failedStepId = String(task?.checkpoint?.failed_step_id || task?.current_step_id || '')
    return executionOrder.value.map((nodeId) => {
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
        label: options.actions.find((item) => item.id === node.action_id)?.label || node.action_id,
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
    }).filter((item): item is NonNullable<typeof item> => Boolean(item)).filter((item) => item.status !== 'pending' || options.task.value)
  })

  return {
    status,
    currentStep,
    inputEntries,
    stepLogs,
    toggleStep,
    stepStatusLabel: flowTestStepStatusLabel,
    outputText: flowTestOutputText
  }
}
