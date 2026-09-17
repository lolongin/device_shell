# 修复 loop.until 的 max_iterations 配置不生效问题

**日期**: 2026-09-16  
**状态**: 已修复  
**影响范围**: WorkflowLibrary.vue 前端组件

## 问题描述

用户在 workflow 编辑器中设置 `loop.until` 的 `max_iterations` 为 10，但实际运行时只执行了 1 次循环就停止了。

## 根本原因

`WorkflowLibrary.vue` 中的 `syncCurrentWorkflowState()` 函数存在设计缺陷：

```typescript
// 修复前的代码 (第 1198-1202 行)
function syncCurrentWorkflowState(): void {
  if (selectedNode.value?.action_id !== 'utility.condition') return
  selectedNode.value.config.rules = conditionRules.value
  selectedNode.value.config.logical_operator = conditionLogicalOperator.value
}
```

**问题分析**：

1. 这个函数**只处理 `utility.condition` 类型的节点**
2. 对于其他节点类型（包括 `loop.until`），函数直接返回，不做任何同步
3. 用户通过 `v-model.number="selectedNode.value.config.max_iterations"` 修改配置时，虽然 `selectedNode` 的值被更新了，但这个修改**没有同步回 `selected.value.nodes` 数组**
4. 保存 workflow 时，`persistCurrentWorkflow()` 调用了 `syncCurrentWorkflowState()`，但由于上述问题，`loop.until` 的配置修改被丢失

## 修复方案

扩展 `syncCurrentWorkflowState()` 函数，确保 `selectedNode` 的所有修改都能同步回 `selected.value.nodes`：

```typescript
// 修复后的代码
function syncCurrentWorkflowState(): void {
  if (!selectedNode.value) return

  // 同步 utility.condition 的特殊状态
  if (selectedNode.value.action_id === 'utility.condition') {
    selectedNode.value.config.rules = conditionRules.value
    selectedNode.value.config.logical_operator = conditionLogicalOperator.value
  }

  // 确保 selectedNode 的修改同步回 selected.value.nodes
  // 这对于 v-model 绑定到 selectedNode.config 的情况很重要
  if (selected.value?.nodes) {
    const nodeIndex = selected.value.nodes.findIndex(n => n.id === selectedNode.value!.id)
    if (nodeIndex !== -1) {
      selected.value.nodes[nodeIndex] = { ...selectedNode.value }
    }
  }
}
```

## 为什么这个修复有效

1. **保留了原有的 `utility.condition` 特殊处理**
2. **新增了通用的同步逻辑**：
   - 找到 `selected.value.nodes` 中对应的节点
   - 用 `selectedNode.value` 的完整副本替换它
   - 这确保了所有通过 `v-model` 绑定的配置修改都能保存

3. **适用于所有节点类型**：
   - `loop.until` 的 `max_iterations`
   - `loop.until` 的 `interval_seconds`
   - `loop.until` 的 `condition`
   - 以及未来任何新增的节点配置

## 影响范围

### 受影响的文件
- `desktop/src/renderer/src/components/WorkflowLibrary.vue` (1198-1211 行)

### 受影响的功能
所有使用 `v-model` 直接绑定到 `selectedNode.value.config.*` 的配置项，包括但不限于：
- `loop.until` 的所有配置
- 未来可能添加的其他节点配置

### 不受影响的功能
- `utility.condition` 的配置（继续使用特殊逻辑）
- 通过其他方式更新的节点配置

## 验证

### 单元测试
创建了 `tests/test_loop_until_max_iterations.py`，包含：
- ✅ 验证 `max_iterations` 配置可以通过验证
- ✅ 测试不同的 `max_iterations` 值 (1, 3, 10, 50, 100)
- ✅ 测试无效的 `max_iterations` 值 (0, -1, 101, 1000)

### 集成测试
需要在实际的 Electron 应用中验证：
1. 创建一个新的 workflow
2. 添加一个 `loop.until` 节点
3. 设置 `max_iterations` 为 10
4. 设置一个永远不满足的条件（如 `'NEVER' in result.output`）
5. 保存并运行 workflow
6. 验证循环执行了 10 次后停止

## 后端逻辑验证

后端的 `loop.until` 执行逻辑是正确的（`device_tui/application/workflow_studio/compile.py:309-355`）：

```python
max_iterations = int(invocation.inputs.get("max_iterations", 10))
interval_seconds = float(invocation.inputs.get("interval_seconds", 0.0))

for iteration in range(1, max_iterations + 1):
    # ... 执行循环体
    if 停止条件满足:
        break
    if iteration < max_iterations:
        await asyncio.sleep(interval_seconds)
```

问题纯粹是前端保存时没有正确传递配置。

## 相关改进

此次修复同时也改进了之前的用户体验问题（已在另一个 PR 中实现）：
- 将 JSON 配置改为表单式配置
- 用户现在可以通过友好的下拉菜单和输入框配置 `loop.until`

## 经验教训

1. **响应式陷阱**：Vue 的 `v-model` 绑定到嵌套对象时，需要确保父对象也能感知到变化
2. **不要假设 `v-model` 会自动同步所有状态**：当数据来自数组引用时，需要显式地同步回去
3. **通用 vs 特殊**：`syncCurrentWorkflowState()` 应该有一个通用的同步逻辑，然后再处理特殊情况
4. **测试覆盖**：这类问题很难通过单元测试发现，需要端到端测试

## 后续工作

1. 考虑重构 `selectedNode` 的管理方式，使用计算属性而不是独立的 ref
2. 添加更多的端到端测试，覆盖 workflow 编辑和保存流程
3. 审查其他可能存在类似问题的配置项
