# Device TUI 内部审批模式设计

## 目标

取消 Device TUI 对外部 AI 动作的内部人工审批。Codex 或其他 MCP 客户端一旦决定调用工具，Device TUI 立即执行对应动作，不再要求用户在“AI 设备助手”中点击批准。

该行为适用于所有设备，包括模拟设备、真实 SSH 设备和真实 Telnet 设备，也适用于普通配置命令、重启、删除、修改启动项和自动换包等中高风险动作。

本改动只取消 Device TUI 内部审批，不修改 Codex 客户端自身的 MCP 工具确认策略。

## 方案

采用“保留风险识别和审批基础设施，通过策略关闭审批门”。

不删除 `RiskLevel`、命令分类、`ApprovalStore`、审批接口或审计字段。这样旧 MCP 客户端保持兼容，也能通过配置恢复 Device TUI 审批。

不采用以下方案：

- 彻底删除审批代码：会破坏旧客户端，并增加未来恢复审批的成本。
- 根据 MCP 来源名称绕过审批：来源名称可以伪造，不能作为授权边界。
- 只对模拟设备免审批：不符合所有设备自动执行的要求。

## 配置

新增环境变量：

```text
DEVICE_TUI_APPROVAL_MODE
```

支持两个值：

- `disabled`：默认值。Device TUI 不要求内部审批。
- `required`：恢复现有审批行为，中高风险和受控流程返回 `approval_required`。

空值或未知值按 `disabled` 处理，同时在审计记录中写入实际生效模式。配置在 App Control Service 启动时读取，修改后需要重启 Device TUI。

## 执行流程

`AppControlService` 仍然由工具参数创建 `AiDeviceAction`，并在 App 内重新计算命令风险。随后根据审批模式执行：

### disabled

1. 计算真实风险等级。
2. 不创建 `ApprovalRecord`。
3. 不返回 HTTP `409 approval_required`。
4. 对需要确认的动作调用 App 动作层时传入 `approved=True`。
5. 动作层再次计算风险，但因策略授权而直接执行。
6. 结果和风险写入审计日志。

### required

保持现有流程：创建审批请求、等待 App UI 批准、消费一次性令牌后执行。

只读和低风险动作在两种模式下都保持原行为。

## UI

默认 `disabled` 模式下：

- “外部 Tool Calling 审批”区域不显示待审批列表。
- 批准和拒绝按钮隐藏。
- 状态文字显示“Device TUI 内部审批已关闭；外部工具动作将直接执行。”

`required` 模式下恢复原有列表、批准和拒绝按钮。

切换审批模式不改变 AI 计划生成区域，也不改变自动换包面板。

## MCP 和 HTTP 兼容性

现有工具签名保持不变：

- `terminal_send_command(..., approval_token=None)`
- `package_upgrade_start(..., approval_token=None)`
- `approval_get(approval_id)`

在 `disabled` 模式下，`approval_token` 被忽略，工具直接返回执行结果。`approval_get` 仍可查询旧的审批记录；没有新审批时不会生成新的审批 ID。

HTTP 路径、Bearer Token、本机监听地址和状态文件格式不变。

Codex 的 `default_tools_approval_mode` 或每工具 `approval_mode` 不由 Device TUI 修改。Codex 是否在调用工具前询问用户，继续由 Codex 配置决定。

## 审计

取消审批不取消审计。每次外部动作继续记录：

- 来源客户端和工具名
- 设备 ID、命令和风险等级
- `device_approval_mode`
- `device_approval_bypassed`
- 执行结果、耗时和错误

当模式为 `disabled` 且动作风险为 `MEDIUM`、`HIGH` 或 `FLOW` 时，`device_approval_bypassed` 为 `true`。

密码、Bearer Token、审批令牌和 URL 凭据继续脱敏。

## 错误处理

- 命令执行失败仍返回 `action_failed`，不会因为免审批而重试。
- Qt 主线程超时仍返回 `ui_timeout`。
- 设备、会话或包配置不存在时继续返回现有错误。
- 自动换包仍由状态机负责空间检查、下载校验、启动项确认和重启确认。
- 禁用审批不会绕过换包状态机内部校验。

## 测试

单元测试覆盖：

- 默认模式为 `disabled`。
- `reboot` 等高风险命令直接进入后端，且 `approved=True`。
- 自动换包直接启动并返回 `operation_id`。
- 不创建待审批记录。
- 审计记录风险等级和审批绕过字段。
- `DEVICE_TUI_APPROVAL_MODE=required` 恢复原审批、令牌绑定和单次消费行为。
- 未知配置值按 `disabled` 处理。

UI 测试覆盖：

- `disabled` 模式隐藏审批列表和按钮。
- `required` 模式显示原审批控件。
- 状态标签正确显示生效模式。

集成测试使用模拟设备验证：

1. 启动默认模式的控制服务。
2. 发送 `reboot`，首次调用直接成功。
3. 启动自动换包，不产生审批请求。
4. 查询操作状态直到完成。
5. 以 `required` 模式启动另一个测试实例，确认原审批流程仍有效。

## 验收标准

- 所有设备的中高风险动作不再需要 Device TUI UI 批准。
- 默认调用不返回 `approval_required`。
- Codex 侧工具确认策略保持不变。
- 风险分类、审计、鉴权和自动换包内部校验继续生效。
- 设置 `DEVICE_TUI_APPROVAL_MODE=required` 并重启后，可恢复原审批行为。
