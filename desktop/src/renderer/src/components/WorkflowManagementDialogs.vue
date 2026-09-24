<script setup lang="ts">
import { Trash2, X } from 'lucide-vue-next'

type Props = {
  state: Record<string, any>
  workflowTemplates: Array<{ id: string; name: string; description?: string; built_in?: boolean; workflow?: Record<string, unknown> }>
  importPreview: { workflow?: Record<string, unknown>; errors?: Array<{ message: string }>; warnings?: Array<{ message: string }> } | null
  importing: boolean
  creating: boolean
  deletingTemplateId: string
  customActionSaving: boolean
  confirmCreate: () => void
  confirmImport: () => void
  saveCustomAction: () => void
  chooseCreateTemplate: (templateId: string) => void
  deleteWorkflowTemplate: (template: any) => void
}
defineProps<Props>()
</script>

<template>
    <div v-if="state.showCreateDialog.value" class="workflow-modal-backdrop" @click.self="state.showCreateDialog.value = false">
      <form class="workflow-import-dialog workflow-create-dialog" role="dialog" aria-modal="true" aria-label="新建流程" @submit.prevent="confirmCreate">
        <header><strong>新建流程</strong><button type="button" title="关闭" @click="state.showCreateDialog.value = false"><X :size="16" /></button></header>
        <label>开始方式<select :value="state.createTemplateId.value" @change="chooseCreateTemplate(($event.target as HTMLSelectElement).value)"><option value="">空白流程</option><option v-for="item in workflowTemplates" :key="item.id" :value="item.id">{{ item.name }}{{ item.built_in ? ' · 内置' : '' }}</option></select></label>
        <section v-if="workflowTemplates.some((item) => !item.built_in)" class="workflow-template-manager" aria-label="我的流程模板">
          <strong>我的模板</strong>
          <div v-for="item in workflowTemplates.filter((template) => !template.built_in)" :key="item.id">
            <span>{{ item.name }}</span>
            <button type="button" :disabled="Boolean(deletingTemplateId)" :title="`删除模板 ${item.name}`" :aria-label="`删除模板 ${item.name}`" @click="deleteWorkflowTemplate(item)"><Trash2 :size="13" /></button>
          </div>
        </section>
        <label>流程名称<input v-model="state.createName.value" autofocus maxlength="120" placeholder="例如：路由器版本检查" /></label>
        <label>流程说明<textarea v-model="state.createDescription.value" rows="3" placeholder="说明这个流程的用途（可选）" /></label>
        <footer><button type="button" @click="state.showCreateDialog.value = false">取消</button><button type="submit" class="primary-action" :disabled="!state.createName.value.trim() || creating">{{ creating ? '创建中…' : '创建流程' }}</button></footer>
      </form>
    </div>
    <div v-if="state.showImportPreview.value" class="workflow-modal-backdrop" @click.self="state.showImportPreview.value = false">
      <section class="workflow-import-dialog" role="dialog" aria-modal="true" aria-label="导入 Workflow 预览">
        <header><strong>导入预览</strong><button type="button" title="关闭" @click="state.showImportPreview.value = false"><X :size="16" /></button></header>
        <p class="field-hint">{{ state.importFilename.value }} · 将作为新草稿导入</p>
        <div v-if="importPreview?.workflow" class="workflow-import-summary">
          <strong>{{ importPreview.workflow.name || '未命名流程' }}</strong>
          <span>{{ Array.isArray(importPreview.workflow.steps) ? importPreview.workflow.steps.length : (Array.isArray(importPreview.workflow.nodes) ? importPreview.workflow.nodes.length : 0) }} 个步骤</span>
        </div>
        <p v-for="issue in importPreview?.errors || []" :key="issue.message" class="workflow-error">{{ issue.message }}</p>
        <p v-for="warning in importPreview?.warnings || []" :key="warning.message" class="workflow-run-message">{{ warning.message }}</p>
        <footer><button type="button" @click="state.showImportPreview.value = false">取消</button><button type="button" class="primary-action" :disabled="importing || Boolean(importPreview?.errors?.length)" @click="confirmImport">确认导入</button></footer>
      </section>
    </div>
    <div v-if="state.showCustomActionDialog.value" class="workflow-modal-backdrop" @click.self="state.showCustomActionDialog.value = false">
      <form class="workflow-import-dialog workflow-create-dialog" role="dialog" aria-modal="true" aria-label="保存自定义 Action" @submit.prevent="saveCustomAction">
        <header><strong>保存自定义 Action</strong><button type="button" title="关闭" @click="state.showCustomActionDialog.value = false"><X :size="16" /></button></header>
        <label>名称<input v-model="state.customActionName.value" autofocus maxlength="80" placeholder="例如：检查设备版本" /></label>
        <label>说明<textarea v-model="state.customActionDescription.value" rows="3" maxlength="400" placeholder="可选，说明这个命令的用途" /></label>
        <footer><button type="button" @click="state.showCustomActionDialog.value = false">取消</button><button type="submit" class="primary-action" :disabled="customActionSaving || !state.customActionName.value.trim()">{{ customActionSaving ? '保存中…' : '保存' }}</button></footer>
      </form>
    </div>

</template>

<style src="./WorkflowManagementDialogs.css"></style>
