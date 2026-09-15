import ELK from 'elkjs/lib/elk.bundled.js'

const elk = new ELK()

export interface LayoutOptions {
  direction: 'TB' | 'LR' | 'BT' | 'RL'  // Top-Bottom, Left-Right, Bottom-Top, Right-Left
  spacing: number
  nodeWidth?: number
  nodeHeight?: number
}

export interface LayoutNode {
  id: string
  position: { x: number; y: number }
  [key: string]: any
}

export interface LayoutEdge {
  id: string
  source: string
  target: string
  [key: string]: any
}

/**
 * 使用 ELK 算法自动布局节点
 */
export async function autoLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  options: LayoutOptions = {
    direction: 'TB',
    spacing: 80,
    nodeWidth: 200,
    nodeHeight: 100
  }
): Promise<{ nodes: LayoutNode[]; edges: LayoutEdge[] }> {
  const { direction, spacing, nodeWidth = 200, nodeHeight = 100 } = options

  // 构建 ELK 图结构
  const elkGraph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': getElkDirection(direction),
      'elk.spacing.nodeNode': spacing.toString(),
      'elk.layered.spacing.nodeNodeBetweenLayers': (spacing * 1.5).toString(),
      'elk.layered.nodePlacement.strategy': 'SIMPLE',
    },
    children: nodes.map(node => ({
      id: node.id,
      width: nodeWidth,
      height: nodeHeight
    })),
    edges: edges.map(edge => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target]
    }))
  }

  try {
    // 执行布局
    const layout = await elk.layout(elkGraph)

    // 应用布局结果到节点
    const layoutedNodes = nodes.map(node => {
      const elkNode = layout.children?.find(n => n.id === node.id)
      if (elkNode) {
        return {
          ...node,
          position: {
            x: elkNode.x ?? node.position.x,
            y: elkNode.y ?? node.position.y
          }
        }
      }
      return node
    })

    return { nodes: layoutedNodes, edges }
  } catch (error) {
    console.error('Auto layout failed:', error)
    // 如果布局失败，返回原始数据
    return { nodes, edges }
  }
}

/**
 * 简单的垂直布局（备用方案）
 */
export function simpleVerticalLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  spacing: number = 120
): { nodes: LayoutNode[]; edges: LayoutEdge[] } {
  const layoutedNodes = nodes.map((node, index) => ({
    ...node,
    position: {
      x: 100,
      y: index * spacing + 50
    }
  }))

  return { nodes: layoutedNodes, edges }
}

/**
 * 简单的水平布局（备用方案）
 */
export function simpleHorizontalLayout(
  nodes: LayoutNode[],
  edges: LayoutEdge[],
  spacing: number = 250
): { nodes: LayoutNode[]; edges: LayoutEdge[] } {
  const layoutedNodes = nodes.map((node, index) => ({
    ...node,
    position: {
      x: index * spacing + 50,
      y: 100
    }
  }))

  return { nodes: layoutedNodes, edges }
}

/**
 * 转换方向到 ELK 格式
 */
function getElkDirection(direction: string): string {
  const directionMap: Record<string, string> = {
    'TB': 'DOWN',
    'BT': 'UP',
    'LR': 'RIGHT',
    'RL': 'LEFT'
  }
  return directionMap[direction] || 'DOWN'
}

/**
 * 计算图的边界框
 */
export function getGraphBounds(nodes: LayoutNode[]): {
  minX: number
  minY: number
  maxX: number
  maxY: number
  width: number
  height: number
} {
  if (nodes.length === 0) {
    return { minX: 0, minY: 0, maxX: 0, maxY: 0, width: 0, height: 0 }
  }

  const xs = nodes.map(n => n.position.x)
  const ys = nodes.map(n => n.position.y)

  const minX = Math.min(...xs)
  const minY = Math.min(...ys)
  const maxX = Math.max(...xs)
  const maxY = Math.max(...ys)

  return {
    minX,
    minY,
    maxX,
    maxY,
    width: maxX - minX + 200, // 加上节点宽度
    height: maxY - minY + 100  // 加上节点高度
  }
}
