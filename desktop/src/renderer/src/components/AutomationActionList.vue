<script setup lang="ts">
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-vue-next'
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

function cloneActions(): AutoResponseAction[] {
  return JSON.parse(JSON.stringify(props.actions)) as AutoResponseAction[]
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
    actions: kind === 'loop' || kind === 'condition'
      ? [defaultAction('send')]
      : []
  }
}

function addAction(kind: AutoResponseAction['kind']): void {
  emit('update', [...cloneActions(), defaultAction(kind)])
}

function updateField<K extends keyof AutoResponseAction>(
  index: number,
  field: K,
  value: AutoResponseAction[K]
): void {
  const next = cloneActions()
  next[index][field] = value
  emit('update', next)
}

function updateChildren(index: number, actions: AutoResponseAction[]): void {
  updateField(index, 'actions', actions)
}

function removeAction(index: number): void {
  const next = cloneActions()
  next.splice(index, 1)
  emit('update', next)
}

function moveAction(index: number, offset: number): void {
  const target = index + offset
  if (target < 0 || target >= props.actions.length) return
  const next = cloneActions()
  const [action] = next.splice(index, 1)
  next.splice(target, 0, action)
  emit('update', next)
}

function targetKnown(value: string): boolean {
  return props.targets.some((target) => target.value === value)
}

function actionLabel(kind: AutoResponseAction['kind']): string {
  return kind === 'send' ? '发送'
    : kind === 'wait' ? '等待'
      : kind === 'loop' ? '循环'
        : kind === 'condition' ? '条件'
          : '退出'
}

function numberValue(event: Event): number {
  return Math.max(0, Number((event.target as HTMLInputElement).value) || 0)
}
</script>

<template>
  <div class="automation-action-list" :data-depth="depth">
    <div class="automation-action-add" role="toolbar" :aria-label="depth ? '添加嵌套动作' : '添加动作'">
      <span>{{ depth ? '添加子动作' : '动作流' }}</span>
      <button type="button" data-action-kind="send" :disabled="lockedStructure" @click="addAction('send')"><Plus :size="11" />发送</button>
      <button type="button" data-action-kind="wait" :disabled="lockedStructure" @click="addAction('wait')"><Plus :size="11" />等待</button>
      <button type="button" data-action-kind="loop" :disabled="lockedStructure" @click="addAction('loop')"><Plus :size="11" />循环</button>
      <button type="button" data-action-kind="condition" :disabled="lockedStructure" @click="addAction('condition')"><Plus :size="11" />条件</button>
      <button type="button" data-action-kind="exit" :disabled="lockedStructure" @click="addAction('exit')"><Plus :size="11" />退出</button>
    </div>

    <article
      v-for="(action, index) in actions"
      :key="index"
      class="automation-action-card"
      :class="[`kind-${action.kind}`, { protected: action.text.includes('••••••') }]"
      :data-action-index="index"
      :data-action-kind="action.kind"
    >
      <header>
        <strong>{{ actionLabel(action.kind) }}</strong>
        <span>#{{ index + 1 }}</span>
        <button type="button" title="上移动作" :disabled="lockedStructure || index === 0" @click="moveAction(index, -1)"><ArrowUp :size="12" /></button>
        <button type="button" title="下移动作" :disabled="lockedStructure || index === actions.length - 1" @click="moveAction(index, 1)"><ArrowDown :size="12" /></button>
        <button class="danger-icon" type="button" title="删除动作" :disabled="lockedStructure" @click="removeAction(index)"><Trash2 :size="12" /></button>
      </header>

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
            <span>条件文本</span>
            <input class="automation-action-condition-pattern" :value="action.condition_pattern" maxlength="4000" @input="updateField(index, 'condition_pattern', ($event.target as HTMLInputElement).value)" />
          </label>
          <label class="form-field">
            <span>条件匹配</span>
            <select class="automation-action-condition-match" :value="action.condition_match_type" @change="updateField(index, 'condition_match_type', ($event.target as HTMLSelectElement).value as 'contains' | 'regex')">
              <option value="contains">包含文本</option>
              <option value="regex">正则表达式</option>
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
    </article>

    <p v-if="!actions.length" class="automation-action-empty">还没有动作。添加发送、等待、循环、条件或退出动作。</p>
  </div>
</template>
