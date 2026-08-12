<script setup lang="ts">
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-vue-next'
import type { AutoResponseStep, AutomationTargetOption } from '../types'

const props = withDefaults(defineProps<{
  steps: AutoResponseStep[]
  targets: AutomationTargetOption[]
  lockedStructure?: boolean
}>(), {
  lockedStructure: false
})

const emit = defineEmits<{
  update: [steps: AutoResponseStep[]]
}>()

function defaultStep(): AutoResponseStep {
  return {
    pattern: '',
    responses: [''],
    response_texts: [''],
    response_targets: ['source'],
    response_delays: [0],
    response_append_enters: [true]
  }
}

function cloneSteps(): AutoResponseStep[] {
  return JSON.parse(JSON.stringify(props.steps)) as AutoResponseStep[]
}

function updateStepPattern(index: number, pattern: string): void {
  const next = cloneSteps()
  next[index].pattern = pattern
  emit('update', next)
}

function updateResponse(
  stepIndex: number,
  responseIndex: number,
  field: 'text' | 'target' | 'delay' | 'append_enter',
  value: string | number | boolean
): void {
  const next = cloneSteps()
  const step = next[stepIndex]
  if (field === 'text') {
    step.response_texts[responseIndex] = String(value)
    step.responses[responseIndex] = String(value)
  } else if (field === 'target') {
    step.response_targets[responseIndex] = String(value)
  } else if (field === 'delay') {
    step.response_delays[responseIndex] = Math.max(0, Number(value) || 0)
  } else {
    step.response_append_enters[responseIndex] = Boolean(value)
  }
  emit('update', next)
}

function addStep(): void {
  emit('update', [...cloneSteps(), defaultStep()])
}

function removeStep(index: number): void {
  const next = cloneSteps()
  next.splice(index, 1)
  emit('update', next)
}

function moveStep(index: number, offset: number): void {
  const target = index + offset
  if (target < 0 || target >= props.steps.length) return
  const next = cloneSteps()
  const [step] = next.splice(index, 1)
  next.splice(target, 0, step)
  emit('update', next)
}

function addResponse(stepIndex: number): void {
  const next = cloneSteps()
  const step = next[stepIndex]
  step.responses.push('')
  step.response_texts.push('')
  step.response_targets.push('source')
  step.response_delays.push(0)
  step.response_append_enters.push(true)
  emit('update', next)
}

function removeResponse(stepIndex: number, responseIndex: number): void {
  const next = cloneSteps()
  const step = next[stepIndex]
  for (const values of [
    step.responses,
    step.response_texts,
    step.response_targets,
    step.response_delays,
    step.response_append_enters
  ]) values.splice(responseIndex, 1)
  emit('update', next)
}

function targetKnown(value: string): boolean {
  return props.targets.some((target) => target.value === value)
}
</script>

<template>
  <section class="automation-step-editor" aria-label="分步流程编辑器">
    <header>
      <div><strong>分步流程</strong><small>每一步可等待新的终端输出，再向指定会话发送一个或多个响应。</small></div>
      <button class="secondary-button" type="button" :disabled="lockedStructure" @click="addStep"><Plus :size="12" />添加步骤</button>
    </header>
    <article v-for="(step, stepIndex) in steps" :key="stepIndex" class="automation-step-card" :data-step-index="stepIndex">
      <header>
        <strong>步骤 {{ stepIndex + 1 }}</strong>
        <button type="button" title="上移步骤" :disabled="lockedStructure || stepIndex === 0" @click="moveStep(stepIndex, -1)"><ArrowUp :size="12" /></button>
        <button type="button" title="下移步骤" :disabled="lockedStructure || stepIndex === steps.length - 1" @click="moveStep(stepIndex, 1)"><ArrowDown :size="12" /></button>
        <button class="danger-icon" type="button" title="删除步骤" :disabled="lockedStructure || steps.length <= 1" @click="removeStep(stepIndex)"><Trash2 :size="12" /></button>
      </header>
      <label class="form-field form-field-wide">
        <span>等待终端输出（首步留空表示立即执行）</span>
        <input :value="step.pattern" maxlength="4000" placeholder="例如 Login: / Code:" @input="updateStepPattern(stepIndex, ($event.target as HTMLInputElement).value)" />
      </label>
      <div class="automation-step-responses">
        <div v-for="(responseText, responseIndex) in step.response_texts" :key="responseIndex" class="automation-step-response" :data-response-index="responseIndex">
          <label class="form-field form-field-wide">
            <span>响应 {{ responseIndex + 1 }}</span>
            <textarea
              class="automation-step-response-text"
              :value="responseText"
              rows="2"
              spellcheck="false"
              :readonly="responseText.includes('••••••')"
              @input="updateResponse(stepIndex, responseIndex, 'text', ($event.target as HTMLTextAreaElement).value)"
            ></textarea>
          </label>
          <label class="form-field">
            <span>发送目标</span>
            <select class="automation-step-response-target" :value="step.response_targets[responseIndex] || 'source'" @change="updateResponse(stepIndex, responseIndex, 'target', ($event.target as HTMLSelectElement).value)">
              <option v-if="!targetKnown(step.response_targets[responseIndex] || 'source')" :value="step.response_targets[responseIndex]">保留目标：{{ step.response_targets[responseIndex] }}</option>
              <option v-for="target in targets" :key="target.value" :value="target.value">{{ target.label }}</option>
            </select>
          </label>
          <label class="form-field">
            <span>发送前延迟（ms）</span>
            <input class="automation-step-response-delay" :value="step.response_delays[responseIndex] || 0" type="number" min="0" max="3600000" @input="updateResponse(stepIndex, responseIndex, 'delay', Number(($event.target as HTMLInputElement).value))" />
          </label>
          <label class="automation-inline-option"><input class="automation-step-response-append" :checked="step.response_append_enters[responseIndex]" type="checkbox" @change="updateResponse(stepIndex, responseIndex, 'append_enter', ($event.target as HTMLInputElement).checked)" />发送后追加 Enter</label>
          <button class="automation-response-remove" type="button" :disabled="lockedStructure || step.response_texts.length <= 1" title="删除响应" @click="removeResponse(stepIndex, responseIndex)"><Trash2 :size="12" /></button>
        </div>
        <button class="automation-add-response" type="button" :disabled="lockedStructure" @click="addResponse(stepIndex)"><Plus :size="12" />添加响应</button>
      </div>
    </article>
    <p v-if="!steps.length" class="automation-action-empty">还没有步骤。</p>
  </section>
</template>
