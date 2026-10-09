# Workflow 节点输入引用设计

**状态**：设计中  
**日期**：2026-10-09  
**范围**：Workflow Studio 节点库、节点属性面板、Workflow 编译和运行时输入绑定

## 1. 背景

Workflow 运行时已经支持解析节点输入中的动态引用，例如：

- `${inputs.device_id}`：流程输入
- `${check.output}`：前序节点输出字段
- `${current_version}`：`variable.set` 创建的流程变量
- `${item}`、`${device_id}`：循环体局部值

但节点库的输入配置没有统一暴露这些能力。当前只有命令、脚本、文件上传、部分循环和变量节点提供引用选择器，很多节点仍然是固定值输入框。用户必须记忆引用语法，或者配置出一个运行时支持、编辑时却无法发现的绑定。

目前主要存在三层契约：

1. 后端 `ActionCatalog` 的输入 schema。
2. 前端各节点的专用配置组件。
3. Framework 编排器实际解析 `input_mapping` 的规则。

三层没有共同的“输入绑定”模型，导致节点之间的体验和校验不一致。

## 2. 目标

- 所有可在运行时变化的节点输入，都能选择流程输入、上游输出或流程变量。
- 引用候选按输入类型过滤，并显示来源、类型和可用范围。
- 固定配置和运行时输入明确区分，避免把结构配置误做成动态引用。
- 保持现有 `${...}` 语法和已发布 Workflow 的兼容性。
- 在发布前发现引用不存在、类型不兼容、作用域不可见等问题。
- 循环、条件和子 Workflow 的特殊输入也使用同一套概念。

## 3. 非目标

- 本阶段不引入新的表达式语言。
- 不允许通过引用动态改变节点类型、动作 ID、子 Workflow 版本或画布结构。
- 不把所有 JSON 配置都自动变成可引用字段；字段必须由节点契约声明。
- 不改变后端已有的任务编排和会话执行语义。

## 4. 术语和引用模型

### 4.1 输入绑定

节点输入的值有三种形式：

```text
Literal       固定值，例如 30、"flash:/image.cc"
Reference     完整引用，例如 ${inputs.timeout}
Template      文本中的引用，例如 "show ${inputs.interface}"
```

精确引用保留原始类型；模板引用最终转换为字符串。例如 `${inputs.count}` 可以得到数字，而 `"count=${inputs.count}"` 得到文本。

### 4.2 引用来源

| 来源 | 示例 | 可见范围 |
|---|---|---|
| 流程输入 | `${inputs.package_path}` | 整个流程 |
| 前序节点输出 | `${probe.software_version}` | 当前节点的上游依赖 |
| 流程变量 | `${version}` | 定义变量之后的后继节点 |
| 当前设备 | `${device.id}`、`${device_id}` | `device.for_each` 循环体 |
| 当前项 | `${item}`、`${index}` | `loop.for_each` / `loop.until` 循环体 |
| 运行上下文 | `${context.target.session_id}` | 仅允许契约明确声明的字段 |

引用选择器只展示当前节点可见的来源。不能引用同级后续节点，也不能引用条件节点本身的“输出”。

### 4.3 计算时机

| 输入类别 | 计算时机 | 示例 |
|---|---|---|
| 静态配置 | 编译 Workflow | `action_id`、`workflow_id`、`version`、分支目标 |
| 节点输入 | 节点执行前 | `command`、`timeout_seconds`、文件路径 |
| 循环子输入 | 每次迭代 | `action_inputs` 中的 `${item}`、`${device_id}` |
| 条件右值 | 分支评估时 | 规则右值引用、条件表达式中的输入 |

## 5. 节点输入契约

`ActionSpec.input_schema.properties` 中的字段增加运行时绑定元数据。示例：

```json
{
  "timeout_seconds": {
    "type": "number",
    "default": 30,
    "minimum": 0,
    "maximum": 86400,
    "description": "节点执行超时时间，0 表示不设上限",
    "binding": {
      "mode": "runtime",
      "reference_types": ["number", "integer"]
    }
  },
  "workflow_id": {
    "type": "string",
    "description": "要调用的已发布 Workflow",
    "binding": {
      "mode": "static"
    }
  }
}
```

### 5.1 `binding.mode`

- `static`：只能填写固定值或从目录选择。
- `runtime`：支持固定值和完整引用。
- `template`：支持固定文本和文本内嵌引用。
- `expression`：由专用表达式编辑器维护；仍使用同一引用上下文。
- `json`：对象/数组由结构化编辑器维护，内部叶子字段可绑定引用。

默认值为 `static`，避免旧节点被意外开放动态配置。

### 5.2 类型兼容

引用候选按 schema 类型过滤：

| 输入类型 | 允许来源类型 |
|---|---|
| `string` | `string`、`file`、`device`、`number`、`integer`、`boolean`（模板模式） |
| `file` | `file`、`file_path`、`string` |
| `device` | `device`、`string` |
| `number` | `number`、`integer` |
| `integer` | `integer` |
| `boolean` | `boolean` |
| `array` | `array`、`devices`、具有数组输出结构的字段 |
| `object` | `object`、完整节点输出 |

`devices` 是运行时数组，不能只按旧的字符串类型匹配。对象和数组需要保留 `items` / `properties`，才能继续校验嵌套引用。

## 6. 统一输入绑定控件

新增前端共享组件，例如 `ValueBindingField.vue`，由节点专用配置和通用 schema 配置共同使用。

### 6.1 控件行为

每个可绑定字段显示：

1. 当前模式：固定值 / 选择引用 / 模板或表达式。
2. 与字段类型匹配的输入控件。
3. 引用来源选择器，按“流程输入、步骤输出、流程变量、循环上下文”分组。
4. 当前绑定的原始表达式和类型提示。
5. 引用不可见或类型不匹配时的错误状态。

字段值仍写入现有 `node.config` / `input_mapping`，不改变已发布文档格式。必要时可在内部把固定配置和输入映射分开，保存时保持兼容的合并结果。

### 6.2 候选模型

前端统一使用：

```ts
type WorkflowReference = {
  reference: string
  label: string
  source: 'input' | 'node' | 'variable' | 'loop' | 'context'
  type: string
  path?: string
  scope: string
}
```

候选生成逻辑从 `useWorkflowNodeConfig.ts` 提取为独立 composable。它负责：

- 根据图依赖计算可见节点。
- 从 Action Catalog 输出 schema 生成字段路径。
- 展开对象属性和数组元素 schema。
- 添加流程输入、变量和循环局部值。
- 按 `reference_types` 过滤并标记兼容性。

## 7. 节点覆盖范围

### 7.1 第一优先级：直接补齐动态输入

| 节点 | 输入字段 | 绑定方式 |
|---|---|---|
| `file.download` | `source`、`destination` | runtime |
| `utility.wait` | `seconds` | runtime |
| `utility.confirm` | `prompt` | template；按钮文字可选 template |
| `device.connect` | `device_id`、`timeout_seconds` | runtime |
| `workflow.call` | 子 Workflow 的每个输入 | runtime |
| `result.save` | `value` | runtime；`key` 保持 static |

### 7.2 第二优先级：控制流和循环

| 节点 | 输入字段 | 设计要求 |
|---|---|---|
| `utility.condition` | 规则左值、右值 | 左值和右值都支持引用；右值按比较类型绑定 |
| `expression.evaluate` | `expression`、`values` | 表达式使用统一引用候选；JSON 改为结构化字段绑定 |
| `loop.for_each` | `items`、`action_inputs` | `items` 支持流程输入和上游数组；子动作参数按动作 schema 展开 |
| `device.for_each` | `devices`、`action_inputs` | 设备列表和每台设备的动作参数均可绑定 |
| `loop.until` | `condition`、`max_iterations`、`interval_seconds` | 停止条件支持上次结果、流程输入和变量；数字字段支持 runtime |

### 7.3 保持静态的输入

- `workflow.call.workflow_id`、`workflow.call.version`
- 循环 `action_id`、`body_mode`、`body_start`、`body_end`
- `variable.set.name`
- 条件分支目标和画布连接关系
- `device.info.fields` 的采集字段选择

这些字段改变流程结构或编译结果，不能使用普通运行时引用。

## 8. 条件节点设计

条件节点不能只把规则右值当作字符串。每条规则应保存：

```json
{
  "field": "probe.software_version",
  "field_binding": "reference",
  "operator": "equals",
  "value": "7.1.0",
  "value_binding": "literal",
  "value_type": "string"
}
```

引用右值示例：

```json
{
  "field": "probe.count",
  "field_binding": "reference",
  "operator": "greater_than",
  "value": "${inputs.minimum_count}",
  "value_binding": "reference",
  "value_type": "integer"
}
```

编译器在生成 `run_if` 前解析引用；运行时仍使用现有安全的规则比较器，不执行任意 Python 表达式。旧格式中没有 `*_binding` 的规则按 `field` 为上游字段、`value` 为字面量处理。

## 9. 循环子输入设计

当前 `action_inputs` 是 JSON 文本框，导致循环节点最难配置。改为根据所选 `action_id` 读取 Action Catalog：

1. 展示子动作的输入字段。
2. 每个字段使用 `ValueBindingField`。
3. 自动提供当前循环上下文：`${item}`、`${index}`；设备循环额外提供 `${device}`、`${device_id}`。
4. 保存时仍生成现有 `action_inputs` 对象。

这样既保留后端循环执行器的输入格式，也避免用户手写 JSON 和引用语法。

## 10. 校验规则

发布前和保存草稿时都应检查：

- 引用语法完整且只包含允许的路径字符。
- 来源节点位于当前节点的上游可见范围内。
- 引用字段存在于输出 schema 中。
- 引用类型与输入 `reference_types` 兼容。
- `devices`、数组和对象的结构匹配。
- 循环局部变量只在循环体内使用。
- 静态字段不接受 `${...}`。
- 条件比较的左右值类型兼容。

错误信息应包含节点名、输入字段、原始引用和修复建议，例如：

```text
步骤“上传文件”的“设备目标路径”引用 ${probe.version} 类型为 string，当前字段需要 file_path 或 string。
```

## 11. 兼容和迁移

- 现有 `${...}` 字符串继续有效。
- 旧节点没有 `binding` 元数据时按 `static` 处理，但专用节点可提供兼容默认值。
- 旧的 `input_mapping` 与 `config` 合并规则保持不变。
- `device.for_each.devices` 的旧数组和 `${input.devices}` 写法继续支持，并统一规范为 `${inputs.devices}`。
- `workflow.call` 中已经手写的输入引用不自动改写，只在编辑时识别并显示为“引用”模式。
- 发布版本的输入契约不可变；新字段只影响草稿和后续发布版本。

## 12. 实施阶段

### 阶段一：基础契约和共享控件

- 扩展 `ActionSpec` 字段元数据和数组/对象 schema。
- 提取统一的引用候选生成器。
- 新增 `ValueBindingField.vue`。
- 先接入 `file.download`、`utility.wait`、`utility.confirm`、`device.connect`。
- 增加输入引用的前端和后端契约测试。

### 阶段二：子 Workflow、条件和循环

- 接入 `workflow.call` 的子流程输入映射。
- 重做条件规则编辑器的左右值绑定。
- 把循环 `action_inputs` JSON 改为 schema 驱动表单。
- 增加循环局部上下文和嵌套引用测试。

### 阶段三：统一校验和体验完善

- 将引用解析、可见性和类型检查收敛到共享校验路径。
- 增加嵌套对象字段和数组元素提示。
- 增加引用自动补全、搜索和“复制引用”。
- 对已有 Workflow 做一次兼容性扫描，报告不可解析的旧引用。

## 13. 验收标准

### 功能

- 所有标记为 `runtime` 或 `template` 的输入都有引用选择器。
- 引用选择器只显示当前作用域和类型兼容的来源。
- 循环子动作不需要手写 JSON 即可绑定 `${item}`、`${device_id}` 和上游输出。
- 条件节点可以比较流程输入或上游字段与固定值/另一个引用。
- 子 Workflow 输入可以选择流程输入或上游输出。

### 正确性

- 发布前拒绝未知字段、越界作用域、类型不兼容和静态字段引用。
- 精确引用保留数字、布尔、数组和对象类型。
- 模板引用只产生字符串，不改变现有命令和提示文本语义。
- 旧版 Workflow 无需手工迁移即可继续发布和执行。

### 测试

- 后端覆盖引用解析、嵌套对象、数组、循环局部变量和条件右值。
- 前端覆盖每个第一优先级节点的“固定值 → 引用 → 清除引用”流程。
- 至少覆盖一个串口/网络设备流程，确认动态 `device_id`、路径和超时输入不会改变原有会话选择语义。
- 运行 Python 专项测试、`npm run typecheck` 和 `npm run build`。

## 14. 相关代码

- `device_tui/application/workflow_studio/catalog.py`
- `device_tui/application/workflow_studio/validation.py`
- `device_tui/interfaces/desktop_api/routers/workflow_definitions.py`
- `device_tui/framework/orchestrator.py`
- `desktop/src/renderer/src/composables/useWorkflowNodeConfig.ts`
- `desktop/src/renderer/src/components/workflow-config/GenericNodeConfig.vue`
- `desktop/src/renderer/src/components/workflow-config/AdvancedNodeConfig.vue`
- `desktop/src/renderer/src/components/workflow-config/CommandNodeConfig.vue`
- `desktop/src/renderer/src/components/workflow-config/ScriptNodeConfig.vue`
