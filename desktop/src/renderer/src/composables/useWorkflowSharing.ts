import type { Ref } from 'vue'
import { desktopApi } from '../transport/api'
import type { WorkflowScript } from '../types'

export interface WorkflowSharingPreview {
  workflow?: Record<string, unknown>
  errors?: Array<{ message: string }>
  warnings?: Array<{ message: string }>
}

interface SharingContext {
  selected: Ref<{ id: string; name: string; description?: string } | null>
  selectedNode: Ref<{ action_id: string; config: Record<string, unknown>; input_mapping?: Record<string, unknown> } | null>
  importing: Ref<boolean>
  importFilename: Ref<string>
  importContent: Ref<string>
  importPreview: Ref<WorkflowSharingPreview | null>
  showImportPreview: Ref<boolean>
  customActionName: Ref<string>
  customActionDescription: Ref<string>
  customActionSaving: Ref<boolean>
  customActionWorkflowVersion: Ref<{ id: string; version: string | number; name: string; description?: string; inputs?: Array<{ name: string; default?: unknown }> } | null>
  showCustomActionDialog: Ref<boolean>
  selectedCatalogAction: Ref<{ id: string } | null>
  actions: Array<{ id: string; category?: string; inputSchema?: Record<string, unknown>; outputSchema?: Record<string, unknown>; risk?: string }>
  outputFieldsFromSchema: (schema: Record<string, unknown>) => Array<{ name: string; label: string }>
  refresh: () => Promise<void>
  selectWorkflow: (workflow: unknown) => void
  loadCustomActions: () => Promise<void>
  setError: (message: string) => void
  setRunMessage: (message: string) => void
}

export function useWorkflowSharing(context: SharingContext) {
  async function importWorkflow(): Promise<void> {
    try {
      const filePath = await window.desktopApi.chooseWorkflowFile({ label: 'Workflow 文件', extensions: ['workflow.yaml', 'yaml', 'yml', 'json'] })
      if (!filePath) return
      context.importing.value = true
      context.importFilename.value = filePath.split(/[\\/]/).pop() || 'workflow.workflow.yaml'
      context.importContent.value = await window.desktopApi.readWorkflowFile(filePath)
      context.importPreview.value = await desktopApi.previewWorkflowImport(context.importFilename.value, context.importContent.value)
      context.showImportPreview.value = true
    } catch (cause) { context.setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { context.importing.value = false }
  }

  async function confirmImport(): Promise<void> {
    if (!context.importPreview.value || (context.importPreview.value.errors || []).length) return
    context.importing.value = true
    try {
      const result = await desktopApi.importWorkflowDefinition(context.importFilename.value, context.importContent.value, 'create_copy')
      context.showImportPreview.value = false
      context.importPreview.value = null
      await context.refresh()
      context.selectWorkflow(result.workflow)
    } catch (cause) { context.setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { context.importing.value = false }
  }

  async function exportWorkflow(format: 'yaml' | 'json'): Promise<void> {
    if (!context.selected.value) return
    try {
      const result = await desktopApi.exportWorkflowDefinition(context.selected.value.id, format)
      await window.desktopApi.saveWorkflowFile({ suggestedName: result.filename, content: result.content })
    } catch (cause) { context.setError(cause instanceof Error ? cause.message : String(cause)) }
  }

  async function copyAiPrompt(): Promise<void> {
    if (!context.selected.value) return
    try {
      const exported = await desktopApi.exportWorkflowDefinition(context.selected.value.id, 'yaml')
      const prompt = `请生成一个 Device TUI Workflow 配置。要求：使用 device-tui.workflow 格式、schema_version: 1，只输出可导入的 YAML，不要解释。\n\n当前流程参考：\n${exported.content}`
      await window.desktopApi.writeClipboardText(prompt)
      context.setRunMessage('AI 提示词已复制到剪贴板')
    } catch (cause) { context.setError(cause instanceof Error ? cause.message : String(cause)) }
  }

  function openCustomActionDialog(): void {
    if (!context.selectedNode.value || context.selectedNode.value.action_id === 'utility.condition') return
    context.customActionWorkflowVersion.value = null
    context.customActionName.value = ''
    context.customActionDescription.value = ''
    context.showCustomActionDialog.value = true
  }

  function openWorkflowCustomActionDialog(version: SharingContext['customActionWorkflowVersion']['value']): void {
    context.customActionWorkflowVersion.value = version
    context.customActionName.value = version?.name || ''
    context.customActionDescription.value = version?.description || ''
    context.showCustomActionDialog.value = true
  }

  async function saveCustomAction(): Promise<void> {
    if ((!context.selectedNode.value && !context.customActionWorkflowVersion.value) || !context.customActionName.value.trim()) return
    context.customActionSaving.value = true
    try {
      const sourceVersion = context.customActionWorkflowVersion.value
      const payload: Record<string, unknown> = { name: context.customActionName.value.trim(), description: context.customActionDescription.value.trim() }
      if (sourceVersion) {
        payload.workflow_id = sourceVersion.id
        payload.version = sourceVersion.version
        payload.inputs = Object.fromEntries((sourceVersion.inputs || []).map((input) => [input.name, input.default ?? `\${inputs.${input.name}}`]))
      } else if (context.selectedNode.value) {
        payload.action_id = context.selectedNode.value.action_id
        payload.config = { ...context.selectedNode.value.config, ...(context.selectedNode.value.input_mapping || {}) }
      }
      await desktopApi.createWorkflowCustomAction(payload)
      await context.loadCustomActions()
      context.showCustomActionDialog.value = false
      context.customActionWorkflowVersion.value = null
      context.setRunMessage('已保存为自定义 Action，可从节点库重复使用。')
    } catch (cause) { context.setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { context.customActionSaving.value = false }
  }

  async function deleteCustomAction(action: { id: string; preset?: { customActionId?: string } }): Promise<void> {
    const customId = action.preset?.customActionId
    if (!customId) return
    try {
      await desktopApi.deleteWorkflowCustomAction(customId)
      if (context.selectedCatalogAction.value?.id === action.id) context.selectedCatalogAction.value = null
      await context.loadCustomActions()
    } catch (cause) { context.setError(cause instanceof Error ? cause.message : String(cause)) }
  }

  return { importWorkflow, confirmImport, exportWorkflow, copyAiPrompt, openCustomActionDialog, openWorkflowCustomActionDialog, saveCustomAction, deleteCustomAction }
}
