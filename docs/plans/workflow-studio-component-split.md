# Workflow Studio 主组件拆分计划

## 目标

将 `desktop/src/renderer/src/components/WorkflowLibrary.vue` 从承载完整编辑器、脚本资源工作台、版本管理、执行预览和大量样式的单体组件，逐步拆成职责明确的 Vue 组件与 composable。

拆分期间保持现有 API、流程数据格式、脚本行为和用户交互兼容。每一阶段都可独立验证和回滚，不做整体重写，也不借机改动 Workflow 的业务语义。

## 当前边界

`WorkflowLibrary.vue` 约 4,378 行，目前包含：

- 流程与脚本工作台切换、加载和选择状态。
- 脚本资源创建、复制、保存、删除、参数配置和测试执行。
- 流程草稿、节点/边编辑、画布交互与撤销重做。
- 流程输入输出、子流程版本和已发布版本管理。
- 校验、导入导出、发布、运行预览及测试任务监控。
- 上述各功能的模态框和大部分局部样式。

画布已经由 `WorkflowCanvas.vue` 承担渲染，但画布状态操作仍留在主组件。现有 `tests/test_workflow_studio_ui.py` 有不少检查直接读取主组件源码；代码搬迁时需要将这些检查改为验证真实职责所在的文件和组件契约，而不是为通过文本断言把实现继续留在主组件。

## 拆分原则

1. 先按现有状态所有权和事件流拆分，不先引入新的全局 Store。
2. 子组件通过明确的 props、emits 或局部 composable 交互，不直接依赖 `App.vue`。
3. 跨面板共享的流程草稿、选中节点、设备和 API 调用保留在工作台容器，直到有证据需要进一步下沉。
4. 一次只迁移一个完整职责，迁移后删除旧实现，避免双重状态源。
5. 样式跟随组件迁移；共享主题覆盖保留在现有全局样式中。
6. 不改变 `WorkflowDraft`/节点/边持久化结构、端点、发布版本语义和执行确认流程。

## 实施阶段

### 阶段 0：建立基线

- 确认工作区干净，记录当前组件职责和相关源码级 UI 测试。
- 运行 `python -m pytest tests/test_workflow_studio_ui.py` 与 `cd desktop && npm run typecheck`，记录基线结果。
- 本计划单独提交，作为后续重构的范围和验收依据。

### 阶段 1：抽离脚本资源工作台

- 新建 `WorkflowScriptStudio.vue`，承接脚本列表、脚本编辑器、参数配置、独立测试面板和脚本模板对话框。
- 新建 `useWorkflowScripts.ts`（或同职责 composable）管理脚本加载、创建/复制/保存/删除、测试任务轮询及脚本快照。
- 容器只保留 flow/scripts 模式切换及被流程节点编辑器消费的脚本引用接口。
- 通过 props/emits 暴露必要的脚本列表和操作；避免脚本子组件读取整个 workspace store。
- 迁移脚本面板私有样式到组件；全局主题选择器和真正共享的布局样式留在原位置。
- 更新源码测试，检查组件职责和用户可见契约；增加针对脚本 composable 的行为测试（若该逻辑可在现有测试栈中直接验证）。

### 阶段 2：抽离执行预览与运行测试面板

- 将流程执行预览、高风险确认、草稿测试状态和执行日志视图拆入独立组件。
- 后端启动/取消/恢复执行、设备选择及任务刷新策略由容器或专用 composable 保持单一所有权。
- 验证单设备、多设备、风险确认、失败日志和任务轮询恢复路径。

### 阶段 3：抽离版本/导入导出对话框

- 把发布版本列表与操作、导入预览、创建流程和模板管理拆成独立组件。
- 持久化动作仍统一经 `desktopApi` 和容器协调；对话框负责输入和事件回传。
- 验证版本恢复、删除、导入错误提示和未保存修改保护。

### 阶段 4：收拢画布编辑状态与节点属性

- 将节点/边增删改、自动布局、画布快捷键和 issue 定位迁入 `useWorkflowEditor.ts` 等局部 composable。
- 评估 `WorkflowNodeProperties.vue` 当前配置组件是否可直接复用；避免一次性重写节点表单。
- 主容器最终负责工作台布局、流程选择/保存协调和子区域装配。
- 梳理并删除重复状态、失效处理器和搬迁后未使用的样式。

## 每阶段验证

- `python -m pytest tests/test_workflow_studio_ui.py`
- 与迁移职责相关的 Workflow Studio API、模型、验证或持久化测试。
- `cd desktop && npm run typecheck`
- 最终阶段运行 `cd desktop && npm run build`。
- 手工检查流程/脚本模式切换、未保存提示、画布编辑与撤销重做、发布版本、执行预览、高风险确认和脚本测试。

## 完成标准

- `WorkflowLibrary.vue` 只负责工作台编排，不再包含完整脚本工作台、运行面板等子域的实现。
- 流程与脚本功能没有重复状态源，组件边界通过显式 props/emits/composable 契约连接。
- 现有节点/边和版本数据兼容，既有 API 与运行确认安全检查仍有效。
- 相关 Python 测试、桌面端类型检查和生产构建通过。
- 源码测试验证职责和行为，不依赖搬迁前的文件位置。

## 风险与处理

- **脚本状态被多个区域消费：** 阶段 1 先盘点脚本节点配置、独立脚本编辑器和测试之间共享的数据，确定唯一所有者后再移动。
- **长任务轮询在模式切换时中断：** 保持请求 ID/卸载清理语义，并验证重新进入面板时可以恢复监控。
- **scoped CSS 与主题覆盖失效：** 搬迁局部样式时检查全局主题选择器、Teleport 对话框和样式作用域。
- **源码测试脆弱：** 将静态断言指向组件 API/实际实现文件，行为测试覆盖关键用户路径。
- **重构范围膨胀：** 每阶段以职责搬迁为边界，不加入新交互、状态库或后端 schema 变更。

## 建议提交顺序

1. `docs: add workflow studio split plan`
2. `refactor: extract workflow script studio`
3. `refactor: extract workflow execution panels`
4. `refactor: extract workflow management dialogs`
5. `refactor: isolate workflow editor state`
