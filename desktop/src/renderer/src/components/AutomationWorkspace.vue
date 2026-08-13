<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  CircleStop,
  KeyRound,
  Play,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
  Workflow,
  X
} from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import AutomationActionList from './AutomationActionList.vue'
import AutomationStepEditor from './AutomationStepEditor.vue'
import type {
  AutoResponseAction,
  AutoResponseRulePayload,
  AutoResponseStep,
  AutomationRuleRecord,
  AutomationTargetOption
} from '../types'

type EditorMode = 'basic' | 'steps' | 'actions'

const workspace = useWorkspaceStore()
const selectedId = ref('')
const draft = ref<AutoResponseRulePayload>(newRule())
const localError = ref('')
const editorMode = ref<EditorMode>('basic')

const selectedRecord = computed<AutomationRuleRecord | null>(() =>
  workspace.automationRules.find((record) => record.id === selectedId.value) || null
)
const activeRunningIds = computed(
  () => new Set(workspace.activeAutomationStatus?.running_rule_ids || [])
)
const selectedRunning = computed(
  () => Boolean(selectedId.value && activeRunningIds.value.has(selectedId.value))
)
const activeTriggeredIds = computed(
  () => new Set(workspace.activeAutomationStatus?.triggered_rule_ids || [])
)
const runningRuleNames = computed(() =>
  workspace.automationRules
    .filter((record) => activeRunningIds.value.has(record.id))
    .map((record) => record.rule.name)
)
const triggeredRuleNames = computed(() =>
  workspace.automationRules
    .filter((record) => activeTriggeredIds.value.has(record.id))
    .map((record) => record.rule.name)
)
const automationStatusText = computed(() => {
  if (!workspace.activeSession) return '当前没有活动终端会话。'
  const target = workspace.activeSession.title
  if (runningRuleNames.value.length) return `${target} · 运行中：${runningRuleNames.value.join('、')}`
  if (triggeredRuleNames.value.length) return `${target} · 已触发：${triggeredRuleNames.value.join('、')}`
  return `${target} · 当前会话暂无运行中的自动响应。`
})
const protectedResponse = computed(() => draft.value.response_text.includes('••••••'))
const protectedAdvancedStructure = computed(() =>
  JSON.stringify([draft.value.steps || [], draft.value.actions || []]).includes('••••••')
)
const automationTargets = computed<AutomationTargetOption[]>(() => [
  { value: 'source', label: '触发来源会话' },
  { value: 'current', label: '当前触发会话' },
  { value: 'next', label: '同设备下一个会话' },
  ...workspace.sessions.map((session) => ({
    value: `session:${session.device_id}:${session.kind}:${session.title}`,
    label: `${session.title} · ${session.kind.toUpperCase()}`
  }))
])

watch(
  () => workspace.automationRules,
  (rules) => {
    if (!selectedId.value && rules.length) selectedId.value = rules[0].id
    if (selectedId.value && !rules.some((record) => record.id === selectedId.value)) {
      selectedId.value = rules[0]?.id || ''
    }
  },
  { immediate: true, deep: true }
)

watch(selectedRecord, (record) => {
  if (record) {
    draft.value = cloneRule(record.rule)
    editorMode.value = ruleEditorMode(record.rule)
  }
}, { immediate: true })

function newRule(): AutoResponseRulePayload {
  return {
    name: '新建自动化',
    pattern: '',
    response: '',
    response_text: '',
    append_enter: true,
    enabled: true,
    case_sensitive: false,
    once: false,
    match_type: 'contains',
    delay_ms: 0,
    max_triggers: 0,
    trigger_type: 'match',
    trigger_delay_ms: 0,
    loop_count: 1,
    kind: 'capture',
    allow_startup_trigger: false,
    trigger_count: 0,
    steps: [],
    actions: []
  }
}

function cloneRule(rule: AutoResponseRulePayload): AutoResponseRulePayload {
  return JSON.parse(JSON.stringify(rule)) as AutoResponseRulePayload
}

function ruleEditorMode(rule: AutoResponseRulePayload): EditorMode {
  if (rule.actions?.length) return 'actions'
  if (rule.steps?.length) return 'steps'
  return 'basic'
}

function defaultStep(): AutoResponseStep {
  const text = draft.value.response_text || ''
  return {
    pattern: draft.value.pattern || '',
    responses: [text],
    response_texts: [text],
    response_targets: ['source'],
    response_delays: [Math.max(0, Number(draft.value.delay_ms) || 0)],
    response_append_enters: [draft.value.append_enter]
  }
}

function defaultAction(): AutoResponseAction {
  return {
    kind: 'send',
    text: draft.value.response_text || '',
    target: 'current',
    delay_ms: Math.max(0, Number(draft.value.delay_ms) || 0),
    append_enter: draft.value.append_enter,
    repeat_count: 1,
    interval_ms: 0,
    exit_pattern: '',
    exit_scope: 'loop',
    condition_pattern: '',
    condition_match_type: 'contains',
    actions: []
  }
}

function setEditorMode(mode: EditorMode): void {
  if (mode === editorMode.value) return
  if (protectedAdvancedStructure.value) {
    localError.value = '该规则包含受保护的敏感响应，不能改变高级结构；可继续编辑非结构字段。'
    return
  }
  const hasAdvanced = Boolean(draft.value.steps?.length || draft.value.actions?.length)
  if (
    hasAdvanced
    && selectedRecord.value
    && !window.confirm('切换编辑模式会将现有高级结构转换为所选模式，是否继续？')
  ) return
  if (mode === 'steps') {
    draft.value.steps = draft.value.steps?.length ? draft.value.steps : [defaultStep()]
    draft.value.actions = []
    draft.value.kind = 'advanced'
  } else if (mode === 'actions') {
    draft.value.actions = draft.value.actions?.length ? draft.value.actions : [defaultAction()]
    draft.value.steps = []
    draft.value.kind = 'advanced'
  } else {
    const firstStepText = draft.value.steps?.[0]?.response_texts?.[0]
    const firstActionText = firstSendText(draft.value.actions || [])
    if (!draft.value.response_text) {
      draft.value.response_text = firstStepText || firstActionText || ''
    }
    draft.value.steps = []
    draft.value.actions = []
    draft.value.kind = 'capture'
  }
  editorMode.value = mode
  localError.value = ''
}

function firstSendText(actions: AutoResponseAction[]): string {
  for (const action of actions) {
    if (action.kind === 'send') return action.text
    const nested = firstSendText(action.actions || [])
    if (nested) return nested
  }
  return ''
}

function updateSteps(steps: AutoResponseStep[]): void {
  draft.value.steps = steps
}

function updateActions(actions: AutoResponseAction[]): void {
  draft.value.actions = actions
}

function beginCreate(): void {
  selectedId.value = ''
  draft.value = newRule()
  editorMode.value = 'basic'
  localError.value = ''
}

function selectRule(record: AutomationRuleRecord): void {
  selectedId.value = record.id
  draft.value = cloneRule(record.rule)
  localError.value = ''
}

async function save(): Promise<void> {
  localError.value = ''
  const value = cloneRule(draft.value)
  value.name = value.name.trim()
  value.pattern = value.pattern.trim()
  value.delay_ms = Math.max(0, Number(value.delay_ms) || 0)
  value.trigger_delay_ms = Math.max(0, Number(value.trigger_delay_ms) || 0)
  value.max_triggers = Math.max(0, Number(value.max_triggers) || 0)
  value.loop_count = Math.max(1, Math.min(10, Number(value.loop_count) || 1))
  if (!value.name) {
    localError.value = '请输入规则名称。'
    return
  }

  if (editorMode.value === 'steps') {
    value.steps = normalizeSteps(value.steps || [])
    value.actions = []
    value.kind = 'advanced'
    if (!value.steps.length) {
      localError.value = '请至少添加一个流程步骤。'
      return
    }
    if (value.steps.some((step) => !step.response_texts.length || step.response_texts.some((text) => !text))) {
      localError.value = '每个流程步骤都必须包含非空响应。'
      return
    }
    if (value.trigger_type === 'match' && !value.steps[0].pattern) {
      localError.value = '输出匹配流程的第一步必须填写等待文本。'
      return
    }
    value.pattern = value.steps[0].pattern || value.pattern
    value.response_text = value.steps[0].response_texts[0] || ''
    value.response = ''
  } else if (editorMode.value === 'actions') {
    value.actions = normalizeActions(value.actions || [])
    value.steps = []
    value.kind = 'advanced'
    const validationError = validateActions(value.actions)
    if (validationError) {
      localError.value = validationError
      return
    }
    value.response_text = firstSendText(value.actions)
    value.response = ''
  } else {
    value.steps = []
    value.actions = []
    value.kind = 'capture'
    if (!value.response_text) {
      localError.value = '请输入发送内容。'
      return
    }
    value.response = value.response_text === '••••••' ? '••••••' : ''
  }
  if (value.trigger_type === 'match' && !value.pattern) {
    localError.value = '输出匹配规则需要填写触发文本。'
    return
  }
  const saved = await workspace.saveAutomationRule(value, selectedId.value)
  if (saved) {
    selectedId.value = saved.id
    draft.value = cloneRule(saved.rule)
  }
}

function normalizeSteps(steps: AutoResponseStep[]): AutoResponseStep[] {
  return steps.map((step) => {
    const responseTexts = [...(step.response_texts || [])].map(String)
    return {
      pattern: String(step.pattern || '').trim(),
      responses: responseTexts.slice(),
      response_texts: responseTexts,
      response_targets: responseTexts.map((_, index) => step.response_targets?.[index] || 'source'),
      response_delays: responseTexts.map((_, index) => Math.max(0, Number(step.response_delays?.[index]) || 0)),
      response_append_enters: responseTexts.map((_, index) => Boolean(step.response_append_enters?.[index]))
    }
  })
}

function normalizeActions(actions: AutoResponseAction[]): AutoResponseAction[] {
  return actions.map((action) => ({
    ...action,
    text: String(action.text || ''),
    target: String(action.target || 'current'),
    delay_ms: Math.max(0, Number(action.delay_ms) || 0),
    append_enter: Boolean(action.append_enter),
    repeat_count: Math.max(0, Math.min(100, Number(action.repeat_count) || 0)),
    interval_ms: Math.max(0, Number(action.interval_ms) || 0),
    exit_pattern: String(action.exit_pattern || ''),
    exit_scope: action.exit_scope === 'rule' ? 'rule' : 'loop',
    condition_pattern: String(action.condition_pattern || ''),
    condition_match_type: action.condition_match_type === 'regex' ? 'regex' : 'contains',
    actions: normalizeActions(action.actions || [])
  }))
}

function validateActions(actions: AutoResponseAction[], path = '动作流'): string {
  if (!actions.length) return `${path}不能为空。`
  for (let index = 0; index < actions.length; index += 1) {
    const action = actions[index]
    const label = `${path}第 ${index + 1} 项`
    if (action.kind === 'send' && !action.text) return `${label}的发送内容不能为空。`
    if (action.kind === 'exit' && !action.exit_pattern) return `${label}必须填写退出匹配文本。`
    if (action.kind === 'condition') {
      if (!action.condition_pattern) return `${label}必须填写条件文本。`
      const nested = validateActions(action.actions || [], `${label}的条件分支`)
      if (nested) return nested
    }
    if (action.kind === 'loop') {
      const nested = validateActions(action.actions || [], `${label}的循环体`)
      if (nested) return nested
    }
  }
  return ''
}

async function toggleEnabled(record: AutomationRuleRecord): Promise<void> {
  await workspace.setAutomationRuleEnabled(record.id, !record.rule.enabled)
}

async function removeSelected(): Promise<void> {
  const record = selectedRecord.value
  if (!record || !window.confirm(`确定删除自动化“${record.rule.name}”吗？`)) return
  if (await workspace.deleteAutomationRule(record.id)) beginCreate()
}

function closeOnEscape(event: KeyboardEvent): void {
  if (event.key === 'Escape' && workspace.automationPanelOpen) {
    workspace.automationPanelOpen = false
  }
}

onMounted(() => document.addEventListener('keydown', closeOnEscape))
onBeforeUnmount(() => document.removeEventListener('keydown', closeOnEscape))
</script>

<template>
  <div
    v-if="workspace.automationPanelOpen"
    class="automation-backdrop"
    @mousedown.self="workspace.automationPanelOpen = false"
  >
    <aside
      class="automation-workspace"
      role="region"
      aria-labelledby="automation-title"
      :data-active-session-id="workspace.activeSessionId"
    >
      <header class="automation-header">
        <div class="automation-heading">
          <span class="automation-icon"><Workflow :size="18" /></span>
          <div>
            <p class="eyebrow">PYTHON ORCHESTRATION</p>
            <h2 id="automation-title">终端自动化</h2>
          </div>
        </div>
        <div class="automation-header-actions">
          <span>{{ workspace.automationRules.length }} 条规则</span>
          <span
            class="automation-session-status"
            :data-state="runningRuleNames.length ? 'running' : triggeredRuleNames.length ? 'triggered' : 'idle'"
          >{{ automationStatusText }}</span>
          <button class="icon-button" type="button" aria-label="关闭自动化面板" @click="workspace.automationPanelOpen = false">
            <X :size="16" />
          </button>
        </div>
      </header>

      <div class="automation-body">
        <nav class="automation-rule-list" aria-label="自动化规则">
          <button class="automation-new-button" type="button" @click="beginCreate">
            <Plus :size="14" />新建规则
          </button>
          <button
            v-for="record in workspace.automationRules"
            :key="record.id"
            class="automation-rule-row"
            :class="{ selected: record.id === selectedId }"
            type="button"
            :aria-current="record.id === selectedId ? 'true' : undefined"
            @click="selectRule(record)"
          >
            <i :data-state="activeRunningIds.has(record.id) ? 'running' : activeTriggeredIds.has(record.id) ? 'triggered' : record.rule.enabled ? 'enabled' : 'disabled'"></i>
            <span>
              <strong>{{ record.rule.name }}</strong>
              <small>{{ record.rule.trigger_type === 'match' ? record.rule.pattern : record.rule.trigger_type }}</small>
            </span>
            <b v-if="activeRunningIds.has(record.id)">运行中</b>
            <b v-else-if="activeTriggeredIds.has(record.id)">已触发</b>
          </button>
          <p v-if="!workspace.automationRules.length" class="automation-empty">
            暂无规则。创建后由 Python 后端监听终端输出并执行。
          </p>
        </nav>

        <form class="automation-editor" @submit.prevent="save">
          <div class="automation-editor-toolbar">
            <div>
              <strong>{{ selectedRecord ? '编辑规则' : '新建规则' }}</strong>
              <span v-if="selectedRecord" class="mono">{{ selectedRecord.id }}</span>
            </div>
            <div>
              <button
                v-if="selectedRecord"
                class="secondary-button"
                type="button"
                data-testid="automation-run"
                :disabled="!workspace.activeSession || !selectedRecord.rule.enabled || workspace.automationBusy"
                @click="workspace.triggerAutomationRule(selectedRecord.id)"
              ><Play :size="13" />{{ selectedRunning ? '运行中' : '运行一次' }}</button>
              <button
                v-if="workspace.activeAutomationStatus?.running_rule_ids.length"
                class="secondary-button danger-button"
                type="button"
                :disabled="workspace.automationBusy"
                @click="workspace.cancelActiveAutomation"
              ><CircleStop :size="13" />停止</button>
            </div>
          </div>

          <div class="automation-form-scroll">
            <div v-if="protectedAdvancedStructure" class="automation-info-banner secure">
              <ShieldCheck :size="15" />高级结构包含系统凭据库托管的敏感响应；为避免错配，结构增删和移动已锁定。
            </div>
            <div v-if="protectedResponse" class="automation-info-banner secure">
              <ShieldCheck :size="15" />敏感响应保存在操作系统凭据库中，界面只显示掩码。
            </div>

            <label class="form-field form-field-wide">
              <span>规则名称</span>
              <input v-model="draft.name" data-testid="automation-name" maxlength="160" autocomplete="off" />
            </label>
            <div class="automation-editor-mode" role="radiogroup" aria-label="响应编辑模式">
              <button type="button" data-testid="automation-mode-basic" :class="{ active: editorMode === 'basic' }" :aria-checked="editorMode === 'basic'" role="radio" @click="setEditorMode('basic')">基础响应</button>
              <button type="button" data-testid="automation-mode-steps" :class="{ active: editorMode === 'steps' }" :aria-checked="editorMode === 'steps'" role="radio" @click="setEditorMode('steps')">分步流程</button>
              <button type="button" data-testid="automation-mode-actions" :class="{ active: editorMode === 'actions' }" :aria-checked="editorMode === 'actions'" role="radio" @click="setEditorMode('actions')">动作流</button>
            </div>
            <label class="form-field">
              <span>触发方式</span>
              <select v-model="draft.trigger_type" data-testid="automation-trigger">
                <option value="match">匹配终端输出</option>
                <option value="connected">连接成功后</option>
                <option value="immediate">会话就绪后立即</option>
                <option value="delay">连接后延迟</option>
                <option value="manual">仅手动运行</option>
              </select>
            </label>
            <label class="form-field">
              <span>匹配方式</span>
              <select v-model="draft.match_type" :disabled="draft.trigger_type !== 'match'">
                <option value="contains">包含文本</option>
                <option value="regex">正则表达式</option>
              </select>
            </label>
            <label class="form-field form-field-wide">
              <span>触发文本</span>
              <input
                v-model="draft.pattern"
                :disabled="draft.trigger_type !== 'match'"
                maxlength="4000"
                placeholder="例如 Login: 或正则表达式"
                autocomplete="off"
              />
            </label>
            <label v-if="editorMode === 'basic'" class="form-field form-field-wide">
              <span>发送内容</span>
              <textarea
                v-model="draft.response_text"
                data-testid="automation-response"
                rows="4"
                maxlength="100000"
                spellcheck="false"
                :readonly="protectedResponse"
                placeholder="支持 Ctrl+B、\\r、\\n、\\x1b 等写法"
              ></textarea>
            </label>

            <AutomationStepEditor
              v-if="editorMode === 'steps'"
              :steps="draft.steps || []"
              :targets="automationTargets"
              :locked-structure="protectedAdvancedStructure"
              @update="updateSteps"
            />
            <AutomationActionList
              v-else-if="editorMode === 'actions'"
              :actions="draft.actions || []"
              :targets="automationTargets"
              :locked-structure="protectedAdvancedStructure"
              @update="updateActions"
            />

            <div class="automation-number-grid">
              <label class="form-field">
                <span>发送前延迟（ms）</span>
                <input v-model.number="draft.delay_ms" type="number" min="0" max="3600000" />
              </label>
              <label class="form-field">
                <span>触发延迟（ms）</span>
                <input v-model.number="draft.trigger_delay_ms" type="number" min="0" max="3600000" :disabled="draft.trigger_type !== 'delay'" />
              </label>
              <label class="form-field">
                <span>流程循环</span>
                <input v-model.number="draft.loop_count" type="number" min="1" max="10" />
              </label>
              <label class="form-field">
                <span>最大命中（0=不限）</span>
                <input v-model.number="draft.max_triggers" type="number" min="0" max="100000" />
              </label>
            </div>

            <fieldset class="automation-options">
              <legend>执行策略</legend>
              <label><input v-model="draft.append_enter" type="checkbox" />发送后追加 Enter</label>
              <label><input v-model="draft.once" type="checkbox" />完成后自动停用</label>
              <label><input v-model="draft.case_sensitive" type="checkbox" />区分大小写</label>
              <label><input v-model="draft.allow_startup_trigger" type="checkbox" />允许在登录前触发</label>
            </fieldset>

            <div class="automation-security-note">
              <KeyRound :size="14" />密码、口令和令牌响应不能通过普通编辑器保存；旧数据会自动迁入系统凭据库。
            </div>
            <p v-if="localError || workspace.error" class="automation-error" role="alert">
              {{ localError || workspace.error }}
            </p>
          </div>

          <footer class="automation-footer">
            <div>
              <button
                v-if="selectedRecord"
                class="secondary-button danger-button"
                type="button"
                :disabled="workspace.automationBusy"
                @click="removeSelected"
              ><Trash2 :size="13" />删除</button>
              <button
                v-if="selectedRecord"
                class="secondary-button"
                type="button"
                :disabled="workspace.automationBusy"
                @click="toggleEnabled(selectedRecord)"
              >{{ selectedRecord.rule.enabled ? '停用规则' : '启用规则' }}</button>
            </div>
            <button class="primary-button" data-testid="automation-save" type="submit" :disabled="workspace.automationBusy">
              <Save :size="14" />{{ workspace.automationBusy ? '保存中…' : '保存规则' }}
            </button>
          </footer>
        </form>
      </div>
    </aside>
  </div>
</template>
