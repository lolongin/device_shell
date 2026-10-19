/**
 * Presentation model for workflow outputs.
 *
 * Declared outputs carry expressions such as `${inspect.result.version}`.  The
 * backend resolves them for stored runs; Studio runs resolve here so the same
 * renderer covers both surfaces.  Loop (each) results wrap the business fields
 * under `value` next to execution metadata; the model promotes the business
 * fields to table columns and keeps the rest for the row detail.
 */

export type OutputDefinition = {
  name: string
  value?: unknown
  resolvedValue?: unknown
  type?: string
  primitiveType?: string
  semanticType?: string
  presentation?: string
  renderer?: { id?: string; props?: Record<string, unknown> }
  description?: string
  mime_type?: string
  mimeType?: string
  download_name?: string
  downloadName?: string
}

export type OutputKind = 'text' | 'list' | 'table' | 'json' | 'download' | 'device' | 'hidden'

export type TableColumn = { key: string; label: string; noise?: boolean }

export type TableRow = {
  id: string
  cells: Record<string, unknown>
  detail?: Record<string, unknown>
}

export type JsonRow = {
  id: string
  depth: number
  parent: string
  key: string
  kind: 'object' | 'array' | 'value'
  value?: unknown
  count?: number
}

export type StepDetail = {
  id: string
  status: string
  summary: string
}

/** Fields that describe execution rather than the business result. */
const NOISE_KEYS = new Set([
  'evidence',
  'steps',
  'run',
  'raw',
  'stdout',
  'stderr',
  'exitCode',
  'exit_code',
  'returncode',
  'program',
  'operation_id',
  'execution_id',
  'host',
  'port',
  'error'
])

const ENVELOPE_KEYS = ['rows', 'data', 'results', 'items', 'records', 'devices']

export function hasOwn(value: unknown, key: string): boolean {
  return Boolean(value) && Object.prototype.hasOwnProperty.call(value, key)
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function lookup(path: string, context: unknown): unknown {
  let current: unknown = context
  let segments = path.trim().split('.')
  if (segments[0] === 'outputs' && !isRecord(context)) segments = segments.slice(1)
  else if (segments[0] === 'outputs' && isRecord(context) && !hasOwn(context, 'outputs')) segments = segments.slice(1)
  for (const part of segments) {
    if (isRecord(current) && hasOwn(current, part)) {
      current = current[part]
    } else if (Array.isArray(current) && /^\d+$/.test(part) && Number(part) < current.length) {
      current = current[Number(part)]
    } else {
      return undefined
    }
  }
  return current
}

/** Resolve `${a.b.0.c}` references against the run output map. */
export function resolveReference(value: unknown, context: unknown): unknown {
  if (typeof value !== 'string' || !value.includes('${')) return value
  const exact = value.trim().match(/^\$\{([^}]+)\}$/)
  if (exact) return lookup(exact[1], context)
  return value.replace(/\$\{([^}]+)\}/g, (_match, path: string) => {
    const resolved = lookup(path, context)
    return resolved === undefined || resolved === null ? '' : stringify(resolved)
  })
}

/** Value precedence: backend-resolved value, runtime value by name, expression. */
export function outputValue(output: OutputDefinition, values: Record<string, unknown>): unknown {
  if (hasOwn(output, 'resolvedValue')) return output.resolvedValue
  const expression = typeof output.value === 'string' && output.value.includes('${')
  if (!expression && hasOwn(values, output.name)) return values[output.name]
  return resolveReference(output.value, values)
}

export function unresolvedExpression(output: OutputDefinition): string {
  return typeof output.value === 'string' && output.value.includes('${') ? output.value : ''
}

export function inferKind(output: OutputDefinition, value: unknown): OutputKind {
  const requested = String(output.renderer?.id || output.presentation || '').toLowerCase()
  if (requested === 'hidden') return 'hidden'
  if (value === undefined) return requested === 'table' || requested === 'json' ? (requested as OutputKind) : 'text'
  if (requested === 'download' && downloadUrl(value)) return 'download'
  if (requested === 'device' && isRecord(value)) return 'device'
  if (requested === 'table') {
    // A declared table backed by plain scalars reads better as a chip list.
    if (Array.isArray(value) && value.length && value.every((item) => isPrimitive(item))) return 'list'
    return 'table'
  }
  if (requested === 'json') return 'json'
  if (Array.isArray(value)) {
    if (value.some((item) => isRecord(item))) return 'table'
    if (value.length) return 'list'
  }
  if (isRecord(value)) {
    if (ENVELOPE_KEYS.some((key) => Array.isArray(value[key]))) return 'table'
    if (requested === 'text' || !requested) return 'json'
  }
  return 'text'
}

export function downloadUrl(value: unknown): string {
  return typeof value === 'string' && /^(file:|https?:|data:)/i.test(value) ? value : ''
}

function parseJsonString(value: unknown): unknown {
  if (typeof value !== 'string') return value
  const trimmed = value.trim()
  if (!trimmed.startsWith('[') && !trimmed.startsWith('{')) return value
  try {
    return JSON.parse(trimmed)
  } catch {
    return value
  }
}

function configuredColumns(value: unknown): TableColumn[] {
  if (!Array.isArray(value)) return []
  return value.map((item): TableColumn | null => {
    if (typeof item === 'string') return { key: item, label: item }
    if (!isRecord(item)) return null
    const key = String(item.key ?? item.field ?? item.dataIndex ?? item.accessorKey ?? item.name ?? item.id ?? item.label ?? '')
    return key ? { key, label: String(item.label ?? item.title ?? key) } : null
  }).filter((item): item is TableColumn => item !== null)
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value) return value
    if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  }
  return ''
}

/**
 * Build the table model for a value.
 *
 * Loop results (`{ results: [{ device_id, status, steps, value }] }`) become one
 * row per device: business fields become columns, status/device become meta
 * cells, and the execution detail stays available for row expansion.
 */
export function buildTable(value: unknown, preferredColumns: unknown): { columns: TableColumn[]; rows: TableRow[] } {
  const declared = configuredColumns(preferredColumns)
  const parsed = parseJsonString(value)
  let rawRows: unknown[] = []
  let envelopeColumns = declared

  if (Array.isArray(parsed)) {
    rawRows = parsed
  } else if (isRecord(parsed)) {
    if (!envelopeColumns.length) {
      envelopeColumns = configuredColumns(parsed.columns ?? parsed.fields ?? parsed.headers)
    }
    const rows = ENVELOPE_KEYS.map((key) => parsed[key]).find(Array.isArray)
    rawRows = Array.isArray(rows) ? rows : [parsed]
  } else if (typeof parsed === 'string') {
    rawRows = parsed.trim() ? [{ value: parsed }] : []
  }

  const rows: TableRow[] = rawRows.map((raw, index) => {
    if (Array.isArray(raw)) {
      return { id: String(index), cells: Object.fromEntries(raw.map((item, column) => [String(column), item])) }
    }
    if (!isRecord(raw)) return { id: String(index), cells: { value: raw } }
    const business = isRecord(raw.value) ? raw.value : raw
    const cells: Record<string, unknown> = { ...business }
    const status = firstText(raw.status, raw.execution_status, business.status)
    const device = firstText(raw.device_id, business.device_id, raw.id, business.id)
    delete cells.device_id
    delete cells.status
    delete cells.execution_status
    if (status) cells.__status = status
    if (device) cells.__device = device
    const detail = isRecord(raw.steps) ? raw.steps : isRecord(raw.run) ? raw.run : undefined
    return { id: String(index), cells, detail }
  })

  const discovered = new Set<string>()
  for (const row of rows) Object.keys(row.cells).forEach((key) => discovered.add(key))

  const columns: TableColumn[] = []
  const seen = new Set<string>()
  const push = (column: TableColumn) => {
    if (seen.has(column.key)) return
    seen.add(column.key)
    columns.push(column)
  }
  if (discovered.has('__device')) push({ key: '__device', label: '设备' })
  if (discovered.has('__status')) push({ key: '__status', label: '状态' })
  for (const column of envelopeColumns) if (discovered.has(column.key)) push({ ...column })
  for (const key of discovered) {
    if (key === '__device' || key === '__status' || seen.has(key)) continue
    push({ key, label: key, noise: NOISE_KEYS.has(key) })
  }

  return { columns, rows }
}

/** Flatten a JSON value into rows for the collapsible tree view. */
export function flattenJson(value: unknown, rootKey = 'result'): JsonRow[] {
  const rows: JsonRow[] = []
  const walk = (current: unknown, key: string, depth: number, id: string, parent: string) => {
    if (Array.isArray(current)) {
      rows.push({ id, depth, parent, key, kind: 'array', count: current.length })
      current.slice(0, 200).forEach((item, index) => walk(item, String(index), depth + 1, `${id}.${index}`, id))
      return
    }
    if (isRecord(current)) {
      const entries = Object.entries(current)
      rows.push({ id, depth, parent, key, kind: 'object', count: entries.length })
      entries.slice(0, 200).forEach(([childKey, child], index) =>
        walk(child, childKey, depth + 1, `${id}.${index}`, id))
      return
    }
    rows.push({ id, depth, parent, key, kind: 'value', value: current })
  }
  walk(value, rootKey, 0, '0', '')
  return rows
}

function rowText(row: JsonRow): string {
  return `${row.key} ${row.kind === 'value' ? stringify(row.value) : ''}`.toLowerCase()
}

/** Rows visible for the current expansion/search state. */
export function visibleJsonRows(rows: JsonRow[], expanded: Set<string>, query: string): JsonRow[] {
  const needle = query.trim().toLowerCase()
  if (!needle) {
    return rows.filter((row) => {
      let cursor = row.parent
      while (cursor) {
        if (!expanded.has(cursor)) return false
        const parent = rows.find((item) => item.id === cursor)
        cursor = parent ? parent.parent : ''
      }
      return true
    })
  }
  const keep = new Set<string>()
  for (const row of rows) {
    if (!rowText(row).includes(needle)) continue
    keep.add(row.id)
    let cursor = row.parent
    while (cursor) {
      keep.add(cursor)
      const parent = rows.find((item) => item.id === cursor)
      cursor = parent ? parent.parent : ''
    }
  }
  return rows.filter((row) => keep.has(row.id))
}

export function stringify(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value) ?? ''
  } catch {
    return String(value)
  }
}

export function cellText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return stringify(value)
  return String(value)
}

export function isPrimitive(value: unknown): boolean {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value)
}

export function textValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  return stringify(value)
}

export function statusTone(status: string): 'ok' | 'bad' | 'warn' | 'idle' {
  const value = status.toLowerCase()
  if (['succeeded', 'success', 'completed', 'ok', 'ready', '已成功', '成功'].includes(value)) return 'ok'
  if (['failed', 'error', 'cancelled', '失败'].includes(value)) return 'bad'
  if (['running', 'pending', 'waiting', '运行中', '等待'].includes(value)) return 'warn'
  return 'idle'
}

export function statusLabel(status: string): string {
  return ({
    succeeded: '成功',
    success: '成功',
    completed: '完成',
    failed: '失败',
    error: '错误',
    cancelled: '已取消',
    running: '运行中',
    pending: '等待',
    skipped: '跳过'
  } as Record<string, string>)[status.toLowerCase()] || status
}

/** Normalize a loop row's step map into displayable timeline entries. */
export function stepDetails(detail: Record<string, unknown> | undefined): StepDetail[] {
  if (!detail) return []
  return Object.entries(detail).map(([id, value]) => {
    if (isRecord(value)) {
      const status = firstText(value.status, value.execution_status, value.result_status) || 'completed'
      const summary = firstText(
        value.command,
        value.probe_command,
        value.summary,
        typeof value.output === 'string' ? value.output.split('\n')[0] : '',
        value.error && isRecord(value.error) ? value.error.message : ''
      )
      return { id, status, summary }
    }
    return { id, status: typeof value === 'string' ? value : 'completed', summary: '' }
  })
}
