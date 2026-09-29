# Workflow Studio 编辑器与动作目录计划

## 目标

继续降低 Workflow Studio 修改成本，并收敛动作元数据来源：

1. 将节点属性面板从 `WorkflowLibrary.vue` 接入并完善为独立模块，容器只协调选中节点、工作流数据和设备/API 操作。
2. 让后端 Action Catalog 成为动作 ID、名称、类别、风险、输入/输出 schema 的权威来源。前端保留纯展示映射和需要复杂交互的专用编辑器，不再维护平行的动作清单或字段契约。

本轮保持现有流程存储格式、执行 API、节点行为和高风险确认语义兼容。

## 当前情况

- `WorkflowLibrary.vue` 仍约 3,332 行；脚本、运行/测试面板、管理对话框和部分编辑状态已经抽离。
- `workflow-config/WorkflowNodeProperties.vue` 及其配置子模块已存在，但主编辑器仍内联渲染完整的节点属性区域。
- 后端 `/workflow-definitions/actions` 返回 `id`、`name`、`category`、`input_schema`、`output_schema`、`risk` 和 `executor_id`。
- 前端仍有静态动作列表、默认输出字段回退及多处按 action ID 分支的配置表单；目录加载只覆盖其中部分字段。

## 计划

## 实施进度

- [x] 定义 Action Catalog 前端类型与目录映射模块；节点库卡片和输出引用字段已从后端 catalog 构建，移除了重复动作卡片与输出字段回退表。
- [x] 将属性栏基础信息（标题、名称、上下游）接入 `WorkflowNodeProperties.vue`，编辑仍委托给 `useWorkflowEditor`。
- [x] 常规节点属性改由 `WorkflowNodeProperties.vue` 装配；Generic 配置根据 catalog input schema 渲染基础类型、required、enum 与 JSON 字段，命令/脚本输出按 catalog 输出字段呈现。
- [x] 将条件、循环、变量、子流程等剩余专用交互模板迁入 `AdvancedNodeConfig.vue`，由 `WorkflowNodeProperties.vue` 装配。
- [x] 目录加载失败时在节点库显示明确错误，补齐配置模块契约测试并完成 UI/API/build 验证。
- [x] 建立 `WorkflowInspectorShell.vue` 作为右侧区域唯一布局和滚动所有者；流程设置、步骤设置、测试运行面板通过插槽进入，移除主组件中冲突的 rail/grid 覆盖规则。
- [x] 建立 `WorkflowSettingsPanel.vue` 承接流程基本信息、输入/输出定义和运行参数，主组件只提供状态与操作回调。

### 阶段 1：接入节点属性模块

- 以 `WorkflowNodeProperties.vue` 作为节点配置区域的唯一入口，移除 `WorkflowLibrary.vue` 中重复的节点表单模板。
- 明确 props/emits：节点和只读目录数据通过 props 输入；节点更新、重命名、前后继调整、删除、测试、保存自定义动作和脚本资源操作通过事件回传。
- 将条件、循环、变量、子流程及通用重试选项分别迁入配置模块；共享节点编辑操作继续由 `useWorkflowEditor` 或容器持有。
- 合并重复/未使用的配置目录 README 和占位模块，确保实际模块契约与文档一致。
- 验证名称修改、配置更新、脚本选择、变量引用、条件分支、循环、测试和删除操作。

### 阶段 2：收敛动作目录数据

- 定义与后端 Action Catalog 对应的前端类型，并将目录加载封装成纯映射/合并函数，便于无窗口环境测试。
- 删除硬编码的动作 ID/名称/类别/输出字段清单；目录加载成功后用后端元数据生成动作卡片、输出引用字段和 schema 驱动的基础配置项。
- 类别分组名称、字段本地化标签、图标/颜色属于展示映射，可以留在前端；不得覆盖后端的动作身份、风险或字段 schema。
- 将复杂配置（命令编辑、文件选择、变量提取、条件、循环、子流程等）保留为专用编辑器，并让它们读取同一动作 schema 来确定字段、必填和输出信息。
- 明确目录加载失败时的用户反馈；避免静默退回一份可能过期的完整动作定义。自定义 Action 继续沿用现有加载路径并遵循同一前端类型。

### 阶段 3：回归与清理

- 将 UI 源码断言迁移到实际节点配置模块/目录映射函数的接口和行为。
- 保留并运行后端目录契约、校验/编译兼容测试。
- 运行 Workflow Studio UI/API 测试、桌面类型检查和生产构建。
- 检查工作流草稿和已发布版本序列化不变，确认画布、测试、预览、发布和运行行为未回归。

## 模块接口原则

- `WorkflowLibrary.vue` 持有当前 workflow、选中节点、设备和持久化/运行操作。
- `WorkflowNodeProperties.vue` 呈现单个选中节点的配置，并通过少量 props/emits 协作，不直接调用 API 或读取全局 workspace store。
- Action Catalog adapter 负责把后端响应规范化为前端只读目录；节点表单和输出引用选择器共用该规范化结果。
- 专用编辑器负责交互体验；schema 负责字段身份、类型、必填和输入/输出契约。

## 完成标准

- 主组件不再包含节点属性的长模板或第二份动作目录。
- 新增后端动作后，目录卡片及通用配置/输出引用能够从 API 元数据生成；特殊交互只需注册专用编辑器。
- 不改变工作流持久化结构、执行路径、危险操作确认或现有脚本行为。
- 相关测试、`npm run typecheck` 和 `npm run build` 通过。
