export interface DeviceWindowMetrics {
  rowHeight: number
  headerHeight: number
  overscan: number
  threshold: number
}

export function deviceWindow(length: number, scrollTop: number, viewportHeight: number, metrics: DeviceWindowMetrics): { virtualized: boolean; start: number; end: number; top: number; bottom: number } {
  const virtualized = length > metrics.threshold
  if (!virtualized) return { virtualized: false, start: 0, end: length, top: 0, bottom: 0 }
  const start = Math.max(0, Math.floor(scrollTop / metrics.rowHeight) - metrics.overscan)
  const visibleHeight = Math.max(metrics.rowHeight, viewportHeight - metrics.headerHeight)
  const end = Math.min(length, Math.ceil((scrollTop + visibleHeight) / metrics.rowHeight) + metrics.overscan)
  return { virtualized, start, end, top: start * metrics.rowHeight, bottom: Math.max(0, (length - end) * metrics.rowHeight) }
}
