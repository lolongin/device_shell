export function normalizeLoopUntilCondition(condition: unknown): unknown {
  if (String(condition ?? '').trim().toLowerCase() === 'true') return 'False'
  return condition
}

type LoopUntilNode = { action_id: string; config: Record<string, unknown> }

export function normalizeLoopUntilNodes(nodes: LoopUntilNode[]): void {
  for (const node of nodes) {
    if (node.action_id === 'loop.until') {
      node.config.condition = normalizeLoopUntilCondition(node.config.condition)
    }
  }
}
