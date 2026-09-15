# Device TUI - 领域模型 (Domain Model)

> 网络设备运维自动化工具的核心概念定义

## 核心域 (Core Domain)

### Process（流程）

用户在 Studio 中设计的**自动化操作序列**。

**概念层次**：
- **Process Blueprint**（流程蓝图）：设计时的可视化流程图，包含节点和连接关系
- **Published Process**（已发布流程）：经过验证和版本化的流程定义，可重复执行
- **Process Execution**（流程执行）：针对具体设备和参数的一次运行实例

**在代码中的映射**：
```
Process Blueprint    → WorkflowDraft       (Studio 层)
Published Process    → WorkflowVersion     (Studio 层)
Process Execution    → Task + TaskPlan     (Runtime 层)
```

**关键区别**：
- 用户创建的是 **Process**（业务术语）
- 技术实现通过 **Workflow**（技术术语）
- 运行时体现为 **Task**（执行术语）

---

### Node（节点）

Process 中的**单个操作单元**，在 Studio 画布上表现为一个可视化元素。

**节点类别**：

#### Execution Node（执行节点）
在目标设备上实际执行的操作。

- `device.command` - 执行单条命令
- `device.reboot` - 重启设备
- `file.upload` / `file.download` - 文件传输
- `device.info` - 采集设备信息

#### Control Node（控制节点）
决定流程走向的逻辑节点，**编译时被消除**（转换为执行计划的元数据）。

- `utility.condition` - 条件分支（if/else）
- `loop.for_each` - 循环遍历

#### Coordination Node（协调节点）
需要外部协调的节点，**运行时阻塞等待**。

- `utility.confirm` - 人工审批关卡
- `utility.wait` - 定时等待

**重要约束**：
- Control Node 在 dry-run 时显示为"将在运行时评估"
- Control Node 不能嵌套（例如：loop 内不能包含 condition）
- Coordination Node 会创建 checkpoint，支持暂停/恢复

---

### Edge（连接）

节点之间的**依赖关系和数据流**。

**属性**：
- `source`: 源节点 ID
- `target`: 目标节点 ID
- `condition`: 条件表达式（可选，用于条件分支）

**语义**：
- "target 在 source 完成后执行"
- 如果 source 失败且无 recovery，target 不执行
- 多个 edge 指向同一 target → 需要所有 source 完成（AND 依赖）

**特殊情况**：
- Condition Node 的 edge 必须标记 `condition: "true" | "false"`
- 没有 incoming edge 的节点是**入口节点**（只能有一个）
- 没有 outgoing edge 的节点是**出口节点**（可以有多个）

---

### Device（设备）

运维操作的**目标实体**，通常是网络设备（路由器、交换机）。

**属性**：
- `device_id`: 唯一标识
- `name`: 人类可读名称
- `address`: IP 地址或主机名
- `software_version`: 软件版本（用于条件判断）
- `status`: 设备状态（online/offline/unknown）

**设备来源**：
- **Imported Source**: 从外部系统导入（Excel、数据库、API）
- **Sample Source**: 内置测试设备
- **Plugin Source**: 通过插件连接企业设备管理系统

**约束**：同一时刻只能有一个活跃的 Device Source。

---

### Session（会话）

与设备的**持久连接通道**，用于执行命令和传输文件。

**协议**：
- SSH
- Telnet
- Serial（串口）
- Simulated（模拟，用于测试）

**生命周期**：
```
disconnected → connecting → connected → disconnected
                  ↓              ↓
               failed        idle_timeout
```

**会话复用**：
- 批量任务优先复用已有 connected session
- 避免重复建立连接，降低设备负载
- Session 状态由 Backend Session Hub 管理

---

## 支撑域 (Supporting Domains)

### Batch Task（批量任务）

针对**多台设备**执行同一 Process 的运维操作。

**关键属性**：
- `batch_id`: 批次唯一标识
- `target_devices`: 目标设备列表（1-N 台）
- `child_tasks`: 每台设备的独立 Task
- `aggregate_status`: 聚合状态

**状态计算**：
```
all completed                    → "completed"
any failed + all others done     → "partial_failure"
any running                      → "running"
```

**批量操作**：
- **Pause Batch**: 暂停所有未完成的 child tasks
- **Cancel Batch**: 取消整个批次
- **Retry Failed**: 只重试失败的设备

**UI 呈现**：
```
批量升级任务 #abc123
├─ 成功：15台  [查看列表]
├─ 失败：3台   [查看错误] [重试]
└─ 进行中：2台 [实时日志]
```

---

### Task（任务）

一次 Process 的**具体执行实例**，针对单台设备。

**属性**：
- `task_id`: 唯一标识
- `workflow_id`: 关联的 Process（blueprint）
- `device_id`: 目标设备
- `status`: 执行状态
- `context`: 运行时输入（参数、变量）
- `outputs`: 执行结果输出

**状态机**：
```
pending → running → completed
            ↓           ↓
        paused      failed
            ↓           ↓
      waiting_decision  ←─┘
```

**Checkpoint 机制**：
- 每个节点完成后创建 checkpoint
- 支持从任意 checkpoint 恢复执行
- 进程重启后自动进入 `waiting_reconcile` 状态

---

### Template（模板）

预制的 Process Blueprint，带有**参数化配置**。

**用途**：
- 快速创建常用流程（如"设备健康检查"、"固件升级"）
- 团队共享最佳实践
- 降低新用户学习成本

**结构**：
```typescript
interface Template {
  id: string
  name: string
  category: string  // "运维" | "诊断" | "配置"
  blueprint: ProcessBlueprint
  parameters: TemplateParameter[]  // 用户需要填写的参数
  documentation: string  // 使用说明
}

interface TemplateParameter {
  name: string
  type: "string" | "device_selector" | "file_path"
  default?: any
  description: string
}
```

**实例化**：
1. 用户选择 Template
2. 填写 Parameters（如：目标版本号、文件路径）
3. 系统生成 Process Blueprint，替换占位符
4. 用户可以进一步编辑（可选）

---

### Approval Gate（审批关卡）

流程中的**预期决策点**，需要人工确认才能继续。

**与 Decision Point 的区别**：

| 特性 | Approval Gate | Decision Point |
|------|---------------|----------------|
| 定义时机 | 设计时（用户明确添加节点） | 运行时（系统遇到错误动态生成） |
| 触发原因 | 业务需要（如：重启前确认） | 技术异常（如：连接失败） |
| 选项数量 | 固定（确认/取消） | 动态（根据错误类型） |
| 批量行为 | 首次确认可应用到全部 | 可选择影响范围（单设备/剩余/全部） |

**配置示例**：
```typescript
{
  node_id: "confirm_reboot",
  action_id: "utility.confirm",
  config: {
    prompt: "设备 ${device.name} 即将重启，当前版本 ${device.software_version}",
    approve_label: "确认重启",
    reject_label: "跳过此设备",
    batch_behavior: "ask_once"  // "ask_once" | "ask_each"
  }
}
```

---

### Recovery Decision（恢复决策）

运行时遇到**意外错误**时，系统生成的决策点。

**触发条件**：
- Action 执行失败且无法自动 reconcile
- 超时或连接中断
- 前置条件不满足

**选项生成逻辑**：
```python
# 伪代码
if error_type == "connection_timeout":
    options = [
        "retry_connection",      # 重试连接
        "skip_device",          # 跳过此设备
        "abort_batch"           # 终止整个批次
    ]
elif error_type == "package_not_found":
    options = [
        "upload_again",         # 重新上传
        "specify_different_file",  # 指定其他文件
        "skip_device"
    ]
```

**批量应用**：
- "仅此设备"：决策只影响当前设备
- "剩余设备"：决策应用到后续所有等待的设备
- "全部设备"：包括已经在执行的设备（暂停并应用）

---

## 技术域 (Technical Domains)

### Execution Plan（执行计划）

从 Process Blueprint **编译**而来的运行时指令序列。

**编译过程**：
```
Process Blueprint (Studio)
  ↓ [validation]
  ↓ [condition elimination]  ← Control Nodes 被消除
  ↓ [dependency resolution]
  ↓ [action mapping]         ← Studio action_id → Framework workflow_id
Execution Plan (Framework)
```

**结构**：
```python
TaskPlan(
  nodes=[
    WorkflowNode(
      id="check_version",
      workflow_id="terminal.command",  # 不是 Studio 的 "device.command"
      depends_on=["connect"],
      input_mapping={"command": "display version"},
      run_if=None,  # 条件节点的判断逻辑编译到这里
      retry_policy={"max_attempts": 3},
      parallel_group=None
    ),
    ...
  ]
)
```

**关键转换**：
- `utility.condition` 节点 → `run_if` 元数据（附加到后续节点）
- `loop.for_each` 节点 → 展开为多个 WorkflowNode（如果 items 是静态列表）
- `device.command` → `terminal.command` workflow（action_id 映射）

---

### Variable Reference（变量引用）

在节点配置中**引用其他节点的输出**或运行时上下文。

**语法**：`${source.field}`

**可用的 source**：
- `inputs.<param_name>` - Process 运行时输入参数
- `<node_id>.<field>` - 前置节点的输出字段
- `device.<property>` - 当前设备的属性
- `item` / `index` - 循环体内的特殊变量

**约束**：
- 只能引用**拓扑顺序上的前置节点**（不能前向引用）
- 在 `loop.for_each` 的 `action_inputs` 中可以使用 `${item}`
- 普通配置值中的变量引用必须**占据整个值**
- `device.command` 的 `command` 文本支持内插，例如 `"dir ${ccfile}"`

**验证**：
- 前端：实时检查引用的节点是否存在于前置集合
- 后端：完整验证字段路径是否有效

---

### Parallel Group（并行组）

将**无依赖关系**的节点标记为可并行执行。

**配置方式**：
```typescript
{
  node_id: "collect_info_A",
  parallel_group: "info_collection"
}
{
  node_id: "collect_info_B",
  parallel_group: "info_collection"  // 同一组
}
```

**运行时行为**：
- 同组节点通过 `asyncio.gather` 并发执行
- 任一节点失败 → 取消其他节点 → 整组失败
- 组内成员**不能有相互依赖**（编译时验证）

**默认行为**：无 `parallel_group` → 串行执行

**用户界面**：
- 应该提供"自动识别可并行节点"功能
- 或拖拽选择多个节点 → "标记为并行"

---

## 边界上下文 (Bounded Contexts)

### Studio Context（工作室上下文）

**职责**：Process 的设计、验证、版本管理

**核心概念**：
- Process Blueprint
- Node / Edge
- Template
- Validation Issue

**不关心**：
- 设备连接细节
- 命令执行机制
- 错误恢复策略

---

### Execution Context（执行上下文）

**职责**：Task 的调度、执行、状态管理

**核心概念**：
- Task / Batch Task
- Execution Plan
- Session
- Recovery Decision

**不关心**：
- Process 是如何设计的
- 用户界面如何渲染
- 节点的可视化表示

---

### Device Context（设备上下文）

**职责**：设备数据管理、连接管理

**核心概念**：
- Device
- Session
- Device Source
- Connection Protocol

**不关心**：
- Process 和 Task 的业务逻辑
- 如何编排多步骤操作

---

## 通用语言约定 (Ubiquitous Language)

### 动词

- **Create Process**：在 Studio 中新建一个流程
- **Publish Process**：将草稿发布为可运行的版本
- **Run Process**：针对特定设备执行流程
- **Execute Node**：执行流程中的一个节点
- **Compile Blueprint**：将设计转换为执行计划
- **Resume Task**：从 checkpoint 恢复执行

### 状态术语

- **Draft**：草稿状态的流程（未发布）
- **Published**：已发布的流程版本（可运行）
- **Running**：正在执行的任务
- **Waiting for Decision**：阻塞在决策点
- **Reconciling**：尝试自动恢复（进程重启后）

### 避免使用的术语

- ❌ "Workflow Definition" → 用 "Process Blueprint"
- ❌ "Action" → 用 "Node" 或 "Operation"
- ❌ "Step" → 在 Studio 中用 "Node"，执行层用 "Step"
- ❌ "Success/Failure" → 用 "Completed/Failed"（更清晰）

---

## 设计决策参考

### ADR 候选主题

以下是可能需要记录 ADR 的决策点（待后续明确）：

1. **为什么 Control Node 在编译时消除而非运行时执行？**
   - 性能考虑
   - 静态分析能力
   - 简化运行时模型

2. **为什么 Batch Task 是一等公民而非虚拟聚合？**
   - 业务操作的原子性
   - 报告生成需求
   - 批量控制能力

3. **为什么不支持嵌套 Process（子流程）？**
   - MVP 范围控制
   - 复杂度权衡
   - 用户需求验证

---

**文档版本**：v0.1 (初始版本)  
**最后更新**：2026-09-13  
**维护者**：Device TUI 开发团队
