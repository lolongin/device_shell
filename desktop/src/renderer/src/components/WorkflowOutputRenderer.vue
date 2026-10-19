<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  buildTable,
  cellText,
  downloadUrl,
  flattenJson,
  inferKind,
  outputValue,
  statusLabel,
  statusTone,
  stepDetails,
  stringify,
  textValue,
  unresolvedExpression,
  visibleJsonRows,
  type JsonRow,
  type OutputDefinition,
  type OutputKind,
  type TableColumn,
  type TableRow
} from './workflow/output-model'

type TableState = {
  query: string
  limit: number
  sortKey: string
  sortDirection: 'asc' | 'desc'
  wrap: boolean
  expandedRow: string
  hidden: Record<string, boolean>
}

type JsonState = { query: string; expanded: Set<string> }

type RenderedOutput = OutputDefinition & {
  kind: OutputKind
  displayValue: unknown
  missing: boolean
  expression: string
  table: { columns: TableColumn[]; rows: TableRow[] } | null
  items: unknown[]
  jsonRows: JsonRow[]
  tableState: TableState
  jsonState: JsonState
}

const props = defineProps<{ definitions: OutputDefinition[]; values: Record<string, unknown> }>()

const tableStates = reactive<Record<string, TableState>>({})
const jsonStates = reactive<Record<string, JsonState>>({})
const copyNotice = ref('')
const columnsOpen = ref('')
let noticeTimer: ReturnType<typeof setTimeout> | null = null

const PAGE_STEP = 50

function tableStateFor(name: string): TableState {
  if (!tableStates[name]) {
    tableStates[name] = { query: '', limit: 20, sortKey: '', sortDirection: 'asc', wrap: false, expandedRow: '', hidden: {} }
  }
  return tableStates[name]
}

function jsonStateFor(name: string): JsonState {
  if (!jsonStates[name]) jsonStates[name] = { query: '', expanded: new Set(['0']) }
  return jsonStates[name]
}

watch(() => props.definitions.map((output) => output.name), (names) => {
  names.forEach((name) => { tableStateFor(name); jsonStateFor(name) })
}, { immediate: true })

const renderedOutputs = computed<RenderedOutput[]>(() => props.definitions.map((definition) => {
  const displayValue = outputValue(definition, props.values)
  const kind = inferKind(definition, displayValue)
  const expression = unresolvedExpression(definition)
  const missing = kind !== 'hidden' && (displayValue === undefined || (displayValue === '' && Boolean(expression)))
  return {
    ...definition,
    kind,
    displayValue,
    missing,
    expression,
    table: kind === 'table' ? buildTable(displayValue, definition.renderer?.props?.columns) : null,
    items: kind === 'list' && Array.isArray(displayValue) ? displayValue : [],
    jsonRows: kind === 'json' ? flattenJson(displayValue, definition.name) : [],
    tableState: tableStateFor(definition.name),
    jsonState: jsonStateFor(definition.name)
  }
}))

const visibleOutputs = computed(() => renderedOutputs.value.filter((output) => output.kind !== 'hidden'))

const kindLabels: Record<OutputKind, string> = {
  text: '文本',
  list: '列表',
  table: '表格',
  json: 'JSON',
  download: '下载',
  device: '设备信息',
  hidden: '隐藏'
}

function kindLabel(kind: OutputKind): string {
  return kindLabels[kind] || kind
}

/* ---------- table ---------- */

function sortedRows(output: RenderedOutput): TableRow[] {
  const rows = output.table?.rows ?? []
  const state = output.tableState
  const query = state.query.trim().toLocaleLowerCase()
  let result = rows
  if (query) {
    const columns = output.table?.columns ?? []
    result = result.filter((row) => columns.some((column) =>
      cellText(row.cells[column.key]).toLocaleLowerCase().includes(query)))
  }
  if (state.sortKey) {
    const direction = state.sortDirection === 'asc' ? 1 : -1
    result = [...result].sort((left, right) => {
      const a = left.cells[state.sortKey]
      const b = right.cells[state.sortKey]
      if (a === b) return 0
      if (a === null || a === undefined) return 1 * direction
      if (b === null || b === undefined) return -1 * direction
      if (typeof a === 'number' && typeof b === 'number') return (a - b) * direction
      return cellText(a).localeCompare(cellText(b), undefined, { numeric: true, sensitivity: 'base' }) * direction
    })
  }
  return result
}

function visibleRows(output: RenderedOutput): TableRow[] {
  return sortedRows(output).slice(0, output.tableState.limit)
}

function rowSummary(output: RenderedOutput): string {
  const total = sortedRows(output).length
  if (!total) return '0 行'
  const shown = Math.min(total, output.tableState.limit)
  return `${shown} / ${total} 行`
}

function columnVisible(output: RenderedOutput, column: TableColumn): boolean {
  const explicit = output.tableState.hidden[column.key]
  if (explicit !== undefined) return !explicit
  return !column.noise
}

function visibleColumns(output: RenderedOutput): TableColumn[] {
  return (output.table?.columns ?? []).filter((column) => columnVisible(output, column))
}

function toggleColumn(output: RenderedOutput, key: string): void {
  const column = (output.table?.columns ?? []).find((item) => item.key === key)
  if (!column) return
  output.tableState.hidden[key] = columnVisible(output, column)
}

function toggleColumns(output: RenderedOutput): void {
  columnsOpen.value = columnsOpen.value === output.name ? '' : output.name
}

function sortBy(output: RenderedOutput, key: string): void {
  const state = output.tableState
  if (state.sortKey === key) state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc'
  else { state.sortKey = key; state.sortDirection = 'asc' }
}

function sortIndicator(output: RenderedOutput, key: string): string {
  const state = output.tableState
  if (state.sortKey !== key) return '↕'
  return state.sortDirection === 'asc' ? '↑' : '↓'
}

function setQuery(output: RenderedOutput, value: string): void {
  output.tableState.query = value
  output.tableState.limit = 20
}

function showMore(output: RenderedOutput): void {
  output.tableState.limit += PAGE_STEP
}

function toggleRow(output: RenderedOutput, rowId: string): void {
  output.tableState.expandedRow = output.tableState.expandedRow === rowId ? '' : rowId
}

function cellTone(value: unknown): string {
  if (value === null || value === undefined) return 'is-null'
  if (typeof value === 'number') return 'is-number'
  if (typeof value === 'boolean') return 'is-boolean'
  if (typeof value === 'object') return 'is-object'
  return ''
}

function cellPills(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.slice(0, 4).map((item) => cellText(item))
}

function cellExtra(value: unknown): number {
  return Array.isArray(value) ? Math.max(0, value.length - 4) : 0
}

function isStatusColumn(column: TableColumn): boolean {
  return column.key === '__status'
}

function isDeviceColumn(column: TableColumn): boolean {
  return column.key === '__device'
}

/* ---------- json ---------- */

function jsonRows(output: RenderedOutput): JsonRow[] {
  return visibleJsonRows(output.jsonRows, output.jsonState.expanded, output.jsonState.query)
}

function toggleJson(output: RenderedOutput, id: string): void {
  const expanded = output.jsonState.expanded
  if (expanded.has(id)) expanded.delete(id)
  else expanded.add(id)
}

function setJsonQuery(output: RenderedOutput, value: string): void {
  output.jsonState.query = value
}

function allJsonExpanded(output: RenderedOutput): boolean {
  return output.jsonRows.every((row) => row.kind === 'value' || output.jsonState.expanded.has(row.id))
}

function toggleAllJson(output: RenderedOutput): void {
  if (allJsonExpanded(output)) {
    output.jsonState.expanded = new Set(['0'])
    return
  }
  const expanded = new Set<string>(['0'])
  output.jsonRows.forEach((row) => { if (row.kind !== 'value') expanded.add(row.id) })
  output.jsonState.expanded = expanded
}

function jsonValueType(value: unknown): string {
  if (value === null) return 'null'
  if (typeof value === 'string') return 'string'
  if (typeof value === 'number') return 'number'
  if (typeof value === 'boolean') return 'boolean'
  return 'object'
}

function jsonValueText(value: unknown): string {
  if (typeof value === 'string') return `"${value}"`
  return stringify(value)
}

function jsonSummaryText(row: JsonRow): string {
  return row.kind === 'array' ? `[${row.count}]` : `{${row.count}}`
}

/* ---------- export ---------- */

function safeFilename(value: string): string {
  return value.replace(/[\\/:*?"<>|]/g, '_').trim() || 'workflow-output'
}

function csvCell(value: unknown): string {
  return `"${cellText(value).replaceAll('"', '""')}"`
}

function tableCsv(output: RenderedOutput): string {
  const columns = visibleColumns(output)
  const header = columns.map((column) => csvCell(column.label)).join(',')
  const rows = sortedRows(output).map((row) => columns.map((column) => csvCell(row.cells[column.key])).join(','))
  return [header, ...rows].join('\r\n')
}

function downloadCsv(output: RenderedOutput): void {
  const url = URL.createObjectURL(new Blob([`\uFEFF${tableCsv(output)}`], { type: 'text/csv;charset=utf-8' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${safeFilename(output.name)}.csv`
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  announce(`已导出 ${safeFilename(output.name)}.csv`)
}

function announce(message: string): void {
  copyNotice.value = message
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { copyNotice.value = '' }, 2200)
}

async function copyText(value: string, message: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value)
    announce(message)
  } catch {
    announce('复制失败，请检查系统剪贴板权限')
  }
}

function copyOutput(output: RenderedOutput): void {
  void copyText(JSON.stringify(output.displayValue, null, 2) ?? '', `已复制 ${output.name}`)
}

function copyCsv(output: RenderedOutput): void {
  void copyText(tableCsv(output), `已复制 ${sortedRows(output).length} 行表格数据`)
}

function downloadName(output: RenderedOutput): string {
  return String(output.renderer?.props?.downloadName || output.downloadName || output.download_name || output.name)
}

function downloadHref(output: RenderedOutput): string {
  return downloadUrl(output.displayValue)
}

function deviceEntries(output: RenderedOutput): Array<{ key: string; value: unknown }> {
  const value = output.displayValue
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>).map(([key, entry]) => ({ key, value: entry }))
}

function pretty(value: unknown): string {
  try { return JSON.stringify(value, null, 2) ?? '' } catch { return String(value) }
}

function resolvedFallback(output: RenderedOutput): string {
  return output.expression ? `引用 ${output.expression}` : '该输出没有返回值'
}

onBeforeUnmount(() => {
  if (noticeTimer) clearTimeout(noticeTimer)
  window.removeEventListener('click', closeColumnMenu)
})

function closeColumnMenu(event: MouseEvent): void {
  if (!columnsOpen.value) return
  const target = event.target as HTMLElement | null
  if (target?.closest('.wf-out-columns')) return
  columnsOpen.value = ''
}

onMounted(() => {
  window.addEventListener('click', closeColumnMenu)
})
</script>

<template>
  <section v-if="visibleOutputs.length" class="wf-out" aria-label="Workflow 输出">
    <header class="wf-out-heading">
      <div class="wf-out-heading-title">
        <span class="wf-out-kicker">RESULTS</span>
        <strong>流程输出</strong>
        <small>{{ visibleOutputs.length }} 个结果</small>
      </div>
    </header>

    <div class="wf-out-grid">
      <article
        v-for="output in visibleOutputs"
        :key="output.name"
        class="wf-out-card"
        :class="{ 'is-wide': output.kind === 'table' || output.kind === 'json' || output.kind === 'device' || output.kind === 'download' }"
      >
        <header class="wf-out-card-head">
          <div class="wf-out-card-title">
            <strong>{{ output.name }}</strong>
            <small v-if="output.description">{{ output.description }}</small>
          </div>
          <div class="wf-out-card-tools">
            <span class="wf-out-kind" :data-kind="output.kind">{{ kindLabel(output.kind) }}</span>
            <button class="wf-out-btn" type="button" :aria-label="`复制 ${output.name}`" @click="copyOutput(output)">复制</button>
          </div>
        </header>

        <div v-if="output.kind === 'text'" class="wf-out-scalar" :data-missing="output.missing">
          <template v-if="output.missing">
            <b>未产生值</b>
            <small>{{ resolvedFallback(output) }}</small>
          </template>
          <template v-else>
            <b :class="{ 'is-path': String(output.displayValue).startsWith('flash:') }">{{ textValue(output.displayValue) }}</b>
          </template>
        </div>

        <ul v-else-if="output.kind === 'list'" class="wf-out-pills">
          <li v-for="(item, index) in output.items" :key="index">{{ cellText(item) }}</li>
        </ul>

        <a
          v-else-if="output.kind === 'download' && downloadHref(output)"
          class="wf-out-download"
          :href="downloadHref(output)"
          :download="downloadName(output)"
        >
          <span aria-hidden="true">↓</span>
          <span class="wf-out-download-copy">
            <strong>下载结果</strong>
            <small>{{ downloadName(output) }}<template v-if="output.mimeType || output.mime_type"> · {{ output.mimeType || output.mime_type }}</template></small>
          </span>
        </a>

        <dl v-else-if="output.kind === 'device'" class="wf-out-device-list">
          <template v-for="entry in deviceEntries(output)" :key="entry.key">
            <dt>{{ entry.key }}</dt>
            <dd>{{ textValue(entry.value) }}</dd>
          </template>
        </dl>

        <div v-else-if="output.kind === 'table'" class="wf-out-table">
          <div class="wf-out-toolbar">
            <label class="wf-out-search">
              <span aria-hidden="true">⌕</span>
              <input
                :value="output.tableState.query"
                type="search"
                :aria-label="`筛选 ${output.name}`"
                placeholder="筛选结果…"
                @input="setQuery(output, ($event.target as HTMLInputElement).value)"
              />
            </label>
            <span class="wf-out-count">{{ rowSummary(output) }}</span>
            <div class="wf-out-actions">
              <div class="wf-out-columns">
                <button
                  class="wf-out-btn"
                  type="button"
                  aria-haspopup="true"
                  :aria-expanded="columnsOpen === output.name"
                  @click="toggleColumns(output)"
                >列</button>
                <div v-if="columnsOpen === output.name" class="wf-out-columns-panel">
                  <label v-for="column in output.table?.columns ?? []" :key="column.key">
                    <input type="checkbox" :checked="columnVisible(output, column)" @change="toggleColumn(output, column.key)" />
                    <span>{{ column.label }}</span>
                  </label>
                </div>
              </div>
              <button
                class="wf-out-btn"
                type="button"
                :class="{ 'is-active': output.tableState.wrap }"
                :aria-pressed="output.tableState.wrap"
                :title="output.tableState.wrap ? '关闭单元格换行' : '开启单元格换行'"
                @click="output.tableState.wrap = !output.tableState.wrap"
              >换行</button>
              <button class="wf-out-btn" type="button" title="复制筛选后的全部行为 CSV" @click="copyCsv(output)">复制 CSV</button>
              <button class="wf-out-btn" type="button" title="下载筛选后的全部行为 CSV" @click="downloadCsv(output)">导出</button>
            </div>
          </div>

          <div class="wf-out-scroll" :class="{ 'is-wrapped': output.tableState.wrap }">
            <table v-if="visibleColumns(output).length" class="wf-out-table-el">
              <thead>
                <tr>
                  <th class="wf-out-toggle-col" scope="col"><span class="wf-out-visually-hidden">展开行</span></th>
                  <th v-for="column in visibleColumns(output)" :key="column.key" scope="col">
                    <button type="button" :aria-label="`按 ${column.label} 排序`" @click="sortBy(output, column.key)">
                      <span>{{ column.label }}</span>
                      <span class="wf-out-sort" :data-active="output.tableState.sortKey === column.key">{{ sortIndicator(output, column.key) }}</span>
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                <template v-for="row in visibleRows(output)" :key="row.id">
                  <tr
                    class="wf-out-row"
                    :aria-expanded="output.tableState.expandedRow === row.id"
                    tabindex="0"
                    @click="toggleRow(output, row.id)"
                    @keydown.enter.prevent="toggleRow(output, row.id)"
                  >
                    <td class="wf-out-toggle-col"><span class="wf-out-chevron" aria-hidden="true">›</span></td>
                    <td v-for="column in visibleColumns(output)" :key="column.key">
                      <span
                        v-if="isStatusColumn(column)"
                        class="wf-out-status"
                        :data-tone="statusTone(cellText(row.cells[column.key]))"
                      ><i></i>{{ statusLabel(cellText(row.cells[column.key])) }}</span>
                      <span v-else-if="isDeviceColumn(column)" class="wf-out-device">{{ cellText(row.cells[column.key]) }}</span>
                      <span v-else-if="Array.isArray(row.cells[column.key])" class="wf-out-pills is-cell">
                        <span v-for="(pill, index) in cellPills(row.cells[column.key])" :key="index">{{ pill }}</span>
                        <span v-if="cellExtra(row.cells[column.key])" class="wf-out-pill-more">+{{ cellExtra(row.cells[column.key]) }}</span>
                      </span>
                      <span v-else class="wf-out-cell" :class="cellTone(row.cells[column.key])" :title="cellText(row.cells[column.key])">{{ cellText(row.cells[column.key]) || '—' }}</span>
                    </td>
                  </tr>
                  <tr v-if="output.tableState.expandedRow === row.id" class="wf-out-detail-row">
                    <td :colspan="visibleColumns(output).length + 1">
                      <ol v-if="stepDetails(row.detail).length" class="wf-out-steps">
                        <li v-for="step in stepDetails(row.detail)" :key="step.id">
                          <span class="wf-out-step-dot" :data-tone="statusTone(step.status)"></span>
                          <small>{{ step.id }}</small>
                          <span>{{ step.summary || statusLabel(step.status) }}</span>
                        </li>
                      </ol>
                      <pre v-else class="wf-out-detail">{{ row.detail ? pretty(row.detail) : pretty(row.cells) }}</pre>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
            <div v-if="!sortedRows(output).length" class="wf-out-empty">
              <strong>{{ output.tableState.query ? '没有匹配的行' : '此输出没有可展示的记录' }}</strong>
              <span>{{ output.tableState.query ? '调整筛选内容后重试。' : '检查工作流的输出定义。' }}</span>
            </div>
            <div v-else-if="!visibleColumns(output).length" class="wf-out-empty">
              <strong>没有可见的列</strong>
              <span>在「列」中重新打开至少一列。</span>
            </div>
          </div>

          <footer class="wf-out-foot">
            <span>{{ rowSummary(output) }}</span>
            <button v-if="sortedRows(output).length > output.tableState.limit" class="wf-out-btn" type="button" @click="showMore(output)">显示更多</button>
          </footer>
        </div>

        <div v-else class="wf-out-json">
          <div class="wf-out-toolbar">
            <label class="wf-out-search">
              <span aria-hidden="true">⌕</span>
              <input
                :value="output.jsonState.query"
                type="search"
                :aria-label="`在 ${output.name} 中搜索`"
                placeholder="搜索 JSON…"
                @input="setJsonQuery(output, ($event.target as HTMLInputElement).value)"
              />
            </label>
            <div class="wf-out-actions">
              <button class="wf-out-btn" type="button" @click="toggleAllJson(output)">{{ allJsonExpanded(output) ? '收起全部' : '展开全部' }}</button>
            </div>
          </div>
          <div class="wf-out-json-tree">
            <div
              v-for="row in jsonRows(output)"
              :key="row.id"
              class="wf-out-json-row"
              :class="{ 'is-expandable': row.kind !== 'value' }"
              :style="{ paddingLeft: `${row.depth * 14}px` }"
              @click="row.kind !== 'value' && toggleJson(output, row.id)"
            >
              <span class="wf-out-json-chevron" aria-hidden="true">{{ row.kind === 'value' ? '' : (output.jsonState.expanded.has(row.id) || output.jsonState.query ? '▾' : '▸') }}</span>
              <span class="wf-out-json-key">{{ row.key }}</span>
              <span class="wf-out-json-colon">:</span>
              <span v-if="row.kind === 'value'" class="wf-out-json-value" :data-type="jsonValueType(row.value)">{{ jsonValueText(row.value) }}</span>
              <span v-else class="wf-out-json-summary">{{ jsonSummaryText(row) }}</span>
            </div>
          </div>
        </div>
      </article>
    </div>

    <p v-if="copyNotice" class="wf-out-notice" role="status" aria-live="polite">{{ copyNotice }}</p>
  </section>
</template>

<style scoped>
.wf-out {
  container: workflow-output / inline-size;
  display: grid;
  gap: 10px;
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--workflow-border, var(--line));
  border-radius: 9px;
  background: var(--workflow-surface, var(--surface));
}
.wf-out-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.wf-out-heading-title { display: flex; align-items: baseline; gap: 8px; }
.wf-out-heading-title strong { color: var(--workflow-text, var(--text)); font-size: 12px; }
.wf-out-heading-title small { color: var(--workflow-muted, var(--muted)); font-size: 10px; }
.wf-out-kicker { color: #38bdf8; font-size: 9px; font-weight: 750; letter-spacing: .11em; }

.wf-out-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; min-width: 0; }
.wf-out-card {
  min-width: 0; display: grid; align-content: start; gap: 8px;
  padding: 11px 12px 12px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 8px;
  background: linear-gradient(180deg, rgba(255, 255, 255, .022), transparent 96px), var(--workflow-surface, var(--surface));
}
.wf-out-card.is-wide { grid-column: 1 / -1; }
.wf-out-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.wf-out-card-title { display: grid; gap: 2px; min-width: 0; }
.wf-out-card-title strong { overflow: hidden; color: var(--workflow-text, var(--text)); font-size: 11.5px; font-weight: 650; text-overflow: ellipsis; }
.wf-out-card-title small { color: var(--workflow-muted, var(--muted)); font-size: 10px; line-height: 1.4; }
.wf-out-card-tools { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.wf-out-kind {
  padding: 2px 7px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 999px;
  color: var(--workflow-muted, var(--muted)); font: 9px/1.5 ui-monospace, Consolas, monospace;
}
.wf-out-kind[data-kind="table"] { color: #7dd3fc; border-color: rgba(56, 189, 248, .35); background: rgba(56, 189, 248, .08); }
.wf-out-kind[data-kind="json"] { color: #fcd34d; border-color: rgba(252, 211, 77, .28); background: rgba(252, 211, 77, .07); }
.wf-out-kind[data-kind="list"] { color: #c4b5fd; border-color: rgba(167, 139, 250, .3); background: rgba(167, 139, 250, .08); }

.wf-out-btn {
  flex: 0 0 auto; padding: 4px 8px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 5px;
  color: var(--workflow-text, var(--text)); background: var(--workflow-surface, var(--surface)); cursor: pointer;
  font-size: 10.5px; white-space: nowrap;
}
.wf-out-btn:hover, .wf-out-btn:focus-visible { border-color: #38bdf8; color: #7dd3fc; outline: none; }
.wf-out-btn.is-active { border-color: rgba(56, 189, 248, .7); color: #7dd3fc; background: rgba(56, 189, 248, .11); }

.wf-out-scalar { display: grid; gap: 4px; min-width: 0; }
.wf-out-scalar b {
  overflow-wrap: anywhere; color: var(--workflow-text, var(--text));
  font: 600 20px/1.25 ui-monospace, Consolas, monospace; font-variant-numeric: tabular-nums;
}
.wf-out-scalar b.is-path { color: #bae6fd; }
.wf-out-scalar small { color: var(--workflow-muted, var(--muted)); font-size: 10px; }
.wf-out-scalar[data-missing="true"] b { color: #fda4af; font-size: 13px; }

.wf-out-pills { display: flex; flex-wrap: wrap; gap: 5px; margin: 0; padding: 0; list-style: none; }
.wf-out-pills > li, .wf-out-pills > span {
  padding: 2px 8px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 4px;
  color: #bae6fd; background: rgba(56, 189, 248, .06); font: 10px/1.6 ui-monospace, Consolas, monospace;
}
.wf-out-pills.is-cell { gap: 3px; }
.wf-out-pills.is-cell > span { padding: 0 5px; font-size: 9px; }
.wf-out-pill-more { border-style: dashed; color: var(--workflow-muted, var(--muted)); }

.wf-out-table, .wf-out-json { display: grid; gap: 0; min-width: 0; }
.wf-out-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-bottom: 8px; }
.wf-out-search {
  flex: 1 1 170px; max-width: 300px; display: flex; align-items: center; gap: 6px;
  height: 27px; padding: 0 8px; border: 1px solid var(--workflow-border, var(--line)); border-radius: 5px;
  color: var(--workflow-muted, var(--muted)); background: var(--workflow-surface-input, var(--surface));
}
.wf-out-search > span { font-size: 15px; line-height: 1; }
.wf-out-search input { width: 100%; min-width: 0; border: 0; outline: none; color: var(--workflow-text, var(--text)); background: transparent; font-size: 10.5px; }
.wf-out-count { color: var(--workflow-muted, var(--muted)); font: 10px ui-monospace, Consolas, monospace; white-space: nowrap; }
.wf-out-actions { display: flex; align-items: center; gap: 5px; margin-left: auto; flex-wrap: wrap; }

.wf-out-columns { position: relative; }
.wf-out-columns-panel {
  position: absolute; right: 0; top: 30px; z-index: 6; min-width: 168px; display: grid; gap: 1px;
  padding: 7px; border: 1px solid var(--line-strong, var(--workflow-border, var(--line))); border-radius: 7px;
  background: var(--workflow-surface-raised, var(--surface)); box-shadow: 0 18px 36px -16px #000;
}
.wf-out-columns-panel label { display: flex; align-items: center; gap: 7px; padding: 5px 6px; border-radius: 4px; color: var(--workflow-muted, var(--muted)); font-size: 10.5px; cursor: pointer; }
.wf-out-columns-panel label:hover { color: var(--workflow-text, var(--text)); background: rgba(148, 163, 184, .09); }
.wf-out-columns-panel input { accent-color: #38bdf8; }

.wf-out-scroll { max-height: 330px; overflow: auto; border: 1px solid var(--workflow-border, var(--line)); border-radius: 6px; }
.wf-out-table-el { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 11px; }
.wf-out-table-el th {
  position: sticky; top: 0; z-index: 1; padding: 0; border-bottom: 1px solid var(--workflow-border, var(--line));
  background: var(--workflow-surface, var(--surface)); text-align: left; white-space: nowrap;
}
.wf-out-table-el th button {
  width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 10px;
  border: 0; color: var(--workflow-muted, var(--muted)); background: transparent; cursor: pointer;
  font-family: inherit; font-size: 10.5px; font-weight: 650;
}
.wf-out-table-el th button:hover { color: #7dd3fc; background: rgba(56, 189, 248, .06); }
.wf-out-sort { color: #38bdf8; opacity: .35; font-size: 10px; }
.wf-out-sort[data-active="true"] { opacity: 1; }
.wf-out-toggle-col { width: 26px; min-width: 26px; padding: 0 !important; }
.wf-out-chevron { display: inline-grid; place-items: center; width: 18px; height: 18px; color: var(--workflow-muted, var(--muted)); font-size: 11px; transition: transform .16s ease; }
.wf-out-row { cursor: pointer; }
.wf-out-row:hover { background: rgba(56, 189, 248, .05); }
.wf-out-row[aria-expanded="true"] .wf-out-chevron { transform: rotate(90deg); color: #7dd3fc; }
.wf-out-table-el td { padding: 8px 10px; border-bottom: 1px solid color-mix(in srgb, var(--workflow-border, var(--line)) 55%, transparent); vertical-align: middle; }
.wf-out-cell { display: block; overflow: hidden; color: var(--workflow-text, var(--text)); text-overflow: ellipsis; white-space: nowrap; }
.wf-out-scroll.is-wrapped .wf-out-cell { white-space: pre-wrap; overflow-wrap: anywhere; }
.wf-out-cell.is-number { color: #a5b4fc; font-variant-numeric: tabular-nums; }
.wf-out-cell.is-boolean { color: #86efac; }
.wf-out-cell.is-null { color: var(--workflow-muted, var(--muted)); }
.wf-out-cell.is-object { color: #fcd34d; font-family: ui-monospace, Consolas, monospace; }
.wf-out-device { color: var(--workflow-text, var(--text)); font-family: ui-monospace, Consolas, monospace; font-size: 10.5px; white-space: nowrap; }
.wf-out-status { display: inline-flex; align-items: center; gap: 5px; font-size: 10.5px; white-space: nowrap; }
.wf-out-status i { width: 5px; height: 5px; border-radius: 50%; background: var(--workflow-muted, var(--muted)); }
.wf-out-status[data-tone="ok"] { color: #86efac; }
.wf-out-status[data-tone="ok"] i { background: #22c55e; box-shadow: 0 0 6px rgba(34, 197, 94, .65); }
.wf-out-status[data-tone="bad"] { color: #fda4af; }
.wf-out-status[data-tone="bad"] i { background: #f43f5e; }
.wf-out-status[data-tone="warn"] { color: #fcd34d; }
.wf-out-status[data-tone="warn"] i { background: #f59e0b; }

.wf-out-detail-row td { padding: 0 !important; background: color-mix(in srgb, var(--workflow-surface-input, var(--surface)) 88%, transparent); }
.wf-out-steps { display: grid; gap: 0; margin: 0; padding: 8px 12px 10px 30px; list-style: none; }
.wf-out-steps li { display: grid; grid-template-columns: 8px 118px minmax(0, 1fr); gap: 9px; align-items: baseline; padding: 6px 0; }
.wf-out-step-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--workflow-muted, var(--muted)); }
.wf-out-step-dot[data-tone="ok"] { background: #22c55e; }
.wf-out-step-dot[data-tone="bad"] { background: #f43f5e; }
.wf-out-step-dot[data-tone="warn"] { background: #f59e0b; }
.wf-out-steps small { color: var(--workflow-muted, var(--muted)); font: 9.5px ui-monospace, Consolas, monospace; }
.wf-out-steps > li > span:last-child { color: var(--workflow-text, var(--text)); font-size: 10.5px; overflow-wrap: anywhere; }
.wf-out-detail {
  max-height: 180px; overflow: auto; margin: 8px 12px 10px 30px; padding: 8px;
  border: 1px solid var(--workflow-border, var(--line)); border-radius: 5px;
  color: #fcd34d; background: var(--workflow-surface, var(--surface));
  font: 9.5px/1.5 ui-monospace, Consolas, monospace; white-space: pre;
}

.wf-out-json-tree {
  max-height: 300px; overflow: auto; padding: 7px 9px;
  border: 1px solid var(--workflow-border, var(--line)); border-radius: 6px;
  background: var(--workflow-surface-input, var(--surface));
  font: 10.5px/1.7 ui-monospace, Consolas, monospace;
}
.wf-out-json-row { display: flex; align-items: baseline; gap: 4px; min-width: max-content; }
.wf-out-json-row.is-expandable { cursor: pointer; }
.wf-out-json-row.is-expandable:hover { background: rgba(56, 189, 248, .06); }
.wf-out-json-chevron { width: 10px; flex: 0 0 10px; color: var(--workflow-muted, var(--muted)); font-size: 8px; }
.wf-out-json-key { color: #93c5fd; }
.wf-out-json-colon { margin-right: 3px; color: var(--workflow-muted, var(--muted)); }
.wf-out-json-summary { color: var(--workflow-muted, var(--muted)); }
.wf-out-json-value { overflow-wrap: anywhere; color: #86efac; white-space: pre-wrap; }
.wf-out-json-value[data-type="number"] { color: #c4b5fd; }
.wf-out-json-value[data-type="boolean"] { color: #fca5a5; }
.wf-out-json-value[data-type="null"] { color: var(--workflow-muted, var(--muted)); }

.wf-out-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding-top: 7px; color: var(--workflow-muted, var(--muted)); font-size: 9.5px; }
.wf-out-empty { display: grid; place-items: center; gap: 3px; padding: 30px 12px; color: var(--workflow-muted, var(--muted)); text-align: center; }
.wf-out-empty strong { color: var(--workflow-text, var(--text)); font-size: 11px; }
.wf-out-empty span { font-size: 10px; }

.wf-out-download {
  display: flex; align-items: center; gap: 9px; width: max-content; max-width: 100%;
  padding: 8px 11px; border: 1px solid rgba(56, 189, 248, .45); border-radius: 6px;
  color: #7dd3fc; background: rgba(56, 189, 248, .08); text-decoration: none;
}
.wf-out-download-copy { display: grid; gap: 1px; min-width: 0; }
.wf-out-download small { overflow: hidden; color: var(--workflow-muted, var(--muted)); font-size: 9px; text-overflow: ellipsis; }
.wf-out-device-list { display: grid; grid-template-columns: minmax(90px, .4fr) minmax(0, 1fr); margin: 0; border: 1px solid var(--workflow-border, var(--line)); border-radius: 6px; overflow: hidden; }
.wf-out-device-list dt, .wf-out-device-list dd { margin: 0; padding: 6px 8px; border-bottom: 1px solid var(--workflow-border, var(--line)); font-size: 10.5px; overflow-wrap: anywhere; }
.wf-out-device-list dt { color: var(--workflow-muted, var(--muted)); background: color-mix(in srgb, var(--workflow-surface, var(--surface)) 75%, transparent); }
.wf-out-notice { margin: 0; color: #86efac; font-size: 10px; }
.wf-out-visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

@container workflow-output (max-width: 560px) {
  .wf-out-grid { grid-template-columns: minmax(0, 1fr); }
  .wf-out-toolbar { align-items: stretch; flex-direction: column; }
  .wf-out-search { width: 100%; max-width: none; }
  .wf-out-actions { margin-left: 0; justify-content: flex-end; }
  .wf-out-count { align-self: flex-end; }
}
</style>
