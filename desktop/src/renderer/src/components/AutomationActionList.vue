<script setup lang="ts">
import { ref, watch } from 'vue'
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Plus, Trash2 } from 'lucide-vue-next'
import type { AutoResponseAction, AutomationTargetOption } from '../types'

defineOptions({ name: 'AutomationActionList' })

const props = withDefaults(defineProps<{
  actions: AutoResponseAction[]
  targets: AutomationTargetOption[]
  depth?: number
  lockedStructure?: boolean
}>(), {
  depth: 0,
  lockedStructure: false
})

const emit = defineEmits<{
  update: [actions: AutoResponseAction[]]
}>()
let pendingActions: AutoResponseAction[] | null = null
const expandedIndexes = ref<Set<number>>(new Set())

watch(() => props.actions, (actions) => {
  const ownCommit = Boolean(
    pendingActions
    && JSON.stringify(actions) === JSON.stringify(pendingActions)
  )
  pendingActions = null
  if (!ownCommit) expandedIndexes.value = new Set()
}, { deep: true })

function cloneActions(): AutoResponseAction[] {
  return JSON.parse(JSON.stringify(pendingActions || props.actions)) as AutoResponseAction[]
}

function commitActions(actions: AutoResponseAction[]): void {
  pendingActions = actions
  emit('update', actions)
}

function defaultAction(kind: AutoResponseAction['kind']): AutoResponseAction {
  return {
    kind,
    text: '',
    target: 'current',
    delay_ms: kind === 'wait' ? 1000 : 0,
    append_enter: false,
    repeat_count: kind === 'loop' ? 2 : 1,
    interval_ms: kind === 'loop' ? 1000 : 0,
    exit_pattern: kind === 'exit' ? 'done' : '',
    exit_scope: 'loop',
    condition_pattern: kind === 'condition' ? '>' : '',
    condition_match_type: 'contains',
    variable_name: kind === 'set' ? 'counter' : '',
    variable_value: kind === 'set' ? '0' : '',
    variable_operation: 'set',
    actions: kind === 'loop' || kind === 'condition'
      ? [defaultAction('send')]
      : []
  }
}

function addAction(kind: AutoResponseAction['kind']): void {
  const next = [...cloneActions(), defaultAction(kind)]
  commitActions(next)
  expandedIndexes.value = new Set([next.length - 1])
}

function updateField<K extends keyof AutoResponseAction>(
  index: number,
  field: K,
  value: AutoResponseAction[K]
): void {
  const next = cloneActions()
  next[index][field] = value
  commitActions(next)
}

function updateChildren(index: number, actions: AutoResponseAction[]): void {
  updateField(index, 'actions', actions)
}

function removeAction(index: number): void {
  const next = cloneActions()
  next.splice(index, 1)
  commitActions(next)
  expandedIndexes.value = new Set(
    [...expandedIndexes.value]
      .filter((candidate) => candidate !== index)
      .map((candidate) => candidate > index ? candidate - 1 : candidate)
  )
}

function moveAction(index: number, offset: number): void {
  const target = index + offset
  const next = cloneActions()
  if (target < 0 || target >= next.length) return
  const [action] = next.splice(index, 1)
  next.splice(target, 0, action)
  commitActions(next)
  const expanded = new Set(expandedIndexes.value)
  const sourceExpanded = expanded.has(index)
  const targetExpanded = expanded.has(target)
  expanded.delete(index)
  expanded.delete(target)
  if (sourceExpanded) expanded.add(target)
  if (targetExpanded) expanded.add(index)
  expandedIndexes.value = expanded
}

function targetKnown(value: string): boolean {
  return props.targets.some((target) => target.value === value)
}

function actionLabel(kind: AutoResponseAction['kind']): string {
  return kind === 'send' ? '发送'
    : kind === 'wait' ? '等待'
      : kind === 'loop' ? '循环'
        : kind === 'condition' ? '条件'
          : kind === 'set' ? '变量'
            : '退出'
}

function isExpanded(index: number): boolean {
  return expandedIndexes.value.has(index)
}

function toggleExpanded(index: number): void {
  expandedIndexes.value = expandedIndexes.value.has(index)
    ? new Set()
    : new Set([index])
}

function compactText(value: string, fallback: string): string {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (!text) return fallback
  return text.length > 42 ? `${text.slice(0, 42)}…` : text
}

function formatDuration(value: number): string {
  const milliseconds = Math.max(0, Number(value) || 0)
  if (milliseconds === 0) return '立即'
  if (milliseconds >= 1000 && milliseconds % 1000 === 0) return `${milliseconds / 1000} 秒`
  return `${milliseconds} ms`
}

function targetLabel(value: string): string {
  return props.targets.find((target) => target.value === value)?.label || value || '当前会话'
}

function actionSummary(action: AutoResponseAction): string {
  if (action.kind === 'send') return compactText(action.text, '未填写发送内容')
  if (action.kind === 'wait') return `等待 ${formatDuration(action.delay_ms)}`
  if (action.kind === 'loop') return action.repeat_count > 0 ? `循环 ${action.repeat_count} 次` : '持续循环'
  if (action.kind === 'condition') {
    const prefix = action.condition_match_type === 'expression' ? '表达式'
      : action.condition_match_type === 'regex' ? '正则匹配'
        : '包含'
    return `${prefix} “${compactText(action.condition_pattern, '未填写条件')}”`
  }
  if (action.kind === 'set') {
    const operation = action.variable_operation === 'set' ? '='
      : action.variable_operation === 'add' ? '+='
        : action.variable_operation === 'subtract' ? '-='
          : '*='
    return `${action.variable_name || '未命名变量'} ${operation} ${compactText(action.variable_value, '未填写值')}`
  }
  return `遇到 “${compactText(action.exit_pattern, '未填写退出文本')}”`
}

function actionMeta(action: AutoResponseAction): string {
  if (action.kind === 'send') {
    const values = [targetLabel(action.target)]
    if (action.delay_ms > 0) values.push(`延迟 ${formatDuration(action.delay_ms)}`)
    if (action.append_enter) values.push('追加 Enter')
    return values.join(' · ')
  }
  if (action.kind === 'loop') {
    const values = [`${action.actions?.length || 0} 个子动作`]
    if (action.interval_ms > 0) values.push(`间隔 ${formatDuration(action.interval_ms)}`)
    return values.join(' · ')
  }
  if (action.kind === 'condition') return `${action.actions?.length || 0} 个子动作`
  if (action.kind === 'set') return '可在后续文本中使用 {{变量名}}'
  if (action.kind === 'exit') return action.exit_scope === 'rule' ? '停止整个规则' : '退出当前循环'
  return ''
}

function numberValue(event: Event): number {
  return Math.max(0, Number((event.target as HTMLInputElement).value) || 0)
}
</script>

<template>
  <div class="automation-action-list" :data-depth="depth">
    <div class="automation-action-add" role="toolbar" :aria-label="depth ? '添加嵌套动作' : '添加动作'">
      <span>
        <strong>{{ depth ? '子动作' : '动作流' }}</strong>
        <small>{{ actions.length }} 个动作 · 点击动作展开参数</small>
      </span>
      <button type="button" data-action-kind="send" :disabled="lockedStructure" @click="addAction('send')"><Plus :size="11" />发送</button>
      <button type="button" data-action-kind="wait" :disabled="lockedStructure" @click="addAction('wait')"><Plus :size="11" />等待</button>
      <button type="button" data-action-kind="loop" :disabled="lockedStructure" @click="addAction('loop')"><Plus :size="11" />循环</button>
      <button type="button" data-action-kind="condition" :disabled="lockedStructure" @click="addAction('condition')"><Plus :size="11" />条件</button>
      <button type="button" data-action-kind="set" :disabled="lockedStructure" @click="addAction('set')"><Plus :size="11" />变量</button>
      <button type="button" data-action-kind="exit" :disabled="lockedStructure" @click="addAction('exit')"><Plus :size="11" />退出</button>
    </div>

    <article
      v-for="(action, index) in actions"
      :key="index"
      class="automation-action-card"
      :class="[`kind-${action.kind}`, { protected: action.text.includes('••••••') }]"
      :data-action-index="index"
      :data-action-kind="action.kind"
      :data-expanded="isExpanded(index)"
    >
      <header>
        <button
          class="automation-action-summary"
          type="button"
          :aria-expanded="isExpanded(index)"
          :title="isExpanded(index) ? '收起动作参数' : '展开动作参数'"
          @click="toggleExpanded(index)"
        >
          <ChevronDown v-if="isExpanded(index)" :size="14" />
          <ChevronRight v-else :size="14" />
          <b>{{ actionLabel(action.kind) }}</b>
          <span>
            <strong>{{ actionSummary(action) }}</strong>
            <small v-if="actionMeta(action)">{{ actionMeta(action) }}</small>
          </span>
          <i>#{{ index + 1 }}</i>
        </button>
        <div class="automation-action-controls">
          <button type="button" title="上移动作" :disabled="lockedStructure || index === 0" @click="moveAction(index, -1)"><ArrowUp :size="12" /></button>
          <button type="button" title="下移动作" :disabled="lockedStructure || index === actions.length - 1" @click="moveAction(index, 1)"><ArrowDown :size="12" /></button>
          <button class="danger-icon" type="button" title="删除动作" :disabled="lockedStructure" @click="removeAction(index)"><Trash2 :size="12" /></button>
        </div>
      </header>

      <div v-show="isExpanded(index)" class="automation-action-details">
      <div v-if="action.kind === 'send'" class="automation-action-fields send-fields">
        <label class="form-field form-field-wide">
          <span>发送内容</span>
          <textarea
            class="automation-action-send-text"
            :value="action.text"
            rows="2"
            spellcheck="false"
            :readonly="action.text.includes('••••••')"
            @input="updateField(index, 'text', ($event.target as HTMLTextAreaElement).value)"
          ></textarea>
        </label>
        <label class="form-field">
          <span>发送目标</span>
          <select class="automation-action-send-target" :value="action.target" @change="updateField(index, 'target', ($event.target as HTMLSelectElement).value)">
            <option v-if="!targetKnown(action.target)" :value="action.target">保留目标：{{ action.target }}</option>
            <option v-for="target in targets" :key="target.value" :value="target.value">{{ target.label }}</option>
          </select>
        </label>
        <label class="form-field">
          <span>发送前延迟（ms）</span>
          <input class="automation-action-send-delay" :value="action.delay_ms" type="number" min="0" max="3600000" @input="updateField(index, 'delay_ms', numberValue($event))" />
        </label>
        <label class="automation-inline-option"><input class="automation-action-send-append" :checked="action.append_enter" type="checkbox" @change="updateField(index, 'append_enter', ($event.target as HTMLInputElement).checked)" />发送后追加 Enter</label>
      </div>

      <div v-else-if="action.kind === 'wait'" class="automation-action-fields">
        <label class="form-field">
          <span>等待时间（ms）</span>
          <input :value="action.delay_ms" type="number" min="0" max="3600000" @input="updateField(index, 'delay_ms', numberValue($event))" />
        </label>
      </div>

      <div v-else-if="action.kind === 'set'" class="automation-action-fields automation-variable-fields">
        <label class="form-field">
          <span>变量名</span>
          <input
            class="automation-action-variable-name"
            :value="action.variable_name"
            maxlength="64"
            autocomplete="off"
            placeholder="例如 counter"
            @input="updateField(index, 'variable_name', ($event.target as HTMLInputElement).value)"
          />
        </label>
        <label class="form-field">
          <span>操作</span>
          <select
            class="automation-action-variable-operation"
            :value="action.variable_operation"
            @change="updateField(index, 'variable_operation', ($event.target as HTMLSelectElement).value as AutoResponseAction['variable_operation'])"
          >
            <option value="set">赋值 =</option>
            <option value="add">增加 +=</option>
            <option value="subtract">减少 -=</option>
            <option value="multiply">乘以 *=</option>
          </select>
        </label>
        <label class="form-field form-field-wide">
          <span>变量值 / 表达式</span>
          <input
            class="automation-action-variable-value"
            :value="action.variable_value"
            maxlength="4000"
            autocomplete="off"
            placeholder="例如 2000 或 {{base + loop.index0 * step}}"
            @input="updateField(index, 'variable_value', ($event.target as HTMLInputElement).value)"
          />
        </label>
        <small class="automation-variable-hint">支持数字、字符串、数组、对象和安全表达式。发送、条件和退出文本可使用 <code v-pre>{{counter}}</code>；赋值时可写 <code v-pre>{{base + loop.index0 * step}}</code>。</small>
      </div>

      <div v-else-if="action.kind === 'exit'" class="automation-action-fields">
        <label class="form-field">
          <span>看到以下输出时退出</span>
            <input class="automation-action-exit-pattern" :value="action.exit_pattern" maxlength="4000" @input="updateField(index, 'exit_pattern', ($event.target as HTMLInputElement).value)" />
        </label>
        <label class="form-field">
          <span>退出范围</span>
          <select class="automation-action-exit-scope" :value="action.exit_scope" @change="updateField(index, 'exit_scope', ($event.target as HTMLSelectElement).value as 'loop' | 'rule')">
            <option value="loop">退出当前循环</option>
            <option value="rule">停止整个规则</option>
          </select>
        </label>
      </div>

      <template v-else-if="action.kind === 'loop'">
        <div class="automation-action-fields">
          <label class="form-field">
            <span>执行次数（0=持续循环）</span>
            <input class="automation-action-loop-repeat" :value="action.repeat_count" type="number" min="0" max="100" @input="updateField(index, 'repeat_count', Math.min(100, numberValue($event)))" />
          </label>
          <label class="form-field">
            <span>每轮间隔（ms）</span>
            <input class="automation-action-loop-interval" :value="action.interval_ms" type="number" min="0" max="3600000" @input="updateField(index, 'interval_ms', numberValue($event))" />
          </label>
        </div>
        <small class="automation-variable-hint">循环体内可直接使用 <code v-pre>{{loop.index}}</code>（从 1 开始）、<code v-pre>{{loop.index0}}</code>（从 0 开始）和 <code v-pre>{{loop.count}}</code>。</small>
        <AutomationActionList
          :actions="action.actions || []"
          :targets="targets"
          :depth="depth + 1"
          :locked-structure="lockedStructure"
          @update="updateChildren(index, $event)"
        />
      </template>

      <template v-else-if="action.kind === 'condition'">
        <div class="automation-action-fields">
          <label class="form-field">
            <span>{{ action.condition_match_type === 'expression' ? '条件表达式' : '条件文本' }}</span>
            <input class="automation-action-condition-pattern" :value="action.condition_pattern" maxlength="4000" @input="updateField(index, 'condition_pattern', ($event.target as HTMLInputElement).value)" />
          </label>
          <label class="form-field">
            <span>条件匹配</span>
            <select class="automation-action-condition-match" :value="action.condition_match_type" @change="updateField(index, 'condition_match_type', ($event.target as HTMLSelectElement).value as AutoResponseAction['condition_match_type'])">
              <option value="contains">包含文本</option>
              <option value="regex">正则表达式</option>
              <option value="expression">变量表达式</option>
            </select>
          </label>
        </div>
        <AutomationActionList
          :actions="action.actions || []"
          :targets="targets"
          :depth="depth + 1"
          :locked-structure="lockedStructure"
          @update="updateChildren(index, $event)"
        />
      </template>
      </div>
    </article>

    <p v-if="!actions.length" class="automation-action-empty">还没有动作。添加发送、等待、循环、条件或退出动作。</p>
  </div>
</template>
