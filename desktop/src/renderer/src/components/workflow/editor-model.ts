import type { Ref } from 'vue'

export interface EditorNode { id: string; action_id: string; config: Record<string, unknown>; input_mapping?: Record<string, unknown>; position?: { x: number; y: number } }
export interface EditorEdge { source: string; target: string; condition?: string; source_handle?: string }
export interface EditorAction { id: string; label: string }

export function nodeLabel(node: EditorNode, actions: EditorAction[]): string {
  return actions.find((action) => action.id === node.action_id)?.label || node.action_id
}

export function incomingEdges(edges: EditorEdge[]): Map<string, EditorEdge> {
  const map = new Map<string, EditorEdge>()
  for (const edge of edges) if (!map.has(edge.target)) map.set(edge.target, edge)
  return map
}

export function reachableNodes(nodes: EditorNode[], edges: EditorEdge[]): Set<string> {
  if (nodes.length < 2) return new Set(nodes.map((node) => node.id))
  const adjacency = new Map<string, string[]>()
  for (const edge of edges) adjacency.set(edge.source, [...(adjacency.get(edge.source) || []), edge.target])
  const reachable = new Set<string>()
  const pending = nodes[0] ? [nodes[0].id] : []
  while (pending.length) {
    const id = pending.pop()
    if (!id || reachable.has(id)) continue
    reachable.add(id)
    for (const target of adjacency.get(id) || []) if (!reachable.has(target)) pending.push(target)
  }
  return reachable
}

export function connectorLabel(node: EditorNode, index: number, incoming: Map<string, EditorEdge>, nodes: EditorNode[], actions: EditorAction[]): string {
  if (!index) return '开始'
  const edge = incoming.get(node.id)
  if (!edge) return '未连接'
  const source = nodes.find((item) => item.id === edge.source)
  if (edge.condition === 'true' || edge.source_handle === 'true') return `满足条件 → ${nodeLabel(source || node, actions)}`
  if (edge.condition === 'false' || edge.source_handle === 'false') return `不满足条件 → ${nodeLabel(source || node, actions)}`
  return source ? `来自 ${nodeLabel(source, actions)}` : '未连接'
}

export function nodeOptions(nodes: EditorNode[], excludeId: string): EditorNode[] {
  return nodes.filter((node) => node.id !== excludeId)
}

export function nodeSettings(node: EditorNode): Record<string, unknown> {
  return { ...node.config, ...(node.input_mapping || {}) }
}

export function hasRequiredConfigValue(node: EditorNode, settings: Record<string, unknown>, key: string): boolean {
  let aliases = [key]
  if (node.action_id === 'script.run' && key === 'script') aliases = ['script', 'script_id']
  if (node.action_id === 'file.upload' || node.action_id === 'file.download') {
    if (key === 'source') aliases = ['source', 'source_path']
    if (key === 'destination') aliases = ['destination', 'destination_path']
  }
  return aliases.some((alias) => {
    const value = settings[alias]
    if (Array.isArray(value)) return value.length > 0
    return value !== undefined && value !== null && String(value).trim() !== ''
  })
}

export function nodeState(node: EditorNode, requiredConfigByAction: Record<string, string[]>): 'ready' | 'attention' {
  const settings = nodeSettings(node)
  const required = requiredConfigByAction[node.action_id] || []
  if (required.some((key) => !hasRequiredConfigValue(node, settings, key))) return 'attention'
  if (node.action_id === 'utility.condition') {
    const rules = settings.rules
    const expression = typeof settings.expression === 'string' ? settings.expression.trim() : ''
    if (!expression && (!Array.isArray(rules) || !rules.some((rule) => rule && String((rule as Record<string, unknown>).field || '').trim() && String((rule as Record<string, unknown>).operator || '').trim()))) return 'attention'
  }
  return 'ready'
}

export function nodeHasHighRiskAction(node: EditorNode, highRiskActions: Set<string>): boolean {
  if (highRiskActions.has(node.action_id)) return true
  return (['loop.for_each', 'loop.until'].includes(node.action_id) || node.action_id === 'device.for_each')
    && highRiskActions.has(String(node.config.action_id || ''))
}

export function configString(node: EditorNode | null, key: string): string {
  return String(node?.config?.[key] ?? '')
}

export function updateConfigString(node: EditorNode | null, key: string, value: string): void {
  if (node) node.config[key] = value
}
