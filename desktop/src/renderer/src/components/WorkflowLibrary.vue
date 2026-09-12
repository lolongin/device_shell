<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CheckCircle2, GitBranch, Play, Plus, Save, Trash2, Workflow, X, AlertTriangle } from 'lucide-vue-next'
import { desktopApi } from '../transport/api'

type NodeItem = { id: string; action_id: string; config: Record<string, unknown> }
type WorkflowItem = { id: string; name: string; description?: string; version?: string | number; nodes?: NodeItem[]; edges?: Array<{ source: string; target: string; condition?: string }> }
type Issue = { code: string; message: string; node_id?: string | null }

const emit = defineEmits<{ close: [] }>()
const workflows = ref<WorkflowItem[]>([])
const selected = ref<WorkflowItem | null>(null)
const selectedNode = ref<NodeItem | null>(null)
const issues = ref<Issue[]>([])
const warnings = ref<Issue[]>([])
const error = ref('')
const loading = ref(false)
const saving = ref(false)

const actions = [
  { id: 'device.command', label: '执行命令', hint: '在设备终端执行一条命令', tone: 'blue' },
  { id: 'device.reboot', label: '重启设备', hint: '高风险操作，需要确认', tone: 'red' },
  { id: 'utility.wait', label: '等待', hint: '等待设备或流程继续', tone: 'amber' },
  { id: 'utility.condition', label: '条件判断', hint: '根据输出选择分支', tone: 'purple' }
]
const selectedAction = computed(() => actions.find((item) => item.id === selectedNode.value?.action_id))
const canPublish = computed(() => Boolean(selected.value && !issues.value.length && (selected.value.nodes?.length || 0) > 0))

async function refresh(): Promise<void> {
  loading.value = true
  error.value = ''
  try { workflows.value = (await desktopApi.workflowDefinitions()).workflows as WorkflowItem[] } catch (cause) { error.value = String(cause) } finally { loading.value = false }
}

function selectWorkflow(item: WorkflowItem): void {
  selected.value = item
  selectedNode.value = item.nodes?.[0] || null
  issues.value = []
  warnings.value = []
}

async function create(): Promise<void> {
  const result = await desktopApi.createWorkflowDefinition({
    name: '设备检查流程',
    description: '检查设备版本并输出结果',
    nodes: [{ id: 'command_1', action_id: 'device.command', config: { command: 'display version' } }],
    edges: []
  })
  await refresh()
  selectWorkflow(result.workflow as WorkflowItem)
}

function addNode(actionId: string): void {
  if (!selected.value) return
  const node: NodeItem = {
    id: `${actionId.split('.').pop()}_${Date.now().toString(36)}`,
    action_id: actionId,
    config: actionId === 'device.command' ? { command: '' } : actionId === 'utility.wait' ? { seconds: 1 } : actionId === 'utility.condition' ? { expression: '' } : {}
  }
  selected.value.nodes = [...(selected.value.nodes || []), node]
  selectedNode.value = node
}

function connectLast(): void {
  if (!selected.value || (selected.value.nodes || []).length < 2) return
  const nodes = selected.value.nodes || []
  const source = nodes[nodes.length - 2]
  const target = nodes[nodes.length - 1]
  const exists = (selected.value.edges || []).some((edge) => edge.source === source.id && edge.target === target.id)
  if (!exists) selected.value.edges = [...(selected.value.edges || []), { source: source.id, target: target.id }]
}

function removeNode(): void {
  if (!selected.value || !selectedNode.value) return
  const id = selectedNode.value.id
  selected.value.nodes = (selected.value.nodes || []).filter((node) => node !== selectedNode.value)
  selected.value.edges = (selected.value.edges || []).filter((edge) => edge.source !== id && edge.target !== id)
  selectedNode.value = selected.value.nodes?.[0] || null
}

async function validate(): Promise<void> {
  if (!selected.value) return
  const result = await desktopApi.validateWorkflowDefinition(selected.value.id, selected.value)
  issues.value = result.errors || []
  warnings.value = result.warnings || []
}

async function save(): Promise<void> {
  if (!selected.value) return
  saving.value = true
  try { const result = await desktopApi.saveWorkflowDefinition(selected.value.id, selected.value as unknown as Record<string, unknown>); selectWorkflow(result.workflow as WorkflowItem); await validate() } catch (cause) { error.value = String(cause) } finally { saving.value = false }
}

async function publish(): Promise<void> {
  if (!selected.value) return
  await validate()
  if (!canPublish.value) return
  const result = await desktopApi.publishWorkflowDefinition(selected.value.id)
  if (!result.published) issues.value = (result.errors || []).map((item) => ({ code: 'publish_error', message: item.message }))
  await refresh()
}

async function remove(): Promise<void> {
  if (!selected.value) return
  await desktopApi.deleteWorkflowDefinition(selected.value.id)
  selected.value = null
  selectedNode.value = null
  await refresh()
}

function nodeState(node: NodeItem): 'ready' | 'attention' {
  if (node.action_id === 'device.command') return typeof node.config.command === 'string' && Boolean(node.config.command.trim()) ? 'ready' : 'attention'
  if (node.action_id === 'utility.condition') return typeof node.config.expression === 'string' && Boolean(node.config.expression.trim()) ? 'ready' : 'attention'
  return 'ready'
}
function configString(key: string): string { return String(selectedNode.value?.config?.[key] ?? '') }
function updateConfigString(key: string, event: Event): void { if (selectedNode.value) selectedNode.value.config[key] = (event.target as HTMLInputElement | HTMLTextAreaElement).value }

onMounted(async () => { await refresh(); if (workflows.value[0]) selectWorkflow(workflows.value[0]) })
</script>

<template>
  <section class="workflow-library" aria-label="Workflow Library">
    <header class="workflow-library-header">
      <div><Workflow :size="18" /><div><strong>Workflow Studio</strong><small>把重复操作变成可复用流程</small></div></div>
      <button type="button" title="关闭" @click="emit('close')"><X :size="16" /></button>
    </header>
    <div class="workflow-library-toolbar">
      <button type="button" @click="create"><Plus :size="14" />新建流程</button>
      <button type="button" :disabled="!selected || saving" @click="save"><Save :size="14" />{{ saving ? '保存中…' : '保存草稿' }}</button>
      <button type="button" :disabled="!selected" @click="validate"><CheckCircle2 :size="14" />检查流程</button>
      <button class="primary-action" type="button" :disabled="!canPublish" @click="publish"><Play :size="14" />发布</button>
      <button class="danger-action" type="button" :disabled="!selected" @click="remove"><Trash2 :size="14" />删除</button>
    </div>
    <p v-if="error" class="workflow-error">{{ error }}</p>
    <div class="workflow-library-body">
      <aside class="workflow-list-pane">
        <div class="workflow-list-title"><span>我的流程</span><small>{{ workflows.length }} 个</small></div>
        <button v-for="item in workflows" :key="item.id" type="button" :class="{ active: selected?.id === item.id }" @click="selectWorkflow(item)">
          <strong>{{ item.name }}</strong><small>{{ item.description || '暂无描述' }}</small><em>v{{ item.version || '草稿' }}</em>
        </button>
        <p v-if="!loading && !workflows.length" class="workflow-empty-list">还没有流程<br /><span>点击“新建流程”开始</span></p>
      </aside>
      <main v-if="selected" class="workflow-studio-grid">
        <section class="workflow-action-catalog">
          <div class="panel-heading"><strong>添加步骤</strong><small>点击添加到流程末尾</small></div>
          <button v-for="action in actions" :key="action.id" type="button" :class="`action-tile tone-${action.tone}`" @click="addNode(action.id)"><span class="action-icon"><Plus :size="12" /></span><span><b>{{ action.label }}</b><small>{{ action.hint }}</small></span></button>
          <button class="connect-button" type="button" :disabled="(selected.nodes || []).length < 2" @click="connectLast"><GitBranch :size="13" />连接最近两步</button>
        </section>
        <section class="workflow-canvas">
          <div class="workflow-meta-fields"><label>流程名称<input v-model="selected.name" placeholder="例如：设备版本巡检" /></label><label>说明<input v-model="selected.description" placeholder="让团队知道这个流程做什么" /></label></div>
          <div class="canvas-hint"><span>开始</span><i></i><span>{{ (selected.nodes || []).length }} 个步骤</span><i></i><span>结束</span></div>
          <div class="workflow-node-list">
            <template v-for="(node, index) in selected.nodes || []" :key="node.id"><button type="button" class="workflow-node-card" :class="[{ active: selectedNode === node }, `state-${nodeState(node)}`]" @click="selectedNode = node"><span class="node-index">{{ index + 1 }}</span><span><strong>{{ actions.find((item) => item.id === node.action_id)?.label || node.action_id }}</strong><small>{{ node.id }}</small></span><CheckCircle2 v-if="nodeState(node) === 'ready'" :size="15" /><AlertTriangle v-else :size="15" /></button><div v-if="index < (selected.nodes || []).length - 1" class="node-connector">↓</div></template>
            <p v-if="!(selected.nodes || []).length" class="canvas-empty">从左侧选择一个步骤<br /><small>流程会按从上到下的顺序执行</small></p>
          </div>
        </section>
        <section v-if="selectedNode" class="workflow-properties">
          <div class="panel-heading"><strong>步骤设置</strong><small>{{ selectedAction?.label }}</small></div>
          <label>步骤名称<input v-model="selectedNode.id" /></label>
          <label v-if="selectedNode.action_id === 'device.command'">要执行的命令<textarea :value="configString('command')" rows="3" placeholder="例如：display version" @input="updateConfigString('command', $event)" /></label>
          <label v-else-if="selectedNode.action_id === 'utility.wait'">等待秒数<input v-model.number="selectedNode.config.seconds" type="number" min="1" max="3600" /></label>
          <label v-else-if="selectedNode.action_id === 'utility.condition'">判断条件<input :value="configString('expression')" placeholder="例如：输出包含 Online" @input="updateConfigString('expression', $event)" /></label>
          <div v-else class="risk-note"><AlertTriangle :size="15" />此步骤会执行高风险操作，发布前请确认目标设备。</div>
          <button class="remove-node-button" type="button" @click="removeNode"><Trash2 :size="13" />删除步骤</button>
        </section>
        <section v-else class="workflow-properties workflow-empty">选择一个步骤编辑参数</section>
      </main>
      <main v-else class="workflow-empty">选择一个 Workflow 开始编辑</main>
    </div>
    <footer v-if="selected" class="workflow-validation-bar" :class="{ invalid: issues.length, valid: !issues.length }"><span v-if="issues.length"><AlertTriangle :size="15" />还有 {{ issues.length }} 个问题需要处理</span><span v-else><CheckCircle2 :size="15" />流程结构看起来没问题</span><span v-if="warnings.length" class="warning-count">{{ warnings.length }} 个风险提示</span><button v-if="issues.length" type="button" @click="validate">重新检查</button></footer>
  </section>
</template>
