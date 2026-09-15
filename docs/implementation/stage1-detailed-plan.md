# 阶段1实施计划：后端增强 + 快速体验改进

**时间**：2周（10个工作日）  
**目标**：在最短时间内解决最痛的问题

## 任务清单

### Day 1：后端统一验证 API

#### Task 1.1：增强验证错误信息
**文件**：`device_tui/application/workflow_studio/validation.py`

```python
@dataclass(frozen=True, slots=True)
class EnhancedValidationIssue:
    code: str
    message: str
    node_id: str | None = None
    severity: Literal["error", "warning", "info"] = "error"
    
    # 新增字段
    fix_suggestion: str | None = None
    doc_link: str | None = None
    affected_nodes: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "node_id": self.node_id,
            "severity": self.severity,
            "fix_suggestion": self.fix_suggestion,
            "doc_link": self.doc_link,
            "affected_nodes": self.affected_nodes,
        }
```

**具体改进**：
- 为每个错误类型添加 `fix_suggestion`
- 添加文档链接（如：`/docs/nodes/device-command`）
- 识别错误影响范围（如：断开的节点会影响下游所有节点）

**验收**：
```python
# test_enhanced_validation.py
def test_validation_provides_fix_suggestion():
    draft = WorkflowDraft("w", "x", nodes=[
        WorkflowNode("cmd", "device.command", {"command": ""})
    ])
    result = validate_workflow(draft, CATALOG)
    issue = result.errors[0]
    
    assert issue.fix_suggestion == "请输入要执行的命令，例如 'display version'"
    assert issue.doc_link == "/docs/nodes/device-command"
```

---

### Day 2-6：集成 Vue Flow 替换画布

#### Task 2.1：安装依赖和 POC（Day 2）

```bash
cd desktop
npm install @vue-flow/core @vue-flow/background @vue-flow/controls @vue-flow/minimap
```

**POC 验证**：创建简单的 Vue Flow 示例，确认：
- 节点渲染
- 边连接
- 拖拽布局
- 事件处理

**文件**：`desktop/src/renderer/src/components/WorkflowCanvas.vue`（新建）

```vue
<script setup lang="ts">
import { ref, computed } from 'vue'
import { VueFlow, useVueFlow, Panel } from '@vue-flow/core'
import { Background } from '@vue-flow/background'
import { Controls } from '@vue-flow/controls'
import { MiniMap } from '@vue-flow/minimap'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'

const props = defineProps<{
  workflow: WorkflowItem | null
}>()

const emit = defineEmits<{
  nodeSelect: [nodeId: string]
  nodeAdd: [position: { x: number, y: number }]
  connect: [{ source: string, target: string }]
}>()

// 转换数据格式
const nodes = computed(() => {
  if (!props.workflow?.nodes) return []
  
  return props.workflow.nodes.map((node, index) => ({
    id: node.id,
    type: 'custom',  // 使用自定义节点组件
    position: node.position || { x: 50, y: index * 120 },
    data: {
      label: node.id,
      action_id: node.action_id,
      config: node.config
    }
  }))
})

const edges = computed(() => {
  if (!props.workflow?.edges) return []
  
  return props.workflow.edges.map(edge => ({
    id: `${edge.source}-${edge.target}`,
    source: edge.source,
    target: edge.target,
    type: edge.condition ? 'custom' : 'default',
    label: edge.condition === 'true' ? '是' : edge.condition === 'false' ? '否' : '',
    animated: false
  }))
})

// Vue Flow 实例
const { onConnect, onNodeDragStop, onNodeClick } = useVueFlow()

onConnect((params) => {
  emit('connect', { source: params.source, target: params.target })
})

onNodeClick((event) => {
  emit('nodeSelect', event.node.id)
})

onNodeDragStop((event) => {
  // 保存新位置
  const node = props.workflow?.nodes.find(n => n.id === event.node.id)
  if (node) {
    node.position = event.node.position
  }
})
</script>

<template>
  <div class="workflow-canvas-container">
    <VueFlow
      :nodes="nodes"
      :edges="edges"
      :default-zoom="1"
      :min-zoom="0.2"
      :max-zoom="4"
      fit-view-on-init
    >
      <Background />
      <Controls />
      <MiniMap />
      
      <Panel position="top-left" class="canvas-toolbar">
        <button @click="$emit('nodeAdd', { x: 100, y: 100 })">
          <Plus :size="16" /> 添加节点
        </button>
      </Panel>
    </VueFlow>
  </div>
</template>

<style scoped>
.workflow-canvas-container {
  width: 100%;
  height: 100%;
  background: #1a1a2e;
}
</style>
```

#### Task 2.2：自定义节点组件（Day 3）

**文件**：`desktop/src/renderer/src/components/WorkflowNode.vue`（新建）

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { Handle, Position } from '@vue-flow/core'
import { CheckCircle2, AlertTriangle } from 'lucide-vue-next'

const props = defineProps<{
  id: string
  data: {
    label: string
    action_id: string
    config: Record<string, unknown>
    state?: 'ready' | 'attention'
  }
}>()

const actionMeta = computed(() => {
  // 从 catalog 获取 action 元信息
  return {
    label: props.data.action_id,
    tone: 'blue',
    category: 'device'
  }
})
</script>

<template>
  <div :class="['workflow-node', `state-${data.state || 'ready'}`, `tone-${actionMeta.tone}`]">
    <Handle type="target" :position="Position.Top" />
    
    <div class="node-header">
      <span class="node-label">{{ actionMeta.label }}</span>
      <CheckCircle2 v-if="data.state === 'ready'" :size="14" />
      <AlertTriangle v-else :size="14" />
    </div>
    
    <div class="node-id">{{ data.label }}</div>
    
    <Handle type="source" :position="Position.Bottom" />
  </div>
</template>

<style scoped>
.workflow-node {
  padding: 12px 16px;
  border-radius: 8px;
  border: 2px solid rgba(100, 116, 139, 0.3);
  background: rgba(30, 41, 59, 0.9);
  min-width: 180px;
  cursor: pointer;
  transition: all 0.2s;
}

.workflow-node:hover {
  border-color: rgba(59, 130, 246, 0.5);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);
}

.workflow-node.state-attention {
  border-color: rgba(251, 191, 36, 0.6);
}

.node-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
  font-weight: 600;
  color: #e2e8f0;
}

.node-id {
  font-size: 11px;
  color: rgba(226, 232, 240, 0.6);
}
</style>
```

#### Task 2.3：集成到 WorkflowLibrary（Day 4-5）

**文件**：`desktop/src/renderer/src/components/WorkflowLibrary.vue`

**修改步骤**：
1. 导入 WorkflowCanvas 组件
2. 替换现有的 `<div class="workflow-node-list">` 部分
3. 保持其他部分不变（节点库、属性面板、工具栏）

```vue
<script setup lang="ts">
// 原有导入保持不变
import WorkflowCanvas from './WorkflowCanvas.vue'

// 原有逻辑保持不变
// ...

function handleNodeSelect(nodeId: string) {
  const node = selected.value?.nodes?.find(n => n.id === nodeId)
  if (node) selectedNode.value = node
}

function handleConnect({ source, target }: { source: string, target: string }) {
  addEdge(source, target)
}

function handleNodePositionChange(nodeId: string, position: { x: number, y: number }) {
  const node = selected.value?.nodes?.find(n => n.id === nodeId)
  if (node) {
    node.position = position
  }
}
</script>

<template>
  <!-- ... 原有的 header 和 toolbar 保持不变 ... -->
  
  <div class="workflow-library-body">
    <aside class="workflow-list-pane">
      <!-- 原有的流程列表保持不变 -->
    </aside>
    
    <main v-if="selected" class="workflow-studio-grid">
      <section class="workflow-action-catalog">
        <!-- 原有的节点库保持不变 -->
      </section>
      
      <!-- 关键变化：用 WorkflowCanvas 替换原来的节点列表 -->
      <section class="workflow-canvas-section">
        <div class="workflow-meta-fields">
          <!-- 流程名称和说明保持不变 -->
        </div>
        
        <WorkflowCanvas
          :workflow="selected"
          @node-select="handleNodeSelect"
          @connect="handleConnect"
          @node-position-change="handleNodePositionChange"
        />
      </section>
      
      <section v-if="selectedNode" class="workflow-properties">
        <!-- 原有的属性面板保持不变 -->
      </section>
    </main>
  </div>
</template>

<style scoped>
.workflow-canvas-section {
  grid-column: 2;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
}

.workflow-canvas-section > :last-child {
  flex: 1;
  min-height: 0;
}
</style>
```

#### Task 2.4：自动布局功能（Day 6）

```bash
npm install elkjs
```

**文件**：`desktop/src/renderer/src/utils/layoutAlgorithms.ts`（新建）

```typescript
import ELK from 'elkjs/lib/elk.bundled.js'

const elk = new ELK()

export interface LayoutOptions {
  direction: 'TB' | 'LR'  // Top-Bottom or Left-Right
  spacing: number
}

export async function autoLayout(
  nodes: any[],
  edges: any[],
  options: LayoutOptions = { direction: 'TB', spacing: 80 }
): Promise<{ nodes: any[], edges: any[] }> {
  const elkGraph = {
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': options.direction === 'TB' ? 'DOWN' : 'RIGHT',
      'elk.spacing.nodeNode': options.spacing.toString(),
      'elk.layered.spacing.nodeNodeBetweenLayers': options.spacing.toString()
    },
    children: nodes.map(node => ({
      id: node.id,
      width: 200,
      height: 80
    })),
    edges: edges.map(edge => ({
      id: edge.id,
      sources: [edge.source],
      targets: [edge.target]
    }))
  }
  
  const layout = await elk.layout(elkGraph)
  
  const layoutedNodes = nodes.map(node => {
    const elkNode = layout.children?.find(n => n.id === node.id)
    return {
      ...node,
      position: {
        x: elkNode?.x ?? node.position.x,
        y: elkNode?.y ?? node.position.y
      }
    }
  })
  
  return { nodes: layoutedNodes, edges }
}
```

**集成到画布**：

```vue
<script setup lang="ts">
import { autoLayout } from '../utils/layoutAlgorithms'

async function applyAutoLayout() {
  if (!props.workflow) return
  
  const { nodes: layoutedNodes } = await autoLayout(
    nodes.value,
    edges.value,
    { direction: 'TB', spacing: 100 }
  )
  
  // 更新节点位置
  layoutedNodes.forEach(layouted => {
    const node = props.workflow?.nodes.find(n => n.id === layouted.id)
    if (node) {
      node.position = layouted.position
    }
  })
}
</script>

<template>
  <VueFlow ...>
    <Panel position="top-left">
      <button @click="applyAutoLayout">
        <GitBranch :size="16" /> 自动布局
      </button>
    </Panel>
  </VueFlow>
</template>
```

---

### Day 7-8：实现撤销/重做

#### Task 3.1：撤销栈实现（Day 7）

**文件**：`desktop/src/renderer/src/composables/useUndoRedo.ts`（新建）

```typescript
import { ref, computed, Ref } from 'vue'

export interface UndoRedoOptions<T> {
  initialState: T
  maxHistory?: number
}

export function useUndoRedo<T>(options: UndoRedoOptions<T>) {
  const { initialState, maxHistory = 50 } = options
  
  const past = ref<T[]>([]) as Ref<T[]>
  const present = ref<T>(deepClone(initialState)) as Ref<T>
  const future = ref<T[]>([]) as Ref<T[]>
  
  const canUndo = computed(() => past.value.length > 0)
  const canRedo = computed(() => future.value.length > 0)
  
  function deepClone<T>(obj: T): T {
    return JSON.parse(JSON.stringify(obj))
  }
  
  function commit(newState: T) {
    past.value.push(deepClone(present.value))
    
    // 限制历史记录数量
    if (past.value.length > maxHistory) {
      past.value.shift()
    }
    
    present.value = deepClone(newState)
    future.value = []  // 清空 redo 栈
  }
  
  function undo() {
    if (!canUndo.value) return
    
    future.value.push(deepClone(present.value))
    present.value = past.value.pop()!
  }
  
  function redo() {
    if (!canRedo.value) return
    
    past.value.push(deepClone(present.value))
    present.value = future.value.pop()!
  }
  
  function reset(newState: T) {
    past.value = []
    present.value = deepClone(newState)
    future.value = []
  }
  
  return {
    state: present,
    canUndo,
    canRedo,
    commit,
    undo,
    redo,
    reset
  }
}
```

#### Task 3.2：集成到 WorkflowLibrary（Day 8）

```vue
<script setup lang="ts">
import { useUndoRedo } from '../composables/useUndoRedo'
import { watch } from 'vue'

// 初始化撤销栈
const workflowHistory = useUndoRedo({
  initialState: selected.value,
  maxHistory: 50
})

// 监听 workflow 变化，提交到历史栈
let isUndoRedoAction = false

watch(
  () => selected.value,
  (newWorkflow) => {
    if (isUndoRedoAction || !newWorkflow) return
    workflowHistory.commit(newWorkflow)
  },
  { deep: true }
)

// 撤销/重做操作
function performUndo() {
  isUndoRedoAction = true
  workflowHistory.undo()
  selected.value = workflowHistory.state.value
  isUndoRedoAction = false
}

function performRedo() {
  isUndoRedoAction = true
  workflowHistory.redo()
  selected.value = workflowHistory.state.value
  isUndoRedoAction = false
}

// 快捷键支持
onMounted(() => {
  document.addEventListener('keydown', handleKeyboard)
})

onUnmounted(() => {
  document.removeEventListener('keydown', handleKeyboard)
})

function handleKeyboard(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
    e.preventDefault()
    if (e.shiftKey) {
      performRedo()
    } else {
      performUndo()
    }
  }
}
</script>

<template>
  <div class="workflow-library-toolbar">
    <button @click="performUndo" :disabled="!workflowHistory.canUndo.value" title="撤销 (Ctrl+Z)">
      <Undo :size="14" /> 撤销
    </button>
    <button @click="performRedo" :disabled="!workflowHistory.canRedo.value" title="重做 (Ctrl+Shift+Z)">
      <Redo :size="14" /> 重做
    </button>
    <!-- 其他按钮保持不变 -->
  </div>
</template>
```

---

### Day 9-10：批量任务聚合显示

#### Task 4.1：后端 BatchTask 实体（Day 9）

**文件**：`device_tui/domain/batch_task.py`（新建）

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

BatchStatus = Literal["pending", "running", "completed", "partial_failure", "failed", "cancelled"]

@dataclass
class BatchTaskSummary:
    total: int
    completed: int
    failed: int
    running: int
    pending: int

@dataclass
class BatchTask:
    batch_id: str
    workflow_id: str
    workflow_name: str
    target_devices: list[str]
    child_task_ids: list[str]
    aggregate_status: BatchStatus
    summary: BatchTaskSummary
    created_at: datetime
    updated_at: datetime
    concurrency: int = 5
    failure_strategy: Literal["continue", "stop_on_first", "stop_on_threshold"] = "continue"
    
    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "target_devices": self.target_devices,
            "child_task_ids": self.child_task_ids,
            "aggregate_status": self.aggregate_status,
            "summary": {
                "total": self.summary.total,
                "completed": self.summary.completed,
                "failed": self.summary.failed,
                "running": self.summary.running,
                "pending": self.summary.pending
            },
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "concurrency": self.concurrency
        }
```

**文件**：`device_tui/infrastructure/persistence/sqlite_batch_tasks.py`（新建）

```python
import sqlite3
import json
from datetime import datetime
from pathlib import Path

class SqliteBatchTaskRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_schema()
    
    def _ensure_schema(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS batch_tasks (
                    batch_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    workflow_name TEXT NOT NULL,
                    target_devices JSON NOT NULL,
                    child_task_ids JSON NOT NULL,
                    aggregate_status TEXT NOT NULL,
                    summary JSON NOT NULL,
                    concurrency INTEGER DEFAULT 5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 修改现有 tasks 表
            try:
                conn.execute("ALTER TABLE tasks ADD COLUMN batch_id TEXT")
            except sqlite3.OperationalError:
                pass  # 列已存在
    
    def save(self, batch: BatchTask) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO batch_tasks 
                (batch_id, workflow_id, workflow_name, target_devices, child_task_ids, 
                 aggregate_status, summary, concurrency, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                batch.batch_id,
                batch.workflow_id,
                batch.workflow_name,
                json.dumps(batch.target_devices),
                json.dumps(batch.child_task_ids),
                batch.aggregate_status,
                json.dumps(batch.summary.__dict__),
                batch.concurrency,
                batch.created_at.isoformat(),
                datetime.now().isoformat()
            ))
    
    def get(self, batch_id: str) -> BatchTask | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM batch_tasks WHERE batch_id = ?",
                (batch_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return BatchTask(
                batch_id=row["batch_id"],
                workflow_id=row["workflow_id"],
                workflow_name=row["workflow_name"],
                target_devices=json.loads(row["target_devices"]),
                child_task_ids=json.loads(row["child_task_ids"]),
                aggregate_status=row["aggregate_status"],
                summary=BatchTaskSummary(**json.loads(row["summary"])),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                concurrency=row["concurrency"]
            )
    
    def list(self, limit: int = 50) -> list[BatchTask]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM batch_tasks ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            
            return [self._row_to_batch(row) for row in rows]
```

#### Task 4.2：前端批量卡片组件（Day 10）

**文件**：`desktop/src/renderer/src/components/BatchTaskCard.vue`（新建）

```vue
<script setup lang="ts">
import { computed } from 'vue'
import { CheckCircle2, XCircle, Clock, ChevronDown, ChevronUp } from 'lucide-vue-next'

const props = defineProps<{
  batch: BatchTask
  expanded?: boolean
}>()

const emit = defineEmits<{
  toggle: []
  pause: []
  cancel: []
  retryFailed: []
  exportReport: []
}>()

const statusBadge = computed(() => {
  const map = {
    running: { label: '执行中', class: 'status-running' },
    completed: { label: '已完成', class: 'status-success' },
    partial_failure: { label: '部分失败', class: 'status-warning' },
    failed: { label: '失败', class: 'status-error' },
    cancelled: { label: '已取消', class: 'status-cancelled' }
  }
  return map[props.batch.aggregate_status] || { label: '未知', class: '' }
})
</script>

<template>
  <div class="batch-card">
    <div class="batch-header">
      <div class="batch-title">
        <h4>{{ batch.workflow_name }}</h4>
        <span :class="['status-badge', statusBadge.class]">
          {{ statusBadge.label }}
        </span>
      </div>
      <small class="batch-id">{{ batch.batch_id.slice(0, 8) }}</small>
    </div>
    
    <div class="batch-summary">
      <div class="stat success">
        <CheckCircle2 :size="16" />
        <span>成功：{{ batch.summary.completed }}</span>
      </div>
      <div class="stat error" v-if="batch.summary.failed > 0">
        <XCircle :size="16" />
        <span>失败：{{ batch.summary.failed }}</span>
      </div>
      <div class="stat running" v-if="batch.summary.running > 0">
        <Clock :size="16" />
        <span>进行中：{{ batch.summary.running }}</span>
      </div>
    </div>
    
    <div class="batch-actions">
      <button @click="emit('toggle')" class="toggle-btn">
        <ChevronDown v-if="!expanded" :size="14" />
        <ChevronUp v-else :size="14" />
        {{ expanded ? '收起' : '查看详情' }}
      </button>
      
      <button v-if="batch.aggregate_status === 'running'" @click="emit('pause')">
        暂停批次
      </button>
      
      <button v-if="batch.summary.failed > 0" @click="emit('retryFailed')" class="primary">
        重试失败
      </button>
      
      <button @click="emit('exportReport')">
        导出报告
      </button>
    </div>
    
    <div v-if="expanded" class="child-tasks">
      <slot name="child-tasks"></slot>
    </div>
  </div>
</template>

<style scoped>
.batch-card {
  padding: 16px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  background: rgba(30, 41, 59, 0.5);
  margin-bottom: 12px;
}

.batch-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 12px;
}

.batch-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.batch-title h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: #e2e8f0;
}

.status-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.status-running { background: rgba(59, 130, 246, 0.2); color: #93c5fd; }
.status-success { background: rgba(34, 197, 94, 0.2); color: #86efac; }
.status-warning { background: rgba(251, 191, 36, 0.2); color: #fcd34d; }
.status-error { background: rgba(239, 68, 68, 0.2); color: #fca5a5; }

.batch-summary {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}

.stat {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: rgba(226, 232, 240, 0.8);
}

.stat.success { color: #86efac; }
.stat.error { color: #fca5a5; }
.stat.running { color: #93c5fd; }

.batch-actions {
  display: flex;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}

.batch-actions button {
  padding: 6px 12px;
  font-size: 12px;
  border-radius: 4px;
  border: 1px solid rgba(148, 163, 184, 0.3);
  background: rgba(51, 65, 85, 0.5);
  color: #e2e8f0;
  cursor: pointer;
}

.batch-actions button:hover {
  background: rgba(51, 65, 85, 0.8);
}

.batch-actions button.primary {
  background: rgba(59, 130, 246, 0.3);
  border-color: rgba(59, 130, 246, 0.5);
}

.child-tasks {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}
</style>
```

---

## 验收清单

### Day 1 完成后
- [ ] 验证错误包含 fix_suggestion 和 doc_link
- [ ] 测试覆盖所有错误类型
- [ ] API 返回格式符合预期

### Day 6 完成后
- [ ] Vue Flow 画布正常显示
- [ ] 节点可拖拽布局
- [ ] 鼠标连线功能可用
- [ ] 自动布局按钮工作正常
- [ ] 所有现有功能未受影响

### Day 8 完成后
- [ ] 撤销/重做功能正常（至少10步历史）
- [ ] Ctrl+Z / Ctrl+Shift+Z 快捷键可用
- [ ] 性能无明显下降

### Day 10 完成后
- [ ] 批量任务在列表中聚合显示
- [ ] 可展开查看子任务
- [ ] 批量控制按钮功能正常
- [ ] 现有单任务仍可正常显示

### 整体验收
- [ ] 所有现有测试通过
- [ ] 新增测试覆盖率 >80%
- [ ] 性能指标达标（首次渲染 <100ms）
- [ ] 现有 workflows 可无损迁移

---

## 风险与应对

### 风险1：Vue Flow 集成困难
**概率**：低  
**应对**：Day 2 完成 POC 验证后再继续

### 风险2：性能回退
**概率**：中  
**应对**：每日进行性能测试，发现问题立即优化

### 风险3：撤销栈内存占用过高
**概率**：低  
**应对**：限制历史记录数量（maxHistory=50），使用浅拷贝优化

---

**负责人**：待分配  
**审核人**：待分配  
**开始日期**：待定
