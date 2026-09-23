# Workflow 配置组件重构

## 概述

这个目录包含了重构后的 workflow 步骤配置组件。原来 WorkflowLibrary.vue 中超过 170 行的配置模板代码被拆分为多个独立的、可维护的子组件。

## 组件结构

```
workflow-config/
├── types.ts                  # 共享类型定义
├── index.ts                  # 统一导出
├── BaseNodeConfig.vue        # 基础配置（步骤名称、上下游）
├── ScriptNodeConfig.vue      # 脚本执行节点配置
├── CommandNodeConfig.vue     # 设备命令节点配置
└── GenericNodeConfig.vue     # 通用节点配置
```

## 使用方法

### 1. 在 WorkflowLibrary.vue 中导入组件

```vue
<script setup lang="ts">
import {
  BaseNodeConfig,
  ScriptNodeConfig,
  CommandNodeConfig,
  GenericNodeConfig
} from './workflow-config'
import type { NodeItem } from './workflow-config'
</script>
```

### 2. 替换原有的步骤配置模板

将原来的 `<section class="workflow-properties">` 替换为：

```vue
<section v-if="selectedNode && !flowTestOpen && rightRailMode === 'step'" class="workflow-properties" aria-label="步骤设置">
  <!-- 基础配置 -->
  <BaseNodeConfig
    :node="selectedNode"
    :node-options="nodeOptions(selectedNode.id)"
    :predecessor-id="nodePredecessorId"
    :successor-id="nodeSuccessorId"
    :selected-action="selectedAction"
    @rename="renameNode"
    @update:predecessor-id="setNodePredecessor"
    @update:successor-id="setNodeSuccessor"
  />

  <!-- 节点特定配置 -->
  <ScriptNodeConfig
    v-if="selectedNode.action_id === 'script.run'"
    :node="selectedNode"
    :scripts="scripts"
    :command-references="commandReferences"
    :script-saving="scriptSaving"
    @update="(node) => selectedNode = node"
    @remove="removeNode"
    @test="testSelectedStep"
    @save-as-action="openCustomActionDialog"
    @open-script-studio="openScriptStudio"
    @save-script="saveNodeScriptResource"
  />

  <CommandNodeConfig
    v-else-if="selectedNode.action_id === 'device.command'"
    :node="selectedNode"
    :command-references="commandReferences"
    @update="(node) => selectedNode = node"
    @remove="removeNode"
    @test="testSelectedStep"
    @save-as-action="openCustomActionDialog"
  />

  <GenericNodeConfig
    v-else
    :node="selectedNode"
    :available-devices="availableDevices"
    @update="(node) => selectedNode = node"
    @remove="removeNode"
    @test="testSelectedStep"
  />

  <!-- 通用配置选项（重试、并行等） -->
  <CommonNodeOptions
    v-if="selectedNode.action_id !== 'variable.set'"
    :node="selectedNode"
    @update="(node) => selectedNode = node"
  />
</section>
```

## 优势

### 1. **职责清晰**
每个组件只负责一种节点类型的配置，代码更易理解和维护。

### 2. **减少复杂度**
- 主组件从 170+ 行配置模板减少到约 30 行
- 每个子组件独立维护，平均 100-200 行
- 减少了深层嵌套的 v-if 条件判断

### 3. **更好的复用**
- 共享类型定义避免重复
- 配置逻辑可以在多个组件间复用
- 更容易编写单元测试

### 4. **更好的性能**
- 只渲染当前需要的配置组件
- 减少了不必要的条件判断
- 更好的代码分割和懒加载

## 扩展指南

### 添加新的节点类型配置

1. 在 `workflow-config/` 目录创建新组件：

```vue
<!-- NewNodeConfig.vue -->
<script setup lang="ts">
import type { NodeConfigProps, NodeConfigEmits } from './types'

const props = defineProps<NodeConfigProps>()
const emit = defineEmits<NodeConfigEmits>()

function updateConfig(key: string, value: unknown): void {
  props.node.config[key] = value
  emit('update', props.node)
}
</script>

<template>
  <div class="new-node-config">
    <!-- 配置表单 -->
  </div>
</template>
```

2. 在 `index.ts` 中导出：

```typescript
export { default as NewNodeConfig } from './NewNodeConfig.vue'
```

3. 在主组件中使用：

```vue
<NewNodeConfig
  v-else-if="selectedNode.action_id === 'new.action'"
  :node="selectedNode"
  @update="(node) => selectedNode = node"
  @remove="removeNode"
/>
```

## 待完成的工作

目前还需要创建以下专门的配置组件：

- [ ] **LoopNodeConfig.vue** - 循环节点 (loop.for_each, loop.until)
- [ ] **ConditionNodeConfig.vue** - 条件判断节点 (utility.condition)
- [ ] **VariableNodeConfig.vue** - 变量设置节点 (variable.set)
- [ ] **WorkflowCallNodeConfig.vue** - 子流程调用节点 (workflow.call)
- [ ] **CommonNodeOptions.vue** - 通用选项（重试、并行、失败处理）

这些组件可以按需逐步实现，当前的 GenericNodeConfig 已经提供了基础支持。

## 样式说明

所有配置组件共享以下 CSS 变量：

- `--workflow-bg` - 背景色
- `--workflow-surface` - 表面色
- `--workflow-surface-muted` - 弱化表面色
- `--workflow-surface-input` - 输入框背景
- `--workflow-border` - 边框色
- `--workflow-text` - 主文本色
- `--workflow-muted` - 次要文本色

这些变量在 `styles.css` 中定义，支持明暗主题切换。
