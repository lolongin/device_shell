import type { Ref } from 'vue'
import { desktopApi } from '../transport/api'

export interface WorkflowTemplateModel { id: string; name: string; description?: string; built_in?: boolean; workflow?: unknown }
interface TemplateContext {
  templates: Ref<WorkflowTemplateModel[]>
  showCreateMenu: Ref<boolean>
  showCreateDialog: Ref<boolean>
  createBlank: Ref<boolean>
  createTemplateId: Ref<string>
  createName: Ref<string>
  createDescription: Ref<string>
  creating: Ref<boolean>
  deletingTemplateId: Ref<string>
  error: Ref<string>
  refresh: () => Promise<void>
  selectWorkflow: (workflow: unknown) => void
  persistCurrentWorkflow: () => Promise<boolean>
  selectedWorkflow: Ref<{ id: string; name: string; description?: string } | null>
  setRunMessage: (message: string) => void
}

export function useWorkflowTemplates(context: TemplateContext) {
  const { templates, showCreateMenu, showCreateDialog, createBlank, createTemplateId, createName, createDescription, creating, deletingTemplateId, error } = context

  function openCreateDialog(blank = false): void {
    showCreateMenu.value = false
    createBlank.value = blank
    createTemplateId.value = blank ? '' : (templates.value[0]?.id || '')
    const template = templates.value.find((item) => item.id === createTemplateId.value)
    createName.value = blank ? '' : (template?.name || '')
    createDescription.value = blank ? '' : (template?.description || '')
    showCreateDialog.value = true
  }

  function openCreateDialogFromTemplate(templateId: string): void {
    openCreateDialog(false)
    chooseCreateTemplate(templateId)
  }

  function chooseCreateTemplate(templateId: string): void {
    createTemplateId.value = templateId
    createBlank.value = !templateId
    const template = templates.value.find((item) => item.id === templateId)
    if (template) {
      createName.value = template.name
      createDescription.value = template.description || ''
    }
  }

  async function confirmCreate(): Promise<void> {
    const name = createName.value.trim()
    if (!name || creating.value) return
    creating.value = true
    error.value = ''
    try {
      const result = createTemplateId.value
        ? await desktopApi.instantiateWorkflowTemplate(createTemplateId.value, { name, description: createDescription.value.trim() })
        : await desktopApi.createWorkflowDefinition({ name, description: createDescription.value.trim(), inputs: [], outputs: [], nodes: [], edges: [] })
      showCreateDialog.value = false
      await context.refresh()
      context.selectWorkflow(result.workflow)
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally { creating.value = false }
  }

  async function saveCurrentAsTemplate(): Promise<void> {
    const selected = context.selectedWorkflow.value
    if (!selected || !await context.persistCurrentWorkflow()) return
    try {
      await desktopApi.createWorkflowTemplate({ workflow_id: selected.id, name: selected.name, description: selected.description || '' })
      await loadWorkflowTemplates()
      context.setRunMessage('当前流程已保存为模板。')
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  }

  async function deleteWorkflowTemplate(template: WorkflowTemplateModel): Promise<void> {
    if (template.built_in || deletingTemplateId.value) return
    if (!window.confirm(`确定删除模板“${template.name}”吗？此操作不会删除已创建的流程。`)) return
    deletingTemplateId.value = template.id
    error.value = ''
    try {
      await desktopApi.deleteWorkflowTemplate(template.id)
      await loadWorkflowTemplates()
      if (createTemplateId.value === template.id) chooseCreateTemplate(templates.value[0]?.id || '')
    } catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
    finally { deletingTemplateId.value = '' }
  }

  async function loadWorkflowTemplates(): Promise<void> {
    templates.value = (await desktopApi.workflowTemplates()).templates as unknown as WorkflowTemplateModel[]
  }

  return { openCreateDialog, openCreateDialogFromTemplate, chooseCreateTemplate, confirmCreate, saveCurrentAsTemplate, deleteWorkflowTemplate, loadWorkflowTemplates }
}
