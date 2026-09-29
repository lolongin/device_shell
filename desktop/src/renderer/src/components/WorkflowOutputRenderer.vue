<script setup lang="ts">
type OutputDefinition = {
  name: string
  value?: unknown
  type?: string
  presentation?: string
  renderer?: { id?: string; props?: Record<string, unknown> }
  description?: string
}

const props = defineProps<{ definitions: OutputDefinition[]; values: Record<string, unknown> }>()

function outputValue(output: OutputDefinition): unknown {
  return Object.prototype.hasOwnProperty.call(props.values, output.name) ? props.values[output.name] : output.value
}
function outputRenderer(output: OutputDefinition): string {
  return output.renderer?.id || output.presentation || (output.type === 'object' || output.type === 'array' ? 'json' : 'text')
}
function displayValue(value: unknown): string {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2) || ''
}
function tableRows(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object' && !Array.isArray(item)))
}
function downloadUrl(value: unknown): string {
  return typeof value === 'string' && /^(file:|https?:|data:)/i.test(value) ? value : ''
}
</script>

<template>
  <section v-if="definitions.length" class="workflow-output-renderer" aria-label="Workflow 输出">
    <div class="workflow-output-renderer-heading"><strong>流程输出</strong><small>{{ definitions.length }} 个结果</small></div>
    <article v-for="output in definitions" :key="output.name" v-show="outputRenderer(output) !== 'hidden'" class="workflow-output-rendered-item">
      <header><strong>{{ output.name }}</strong><small v-if="output.description">{{ output.description }}</small></header>
      <table v-if="outputRenderer(output) === 'table' && tableRows(outputValue(output)).length"><thead><tr><th v-for="key in Object.keys(tableRows(outputValue(output))[0] || {})" :key="key">{{ key }}</th></tr></thead><tbody><tr v-for="(row, index) in tableRows(outputValue(output))" :key="index"><td v-for="key in Object.keys(row)" :key="key">{{ displayValue(row[key]) }}</td></tr></tbody></table>
      <a v-else-if="outputRenderer(output) === 'download' && downloadUrl(outputValue(output))" class="workflow-output-download" :href="downloadUrl(outputValue(output))" :download="String(output.renderer?.props?.downloadName || output.name)">下载结果</a>
      <pre v-else :class="{ 'workflow-output-json': outputRenderer(output) === 'json' }">{{ displayValue(outputValue(output)) }}</pre>
    </article>
  </section>
</template>

<style scoped>
.workflow-output-renderer { display: grid; gap: 8px; padding: 10px 12px; border: 1px solid var(--workflow-border); border-radius: 6px; background: var(--workflow-surface); }
.workflow-output-renderer-heading, .workflow-output-rendered-item header { display: flex; align-items: baseline; gap: 8px; }
.workflow-output-renderer-heading small, .workflow-output-rendered-item header small { color: var(--workflow-muted); font-size: 10px; }
.workflow-output-rendered-item { min-width: 0; display: grid; gap: 5px; }
.workflow-output-rendered-item pre { max-height: 180px; overflow: auto; margin: 0; padding: 8px; border-radius: 4px; color: var(--workflow-text); background: var(--workflow-surface-input); white-space: pre-wrap; word-break: break-word; }
.workflow-output-rendered-item table { width: 100%; border-collapse: collapse; font-size: 11px; }
.workflow-output-rendered-item th, .workflow-output-rendered-item td { padding: 5px 6px; border: 1px solid var(--workflow-border); text-align: left; }
.workflow-output-download { width: max-content; padding: 5px 8px; border: 1px solid var(--workflow-border); border-radius: 4px; color: inherit; text-decoration: none; }
</style>
