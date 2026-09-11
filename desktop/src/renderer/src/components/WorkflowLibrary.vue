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
const selectedNode = ref<Record<string, any> | null>(null)
const configText = ref('{}')
const actions = [{ id: 'device.command', label: '执行命令' }, { id: 'device.reboot', label: '重启设备' }, { id: 'utility.wait', label: '等待' }, { id: 'utility.condition', label: '条件判断' }]
async function refresh(): Promise<void> { loading.value = true; try { workflows.value = (await desktopApi.workflowDefinitions()).workflows as WorkflowItem[] } catch (cause) { error.value = String(cause) } finally { loading.value = false } }
async function create(): Promise<void> { const result = await desktopApi.createWorkflowDefinition({ name: '新建 Workflow', nodes: [], edges: [] }); selected.value = result.workflow as WorkflowItem; await refresh() }
async function save(): Promise<void> { if (!selected.value) return; if (selectedNode.value && typeof selectedNode.value.config === 'string') { try { selectedNode.value.config = JSON.parse(selectedNode.value.config) } catch { error.value = '配置必须是合法 JSON'; return } } const result = await desktopApi.saveWorkflowDefinition(selected.value.id, selected.value); selected.value = result.workflow as WorkflowItem; await refresh() }
async function publish(): Promise<void> { if (!selected.value) return; const result = await desktopApi.publishWorkflowDefinition(selected.value.id); if (!result.published) error.value = (result.errors || []).map((item: { message: string }) => item.message).join('；'); await refresh() }
async function remove(): Promise<void> { if (!selected.value) return; await desktopApi.deleteWorkflowDefinition(selected.value.id); selected.value = null; await refresh() }
function addNode(actionId: string): void { if (!selected.value) return; const node = { id: `${actionId.split('.').pop()}_${Date.now().toString(36)}`, action_id: actionId, config: actionId === 'device.command' ? { command: '' } : actionId === 'utility.wait' ? { seconds: 1 } : {} }; selected.value.nodes = [...(selected.value.nodes || []), node]; selectedNode.value = node }
function chooseNode(node: unknown): void { selectedNode.value = node as Record<string, any>; configText.value = JSON.stringify(selectedNode.value.config || {}, null, 2) }
function removeNode(): void { if (!selected.value || !selectedNode.value) return; selected.value.nodes = (selected.value.nodes || []).filter((node: any) => node !== selectedNode.value); selectedNode.value = null }
function updateNodeConfig(event: Event): void { if (!selectedNode.value) return; try { const parsed = JSON.parse((event.target as HTMLTextAreaElement).value); if (parsed && typeof parsed === 'object') selectedNode.value.config = parsed } catch { error.value = '配置必须是合法 JSON' } }
onMounted(refresh)
</script>

<template>
  <section class="workflow-library" aria-label="Workflow Library">
    <header class="workflow-library-header"><div><Workflow :size="18" /><strong>Workflow Library</strong></div><button type="button" title="关闭" @click="emit('close')"><X :size="16" /></button></header>
    <div class="workflow-library-toolbar"><button type="button" @click="create"><Plus :size="14" />新建</button><button type="button" :disabled="!selected" @click="save"><Save :size="14" />保存</button><button type="button" :disabled="!selected" @click="publish"><Play :size="14" />发布</button><button type="button" :disabled="!selected" @click="remove"><Trash2 :size="14" />删除</button></div>
    <p v-if="error" class="workflow-error">{{ error }}</p>
    <div class="workflow-library-body"><aside><button v-for="item in workflows" :key="item.id" type="button" :class="{ active: selected?.id === item.id }" @click="selected = item; selectedNode = null"><strong>{{ item.name }}</strong><small>{{ item.id }} · v{{ item.version || 'draft' }}</small></button><p v-if="!loading && !workflows.length">暂无 Workflow</p></aside><main v-if="selected" class="workflow-studio-grid"><section class="workflow-action-catalog"><strong>Action Catalog</strong><button v-for="action in actions" :key="action.id" type="button" @click="addNode(action.id)"><Plus :size="12" />{{ action.label }}</button></section><section class="workflow-canvas"><label>名称<input v-model="selected.name" /></label><label>描述<textarea v-model="selected.description" rows="2" /></label><div class="workflow-node-list"><button v-for="node in selected.nodes || []" :key="(node as any).id" type="button" :class="{ active: selectedNode === node }" @click="chooseNode(node)"><Workflow :size="13" />{{ (node as any).id }}<small>{{ (node as any).action_id }}</small></button><p v-if="!(selected.nodes || []).length">从左侧添加 Action</p></div></section><section class="workflow-properties" v-if="selectedNode"><strong>Properties</strong><label>节点 ID<input v-model="selectedNode.id" /></label><label>配置 JSON<textarea v-model="selectedNode.config" rows="8" spellcheck="false" /></label><button type="button" @click="removeNode"><Trash2 :size="13" />删除节点</button></section><section v-else class="workflow-properties workflow-empty">选择节点编辑参数</section></main><main v-else class="workflow-empty">选择一个 Workflow 开始编辑</main></div>
  </section>
</template>
