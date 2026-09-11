<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Play, Plus, Save, Trash2, Workflow, X } from 'lucide-vue-next'
import { desktopApi } from '../transport/api'

type WorkflowItem = { id: string; name: string; description?: string; version?: string | number; nodes?: unknown[]; edges?: unknown[] }
const emit = defineEmits<{ close: [] }>()
const workflows = ref<WorkflowItem[]>([])
const selected = ref<WorkflowItem | null>(null)
const error = ref('')
const loading = ref(false)
async function refresh(): Promise<void> { loading.value = true; try { workflows.value = (await desktopApi.workflowDefinitions()).workflows as WorkflowItem[] } catch (cause) { error.value = String(cause) } finally { loading.value = false } }
async function create(): Promise<void> { const result = await desktopApi.createWorkflowDefinition({ name: '新建 Workflow', nodes: [], edges: [] }); selected.value = result.workflow as WorkflowItem; await refresh() }
async function save(): Promise<void> { if (!selected.value) return; const result = await desktopApi.saveWorkflowDefinition(selected.value.id, selected.value); selected.value = result.workflow as WorkflowItem; await refresh() }
async function publish(): Promise<void> { if (!selected.value) return; const result = await desktopApi.publishWorkflowDefinition(selected.value.id); if (!result.published) error.value = (result.errors || []).map((item: { message: string }) => item.message).join('；'); await refresh() }
async function remove(): Promise<void> { if (!selected.value) return; await desktopApi.deleteWorkflowDefinition(selected.value.id); selected.value = null; await refresh() }
onMounted(refresh)
</script>

<template>
  <section class="workflow-library" aria-label="Workflow Library">
    <header class="workflow-library-header"><div><Workflow :size="18" /><strong>Workflow Library</strong></div><button type="button" title="关闭" @click="emit('close')"><X :size="16" /></button></header>
    <div class="workflow-library-toolbar"><button type="button" @click="create"><Plus :size="14" />新建</button><button type="button" :disabled="!selected" @click="save"><Save :size="14" />保存</button><button type="button" :disabled="!selected" @click="publish"><Play :size="14" />发布</button><button type="button" :disabled="!selected" @click="remove"><Trash2 :size="14" />删除</button></div>
    <p v-if="error" class="workflow-error">{{ error }}</p>
    <div class="workflow-library-body"><aside><button v-for="item in workflows" :key="item.id" type="button" :class="{ active: selected?.id === item.id }" @click="selected = item"><strong>{{ item.name }}</strong><small>{{ item.id }} · v{{ item.version || 'draft' }}</small></button><p v-if="!loading && !workflows.length">暂无 Workflow</p></aside><main v-if="selected"><label>名称<input v-model="selected.name" /></label><label>描述<textarea v-model="selected.description" rows="2" /></label><pre>{{ JSON.stringify(selected.nodes || [], null, 2) }}</pre></main><main v-else class="workflow-empty">选择一个 Workflow 开始编辑</main></div>
  </section>
</template>
