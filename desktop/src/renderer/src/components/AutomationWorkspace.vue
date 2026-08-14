<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  CircleStop,
  ChevronDown,
  CopyPlus,
  History,
  KeyRound,
  Play,
  Plus,
  Save,
  Search,
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
  AutomationActivityRecord,
  AutomationTargetOption
} from '../types'

type EditorMode = 'basic' | 'steps' | 'actions'

const workspace = useWorkspaceStore()
const selectedId = ref('')
const draft = ref<AutoResponseRulePayload>(newRule())
const draftBaseline = ref(JSON.stringify(draft.value))
const creatingNew = ref(false)
const loadedRuleId = ref('')
const ruleQuery = ref('')
const ruleStatusFilter = ref<'all' | 'active' | 'enabled' | 'disabled'>('all')
const ruleSearchInput = ref<HTMLInputElement | null>(null)
const activityExpanded = ref(false)
const localError = ref('')
const editorMode = ref<EditorMode>('basic')
let releaseCloseGuard: (() => void) | null = null

const isDirty = computed(() => JSON.stringify(draft.value) !== draftBaseline.value)
const draftStateText = computed(() => {
  if (isDirty.value) return '有未保存修改'
  return selectedRecord.value ? '已保存' : '新规则草稿'
})

const selectedRecord = computed<AutomationRuleRecord | null>(() =>
  workspace.automationRules.find((record) => record.id === selectedId.value) || null
)
const activeRunningIds = computed(
  () => new Set(workspace.activeAutomationStatus?.running_rule_ids || [])
)
const activeWaitingIds = computed(
  () => new Set(workspace.activeAutomationStatus?.waiting_rule_ids || [])
)
const filteredAutomationRules = computed(() => {
  const query = ruleQuery.value.trim().toLocaleLowerCase()
  return workspace.automationRules.filter((record) => {
    const active = activeRunningIds.value.has(record.id) || activeWaitingIds.value.has(record.id)
    if (ruleStatusFilter.value === 'active' && !active) return false
    if (ruleStatusFilter.value === 'enabled' && !record.rule.enabled) return false
    if (ruleStatusFilter.value === 'disabled' && record.rule.enabled) return false
    if (!query) return true
    return [record.id, record.rule.name, record.rule.pattern, record.rule.trigger_type]
      .join(' ')
      .toLocaleLowerCase()
      .includes(query)
  })
})
const ruleCountText = computed(() => {
  if (filteredAutomationRules.value.length === workspace.automationRules.length) {
    return `${workspace.automationRules.length} 条规则`
  }
  return `${filteredAutomationRules.value.length}/${workspace.automationRules.length} 条规则`
})
const recentActivity = computed(() => workspace.automationActivity
  .filter((item) => !workspace.activeSessionId || item.session_id === workspace.activeSessionId)
  .slice(0, 20)
)
const selectedRunning = computed(
  () => Boolean(selectedId.value && activeRunningIds.value.has(selectedId.value))
)
const selectedWaiting = computed(
  () => Boolean(selectedId.value && activeWaitingIds.value.has(selectedId.value))
)
const selectedInProgress = computed(() => selectedRunning.value || selectedWaiting.value)
const activeSessionConnected = computed(() => workspace.activeSession?.status === 'connected')
const runActionHint = computed(() => {
  if (!workspace.activeSession) return '请先打开并选择一个终端会话'
  if (!activeSessionConnected.value) return '当前终端未连接，请先重连终端'
  if (!selectedRecord.value) return '请先选择或保存一条规则'
  if (!selectedRecord.value.rule.enabled) return '当前规则已停用，请先启用规则'
  if (selectedRunning.value) return '规则正在当前终端执行'
  if (selectedWaiting.value) return '规则正在等待下一步终端输出'
  return '可在当前终端运行一次'
})
const activeTriggeredIds = computed(
  () => new Set(workspace.activeAutomationStatus?.triggered_rule_ids || [])
)
const runningRuleNames = computed(() =>
  workspace.automationRules
    .filter((record) => activeRunningIds.value.has(record.id))
    .map((record) => record.rule.name)
)
const waitingRuleNames = computed(() =>
  workspace.automationRules
    .filter((record) => activeWaitingIds.value.has(record.id))
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
  if (waitingRuleNames.value.length) return `${target} · 等待中：${waitingRuleNames.value.join('、')}`
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
    value: `session-id:${session.id}`,
    label: `${session.title} · ${session.kind.toUpperCase()}${session.status === 'connected' ? '' : ' · 未连接'}`
  }))
])

watch(
  () => workspace.automationRules,
  (rules) => {
    if (!selectedId.value && !creatingNew.value && rules.length) selectedId.value = rules[0].id
    if (selectedId.value && !rules.some((record) => record.id === selectedId.value)) {
      selectedId.value = rules[0]?.id || ''
      creatingNew.value = !selectedId.value
    }
  },
  { immediate: true, deep: true }
)

watch(selectedRecord, (record) => {
  if (record) {
    if (record.id === loadedRuleId.value && isDirty.value) return
    loadRecord(record)
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

function setDraftBaseline(): void {
  draftBaseline.value = JSON.stringify(draft.value)
}

function loadRecord(record: AutomationRuleRecord): void {
  selectedId.value = record.id
  loadedRuleId.value = record.id
  creatingNew.value = false
  draft.value = cloneRule(record.rule)
  editorMode.value = ruleEditorMode(record.rule)
  localError.value = ''
  setDraftBaseline()
}

function loadNewDraft(): void {
  selectedId.value = ''
  loadedRuleId.value = ''
  creatingNew.value = true
  draft.value = newRule()
  editorMode.value = 'basic'
  localError.value = ''
  setDraftBaseline()
}

function confirmDiscardChanges(action: string): boolean {
  return !isDirty.value || window.confirm(`当前规则有未保存修改，${action}会丢失这些修改。是否继续？`)
}

function discardCurrentDraft(): void {
  if (selectedRecord.value) loadRecord(selectedRecord.value)
  else loadNewDraft()
}

function prepareClose(): boolean {
  if (!confirmDiscardChanges('关闭自动化面板')) return false
  discardCurrentDraft()
  return true
}

function requestClose(): void {
  workspace.closeAutomationPanel()
}

function activityLabel(event: AutomationActivityRecord['event']): string {
  return event === 'started' ? '开始'
    : event === 'sent' ? '发送'
      : event === 'waiting' ? '等待'
        : event === 'completed' ? '完成'
          : event === 'failed' ? '失败'
            : '取消'
}

function activityTime(timestamp: string): string {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return '--:--:--'
  return date.toLocaleTimeString('zh-CN', { hour12: false })
}

function activityTarget(item: AutomationActivityRecord): string {
  if (!item.target_session_id) return ''
  const session = workspace.sessions.find((candidate) => candidate.id === item.target_session_id)
  return session ? ` → ${session.title}` : ` → ${item.target_session_id.slice(0, 8)}`
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
    response_append_enters: [draft.value.append_enter],
    timeout_ms: 0
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
  if (!confirmDiscardChanges('新建规则')) return
  loadNewDraft()
}

function selectRule(record: AutomationRuleRecord): void {
  if (record.id === selectedId.value) return
  if (!confirmDiscardChanges('切换规则')) return
  loadRecord(record)
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
    loadRecord(saved)
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
      response_append_enters: responseTexts.map((_, index) => Boolean(step.response_append_enters?.[index])),
      timeout_ms: Math.max(0, Math.min(3_600_000, Number(step.timeout_ms) || 0))
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
  if (!confirmDiscardChanges(record.rule.enabled ? '停用规则' : '启用规则')) return
  if (isDirty.value) discardCurrentDraft()
  await workspace.setAutomationRuleEnabled(record.id, !record.rule.enabled)
}

async function cloneSelected(): Promise<void> {
  const record = selectedRecord.value
  if (!record || isDirty.value) return
  const cloned = await workspace.cloneAutomationRule(record.id)
  if (!cloned) return
  ruleQuery.value = ''
  ruleStatusFilter.value = 'all'
  loadRecord(cloned)
}

async function removeSelected(): Promise<void> {
  const record = selectedRecord.value
  if (!record || !window.confirm(`确定删除自动化“${record.rule.name}”吗？`)) return
  if (await workspace.deleteAutomationRule(record.id)) loadNewDraft()
}

function handleAutomationShortcuts(event: KeyboardEvent): void {
  if (!workspace.automationPanelOpen) return
  if ((event.ctrlKey || event.metaKey) && event.key.toLocaleLowerCase() === 'f') {
    event.preventDefault()
    event.stopPropagation()
    ruleSearchInput.value?.focus()
    ruleSearchInput.value?.select()
    return
  }
  if (event.key !== 'Escape') return
  event.stopPropagation()
  if (ruleQuery.value) {
    ruleQuery.value = ''
    ruleSearchInput.value?.focus()
    return
  }
  requestClose()
}

function warnBeforeUnload(event: BeforeUnloadEvent): void {
  if (!isDirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onMounted(() => {
  releaseCloseGuard = workspace.registerAutomationCloseGuard(prepareClose)
  document.addEventListener('keydown', handleAutomationShortcuts, true)
  window.addEventListener('beforeunload', warnBeforeUnload)
})
onBeforeUnmount(() => {
  releaseCloseGuard?.()
  document.removeEventListener('keydown', handleAutomationShortcuts, true)
  window.removeEventListener('beforeunload', warnBeforeUnload)
})
</script>

<template>
  <div
    v-if="workspace.automationPanelOpen"
    class="automation-backdrop"
    @mousedown.self="requestClose"
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
          <span class="automation-rule-count">{{ ruleCountText }}</span>
          <span
            class="automation-session-status"
            :data-state="runningRuleNames.length ? 'running' : waitingRuleNames.length ? 'waiting' : triggeredRuleNames.length ? 'triggered' : 'idle'"
          >{{ automationStatusText }}</span>
          <button class="icon-button" type="button" aria-label="关闭自动化面板" @click="requestClose">
            <X :size="16" />
          </button>
        </div>
      </header>

      <div class="automation-body">
        <nav class="automation-rule-list" aria-label="自动化规则">
          <div class="automation-rule-tools">
            <label class="automation-rule-search">
              <Search :size="13" />
              <input
                ref="ruleSearchInput"
                v-model="ruleQuery"
                type="search"
                placeholder="搜索规则"
                aria-label="搜索自动化规则"
                aria-keyshortcuts="Control+F"
              />
            </label>
            <select v-model="ruleStatusFilter" class="automation-rule-filter" aria-label="筛选自动化规则状态">
              <option value="all">全部状态</option>
              <option value="active">运行或等待</option>
              <option value="enabled">已启用</option>
              <option value="disabled">已停用</option>
            </select>
            <button class="automation-new-button" type="button" @click="beginCreate">
              <Plus :size="14" />新建规则
            </button>
          </div>
          <button
            v-for="record in filteredAutomationRules"
            :key="record.id"
            class="automation-rule-row"
            :class="{ selected: record.id === selectedId }"
            type="button"
            :aria-current="record.id === selectedId ? 'true' : undefined"
            @click="selectRule(record)"
          >
            <i :data-state="activeRunningIds.has(record.id) ? 'running' : activeWaitingIds.has(record.id) ? 'waiting' : activeTriggeredIds.has(record.id) ? 'triggered' : record.rule.enabled ? 'enabled' : 'disabled'"></i>
            <span>
              <strong>{{ record.rule.name }}</strong>
              <small>{{ record.rule.trigger_type === 'match' ? record.rule.pattern : record.rule.trigger_type }}</small>
            </span>
            <b v-if="activeRunningIds.has(record.id)">运行中</b>
            <b v-else-if="activeWaitingIds.has(record.id)">等待中</b>
            <b v-else-if="activeTriggeredIds.has(record.id)">已触发</b>
          </button>
          <p v-if="!workspace.automationRules.length" class="automation-empty">
            暂无规则。创建后由 Python 后端监听终端输出并执行。
          </p>
          <p v-else-if="!filteredAutomationRules.length" class="automation-empty">
            没有匹配的规则。可清空搜索词或切换状态筛选。
          </p>
        </nav>

        <form class="automation-editor" @submit.prevent="save">
          <div class="automation-editor-toolbar">
            <div>
              <strong>{{ selectedRecord ? '编辑规则' : '新建规则' }}</strong>
              <span v-if="selectedRecord" class="mono">{{ selectedRecord.id }}</span>
              <span class="automation-draft-state" :data-dirty="isDirty">{{ draftStateText }}</span>
            </div>
            <div>
              <button
                v-if="selectedRecord"
                class="secondary-button"
                type="button"
                data-testid="automation-run"
                :title="runActionHint"
                aria-describedby="automation-run-hint"
                :disabled="!activeSessionConnected || !selectedRecord.rule.enabled || selectedInProgress || workspace.automationBusy"
                @click="workspace.triggerAutomationRule(selectedRecord.id)"
              ><Play :size="13" />{{ selectedRunning ? '运行中' : selectedWaiting ? '等待中' : '运行一次' }}</button>
              <button
                v-if="workspace.activeAutomationStatus?.running_rule_ids.length || workspace.activeAutomationStatus?.waiting_rule_ids.length"
                class="secondary-button danger-button"
                type="button"
                :disabled="workspace.automationBusy"
                @click="workspace.cancelActiveAutomation"
              ><CircleStop :size="13" />停止</button>
              <span id="automation-run-hint" class="automation-run-hint" :data-ready="activeSessionConnected && Boolean(selectedRecord?.rule.enabled)">
                <i aria-hidden="true"></i>{{ runActionHint }}
              </span>
            </div>
          </div>

          <div class="automation-form-scroll">
            <section class="automation-activity-panel" :data-expanded="activityExpanded">
              <button type="button" class="automation-activity-toggle" :aria-expanded="activityExpanded" @click="activityExpanded = !activityExpanded">
                <History :size="14" />
                <span>
                  <strong>最近执行</strong>
                  <small>{{ recentActivity.length ? `${recentActivity.length} 条当前会话记录` : '当前会话暂无记录' }}</small>
                </span>
                <ChevronDown :size="14" />
              </button>
              <div v-if="activityExpanded" class="automation-activity-list" aria-live="polite">
                <div v-for="item in recentActivity" :key="item.id" class="automation-activity-row" :data-event="item.event">
                  <time :datetime="item.timestamp">{{ activityTime(item.timestamp) }}</time>
                  <b>{{ activityLabel(item.event) }}</b>
                  <span><strong>{{ item.name }}</strong><small>{{ item.message }}{{ activityTarget(item) }}</small></span>
                </div>
                <p v-if="!recentActivity.length">运行规则后，开始、发送、等待、完成和失败记录会显示在这里。</p>
              </div>
            </section>
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
                data-testid="automation-clone"
                :title="isDirty ? '请先保存或放弃当前修改，再复制规则' : '创建默认停用的独立副本'"
                :disabled="workspace.automationBusy || isDirty"
                @click="cloneSelected"
              ><CopyPlus :size="13" />复制</button>
              <button
                v-if="selectedRecord"
                class="secondary-button"
                type="button"
                :disabled="workspace.automationBusy"
                @click="toggleEnabled(selectedRecord)"
              >{{ selectedRecord.rule.enabled ? '停用规则' : '启用规则' }}</button>
            </div>
            <button class="primary-button" data-testid="automation-save" type="submit" :disabled="workspace.automationBusy || Boolean(selectedRecord && !isDirty)">
              <Save :size="14" />{{ workspace.automationBusy ? '保存中…' : '保存规则' }}
            </button>
          </footer>
        </form>
      </div>
    </aside>
  </div>
</template>
