# 双通道 CLI 详细设计文档

## 1. 文档目标

本文档用于描述当前 `device_tui` 项目中 CLI 子系统的下一阶段设计方案，将现有“单设备 Telnet 交互窗格”升级为“华为设备运维执行台”。

设计目标：

- 支持两个执行通道：`linux` 与 `device`
- 支持普通命令直接发送到设备 CLI
- 支持 `/` 开头命令触发本地工作流
- 支持工作流按步骤串行执行，并明确每一步的执行目标
- 支持实时输出、状态反馈、异常提示与后续扩展

## 2. 背景与现状

当前项目已具备以下基础能力：

- 设备列表展示与筛选
- 设备详情区
- 右下角 CLI Session 窗格
- 单设备 Telnet 会话
- 简单 Huawei CLI 登录与命令发送
- 输出区实时追加显示

当前限制：

- 仅支持 `device` 单通道
- 不支持 Linux 登录
- 不支持工作流命令
- 不支持多目标步骤编排
- 输入框内所有命令都被视为普通设备命令

## 3. 需求摘要

系统需支持两个执行通道：

- `linux`：SSH 登录后台 Linux
- `device`：Telnet 登录设备 CLI

交互规则：

- 输入普通命令时，默认发送到 `device`
- 输入 `/` 开头命令时，进入本地工作流执行器
- 工作流中的每一步必须显式声明 `target`
- `target` 仅允许为：
  - `linux`
  - `device`
- 步骤必须按定义顺序执行
- 每一步执行过程中的输出需实时显示

界面要求：

- 显示 `linux` 与 `device` 的连接状态
- 提供统一输出区
- 提供统一输入框
- 能明显区分输出来源

## 4. 设计目标

### 4.1 目标

- 在当前 TUI 内构建一个双通道运维执行环境
- 让用户在不离开终端界面的情况下完成设备与后台联动操作
- 提供适合华为设备维护的可扩展工作流机制

### 4.2 非目标

当前阶段不包含：

- 多设备并行执行
- 工作流图形化编辑
- 复杂交互式脚本编排
- 持久化工作流模板存储
- 权限与审批系统

## 5. 总体架构

建议分为 5 层：

1. 界面层
2. 输入路由层
3. 工作流执行层
4. 会话层
5. 输出聚合层

### 5.1 分层说明

#### 界面层

负责：

- 显示连接状态
- 显示目标信息
- 渲染统一输出区
- 提供输入框与快捷键

不负责：

- 协议细节
- 工作流步骤定义
- 业务路由判断

#### 输入路由层

负责：

- 判断输入属于普通命令还是本地工作流命令
- 将普通命令发送到 `device`
- 将 `/` 命令交给工作流解析器

#### 工作流执行层

负责：

- 解析本地命令
- 找到工作流定义
- 校验步骤目标与参数
- 按顺序执行每一步
- 在执行过程中实时输出

#### 会话层

负责：

- `linux` SSH 会话
- `device` Telnet 会话
- 登录、断开、命令发送、状态变更

#### 输出聚合层

负责：

- 将 `linux`、`device`、`workflow` 输出合并到统一窗口
- 给输出增加来源标识
- 维护展示顺序

## 6. 模块设计

建议新增或调整以下模块：

### 6.1 `src/telnet_session.py`

现有模块继续承担：

- Huawei 设备 Telnet 登录
- IAC 控制字节过滤
- 自动登录与 `screen-length 0 temporary`
- 实时设备输出读取

建议补充：

- 与 SSH 会话统一接口风格
- 增加输出来源标识支持

### 6.2 `src/ssh_session.py`

新增 Linux SSH 会话模块。

职责：

- 连接后台 Linux
- 登录
- 发送 Shell 命令
- 异步读取标准输出与标准错误
- 向 UI 报告连接状态与执行输出

建议统一接口：

- `connect(host, port, username, password)`
- `disconnect(message="Disconnected.")`
- `send_command(command)`
- `is_connected`

说明：

- 当前 Python 3.13 环境下，SSH 建议通过第三方库实现
- 第一版可以采用单连接、单命令串行执行模型

### 6.3 `src/workflows.py`

新增工作流定义模块。

职责：

- 注册工作流
- 解析 `/命令`
- 返回结构化步骤列表

建议输出结构：

```python
WorkflowStep = {
    "target": "linux" | "device",
    "command": str,
    "label": str,
}
```

建议接口：

- `parse_workflow_input(text: str) -> WorkflowRequest`
- `build_workflow_steps(request: WorkflowRequest) -> list[WorkflowStep]`

### 6.4 `src/workflow_runner.py`

新增工作流执行模块。

职责：

- 校验每一步目标是否已连接
- 按顺序执行步骤
- 将每一步输出写入统一输出区
- 在步骤失败时终止执行

建议接口：

- `run_workflow(request, sessions, emit_output, emit_status)`

### 6.5 `src/app.py`

继续作为 UI 主入口，但职责要进一步收缩：

- 展示状态
- 组织布局
- 管理输入事件
- 调用会话或工作流模块

不再负责：

- 直接编排复杂工作流步骤
- 处理协议细节

## 7. 会话模型设计

## 7.1 抽象接口

建议定义统一的会话能力约束：

```python
class CommandSession(Protocol):
    async def connect(...)
    async def disconnect(...)
    async def send_command(command: str)
    @property
    def is_connected(self) -> bool
```

同时保留两个回调：

- `on_output(message: str)`
- `on_status(status: str)`

## 7.2 Device 通道

通道标识：`device`

特点：

- Telnet 连接
- 登录目标为华为数通设备 CLI
- 普通命令默认发往该通道
- 登录成功后自动执行 `screen-length 0 temporary`

## 7.3 Linux 通道

通道标识：`linux`

特点：

- SSH 连接
- 登录目标为后台 Linux
- 仅在工作流步骤中显式调用
- 后续也可扩展为手动切换默认命令目标

## 8. 输入路由规则

### 8.1 路由规则

输入框提交文本后按以下规则处理：

- 文本为空：忽略
- 以 `/` 开头：交给工作流解析器
- 否则：按普通命令发送到 `device`

### 8.2 普通命令

规则：

- 仅发送到 `device`
- 若 `device` 未连接，则提示错误
- 输出实时显示

### 8.3 工作流命令

规则：

- 进入本地工作流模式
- 不直接透传给任何远端
- 先解析命令名和参数
- 再构造步骤
- 最后按顺序执行

## 9. 工作流设计

### 9.1 工作流输入格式

建议第一版使用：

- `/collect_log`
- `/change_cc`
- `/change_cc xxx`

### 9.2 工作流步骤结构

建议字段：

- `target`
- `command`
- `label`
- `stop_on_error`

示例：

```python
[
    {"target": "device", "command": "display logbuffer", "label": "read device log", "stop_on_error": True},
    {"target": "linux", "command": "mkdir -p /tmp/huawei_logs", "label": "prepare log dir", "stop_on_error": True},
]
```

### 9.3 执行规则

- 工作流步骤按数组顺序执行
- 上一步未完成前，不执行下一步
- 执行前检查目标通道是否已连接
- 若目标不可用，则工作流失败并停止
- 若步骤失败且 `stop_on_error=True`，则终止
- 每一步开始时输出说明信息
- 每一步执行中的回显实时写入输出区

### 9.4 第一版建议内置工作流

#### `/collect_log`

示例步骤：

1. `device` 执行 `screen-length 0 temporary`
2. `device` 执行 `display logbuffer`
3. `linux` 执行 `mkdir -p /tmp/huawei_logs`
4. `linux` 执行归档命令或记录动作

#### `/change_cc`

示例步骤：

1. `linux` 记录变更前置检查
2. `device` 进入配置模式
3. `device` 执行目标配置命令
4. `device` 执行保存命令
5. `linux` 记录变更结果

说明：

- `/change_cc` 的具体命令内容需要业务侧进一步确认
- 第一版可先用桩命令或占位步骤

## 10. 输出区设计

### 10.1 统一输出区

仍建议使用单一输出窗口，而不是为 `linux` 和 `device` 各自拆分。

原因：

- 更符合“执行台”的概念
- 更容易观察工作流的顺序输出
- 更适合混合展示步骤执行过程

### 10.2 输出标识

建议统一添加来源前缀：

- `[device]`
- `[linux]`
- `[workflow]`
- `[system]`

示例：

```text
[workflow] step 1/3 read device log
[device] Info: command accepted
[device] ...
[workflow] step 2/3 prepare linux dir
[linux] mkdir -p /tmp/huawei_logs
```

### 10.3 输出顺序

- 严格按实际到达顺序显示
- 不重新排序
- 不等待整步完成后统一输出

## 11. UI 设计

## 11.1 现有布局调整方向

当前右下角已存在 CLI 窗格，建议在此基础上扩展。

保留区域：

- 右上：设备详情
- 右下：CLI / Workflow 执行区

## 11.2 CLI / Workflow 窗格建议结构

建议包含：

- `Linux Status`
- `Device Status`
- `Target Device`
- `Device Auth`
- `Linux Auth`
- `Output`
- `Input`

### 11.3 连接区建议

#### Device 连接

- 目标地址默认跟随当前选中设备
- 用户名与密码允许编辑覆盖

#### Linux 连接

- 单独输入：
  - Host
  - Port
  - Username
  - Password

### 11.4 输入区建议

统一输入框行为：

- 普通命令直接发送到 `device`
- `/` 命令走本地工作流

建议在提示文字中说明：

- `normal command -> device`
- `/workflow -> local runner`

## 12. 状态管理设计

建议维护以下状态：

- `device_session`
- `linux_session`
- `device_connected`
- `linux_connected`
- `workflow_running`
- `current_workflow_name`
- `workflow_step_index`

附加状态：

- 当前选中设备
- 当前输出来源
- 输入模式提示

## 13. 并发与异步设计

### 13.1 会话并发

- `linux` 与 `device` 的读循环彼此独立
- 两个通道都可持续输出

### 13.2 工作流执行

- 工作流内部按步骤串行执行
- 工作流运行期间建议禁止再次启动新的工作流
- 工作流运行期间普通命令可选：
  - 第一版建议禁用
  - 避免与步骤执行串扰

### 13.3 UI 响应

- 网络读写不能阻塞 UI
- 所有耗时任务必须通过后台异步任务执行

## 14. 异常处理设计

### 14.1 连接异常

- Linux SSH 连接失败
- Device Telnet 连接失败
- 登录失败
- 超时

处理要求：

- 在状态区提示失败
- 在输出区打印错误说明
- 不导致 UI 崩溃

### 14.2 工作流异常

- 未知工作流命令
- 目标通道未连接
- 步骤执行失败
- 输出读取异常

处理要求：

- 明确提示失败步骤
- 明确提示失败目标
- 默认终止整个工作流

### 14.3 输出异常

- 某个通道断开
- 工作流中途失败

处理要求：

- 输出区记录系统消息
- 状态区立即刷新

## 15. 安全与风险

### 15.1 凭据风险

- 用户名/密码属于敏感信息
- 当前第一版可先沿用内存态输入
- 后续建议接入环境变量或安全存储

### 15.2 命令执行风险

- `/change_cc` 之类工作流可能下发变更命令
- 第一版建议默认先做只读或模拟流程
- 高风险工作流建议后续加确认步骤

### 15.3 通道误操作风险

- 普通命令默认发到 `device`
- 为防止误解，界面需明确提示当前规则

## 16. 第一版实施顺序

建议按如下顺序推进：

1. 抽象统一会话接口
2. 新增 `LinuxSshSession`
3. 在 UI 中增加 Linux 连接状态与认证区
4. 实现输入路由：普通命令 vs `/命令`
5. 新增工作流定义模块
6. 新增工作流执行器
7. 先跑通 `/collect_log`
8. 再补 `/change_cc`
9. 补充错误处理与输出标签

## 17. 测试建议

### 17.1 会话层测试

- Telnet 登录成功
- Telnet 登录失败
- SSH 登录成功
- SSH 登录失败
- 命令发送与输出接收

### 17.2 路由测试

- 普通命令发送到 `device`
- `/collect_log` 被正确识别为工作流
- 未知 `/命令` 提示正确

### 17.3 工作流测试

- 步骤按顺序执行
- 步骤输出实时显示
- 中途失败时工作流终止
- `linux` 或 `device` 未连接时阻止执行

### 17.4 UI 测试

- 双通道状态显示正确
- 输出来源标签正确
- 工作流执行期间交互表现正确

## 18. 结论

该需求可以在现有 `device_tui` 项目上继续演进实现，且与当前已具备的右下角 CLI 窗格、异步 Telnet 会话和统一输出区能力兼容。

建议第一版以“单 Linux + 单 Device + 单输入框 + 少量内置工作流”为边界，优先建立稳定的双通道执行模型，再逐步扩展工作流数量与复杂度。

