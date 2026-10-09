<script setup lang="ts">
import { computed, ref } from 'vue'
import { Plus, Trash2 } from 'lucide-vue-next'
import ValueBindingField from './ValueBindingField.vue'
import type { WorkflowValueReference } from './types'
const props = defineProps<{ modelValue: unknown; references: WorkflowValueReference[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>] }>()
const newKey = ref('')
const values = computed<Record<string, unknown>>(() => props.modelValue && typeof props.modelValue === 'object' && !Array.isArray(props.modelValue) ? props.modelValue as Record<string, unknown> : {})
const schema = { type: ['string', 'number', 'integer', 'boolean', 'object', 'array'], binding: { mode: 'runtime' } }
function update(key: string, value: unknown): void { emit('update:modelValue', { ...values.value, [key]: value }) }
function add(): void { const key = newKey.value.trim(); if (key && !(key in values.value)) { update(key, ''); newKey.value = '' } }
function remove(key: string): void { const next = { ...values.value }; delete next[key]; emit('update:modelValue', next) }
</script>
<template>
  <div class="object-binding-fields"><div v-for="(value, key) in values" :key="key" class="object-binding-row"><ValueBindingField :model-value="value" :label="String(key)" :schema="schema" :references="references" @update:model-value="update(String(key), $event)" /><button type="button" :title="`删除 ${key}`" :aria-label="`删除 ${key}`" @click="remove(String(key))"><Trash2 :size="13" /></button></div><div class="object-binding-add"><input v-model="newKey" aria-label="字段名" placeholder="字段名" @keydown.enter.prevent="add" /><button type="button" title="添加字段" aria-label="添加字段" :disabled="!newKey.trim() || newKey.trim() in values" @click="add"><Plus :size="14" /></button></div></div>
</template>
<style scoped>
.object-binding-fields { display: grid; gap: 8px; min-width: 0; }
.object-binding-row, .object-binding-add { display: grid; grid-template-columns: minmax(0, 1fr) 28px; align-items: start; gap: 6px; }
button { display: grid; place-items: center; height: 28px; border: 1px solid var(--workflow-border); border-radius: 4px; color: var(--workflow-text); background: var(--workflow-surface-input); cursor: pointer; }
input { box-sizing: border-box; min-width: 0; width: 100%; padding: 6px 8px; color: var(--workflow-text); border: 1px solid var(--workflow-border); border-radius: 4px; background: var(--workflow-surface-input); }
</style>
