import type { Ref } from 'vue'
import { desktopApi } from '../../transport/api'

type Issue = { code: string; message: string; node_id?: string }
type WorkflowItem = { id: string; name: string; nodes?: Array<{ id: string }>; [key: string]: unknown }

export function useWorkflowPersistence(options: {
  selected: Ref<WorkflowItem | null>
  selectedNodeId: Ref<string | undefined>
  issues: Ref<Issue[]>
  error: Ref<string>
  runMessage: Ref<string>
  saving: Ref<boolean>
  savedSnapshot: Ref<string>
  snapshot: (workflow: WorkflowItem) => string
  sync: () => void
  refresh: () => Promise<void>
  refreshVersions: (id: string) => Promise<void>
  publishedWorkflows: Ref<WorkflowItem[]>
  canPublish: Ref<boolean>
  showValidationProblem: () => void
  onPersisted?: (workflow: WorkflowItem) => void
}) {
  async function validate(): Promise<boolean> {
    const workflow = options.selected.value
    if (!workflow) return false
    options.sync()
    const result = await desktopApi.validateWorkflowDefinition(workflow.id, workflow)
    options.issues.value = [
      ...(workflow.name.trim() ? [] : [{ code: 'missing_workflow_name', message: 'workflow name is required' }]),
      ...(result.errors || []).map((item) => ({ ...item, node_id: item.node_id || undefined }))
    ]
    return options.issues.value.length === 0
  }

  async function persist(): Promise<boolean> {
    const workflow = options.selected.value
    if (!workflow) return false
    options.sync()
    options.saving.value = true
    try {
      const result = await desktopApi.saveWorkflowDefinition(workflow.id, workflow)
      const saved = result.workflow as WorkflowItem
      options.selected.value = saved
      options.savedSnapshot.value = options.snapshot(saved)
      options.onPersisted?.(saved)
      return true
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      options.error.value = message
      options.runMessage.value = `保存失败，未执行当前流程：${message}`
      return false
    } finally { options.saving.value = false }
  }

  async function save(): Promise<void> {
    if (!options.selected.value || !await validate()) {
      if (options.issues.value.length) options.showValidationProblem()
      return
    }
    await persist()
  }

  async function publish(): Promise<void> {
    const workflow = options.selected.value
    if (!workflow || !await validate()) {
      if (options.issues.value.length) options.showValidationProblem()
      return
    }
    if (!await persist() || !options.canPublish.value) return
    const result = await desktopApi.publishWorkflowDefinition(workflow.id)
    if (!result.published) options.issues.value = (result.errors || []).map((item) => ({ code: item.code || 'publish_error', message: item.message, node_id: item.node_id || undefined }))
    await options.refresh()
    await options.refreshVersions(workflow.id)
    options.publishedWorkflows.value = (await desktopApi.publishedWorkflowDefinitions()).workflows as unknown as WorkflowItem[]
  }

  return { validate, persist, save, publish }
}
