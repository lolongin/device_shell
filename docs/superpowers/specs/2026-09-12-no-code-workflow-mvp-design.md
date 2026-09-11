# No-Code Workflow MVP 设计

## 目标

为网络设备运维场景提供一个可保存、可编辑、可发布并可执行的通用 Workflow P0 闭环。用户通过 Studio 组合 Action，不编写 Python、Shell 或 YAML；发布后的流程复用现有 Task/Execution 框架运行并展示状态与日志。

## 范围

本阶段包含：

- Workflow Library：列表、搜索、新建、复制、删除、启用/停用。
- Workflow Studio：Action Catalog、画布、属性面板三栏布局。
- Action：选择设备、SSH、Telnet、执行命令、上传文件、下载文件、重启、等待、条件判断。
- 流程：顺序执行与条件分支；节点输入引用前序节点输出；基础变量。
- 生命周期：草稿保存、发布、版本递增；发布前校验。
- 执行：由已存在的 TaskService/WorkflowEngine 创建 Task，复用运行状态、日志、取消和重试能力。

本阶段不包含并行、批量设备、人工审批、Dry Run、Step 调试、模板市场、子 Workflow、定时触发和自定义 Action。

## 架构

新增通用 Workflow Definition 存储层，保存 workflow 元数据、版本、输入、节点、边、输出和状态。节点引用 Action Catalog 中的稳定 action id，并保存配置、输入映射、重试与失败策略。Catalog 负责描述 Action 的输入/输出和风险等级；Studio 只依赖 Catalog，不把设备执行细节写入 UI。

发布时执行校验器：检查名称、节点连接、必填配置、引用变量、条件配置、循环风险和高风险节点提示。错误阻止发布，风险项生成警告。发布生成不可变版本快照；创建 Task 时记录 workflow_id 与 workflow_version。

执行适配层把通用节点编译为现有 WorkflowDefinition/TaskCreate 所需结构。已有设备连接、命令、文件传输和重启能力继续由现有 Action/Provider 执行。执行页面读取现有 TaskRecord 与活动日志，不新增第二套状态机。

## 数据流

1. 用户在 Library 新建或复制 Workflow。
2. Studio 加载定义和 Action Catalog，编辑节点与边并实时更新草稿。
3. 保存将草稿写入 WorkflowStore；版本仍保持草稿状态。
4. 发布运行校验器，通过后创建不可变版本并更新 Library 元数据。
5. 用户选择设备和输入参数，后端将版本编译为 TaskCreate 并创建 Task。
6. TaskService/WorkflowEngine 执行，前端轮询或订阅现有 Task 状态与日志。

## 错误处理

- API 对未知 Action、非法边、缺失参数和不存在变量返回结构化校验错误。
- 发布失败不改变当前草稿和已发布版本。
- 执行失败沿用现有 Task 状态和重试策略；节点级错误保留节点 id。
- 删除仅允许删除未被运行 Task 引用的草稿；已发布版本保留供历史 Task 追溯。

## 测试

- Workflow 定义序列化、版本和存储 CRUD。
- 校验器覆盖孤立节点、循环、缺参、变量引用和高风险警告。
- 编译适配器验证 Action 到现有 WorkflowDefinition 的映射。
- API 覆盖保存、发布、创建 Task 和错误响应。
- Vue 类型检查与生产构建；关键 Studio 交互提供组件测试或可重复的行为验证。

## 非目标与后续演进

Action Catalog 使用稳定 Schema，后续可增量加入并行、人工确认、Dry Run 和动态表单，不改变 Studio 核心接口。Workflow 版本采用快照策略，避免历史 Task 受到后续编辑影响。
