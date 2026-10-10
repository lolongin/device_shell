<script setup lang="ts">
import { computed, inject, ref, watch, onBeforeUnmount } from 'vue'
import { referenceEditorKey, type ReferenceTarget } from './reference-editor'
import { Copy, X, ChevronDown } from 'lucide-vue-next'
import ReferencePickerPopup from './ReferencePickerPopup.vue'
import type { WorkflowValueReference } from './types'
import { referenceCompatible, schemaTypes, type BindingSchema } from '../../composables/workflowReferences'

const props = withDefaults(defineProps<{
  modelValue: unknown
  label: string
  schema?: BindingSchema
  references?: WorkflowValueReference[]
  placeholder?: string
  rows?: number
  hideLabel?: boolean
}>(), { schema: () => ({ type: 'string', binding: { mode: 'runtime' } }), references: () => [], rows: 2 })
const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()
const explicitMode = ref('')
const search = ref('')
const error = ref('')
const showReferencePicker = ref(false)
const referenceButton = ref<HTMLElement | null>(null)
const referenceEditor = inject(referenceEditorKey, null)
let activeTarget: ReferenceTarget | null = null
function activateReference(): void {
  if (!referenceEditor || isStatic.value) return
  activeTarget = { label: props.label, candidates: candidates.value, select: (reference) => { if (mode.value === 'literal') explicitMode.value = 'reference'; chooseReference(reference) } }
  referenceEditor.target.value = activeTarget
}
onBeforeUnmount(() => { if (referenceEditor && referenceEditor.target.value?.select === activeTarget?.select) referenceEditor.target.value = null })
const binding = computed(() => props.schema.binding as { mode?: string } | undefined)
const isStatic = computed(() => binding.value?.mode === 'static')
const expression = computed(() => binding.value?.mode === 'expression')
const templateAllowed = computed(() => binding.value?.mode === 'template')
const exactReference = computed(() => typeof props.modelValue === 'string' ? props.modelValue.match(/^\$\{([^}]+)\}$/)?.[1] || '' : '')
const mode = computed(() => explicitMode.value || (exactReference.value ? 'reference' : templateAllowed.value && typeof props.modelValue === 'string' && props.modelValue.includes('${') ? 'template' : 'literal'))
const literalType = ref('')
const type = computed(() => literalType.value || schemaTypes(props.schema)[0] || 'string')
const text = computed(() => props.modelValue === undefined || props.modelValue === null ? '' : typeof props.modelValue === 'string' ? props.modelValue : JSON.stringify(props.modelValue))
const candidates = computed(() => props.references.filter(reference => referenceCompatible(props.schema, reference, mode.value === 'template' || expression.value)))
const filtered = computed(() => candidates.value.filter(reference => `${reference.label} ${reference.reference}`.toLowerCase().includes(search.value.toLowerCase())))
const sources = [{ id: 'input', label: '流程输入' }, { id: 'node', label: '步骤输出' }, { id: 'variable', label: '流程变量' }, { id: 'loop', label: '循环上下文' }, { id: 'context', label: '运行上下文' }]
const invalidReference = computed(() => Boolean(exactReference.value && !candidates.value.some(reference => reference.reference === exactReference.value)))
watch(() => props.modelValue, () => { error.value = '' })

function chooseMode(next: string): void {
  explicitMode.value = next
  error.value = ''
  if (next === 'literal' && exactReference.value) emit('update:modelValue', type.value === 'boolean' ? false : ['array', 'devices'].includes(type.value) ? [] : type.value === 'object' ? {} : ['number', 'integer'].includes(type.value) ? 0 : '')
}
function chooseReference(reference: string): void {
  if (!reference) return
  const token = '${' + reference + '}'
  emit('update:modelValue', mode.value === 'template' || expression.value ? text.value + token : token)
  showReferencePicker.value = false
}
function openReferencePicker(): void {
  if (referenceEditor) { activateReference(); return }
  showReferencePicker.value = true
}
function closeReferencePicker(): void {
  showReferencePicker.value = false
}
function copyReference(): void { void navigator.clipboard?.writeText(text.value) }
function updateLiteral(event: Event): void {
  const target = event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
  let value: unknown = target.value
  if (type.value === 'boolean') value = (target as HTMLInputElement).checked
  else if (['number', 'integer'].includes(type.value) && target.value !== '') value = Number(target.value)
  else if (['object', 'array', 'devices'].includes(type.value) && target.value !== '') {
    try { value = JSON.parse(target.value) } catch { error.value = 'JSON 格式不完整'; return }
  }
  error.value = ''
  emit('update:modelValue', value)
}
</script>

<template>
  <div class="value-binding-field" @focusin="activateReference">
    <div class="binding-heading"><label v-if="!hideLabel">{{ label }}</label><div v-if="!isStatic && !expression" class="binding-modes" role="group" :aria-label="`${label}绑定方式`"><button v-for="item in [{ id: 'literal', label: '固定' }, { id: 'reference', label: '引用' }, ...(templateAllowed ? [{ id: 'template', label: '模板' }] : [])]" :key="item.id" type="button" :aria-pressed="mode === item.id" @click="chooseMode(item.id)">{{ item.label }}</button></div></div>
    <template v-if="!isStatic && (mode !== 'literal' || expression)">
      <!-- 使用新的引用选择器 -->
      <div class="reference-selector-container">
        <button
          ref="referenceButton"
          type="button"
          class="reference-selector-btn"
          @click="openReferencePicker"
        >
          <ChevronDown :size="14" />
          <span>{{ expression || mode === 'template' ? '插入引用' : '选择引用' }}</span>
        </button>

        <Teleport to="body">
          <ReferencePickerPopup
            v-if="showReferencePicker"
            :references="candidates"
            :model-value="exactReference"
            :mode="mode === 'template' || expression ? 'template' : 'single'"
            :placeholder="`搜索${label}引用`"
            @select="chooseReference"
            @close="closeReferencePicker"
          />
        </Teleport>
      </div>

      <div v-if="mode === 'reference' && !expression" class="binding-reference"><input :value="text" :aria-label="`${label}引用表达式`" placeholder="${inputs.name}" @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)" /><button type="button" title="复制引用" :aria-label="`复制${label}引用`" @click="copyReference"><Copy :size="13" /></button><button type="button" title="清除引用" :aria-label="`清除${label}引用`" @click="chooseMode('literal')"><X :size="13" /></button></div>
      <textarea v-else :value="text" :rows="rows" :aria-label="label" :placeholder="placeholder" @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)" />
      <small v-if="invalidReference" class="binding-error">引用不可见或类型不匹配</small>
    </template>
    <template v-else>
      <select v-if="schemaTypes(schema).length > 1" v-model="literalType" :aria-label="`${label}值类型`"><option v-for="item in schemaTypes(schema)" :key="item" :value="item">{{ item }}</option></select>
      <select v-if="Array.isArray(schema.enum)" :value="text" :aria-label="label" @change="updateLiteral"><option value="">请选择</option><option v-for="item in schema.enum" :key="String(item)" :value="String(item)">{{ item }}</option></select>
      <input v-else-if="type === 'boolean'" type="checkbox" :checked="modelValue === true" :aria-label="label" @change="updateLiteral" />
      <textarea v-else-if="['object', 'array', 'devices'].includes(type) || rows > 2" :value="text" :rows="rows" :aria-label="label" :placeholder="placeholder" @input="updateLiteral" />
      <input v-else :type="['number', 'integer'].includes(type) ? 'number' : 'text'" :step="type === 'integer' ? '1' : 'any'" :min="schema.minimum as number | undefined" :max="schema.maximum as number | undefined" :value="text" :aria-label="label" :placeholder="placeholder" @input="updateLiteral" />
    </template>
    <small v-if="error" class="binding-error" role="alert">{{ error }}</small>
  </div>
</template>

<style scoped>
.value-binding-field { display: grid; gap: 5px; min-width: 0; color: var(--workflow-text); font-size: 11px; }
.binding-heading { display: flex; align-items: center; justify-content: space-between; gap: 6px; flex-wrap: wrap; }
.binding-modes { display: flex; gap: 1px; }
.binding-modes button { padding: 3px 6px; border: 1px solid var(--workflow-border); color: var(--workflow-muted); background: var(--workflow-surface-input); cursor: pointer; font: inherit; }
.binding-modes button[aria-pressed="true"] { color: var(--workflow-text); border-color: var(--workflow-focus); }

.reference-selector-container {
  position: relative;
}

.reference-selector-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 6px;
  background: var(--workflow-surface-input, #0a0a0a);
  color: var(--workflow-text, #e0e0e0);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.reference-selector-btn:hover {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.05);
}

.reference-selector-btn:active {
  transform: scale(0.98);
}

input, select, textarea { box-sizing: border-box; width: 100%; min-width: 0; padding: 7px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; color: inherit; background: var(--workflow-surface-input); font: inherit; }
input[type="checkbox"] { width: 15px; height: 15px; }
textarea { resize: vertical; }
.binding-reference { display: grid; grid-template-columns: minmax(0, 1fr) 27px 27px; gap: 3px; }
.binding-reference button { display: grid; place-items: center; border: 1px solid var(--workflow-border); border-radius: 4px; color: inherit; background: var(--workflow-surface-input); cursor: pointer; }
.binding-error { color: #ef4444; overflow-wrap: anywhere; }
</style>
