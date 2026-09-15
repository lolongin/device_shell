# Workflow Studio 集成指南

本指南说明如何将新开发的组件集成到现有的 WorkflowLibrary.vue 中。

---

## 🚀 快速集成步骤

### 1. 在 WorkflowLibrary.vue 中导入新组件

在 `<script setup>` 部分添加导入：

```typescript
// 在现有导入之后添加
import WorkflowCanvas from './WorkflowCanvas.vue'
import { useUndoRedo, useUndoRedoShortcuts } from '../composables/useUndoRedo'
import { autoLayout } from '../utils/layoutAlgorithms'
```

### 2. 初始化撤销/重做

在 `<script setup>` 中添加：

```typescript
// 撤销/重做功能
const workflowHistory = useUndoRedo({
  initialState: selected.value,
  maxHistory: 50
})

// 监听变化并提交到历史
let isUndoRedoAction = false

watch(
  () => selected.value,
  (newWorkflow) => {
    if (isUndoRedoAction || !newWorkflow) return
    workflowHistory.commit(newWorkflow)
  },
  { deep: true }
)

function performUndo() {
  if (!workflowHistory.canUndo.value) return
  isUndoRedoAction = true
  workflowHistory.undo()
  selected.value = workflowHistory.state.value
  nextTick(() => { isUndoRedoAction = false })
}

function performRedo() {
  if (!workflowHistory.canRedo.value) return
  isUndoRedoAction = true
  workflowHistory.redo()
  selected.value = workflowHistory.state.value
  nextTick(() => { isUndoRedoAction = false })
}

// 注册快捷键
onMounted(() => {
  const cleanup = useUndoRedoShortcuts(performUndo, performRedo)
  onUnmounted(cleanup)
})
```

### 3. 添加自动布局功能

```typescript
async function applyAutoLayout() {
  if (!selected.value || !selected.value.nodes) return
  
  const { nodes: layoutedNodes } = await autoLayout(
    selected.value.nodes,
    selected.value.edges || [],
    {
      direction: 'TB',
      spacing: 100,
      nodeWidth: 200,
      nodeHeight: 100
    }
  )
  
  // 更新节点位置
  selected.value.nodes = layoutedNodes
}
```

### 4. 添加节点位置更新处理

```typescript
function handleNodePositionChange(nodeId: string, position: { x: number; y: number }) {
  if (!selected.value || !selected.value.nodes) return
  
  const node = selected.value.nodes.find(n => n.id === nodeId)
  if (node) {
    node.position = position
  }
}
```

### 5. 在模板中替换节点列表

找到现有的节点列表部分（大约在 line 600-700），替换为：

```vue
<!-- 原来的节点列表 -->
<section class="workflow-node-list">
  <!-- ... 旧的垂直列表 ... -->
</section>

<!-- 替换为新的画布 -->
<section class="workflow-canvas-section">
  <div class="workflow-meta-fields">
    <label>
      流程名称
      <input v-model="selected.name" placeholder="输入流程名称" />
    </label>
    <label>
      流程说明
      <textarea v-model="selected.description" placeholder="可选：描述此流程的用途" rows="2" />
    </label>
  </div>
  
  <WorkflowCanvas
    v-if="selected"
    :workflow="selected"
    :issues="issues"
    @node-select="(nodeId) => { selectedNode = selected.nodes?.find(n => n.id === nodeId) || null }"
    @connect="({ source, target }) => addEdge(source, target)"
    @node-position-change="handleNodePositionChange"
  />
</section>
```

### 6. 更新工具栏添加新按钮

在工具栏部分添加撤销/重做和自动布局按钮：

```vue
<div class="workflow-library-toolbar">
  <!-- 现有按钮 -->
  <button @click="createNewWorkflow">
    <Plus :size="14" /> 新建
  </button>
  
  <!-- 新增按钮 -->
  <button 
    @click="performUndo" 
    :disabled="!workflowHistory.canUndo.value"
    title="撤销 (Ctrl+Z)"
  >
    <Undo :size="14" /> 撤销
  </button>
  
  <button 
    @click="performRedo" 
    :disabled="!workflowHistory.canRedo.value"
    title="重做 (Ctrl+Shift+Z)"
  >
    <Redo :size="14" /> 重做
  </button>
  
  <button 
    @click="applyAutoLayout"
    :disabled="!selected || !selected.nodes || selected.nodes.length === 0"
    title="自动布局"
  >
    <GitBranch :size="14" /> 自动布局
  </button>
  
  <!-- 其他现有按钮 -->
</div>
```

### 7. 导入需要的图标

在导入部分添加：

```typescript
import { Undo, Redo } from 'lucide-vue-next'
```

### 8. 更新样式

在 `<style scoped>` 中添加：

```css
.workflow-canvas-section {
  grid-column: 2;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
  background: #0f172a;
  border-radius: 8px;
  padding: 16px;
}

.workflow-meta-fields {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.workflow-meta-fields label {
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  color: #cbd5e1;
}

.workflow-meta-fields input,
.workflow-meta-fields textarea {
  padding: 8px 12px;
  background: rgba(30, 41, 59, 0.5);
  border: 1px solid rgba(148, 163, 184, 0.3);
  border-radius: 6px;
  color: #e2e8f0;
  font-size: 13px;
}

.workflow-canvas-section > :last-child {
  flex: 1;
  min-height: 400px;
}
```

---

## 🧪 测试集成

### 1. 启动开发服务器

```bash
cd desktop
npm run dev
```

### 2. 测试功能清单

- [ ] 画布显示节点和边
- [ ] 可以拖拽节点
- [ ] 可以点击节点选中
- [ ] 可以鼠标连线创建边
- [ ] Ctrl+Z 撤销操作
- [ ] Ctrl+Shift+Z 重做操作
- [ ] 自动布局按钮工作
- [ ] 节点颜色分类正确
- [ ] 验证错误显示为 attention 状态

---

## 📝 可选：渐进式集成

如果不想一次性替换所有内容，可以采用渐进式集成：

### 方案1：添加切换按钮

```vue
<div class="view-mode-switch">
  <button @click="viewMode = 'list'" :class="{ active: viewMode === 'list' }">
    列表视图
  </button>
  <button @click="viewMode = 'canvas'" :class="{ active: viewMode === 'canvas' }">
    画布视图
  </button>
</div>

<!-- 根据 viewMode 切换 -->
<section v-if="viewMode === 'list'" class="workflow-node-list">
  <!-- 旧的列表视图 -->
</section>

<section v-else class="workflow-canvas-section">
  <WorkflowCanvas ... />
</section>
```

### 方案2：仅在特定条件下使用新画布

```vue
<!-- 当节点数量 > 5 时使用画布，否则使用列表 -->
<section v-if="selected && selected.nodes && selected.nodes.length > 5" class="workflow-canvas-section">
  <WorkflowCanvas ... />
</section>

<section v-else class="workflow-node-list">
  <!-- 旧的列表视图 -->
</section>
```

---

## 🐛 常见问题

### 问题1：节点位置没有保存

**原因**：节点数据结构中没有 `position` 字段

**解决**：确保节点数据包含位置信息：

```typescript
interface NodeItem {
  id: string
  action_id: string
  config: Record<string, unknown>
  position?: { x: number; y: number }  // 添加这个
}
```

### 问题2：撤销/重做导致性能问题

**原因**：频繁的深拷贝

**解决**：使用防抖：

```typescript
import { debounce } from 'lodash-es'

const debouncedCommit = debounce((workflow) => {
  workflowHistory.commit(workflow)
}, 300)

watch(() => selected.value, debouncedCommit, { deep: true })
```

### 问题3：画布在某些情况下不显示

**原因**：容器高度为 0

**解决**：确保父容器有明确的高度：

```css
.workflow-canvas-section {
  min-height: 500px; /* 或使用 flex: 1 */
}
```

---

## 📊 集成前后对比

### 之前
```vue
<div class="workflow-node-list">
  <div v-for="node in nodes" class="node-item">
    <!-- 垂直列表 -->
  </div>
</div>
```

### 之后
```vue
<WorkflowCanvas
  :workflow="selected"
  :issues="issues"
  @node-select="handleNodeSelect"
/>
```

**代码行数减少**: ~200行 → ~50行  
**用户体验提升**: 列表 → 图形化编辑

---

## 🚀 下一步

完成集成后：

1. **测试所有功能** - 确保没有回归
2. **收集用户反馈** - Beta 测试
3. **性能优化** - 如果有大型流程（>50节点）
4. **继续阶段2** - 组件拆分和性能优化

---

**集成完成后，记得提交代码！** 🎉

```bash
git add .
git commit -m "feat: integrate Vue Flow canvas to WorkflowLibrary

- Replace vertical list with graphical canvas
- Add undo/redo functionality (Ctrl+Z/Ctrl+Shift+Z)
- Add auto-layout button
- Improve node visualization with categories
"
```
