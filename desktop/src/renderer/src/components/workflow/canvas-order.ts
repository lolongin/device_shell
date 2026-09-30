export interface CanvasNodeLike {
  id: string
}

export interface CanvasEdgeLike {
  source: string
  target: string
}

export function orderCanvasNodes<T extends CanvasNodeLike>(nodes: T[], edges: CanvasEdgeLike[]): T[] {
  if (nodes.length < 2) return nodes
  const ids = new Set(nodes.map((node) => node.id))
  const incoming = new Map(nodes.map((node) => [node.id, 0]))
  const outgoing = new Map(nodes.map((node) => [node.id, [] as string[]]))
  for (const edge of edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target) || edge.source === edge.target) continue
    incoming.set(edge.target, (incoming.get(edge.target) || 0) + 1)
    outgoing.get(edge.source)?.push(edge.target)
  }
  const pending = nodes.filter((node) => !incoming.get(node.id))
  const ordered: T[] = []
  const emitted = new Set<string>()
  while (pending.length) {
    const node = pending.shift()
    if (!node || emitted.has(node.id)) continue
    emitted.add(node.id)
    ordered.push(node)
    for (const target of outgoing.get(node.id) || []) {
      const count = (incoming.get(target) || 0) - 1
      incoming.set(target, count)
      if (!count) {
        const targetNode = nodes.find((item) => item.id === target)
        if (targetNode) pending.push(targetNode)
      }
    }
  }
  return ordered.length === nodes.length ? ordered : nodes
}
