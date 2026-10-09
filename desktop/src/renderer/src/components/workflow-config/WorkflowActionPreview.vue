<script setup lang="ts">
import { computed } from 'vue'
import { fieldLabels, inputFieldLabels } from './actionCatalog'
import type { ActionItem } from './types'

const props = defineProps<{ action: ActionItem }>()

type PreviewField = { name: string; label: string; description: string; defaultValue?: unknown; preconfigured: boolean }

const inputFields = computed(() => {
  const schema = props.action.inputSchema
  const properties = schema.properties
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return []
  const required = new Set(Array.isArray(schema.required) ? schema.required : [])
  return Object.entries(properties as Record<string, unknown>).filter(([, raw]) => !(raw as Record<string, unknown>)?.deprecated).map(([name, raw]) => {
    const definition = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, unknown> : {}
    const presetValue = props.action.preset?.config[name]
    return {
      name,
      label: inputLabel(name),
      description: typeof definition.description === 'string' ? definition.description : '',
      defaultValue: definition.default,
      preconfigured: presetValue !== undefined && presetValue !== null && presetValue !== '',
      required: required.has(name),
    }
  })
})

const requiredFields = computed<PreviewField[]>(() => inputFields.value.filter((field) => field.required))
const optionalFields = computed<PreviewField[]>(() => inputFields.value.filter((field) => !field.required))
const outputFields = computed(() => props.action.outputFields.filter(field => !field.schema?.deprecated))
const primaryOutputs = computed(() => {
  const names = props.action.outputSchema.primary_fields
  return Array.isArray(names) ? outputFields.value.filter(field => names.includes(field.name)) : outputFields.value
})
const otherOutputs = computed(() => outputFields.value.filter(field => !primaryOutputs.value.includes(field)))

function inputLabel(name: string): string {
  const actionId = props.action.preset?.actionId || props.action.id
  if (actionId === 'file.upload') {
    if (name === 'source') return '本机文件路径'
    if (name === 'destination') return '设备目标路径'
  }
  if (actionId === 'file.download') {
    if (name === 'source') return '设备源路径'
    if (name === 'destination') return '本机保存路径'
  }
  return inputFieldLabels[name] || name
}

function defaultLabel(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value)
}
</script>

<template>
  <section class="workflow-action-preview" aria-label="节点配置预览">
    <header>
      <strong>{{ action.label }}</strong>
      <code>{{ action.id }}</code>
      <p>仅查看配置要求。拖拽此动作到画布后才能编辑和运行。</p>
    </header>

    <p v-if="(action.preset?.actionId || action.id) === 'file.upload'" class="preview-note">
      最小输入：本机文件路径；运行流程时还需选择目标设备。VRP 设备目标路径可留空。
    </p>

    <div class="preview-section">
      <h3>必填输入 <span>{{ requiredFields.length }}</span></h3>
      <p v-if="!requiredFields.length" class="preview-empty">无必填配置</p>
      <ul v-else>
        <li v-for="field in requiredFields" :key="field.name">
          <div><b>{{ field.label }}</b><code>{{ field.name }}</code><em v-if="field.preconfigured">预设已配置</em></div>
          <small v-if="field.description">{{ field.description }}</small>
        </li>
      </ul>
    </div>

    <div class="preview-section">
      <h3>可选输入 <span>{{ optionalFields.length }}</span></h3>
      <p v-if="!optionalFields.length" class="preview-empty">无可选配置</p>
      <ul v-else>
        <li v-for="field in optionalFields" :key="field.name">
          <div><b>{{ field.label }}</b><code>{{ field.name }}</code><em v-if="field.preconfigured">预设已配置</em></div>
          <small v-if="field.description">{{ field.description }}</small>
          <small v-if="field.defaultValue !== undefined">默认：{{ defaultLabel(field.defaultValue) }}</small>
        </li>
      </ul>
    </div>

    <div class="preview-section">
      <h3>可用输出 <span>{{ outputFields.length }}</span></h3>
      <p v-if="!outputFields.length" class="preview-empty">未声明输出字段</p>
      <ul v-else>
        <li v-for="field in primaryOutputs" :key="field.name">
          <div><b>{{ fieldLabels[field.name] || field.label }}</b><code>{{ field.name }}</code></div>
        </li>
      </ul>
      <details v-if="otherOutputs.length">
        <summary>其他输出（{{ otherOutputs.length }}）</summary>
        <ul><li v-for="field in otherOutputs" :key="field.name"><div><b>{{ fieldLabels[field.name] || field.label }}</b><code>{{ field.name }}</code></div></li></ul>
      </details>
    </div>
  </section>
</template>

<style scoped>
.workflow-action-preview { padding: 14px 12px 24px; color: var(--workflow-text); font-size: 11px; }
header { display: grid; gap: 5px; padding-bottom: 12px; border-bottom: 1px solid var(--workflow-border); }
header strong { font-size: 14px; }
header code, li code { color: var(--workflow-muted); font-size: 10px; }
header p { margin: 4px 0 0; color: var(--workflow-muted); line-height: 1.5; }
.preview-note { margin: 12px 0 0; padding: 9px; border: 1px solid var(--workflow-border); border-radius: 5px; color: var(--workflow-muted); line-height: 1.5; }
.preview-section { margin-top: 18px; }
h3 { display: flex; justify-content: space-between; margin: 0 0 9px; font-size: 11px; }
h3 span { color: var(--workflow-muted); font-weight: 400; }
ul { display: grid; gap: 7px; margin: 0; padding: 0; list-style: none; }
li { padding: 8px; border: 1px solid var(--workflow-border); border-radius: 5px; background: var(--workflow-surface); }
li div { display: flex; flex-wrap: wrap; align-items: baseline; gap: 6px; }
li b { font-weight: 600; }
li small { display: block; margin-top: 5px; color: var(--workflow-muted); line-height: 1.4; }
li em { color: var(--workflow-focus); font-size: 10px; font-style: normal; }
.preview-empty { margin: 0; color: var(--workflow-muted); }
details { margin-top: 10px; }
summary { cursor: pointer; color: var(--workflow-muted); margin-bottom: 8px; }
</style>
