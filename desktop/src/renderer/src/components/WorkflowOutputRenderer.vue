<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'

type OutputDefinition = {
  name: string
  value?: unknown
  type?: string
  primitiveType?: string
  presentation?: string
  renderer?: { id?: string; props?: Record<string, unknown> }
  description?: string
  mime_type?: string
  mimeType?: string
  download_name?: string
  downloadName?: string
}
type TableColumn = { key: string; label: string }
type TableState = { query: string; page: number; pageSize: number; sortKey: string; sortDirection: 'asc' | 'desc'; wrap: boolean; expandedCell: string }
type TableModel = { columns: TableColumn[]; rows: Array<Record<string, unknown>> }
type RenderedOutput = OutputDefinition & {
  value: unknown
  rendererId: string
  table: TableModel
  filteredRows: Array<Record<string, unknown>>
  visibleRows: Array<Record<string, unknown>>
  totalRows: number
  pageCount: number
  state: TableState
}

const props = defineProps<{ definitions: OutputDefinition[]; values: Record<string, unknown> }>()
const tableStates = reactive<Record<string, TableState>>({})
const copyNotice = ref('')
const pageSizes = [10, 20, 50, 100]

watch(() => props.definitions.map((output) => output.name), (names) => {
  for (const name of names) {
    if (!tableStates[name]) tableStates[name] = { query: '', page: 1, pageSize: 20, sortKey: '', sortDirection: 'asc', wrap: false, expandedCell: '' }
  }
}, { immediate: true })

function stateFor(name: string): TableState {
  if (!tableStates[name]) tableStates[name] = { query: '', page: 1, pageSize: 20, sortKey: '', sortDirection: 'asc', wrap: false, expandedCell: '' }
  return tableStates[name]
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'object') {
    try { return JSON.stringify(value, null, 2) || '—' } catch { return String(value) }
  }
  return String(value)
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') {
    try { return JSON.stringify(value, null, 2) } catch { return String(value) }
  }
  return String(value)
}

function configuredColumns(value: unknown): TableColumn[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (typeof item === 'string') return { key: item, label: item }
    if (!item || typeof item !== 'object') return null
    const column = item as Record<string, unknown>
    const key = String(column.key ?? column.field ?? column.dataIndex ?? column.accessorKey ?? column.name ?? column.id ?? column.label ?? '')
    return key ? { key, label: String(column.label ?? column.title ?? key) } : null
  }).filter((item): item is TableColumn => item !== null)
}

function normalizeTable(value: unknown, preferredColumns: unknown): TableModel {
  let rawRows: unknown[] = []
  let declaredColumns = configuredColumns(preferredColumns)
  if (Array.isArray(value)) {
    rawRows = value
  } else if (value && typeof value === 'object') {
    const envelope = value as Record<string, unknown>
    declaredColumns = declaredColumns.length ? declaredColumns : configuredColumns(envelope.columns ?? envelope.fields ?? envelope.headers)
    const rowValue = ['rows', 'data', 'results', 'items', 'records'].map((key) => envelope[key]).find(Array.isArray)
    if (Array.isArray(rowValue)) rawRows = rowValue
    else rawRows = [value]
  } else if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
      try { return normalizeTable(JSON.parse(trimmed), preferredColumns) } catch { /* show the string as a one-cell row */ }
    }
    rawRows = trimmed ? [{ value }] : []
  }

  const discoveredKeys = new Set<string>()
  for (const row of rawRows) {
    if (row && typeof row === 'object' && !Array.isArray(row)) {
      Object.keys(row as Record<string, unknown>).forEach((key) => discoveredKeys.add(key))
    }
  }
  const columns = [...declaredColumns]
  const known = new Set(columns.map((column) => column.key))
  for (const key of discoveredKeys) {
    if (!known.has(key)) columns.push({ key, label: key })
  }
  if (!columns.length && rawRows.some(Array.isArray)) {
    const width = Math.max(...rawRows.filter(Array.isArray).map((row) => (row as unknown[]).length))
    for (let index = 0; index < width; index += 1) columns.push({ key: String(index), label: `列 ${index + 1}` })
  }
  if (!columns.length && rawRows.some((row) => row === null || typeof row !== 'object')) columns.push({ key: 'value', label: '结果' })

  const rows = rawRows.map((row) => {
    if (Array.isArray(row)) return Object.fromEntries(columns.map((column, index) => [column.key, row[index]]))
    if (row && typeof row === 'object') return row as Record<string, unknown>
    return { value: row }
  })
  return { columns, rows }
}

function inferredRenderer(output: OutputDefinition, value: unknown): string {
  const requested = String(output.renderer?.id || output.presentation || '').toLowerCase()
  if (requested && requested !== 'text') return requested
  if (Array.isArray(value) && value.some((item) => item && typeof item === 'object')) return 'table'
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>
    if (Array.isArray(record.rows) || Array.isArray(record.data) || Array.isArray(record.results) || Array.isArray(record.items) || Array.isArray(record.records)) return 'table'
    if (requested === 'text') return 'json'
  }
  return requested || ((output.type === 'object' || output.type === 'array') ? 'json' : 'text')
}

function rendererLabel(rendererId: string): string {
  const labels: Record<string, string> = {
    text: '文本',
    json: 'JSON',
    table: '表格',
    download: '下载',
    device: '设备信息',
    hidden: '隐藏',
  }
  return labels[rendererId] || rendererId
}

const renderedOutputs = computed<RenderedOutput[]>(() => props.definitions.map((output) => {
  const value = Object.prototype.hasOwnProperty.call(props.values, output.name) ? props.values[output.name] : output.value
  const rendererId = inferredRenderer(output, value)
  const table = normalizeTable(value, output.renderer?.props?.columns)
  const state = stateFor(output.name)
  let filteredRows = table.rows
  if (state.query.trim()) {
    const query = state.query.trim().toLocaleLowerCase()
    filteredRows = filteredRows.filter((row) => table.columns.some((column) => cellText(row[column.key]).toLocaleLowerCase().includes(query)))
  }
  if (state.sortKey) {
    const direction = state.sortDirection === 'asc' ? 1 : -1
    filteredRows = [...filteredRows].sort((left, right) => {
      const a = left[state.sortKey]
      const b = right[state.sortKey]
      if (a === b) return 0
      if (a === null || a === undefined) return 1 * direction
      if (b === null || b === undefined) return -1 * direction
      if (typeof a === 'number' && typeof b === 'number') return (a - b) * direction
      if (typeof a === 'boolean' && typeof b === 'boolean') return (Number(a) - Number(b)) * direction
      return cellText(a).localeCompare(cellText(b), undefined, { numeric: true, sensitivity: 'base' }) * direction
    })
  }
  const totalRows = filteredRows.length
  const pageCount = Math.max(1, Math.ceil(totalRows / state.pageSize))
  state.page = Math.min(state.page, pageCount)
  const visibleRows = filteredRows.slice((state.page - 1) * state.pageSize, state.page * state.pageSize)
  return { ...output, value, rendererId, table, filteredRows, visibleRows, totalRows, pageCount, state }
}))

function setQuery(output: RenderedOutput, value: string): void {
  output.state.query = value
  output.state.page = 1
}
function setPageSize(output: RenderedOutput, value: string): void {
  output.state.pageSize = Number(value) || 20
  output.state.page = 1
}
function sortBy(output: RenderedOutput, key: string): void {
  if (output.state.sortKey === key) output.state.sortDirection = output.state.sortDirection === 'asc' ? 'desc' : 'asc'
  else { output.state.sortKey = key; output.state.sortDirection = 'asc' }
}
function rowNumber(output: RenderedOutput): string {
  if (!output.totalRows) return '0 行'
  const start = (output.state.page - 1) * output.state.pageSize + 1
  return `${start}–${Math.min(start + output.visibleRows.length - 1, output.totalRows)} / ${output.totalRows} 行`
}
function cellClass(value: unknown): string {
  if (value === null || value === undefined) return 'is-null'
  if (typeof value === 'number') return 'is-number'
  if (typeof value === 'boolean') return 'is-boolean'
  if (typeof value === 'object') return 'is-object'
  return ''
}
function isObjectCell(value: unknown): boolean {
  return value !== null && typeof value === 'object'
}
function cellId(output: RenderedOutput, rowIndex: number, columnKey: string): string {
  return `${output.state.page}:${rowIndex}:${columnKey}`
}
function toggleCell(output: RenderedOutput, rowIndex: number, columnKey: string): void {
  const id = cellId(output, rowIndex, columnKey)
  output.state.expandedCell = output.state.expandedCell === id ? '' : id
}
function csvCell(value: unknown): string {
  const text = cellText(value)
  return `"${text.replaceAll('"', '""')}"`
}
function tableCsv(output: RenderedOutput): string {
  const header = output.table.columns.map((column) => csvCell(column.label)).join(',')
  const rows = output.filteredRows.map((row) => output.table.columns.map((column) => csvCell(row[column.key])).join(','))
  return [header, ...rows].join('\r\n')
}
function safeFilename(value: string): string {
  return value.replace(/[\\/:*?"<>|]/g, '_').trim() || 'workflow-output'
}
function downloadBlob(filename: string, content: string, mimeType: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: mimeType }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
function downloadCsv(output: RenderedOutput): void {
  downloadBlob(`${safeFilename(output.name)}.csv`, `\uFEFF${tableCsv(output)}`, 'text/csv;charset=utf-8')
}
async function copyText(value: string, successMessage: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value)
    copyNotice.value = successMessage
  } catch {
    copyNotice.value = '复制失败，请检查系统剪贴板权限'
  }
  window.setTimeout(() => { copyNotice.value = '' }, 2200)
}
function copyOutput(output: RenderedOutput): void {
  void copyText(JSON.stringify(output.value, null, 2) ?? '', `已复制 ${output.name}`)
}
function copyCsv(output: RenderedOutput): void {
  void copyText(tableCsv(output), `已复制 ${output.totalRows} 行表格数据`)
}
function downloadUrl(value: unknown): string {
  return typeof value === 'string' && /^(file:|https?:|data:)/i.test(value) ? value : ''
}
function downloadName(output: RenderedOutput): string {
  return String(output.renderer?.props?.downloadName || output.downloadName || output.download_name || output.name)
}
</script>

<template>
  <section v-if="renderedOutputs.length" class="workflow-output-renderer" aria-label="Workflow 输出">
    <div class="workflow-output-renderer-heading">
      <div><span class="workflow-output-kicker">RESULTS</span><strong>流程输出</strong></div>
      <small>{{ renderedOutputs.length }} 个结果</small>
    </div>
    <p class="workflow-output-hint">当前呈现方式会标在每项结果旁；可在工作流设置的「流程输出」中选择文本、JSON、表格、下载、设备信息或隐藏。</p>
    <article v-for="output in renderedOutputs" :key="output.name" v-show="output.rendererId !== 'hidden'" class="workflow-output-rendered-item">
      <header class="workflow-output-item-heading">
        <div class="workflow-output-title"><strong>{{ output.name }}</strong><small v-if="output.description">{{ output.description }}</small></div>
        <div class="workflow-output-actions">
          <span class="workflow-output-kind" :aria-label="`呈现方式：${rendererLabel(output.rendererId)}`">{{ rendererLabel(output.rendererId) }}</span>
          <button type="button" title="复制原始结果" :aria-label="`复制 ${output.name} 原始结果`" @click="copyOutput(output)">复制 JSON</button>
        </div>
      </header>

      <div v-if="output.rendererId === 'table'" class="workflow-table-shell">
        <div class="workflow-table-toolbar">
          <label class="workflow-table-search"><span aria-hidden="true">⌕</span><input :value="output.state.query" type="search" :aria-label="`筛选 ${output.name} 表格`" placeholder="筛选表格…" @input="setQuery(output, ($event.target as HTMLInputElement).value)" /></label>
          <div class="workflow-table-toolbar-actions">
            <span class="workflow-table-count">{{ rowNumber(output) }}</span>
            <button type="button" :class="{ 'is-active': output.state.wrap }" :aria-pressed="output.state.wrap" :title="output.state.wrap ? '关闭单元格换行' : '开启单元格换行'" @click="output.state.wrap = !output.state.wrap">换行</button>
            <button type="button" title="复制当前筛选结果为 CSV" @click="copyCsv(output)">复制 CSV</button>
            <button type="button" title="下载当前筛选结果为 CSV" @click="downloadCsv(output)">导出 CSV</button>
          </div>
        </div>
        <div class="workflow-table-scroll" :class="{ 'is-wrapped': output.state.wrap }">
          <table v-if="output.table.columns.length" class="workflow-result-table">
            <thead><tr><th v-for="column in output.table.columns" :key="column.key" scope="col"><button type="button" :aria-label="`按 ${column.label} 排序`" @click="sortBy(output, column.key)"><span>{{ column.label }}</span><span v-if="output.state.sortKey === column.key" class="workflow-sort-indicator">{{ output.state.sortDirection === 'asc' ? '↑' : '↓' }}</span><span v-else class="workflow-sort-indicator is-idle">↕</span></button></th></tr></thead>
            <tbody v-if="output.visibleRows.length"><tr v-for="(row, rowIndex) in output.visibleRows" :key="`${output.state.page}-${rowIndex}`"><td v-for="column in output.table.columns" :key="column.key"><template v-if="isObjectCell(row[column.key])"><button type="button" class="workflow-cell-value workflow-cell-expandable" :class="cellClass(row[column.key])" :title="cellText(row[column.key])" :aria-expanded="output.state.expandedCell === cellId(output, rowIndex, column.key)" @click="toggleCell(output, rowIndex, column.key)"><span>{{ cellText(row[column.key]) || '—' }}</span><small>{{ output.state.expandedCell === cellId(output, rowIndex, column.key) ? '收起' : '查看' }}</small></button><pre v-if="output.state.expandedCell === cellId(output, rowIndex, column.key)" class="workflow-cell-detail">{{ displayValue(row[column.key]) }}</pre></template><span v-else class="workflow-cell-value" :class="cellClass(row[column.key])" :title="cellText(row[column.key])">{{ cellText(row[column.key]) || '—' }}</span></td></tr></tbody>
          </table>
          <div v-if="!output.totalRows" class="workflow-table-empty"><strong>{{ output.state.query ? '没有匹配的行' : '表格为空' }}</strong><span>{{ output.state.query ? '调整筛选内容后重试。' : '此输出没有可展示的记录。' }}</span></div>
          <div v-else-if="!output.table.columns.length" class="workflow-table-empty"><strong>没有可展示的列</strong><span>检查表格输出中的列定义。</span></div>
        </div>
        <footer class="workflow-table-footer">
          <label>每页<select :value="output.state.pageSize" @change="setPageSize(output, ($event.target as HTMLSelectElement).value)"><option v-for="size in pageSizes" :key="size" :value="size">{{ size }}</option></select>行</label>
          <div class="workflow-table-pagination"><span>第 {{ output.state.page }} / {{ output.pageCount }} 页</span><button type="button" aria-label="上一页" :disabled="output.state.page <= 1" @click="output.state.page -= 1">‹</button><button type="button" aria-label="下一页" :disabled="output.state.page >= output.pageCount" @click="output.state.page += 1">›</button></div>
        </footer>
      </div>

      <a v-else-if="output.rendererId === 'download' && downloadUrl(output.value)" class="workflow-output-download" :href="downloadUrl(output.value)" :download="downloadName(output)"><span aria-hidden="true">↓</span><span><strong>下载结果</strong><small>{{ downloadName(output) }}<template v-if="output.mimeType || output.mime_type"> · {{ output.mimeType || output.mime_type }}</template></small></span></a>
      <dl v-else-if="output.rendererId === 'device' && output.value && typeof output.value === 'object' && !Array.isArray(output.value)" class="workflow-output-device"><template v-for="(value, key) in output.value as Record<string, unknown>" :key="key"><dt>{{ key }}</dt><dd>{{ displayValue(value) }}</dd></template></dl>
      <pre v-else class="workflow-output-value" :class="{ 'is-json': output.rendererId === 'json' }">{{ displayValue(output.value) }}</pre>
    </article>
    <p v-if="copyNotice" class="workflow-output-copy-notice" role="status" aria-live="polite">{{ copyNotice }}</p>
  </section>
</template>

<style scoped>
.workflow-output-renderer { container: workflow-output / inline-size; display: grid; gap: 10px; min-width: 0; padding: 12px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 9px; background: var(--workflow-surface, var(--surface)); }
.workflow-output-renderer-heading, .workflow-output-item-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.workflow-output-renderer-heading > div { display: flex; align-items: baseline; gap: 8px; }
.workflow-output-renderer-heading strong { color: var(--workflow-text, var(--text)); font-size: 12px; }
.workflow-output-kicker { color: #38bdf8; font-size: 9px; font-weight: 750; letter-spacing: .11em; }
.workflow-output-renderer-heading > small, .workflow-output-title > small { color: var(--workflow-muted, var(--muted)); font-size: 10px; }
.workflow-output-hint { margin: -4px 0 0; color: var(--workflow-muted, var(--muted)); font-size: 10px; line-height: 1.45; }
.workflow-output-rendered-item { display: grid; gap: 8px; min-width: 0; padding: 0; border: 0; background: transparent; }
.workflow-output-title { display: grid; gap: 2px; min-width: 0; }
.workflow-output-title > strong { overflow: hidden; color: var(--workflow-text, var(--text)); font-size: 11px; text-overflow: ellipsis; }
.workflow-output-title > small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-output-actions, .workflow-table-toolbar-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.workflow-output-kind { padding: 2px 6px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 999px; color: var(--workflow-muted, var(--muted)); font: 9px/1.4 ui-monospace, Consolas, monospace; }
.workflow-output-actions button, .workflow-table-toolbar button { flex: 0 0 auto; padding: 5px 8px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 5px; color: var(--workflow-text, var(--text)); background: var(--workflow-surface, var(--surface)); cursor: pointer; font-size: 11px; white-space: nowrap; }
.workflow-output-actions button:hover, .workflow-table-toolbar button:hover { border-color: #38bdf8; color: #7dd3fc; }
.workflow-table-toolbar button.is-active { border-color: color-mix(in srgb, #38bdf8 70%, var(--workflow-border, var(--line))); color: #7dd3fc; background: color-mix(in srgb, #38bdf8 11%, var(--workflow-surface, var(--surface))); }
.workflow-table-shell { overflow: hidden; border: 1px solid var(--workflow-border, var(--line)); border-radius: 7px; background: var(--workflow-surface-input, var(--surface)); }
.workflow-table-toolbar, .workflow-table-footer { min-height: 40px; display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 9px; color: var(--workflow-muted, var(--muted)); background: color-mix(in srgb, var(--workflow-surface, var(--surface)) 78%, transparent); }
.workflow-table-toolbar { border-bottom: 1px solid var(--workflow-border, var(--line)); }
.workflow-table-search { width: auto; min-width: 150px; max-width: 280px; flex: 1 1 180px; display: flex; align-items: center; gap: 6px; padding: 0 7px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 5px; color: var(--workflow-muted, var(--muted)); background: var(--workflow-surface-input, var(--surface)); }
.workflow-table-search > span { font-size: 17px; line-height: 1; }
.workflow-table-search input { width: 100%; min-width: 0; height: 25px; border: 0; outline: none; color: var(--workflow-text, var(--text)); background: transparent; font-size: 10px; }
.workflow-table-count { margin-right: 4px; font: 11px ui-monospace, Consolas, monospace; white-space: nowrap; }
.workflow-table-scroll { max-height: 360px; overflow: auto; scrollbar-color: var(--line-strong) transparent; }
.workflow-result-table { width: max-content; min-width: 100%; table-layout: fixed; border-collapse: separate; border-spacing: 0; color: var(--workflow-text, var(--text)); font-size: 11px; }
.workflow-result-table th { position: sticky; top: 0; z-index: 1; width: 110px; min-width: 110px; padding: 0; border-bottom: 1px solid var(--workflow-border, var(--line)); color: var(--workflow-muted, var(--muted)); background: var(--workflow-surface, var(--surface)); text-align: left; white-space: nowrap; }
.workflow-result-table th:first-child { width: 124px; min-width: 124px; }
.workflow-result-table th + th, .workflow-result-table td + td { border-left: 1px solid color-mix(in srgb, var(--workflow-border, var(--line)) 62%, transparent); }
.workflow-result-table th button { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 9px 10px; border: 0; color: inherit; background: transparent; cursor: pointer; font-size: 11px; font-weight: 650; text-align: left; }
.workflow-result-table th button:hover { color: #7dd3fc; background: color-mix(in srgb, #38bdf8 7%, transparent); }
.workflow-sort-indicator { color: #38bdf8; font-size: 12px; }
.workflow-sort-indicator.is-idle { opacity: .35; }
.workflow-result-table td { width: 110px; min-width: 110px; max-width: 110px; padding: 8px 10px; border-bottom: 1px solid color-mix(in srgb, var(--workflow-border, var(--line)) 50%, transparent); vertical-align: top; }
.workflow-result-table td:first-child { width: 124px; min-width: 124px; max-width: 124px; }
.workflow-result-table tbody tr:nth-child(even) { background: color-mix(in srgb, var(--workflow-surface, var(--surface)) 68%, transparent); }
.workflow-result-table tbody tr:hover { background: color-mix(in srgb, #38bdf8 8%, var(--workflow-surface, var(--surface))); }
.workflow-cell-value { display: block; overflow: hidden; color: var(--workflow-text, var(--text)); text-overflow: ellipsis; white-space: nowrap; }
.workflow-table-scroll.is-wrapped .workflow-cell-value { white-space: pre-wrap; overflow-wrap: anywhere; }
.workflow-cell-value.is-null { color: var(--workflow-subtle, var(--soft)); }
.workflow-cell-value.is-number { color: #a5b4fc; font-variant-numeric: tabular-nums; }
.workflow-cell-value.is-boolean { color: #86efac; }
.workflow-cell-value.is-object { color: #fcd34d; font-family: ui-monospace, Consolas, monospace; font-size: 9px; }
.workflow-cell-expandable { width: 100%; display: flex; align-items: flex-start; justify-content: space-between; gap: 6px; padding: 0; border: 0; background: transparent; cursor: pointer; text-align: left; }
.workflow-cell-expandable > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: inherit; }
.workflow-cell-expandable > small { flex: 0 0 auto; color: #7dd3fc; font-family: inherit; font-size: 9px; line-height: 1.4; }
.workflow-cell-detail { max-height: 180px; overflow: auto; margin: 7px 0 0; padding: 7px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 5px; color: #fcd34d; background: var(--workflow-surface, var(--surface)); font: 9px/1.45 ui-monospace, Consolas, monospace; white-space: pre; }
.workflow-table-empty { min-height: 112px; display: grid; align-content: center; justify-items: center; gap: 4px; color: var(--workflow-muted, var(--muted)); text-align: center; }
.workflow-table-empty strong { color: var(--workflow-text, var(--text)); font-size: 11px; }
.workflow-table-empty span { font-size: 10px; }
.workflow-table-footer { border-top: 1px solid var(--workflow-border, var(--line)); font-size: 10px; }
.workflow-table-footer label { display: flex; align-items: center; gap: 5px; }
.workflow-table-footer select { padding: 3px 5px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 4px; color: var(--workflow-text, var(--text)); background: var(--workflow-surface-input, var(--surface)); font-size: 10px; }
.workflow-table-pagination { display: flex; align-items: center; gap: 6px; }
.workflow-table-pagination button { width: 23px; height: 23px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 5px; color: var(--workflow-text, var(--text)); background: var(--workflow-surface-input, var(--surface)); cursor: pointer; font-size: 16px; line-height: 1; }
.workflow-table-pagination button:disabled { opacity: .38; cursor: default; }
.workflow-output-value { max-height: 240px; overflow: auto; margin: 0; padding: 9px; border-radius: 5px; color: var(--workflow-text, var(--text)); background: var(--workflow-surface-input, var(--surface)); font: 11px/1.5 ui-monospace, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.workflow-output-value.is-json { color: #c4b5fd; }
.workflow-output-download { display: flex; align-items: center; gap: 10px; width: max-content; max-width: 100%; padding: 9px 12px; border: 1px solid color-mix(in srgb, #38bdf8 45%, var(--workflow-border, var(--line))); border-radius: 6px; color: #7dd3fc; background: color-mix(in srgb, #38bdf8 8%, transparent); text-decoration: none; }
.workflow-output-download > span:first-child { font-size: 18px; }
.workflow-output-download > span:last-child { display: grid; gap: 2px; min-width: 0; }
.workflow-output-download small { overflow: hidden; color: var(--workflow-muted, var(--muted)); font-size: 9px; text-overflow: ellipsis; }
.workflow-output-device { display: grid; grid-template-columns: minmax(90px, .35fr) minmax(0, 1fr); gap: 0; margin: 0; border: 1px solid var(--workflow-border, var(--line)); border-radius: 5px; overflow: hidden; }
.workflow-output-device dt, .workflow-output-device dd { margin: 0; padding: 6px 8px; border-bottom: 1px solid var(--workflow-border, var(--line)); font-size: 10px; overflow-wrap: anywhere; }
.workflow-output-device dt { color: var(--workflow-muted, var(--muted)); background: color-mix(in srgb, var(--workflow-surface, var(--surface)) 75%, transparent); }
.workflow-output-device dd { color: var(--workflow-text, var(--text)); }
.workflow-output-copy-notice { margin: 0; color: #86efac; font-size: 10px; }
@container workflow-output (max-width: 560px) {
  .workflow-table-toolbar { align-items: stretch; flex-direction: column; gap: 7px; }
  .workflow-table-search { width: 100%; max-width: none; flex: 1 1 auto; }
  .workflow-table-toolbar-actions { justify-content: flex-end; flex-wrap: nowrap; }
  .workflow-table-count { margin-right: auto; }
  .workflow-output-kind { padding: 2px 5px; font-size: 9px; }
}
</style>
