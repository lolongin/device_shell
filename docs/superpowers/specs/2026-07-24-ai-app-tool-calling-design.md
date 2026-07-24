# AI App Tool Calling / MCP 设计

## 目标

让外部 AI 通过标准 Tool Calling 或 MCP 操作正在运行的设备工作台，包括查看设备、选择设备、打开终端、发送任意命令、读取输出和启动自动换包流程。

“任意命令”表示命令内容不受固定模板限制，但所有执行都必须经过 App 内部统一的风险分类、审批和审计。外部 AI 不直接访问 Telnet、SSH 会话对象，也不能通过 MCP 参数绕过 App 的安全策略。

首个版本以本机单用户场景为范围，优先打通模拟设备的完整链路，不开放局域网监听，不提供远程凭据管理，也不实现多用户权限系统。

## 已选方案

采用“本地 App Control API + 独立 MCP 门面”。

备选方案及取舍：

1. 将 MCP 服务器直接嵌入 PySide6 进程。调用路径短，但 MCP 事件循环、Qt 主线程和应用生命周期会紧耦合，测试和故障隔离较差。
2. 让 MCP 服务器直接导入设备后端。适合无界面自动化，但会绕过当前 App 的设备选择、会话状态、换包界面和用户确认。
3. 本地控制 API 由 App 托管，MCP 服务器作为独立进程调用它。多一层本机通信，但边界清晰，可同时服务 OpenAI Tool Calling、Codex 和其他 MCP 客户端，并且 App 始终是设备操作的唯一执行者。

选择方案 3。MCP 使用官方 Python SDK 的稳定 v1 系列并限制为 `mcp>=1.27,<2`，避免 v2 仍处于预发布阶段时发生不兼容升级。第一版使用 stdio 传输，由 AI 客户端负责拉起 MCP 进程；App Control API 仅监听 `127.0.0.1`。

## 架构

```text
AI / MCP Client
       |
       | stdio MCP tools
       v
Device TUI MCP Server
       |
       | HTTP JSON + bearer token, 127.0.0.1
       v
App Control Server
       |
       | queued call with timeout
       v
Qt UI thread -> AiDeviceOpsMixin -> session/package-upgrade services -> device
```

组件职责：

- `ai_device_ops.py`：保留与界面无关的动作、结果和风险模型。
- `app/ai_device_ops.py`：作为 App 内部唯一设备工具执行入口，负责再次计算风险并分派动作。
- `app_control_server.py`：提供本机 HTTP JSON API、认证、审批状态和审计记录；通过 Qt 调度队列执行 App 调用。
- `mcp_server.py`：使用 FastMCP 暴露工具，只做参数校验、调用本地 API 和返回结构化结果，不持有设备连接。
- `app_control_client.py`：封装本地 API 调用，供 MCP 服务器和普通 Tool Calling 适配器复用。

## App Control API

服务启动时选择可用的本机端口并生成 256 位随机令牌。运行信息写入用户运行目录中的状态文件，内容包括 `pid`、`base_url`、`token` 和启动时间。状态文件只用于当前用户本机进程发现，App 退出时删除。

统一响应字段：

```json
{
  "ok": true,
  "request_id": "uuid",
  "message": "已读取 3 台设备",
  "data": {},
  "approval": null,
  "error": null
}
```

首版接口：

- `GET /v1/health`：检查 App 和控制服务状态。
- `GET /v1/devices`：返回设备快照。
- `POST /v1/devices/select`：按稳定的 `device_id` 选择设备。
- `POST /v1/sessions/open`：为设备打开或复用终端会话。
- `POST /v1/terminal/send`：发送任意命令，参数为 `device_id`、`command` 和可选 `approval_token`。
- `POST /v1/terminal/read`：读取指定设备最近的终端输出，可限制最大字符数。
- `POST /v1/package-upgrade/start`：启动现有受控自动换包流程。
- `GET /v1/operations/{operation_id}`：查询长流程状态。
- `GET /v1/approvals/{approval_id}`：查询等待、批准、拒绝或过期状态；批准后返回一次性审批令牌。

每个请求使用 `Authorization: Bearer <token>`。除 `/health` 外，认证失败统一返回 `401`；请求参数错误返回 `400`；设备或会话不存在返回 `404`；需要审批返回 `409`；Qt 调用超时返回 `504`。

## MCP 工具

MCP 对外提供语义稳定的小工具：

- `device_list()`
- `device_select(device_id)`
- `session_open(device_id)`
- `terminal_send_command(device_id, command, approval_token=None)`
- `terminal_read(device_id, max_chars=4096)`
- `package_upgrade_start(device_id, approval_token=None)`
- `operation_get(operation_id)`
- `approval_get(approval_id)`

工具返回 JSON 可序列化对象，不返回仅供人阅读的长文本。设备必须使用 `device_id` 定位，名称只用于展示，避免重名误操作。

AI 可以先调用 `terminal_send_command`。如果命令需要确认，结果包含风险等级、规范化命令、`approval_id`、过期时间和原因。AI 向用户说明后等待用户在 App 中确认，再用一次性 `approval_token` 重试原请求。令牌绑定请求动作、设备、命令摘要和过期时间，不能用于其他操作。

## 风险和审批

风险策略继续由 App 计算，MCP 提交的风险字段一律不受信任：

- `OBSERVE` / `LOW`：设备列表、读取输出、版本查询等自动允许。
- `MEDIUM`：普通配置命令、文件传输入口等需要用户确认。
- `HIGH`：重启、删除、格式化、保存配置、修改启动包等必须确认。
- `FLOW`：自动换包等受控状态机需要确认，由状态机继续执行内部校验。

审批默认有效 60 秒，只能消费一次。审批对原始命令做去空白规范化后计算摘要；任何设备、命令或参数变化都会使令牌失效。

App 显示待审批动作的设备、命令、风险原因和来源客户端。用户可批准或拒绝，决定由 App 进程直接写入审批存储，不提供对应的 HTTP 写接口。MCP 不能调用一个“直接批准”工具；审批必须来自 App UI，避免 AI 自己批准自己的高风险操作。

## 线程和生命周期

HTTP 服务运行在后台线程。所有读取或修改 Qt 对象的调用通过一个带返回值的 UI 调度器进入 Qt 主线程：

1. 服务线程创建请求任务和单结果队列。
2. `dispatch_ui` 将任务放入现有 UI 队列。
3. Qt 主线程执行动作并写回结果或异常。
4. 服务线程最多等待 10 秒，超时后返回 `504`，不在后台重复执行。

启动阶段先创建 App，再启动控制服务。关闭阶段先停止接受新请求，再等待短时在途请求结束，删除状态文件，最后按现有顺序关闭会话和异步循环。控制服务启动失败不阻止桌面 App 使用，但必须在状态栏和日志中明确提示。

## 长流程和终端输出

发送命令成功只代表命令已经写入会话，不代表设备执行成功。AI 应通过 `terminal_read` 获取输出并判断结果。

自动换包返回 `operation_id`，MCP 使用 `operation_get` 查询阶段、进度、最近消息、最终结果和失败原因。第一版使用轮询，不把 Qt 信号直接暴露到 MCP。操作状态由 App 保存于内存，App 退出后标记为中断，不承诺跨重启恢复。

终端输出默认返回最后 4096 个字符，最大允许 32768 个字符。返回内容包含截断标记和会话标识，避免模型误以为获得完整历史。

## 审计

每次外部调用记录为一行 JSON，至少包含：

- 时间、`request_id`、来源客户端和工具名
- 设备 ID、动作类型、命令摘要和风险等级
- 是否要求审批、审批 ID、审批结果
- 执行结果、耗时和错误码

日志不记录密码、Bearer token、审批 token 或设备凭据。命令正文默认记录；后续可增加按正则脱敏，但首版必须对常见密码参数和 URL 凭据做基础遮蔽。

## 错误处理

- App 未运行：MCP 返回可操作错误，提示先启动 Device TUI。
- 状态文件陈旧：客户端校验 PID 和 `/health`，失败后不连接旧端口。
- 设备已离线：返回明确的设备和会话状态，不自动切换到同名设备。
- 会话未打开：`terminal_send_command` 返回前置条件错误，不隐式连接真实设备；AI 先调用 `session_open`。
- 重复请求：带副作用接口接受可选 `idempotency_key`，相同键在短期内返回原结果。
- App 关闭或 Qt 超时：请求失败，不自动重试高风险动作。
- MCP 进程异常：不影响 App 和已建立的设备会话。

## 测试与验收

单元测试：

- API 请求到 `AiDeviceAction` 的转换和结构化响应。
- Bearer token、输入大小、错误码和状态文件处理。
- Qt 主线程调度成功、异常和超时。
- 风险重新分类，确保外部参数不能降低风险。
- 审批令牌绑定、过期、单次消费和拒绝。
- 审计脱敏与幂等请求。
- MCP 工具参数和本地客户端映射。

集成测试使用模拟设备，不接触真实凭据：

1. 启动 App 控制服务并发现状态文件。
2. MCP 列出设备并选择模拟设备。
3. 打开模拟终端，执行 `display version`，读取并验证输出。
4. 执行 `reboot`，首次得到 `approval_required`。
5. 在测试审批后重试，确认一次性令牌成功且不能复用。
6. 启动模拟自动换包，通过 `operation_get` 观察到完成或可解释的失败。
7. 关闭 App，确认控制端口停止且状态文件被删除。

验收标准是：外部 AI 能完成模拟设备的上述闭环；任意命令均可提交；中高风险操作无法在没有 App 用户确认的情况下执行；所有调用可追踪；控制服务异常不会破坏桌面 App 的正常使用。

## 实施边界

首版不包含：

- 对局域网或公网开放控制端口
- 多用户、角色权限和 OAuth
- AI 自动读取或填写真实设备密码
- 跨 App 重启恢复进行中的换包流程
- 由 AI 自动批准中高风险操作
- 直接暴露底层 Telnet/SSH socket

后续若需要无人值守，可增加由用户预先签发、限定设备与命令范围的策略授权，而不是移除风险门禁。
