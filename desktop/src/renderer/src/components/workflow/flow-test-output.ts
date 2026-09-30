export function flowTestValueText(value: unknown, prefix = ''): string {
  if (value === null || value === undefined) return prefix ? `${prefix}: 无内容` : ''
  if (Array.isArray(value)) return value.map((item, index) => flowTestValueText(item, prefix ? `${prefix}[${index + 1}]` : `${index + 1}`)).filter(Boolean).join('\n')
  if (typeof value === 'object') return Object.entries(value as Record<string, unknown>).map(([key, item]) => flowTestValueText(item, prefix ? `${prefix} · ${key}` : key)).filter(Boolean).join('\n')
  return prefix ? `${prefix}: ${String(value)}` : String(value)
}

export function flowTestOutputText(value: string): string {
  const text = String(value || '').trim()
  if (!text) return ''
  if (text.startsWith('{') || text.startsWith('[')) {
    try { return flowTestValueText(JSON.parse(text)) || text } catch { /* preserve ordinary command output */ }
  }
  return text
}
