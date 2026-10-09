<script setup lang="ts">
import { computed } from 'vue'
import ValueBindingField from './ValueBindingField.vue'
import { inputFieldLabels } from './actionCatalog'
import type { WorkflowValueReference } from './types'

const props = defineProps<{ modelValue: unknown; schema: Record<string, unknown>; references: WorkflowValueReference[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: Record<string, unknown>] }>()
const values = computed<Record<string, unknown>>(() => props.modelValue && typeof props.modelValue === 'object' && !Array.isArray(props.modelValue) ? props.modelValue as Record<string, unknown> : {})
const fields = computed(() => Object.entries((props.schema.properties || {}) as Record<string, Record<string, unknown>>))
function update(name: string, value: unknown): void { emit('update:modelValue', { ...values.value, [name]: value }) }
</script>

<template>
  <div class="schema-binding-fields"><ValueBindingField v-for="[name, definition] in fields" :key="name" :model-value="values[name]" :label="inputFieldLabels[name] || name" :schema="definition" :references="references" @update:model-value="update(name, $event)" /></div>
</template>

<style scoped>
.schema-binding-fields { display: grid; gap: 10px; min-width: 0; }
</style>
