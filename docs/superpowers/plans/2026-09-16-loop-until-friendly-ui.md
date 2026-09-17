# Loop.Until 友好表单式配置界面

**日期**: 2026-09-16  
**状态**: 已完成  
**影响范围**: Desktop UI (WorkflowLibrary.vue)

## 问题

原有的 `loop.until` 配置界面要求用户：
1. 手动编写停止条件表达式（如 `result.status == 'succeeded'`）
2. 用 JSON 格式填写动作参数（`action_inputs`）
3. 理解内部数据结构（`result.output`、`result.status`）

这对非技术用户极不友好，用户不知道该填什么，也不清楚支持哪些字段和操作符。

## 解决方案

将 JSON/表达式配置改为表单式配置：

### 配置项

1. **循环执行什么？** - 下拉选择动作类型
2. **命令内容** - 如果选择"执行命令"，显示命令输入框
3. **何时停止？** - 下拉选择：
   - 达到最大次数
   - 输出包含文本
   - 输出匹配正则
   - 命令成功
   - 命令失败
4. **目标文本/正则** - 根据停止条件显示对应输入框
5. **最多执行** - 数字输入（次数）
6. **每次间隔** - 数字输入（秒）

### 实现细节

#### 前端（WorkflowLibrary.vue）

添加了两个计算属性来管理停止条件：

```typescript
// 停止模式（达到最大次数/输出包含/正则/成功/失败）
const loopUntilStopMode = computed<'max_iterations' | 'output_contains' | 'output_regex' | 'success' | 'failure'>({
  get: () => {
    // 从 condition 表达式解析当前模式
    const condition = String(selectedNode.value.config.condition || '')
    if (condition === 'True' || condition === 'true') return 'max_iterations'
    if (condition.includes("'succeeded'")) return 'success'
    if (condition.includes("'failed'")) return 'failure'
    if (condition.includes('.match(')) return 'output_regex'
    return 'output_contains'
  },
  set: (mode) => {
    // 根据模式生成对应的条件表达式
    if (mode === 'max_iterations') selectedNode.value.config.condition = 'True'
    else if (mode === 'success') selectedNode.value.config.condition = "result.status == 'succeeded'"
    else if (mode === 'failure') selectedNode.value.config.condition = "result.status == 'failed'"
    else if (mode === 'output_contains') selectedNode.value.config.condition = `'${pattern}' in result.output`
    // ...
  }
})

// 匹配模式（输出包含文本/正则表达式时的目标内容）
const loopUntilPattern = computed<string>({
  get: () => {
    // 从条件表达式中提取模式字符串
    const condition = String(selectedNode.value.config.condition || '')
    const match = condition.match(/'([^']+)'\s+in\s+result\.output/)
    return match ? match[1] : ''
  },
  set: (pattern) => {
    // 更新条件表达式中的模式
    selectedNode.value.config.condition = `'${pattern}' in result.output`
  }
})
```

#### 界面模板

```vue
<template v-if="selectedNode.action_id === 'loop.until'">
  <label>循环执行什么？
    <select v-model="selectedNode.config.action_id">
      <option v-for="action in loopChildActions" :value="action.id">
        {{ action.label }}
      </option>
    </select>
  </label>
  
  <div v-if="selectedNode.config.action_id === 'device.command'" class="workflow-command-field">
    <div class="workflow-command-label-row"><span>命令内容</span></div>
    <textarea :value="..." @input="..." />
  </div>
  
  <label>何时停止？
    <select v-model="loopUntilStopMode">
      <option value="max_iterations">达到最大次数</option>
      <option value="output_contains">输出包含文本</option>
      <option value="output_regex">输出匹配正则</option>
      <option value="success">命令成功</option>
      <option value="failure">命令失败</option>
    </select>
  </label>
  
  <label v-if="loopUntilStopMode === 'output_contains' || loopUntilStopMode === 'output_regex'">
    {{ loopUntilStopMode === 'output_contains' ? '目标文本' : '正则表达式' }}
    <input v-model="loopUntilPattern" :placeholder="..." />
  </label>
  
  <label>最多执行
    <input v-model.number="selectedNode.config.max_iterations" type="number" min="1" max="100" /> 次
  </label>
  
  <label>每次间隔
    <input v-model.number="selectedNode.config.interval_seconds" type="number" min="0" step="0.1" /> 秒
  </label>
  
  <small class="field-hint">
    {{ loopUntilStopMode === 'max_iterations' 
       ? '每轮执行一次动作，达到最大次数后停止。' 
       : '每轮执行一次动作并检查停止条件，满足条件或达到最大次数时停止。' }}
  </small>
</template>
```

#### 默认值调整

```typescript
// defaultConfig() 函数
if (actionId === 'loop.until') {
  return {
    action_id: 'device.command',
    action_inputs: { command: 'display version' },
    condition: "True",  // 默认"达到最大次数"
    max_iterations: 10,
    interval_seconds: 2
  }
}
```

### 生成的条件表达式

| 用户选择 | 生成的表达式 |
|---------|------------|
| 达到最大次数 | `True` |
| 输出包含文本: "READY" | `'READY' in result.output` |
| 输出匹配正则: "V\\d+R\\d+" | `'V\\d+R\\d+' in result.output` |
| 命令成功 | `result.status == 'succeeded'` |
| 命令失败 | `result.status == 'failed'` |

### 后端兼容性

后端验证逻辑无需修改，因为：
1. 生成的表达式与原有格式完全一致
2. 验证器已支持这些表达式模式
3. 运行时引擎已支持这些条件判断

## 测试

新增测试文件 `tests/test_loop_until_friendly_config.py`，验证：

1. ✅ "输出包含文本" 模式生成有效条件
2. ✅ "输出匹配正则" 模式生成有效条件
3. ✅ "命令成功" 模式生成有效条件
4. ✅ "命令失败" 模式生成有效条件
5. ✅ 空模式字符串仍然有效

所有测试通过：
```
tests/test_loop_until_friendly_config.py::test_output_contains_condition_is_valid PASSED
tests/test_loop_until_friendly_config.py::test_output_regex_condition_is_valid PASSED
tests/test_loop_until_friendly_config.py::test_command_success_condition_is_valid PASSED
tests/test_loop_until_friendly_config.py::test_command_failure_condition_is_valid PASSED
tests/test_loop_until_friendly_config.py::test_empty_pattern_is_still_valid PASSED
```

## 用户体验提升

### 之前
```
循环动作: [下拉选择]
停止条件: [多行文本框 - 用户需要手写 result.status == 'succeeded']
最大循环次数: [10]
每轮间隔（秒）: [2]
循环动作参数 JSON: [{"command": "display version"}]
```

用户需要：
- 了解 `result` 对象结构
- 知道 `status` 可能的值
- 熟悉表达式语法
- 用 JSON 格式填参数

### 之后
```
循环执行什么？: [执行命令 ▼]
命令内容: [display version]
何时停止？: [达到最大次数 ▼]
最多执行: [10] 次
每次间隔: [2] 秒
```

或者选择基于输出的停止条件：
```
循环执行什么？: [执行命令 ▼]
命令内容: [display version]
何时停止？: [输出包含文本 ▼]
目标文本: [READY]
最多执行: [10] 次
每次间隔: [2] 秒
```

用户只需：
- 选择要做什么
- 填写命令内容
- 选择停止条件类型（包括"达到最大次数"作为最简单的选项）
- 根据停止条件填写期望的文本/模式（如果需要）
- 设置次数和间隔

## 向后兼容

- 已有的 workflow 配置完全兼容
- 表单界面会从现有表达式中解析并显示对应的选项
- 不影响 workflow 的导入/导出/执行

## 相关文件

- `desktop/src/renderer/src/components/WorkflowLibrary.vue` - UI 实现
- `tests/test_loop_until_friendly_config.py` - 新增测试
- `tests/test_workflow_studio_validation.py` - 现有验证测试（全部通过）

## 进一步改进建议

1. 为"输出匹配正则"模式添加正则表达式验证和语法提示
2. 提供常用模式的快捷选择（如"包含错误"、"包含成功"）
3. 支持更多停止条件（如"达到特定时间"、"输出为空"）
4. 为 `loop.for_each` 也提供类似的友好配置界面
