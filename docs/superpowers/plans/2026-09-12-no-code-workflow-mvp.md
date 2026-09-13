# No-Code Workflow MVP Implementation Plan

## 当前进度（2026-09-13）

- 已完成：任务型入口、模板/复制/空白创建、三栏步骤编辑器、业务 Action 表单、可视化条件规则、服务端校验、执行预览、Dry Run、失败步骤重试/断点继续。
- 已完成：条件规则编译为 `TaskPlan.run_if`，运行时只执行真/假匹配分支，并记录跳过原因；支持条件后的步骤继承分支。
- 已完成：条件编辑器支持 AND/OR 多条件组合及“不包含”比较，规则配置保持可视化并写入 Workflow Definition。
- 已完成：新增“人工确认”控制步骤，执行时进入待决策状态，任务页可选择确认继续或取消流程。
- 已完成：新增“重复执行”步骤配置，支持 1-20 次有限迭代，并向执行上下文记录当前迭代。
- 已完成：任务列表增加批量执行结果摘要，直接显示总数、成功数、失败数和等待数。
- 已完成：发布前校验人工确认提示、条件逻辑运算符和重复/重试次数边界，减少运行时配置错误。
- 已完成：结果保存步骤提供字段选择器，可从前置步骤选择版本、状态或输出并自动生成数据引用。
- 已完成：执行预览逐步展示每个动作，并标注人工确认与重复执行次数，运行前可理解影响范围。
- 已完成：执行结果页把等待子任务、状态未知和跳过步骤转换为业务化文案与图标，避免普通用户接触执行器内部状态。
- 已完成：TaskPlan 增加并行组契约字段，并拒绝同组内存在依赖关系的步骤；运行器并发实现需继续接入设备资源锁后开放。
- 已完成：Studio 步骤设置支持填写可选并行组，执行预览会显示并行组名称；空值保持顺序执行。
- 已完成：TaskPlan 提供依赖安全的 `execution_batches()` 调度契约，可将已就绪的同组步骤组成批次；实际并发运行仍需接入持久化状态聚合。
- 已完成：发布前校验禁止连接、上传、下载和重启步骤加入并行组，先确保并行能力不会绕过设备状态安全边界。
- 已完成：发布前校验同样禁止人工确认步骤加入并行组，避免等待决策的子任务被并行批次错误取消。
- 已完成：TaskOrchestrator 消费并行批次并发执行独立步骤，等待批次全部完成后聚合输出；恢复任务仍沿用已有子任务状态路径。
- 已完成：并行批次失败时会取消同批次未完成子任务并将首个业务错误聚合到父任务，避免孤儿执行。
- 已完成：并行批次开始前持久化 `parallel_batch` 元数据，完成或失败后清理；进程中断时父任务会保留“等待子任务”语义，便于恢复审计。
- 已完成：并行子任务创建后立即写回父任务 `node_runs`，批次中途进程退出时可定位已启动的子任务，避免重复创建。
- 已完成：补充部分批次恢复契约测试，已持久化的并行节点会复用其输出，缺失节点才会继续执行。
- 已完成：并行节点继续遵守步骤级重试策略，补充并行路径重试后成功的回归测试。
- 验证记录：完整 Python 套件当前为 731 passed / 9 failed；失败来自既有 Electron parity 断言和 sample data 凭据断言，Workflow 专项测试与桌面构建均通过。
- 已完成：任务列表与时间线使用业务化状态文案；并行批次中的步骤会显示“执行中/已完成/执行失败”等用户可理解状态，重试次数也不再暴露内部 attempt 字段。
- 已完成：运行前预览增加并行批次摘要，明确提示哪些步骤会同时执行，帮助用户理解实际影响范围。
- 已完成：`device.info` 输出结构化 `software_version`，`result.save` 产出业务结果记录，验收主线具备稳定数据传递。
- 已调整：当前阶段不启用风险拦截和二次确认，重启、上传等动作按普通步骤直接配置和执行，优先保证业务流程可用。
- 已完成：执行入口不再因校验问题直接禁用；点击后展示具体缺失项并可定位到对应步骤，底部保留可点击的问题清单。
- 已完成：步骤级失败重试配置（1-5 次）编译到 TaskPlan，并由编排器自动重试失败子流程。
- 已完成：从失败步骤或指定步骤继续时，清除该步骤及其后继节点的执行状态，保留前置成功结果。
- 已完成：任务页“重新执行此步骤 / 从上一步继续”与 Framework 任务状态重置逻辑打通，并覆盖回归测试。
- 已完成：批量目标选择与逐设备任务创建、结果字段选择器、单步测试（自动包含前置步骤）；任务页支持导出业务化 CSV 报告。
- 架构决策：Workflow Studio 只生成 `Workflow Definition`；编译器负责把业务动作和条件转换为 Framework `TaskPlan`，运行器负责分支路由和状态，具体动作仍由注册的 Action Executor 执行。
- 验收主线：选择设备 → 获取版本 → 版本低于阈值时执行上传 → 保存结果，已有编译和运行器回归测试。

### 下一阶段目标计划

1. **P0 闭环（已完成）**：批量目标、字段选择器、单步测试、版本检查主线和 10 分钟内可开始的任务入口均已落地；后续只做体验回归。
2. **P1 执行体验（进行中）**：Dry Run 影响摘要、业务化失败原因、步骤级重试和从指定步骤继续已落地；风险策略暂不参与流程校验。
3. **P2 复杂流程（进行中）**：循环、人工确认、汇总结果、报告导出、独立步骤并行执行及批次恢复已完成；控制节点并行边界已校验，后续可扩展更复杂的并行等待策略。
4. **P3 扩展能力**：支持子 Workflow、API/Webhook、自定义 Action、高级表达式与权限审批，保持 Action Catalog 向后兼容。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a P0 no-code Workflow lifecycle from library and visual editing through validation, publication, Task creation, and execution visibility.

**Architecture:** Add a framework-independent WorkflowDefinitionStore and ActionCatalog boundary, expose CRUD/validate/publish/run APIs, and compile immutable published versions into the existing TaskService boundary. Keep Vue Studio dependent on typed API contracts and catalog metadata; execution remains owned by the existing Task/Workflow engine.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic, SQLite, pytest, Vue 3, TypeScript, lucide-vue-next.

**Spec:** `docs/superpowers/specs/2026-09-12-workflow-studio-optimization-design.md`

## Global Constraints

- Python backend must not add PySide/PyQt dependencies.
- Workflow and Task versions are immutable after publication.
- Renderer must not receive credentials or privileged execution details.
- New Python code uses 4-space indentation, type hints, and snake_case.
- Validate with pytest, `python -m compileall -q device_tui`, `cd desktop && npm run typecheck`, and `cd desktop && npm run build`.

### Task 1: Define generic workflow domain contracts

**Files:**
- Create: `device_tui/application/workflow_studio/models.py`
- Create: `device_tui/application/workflow_studio/catalog.py`
- Create: `device_tui/application/workflow_studio/validation.py`
- Create: `device_tui/application/workflow_studio/__init__.py`
- Test: `tests/test_workflow_studio_models.py`
- Test: `tests/test_workflow_studio_validation.py`

**Interfaces:**
- `WorkflowDraft`, `WorkflowVersion`, `WorkflowNode`, `WorkflowEdge`, `WorkflowInput` dataclasses with `to_dict()`/`from_dict()`.
- `ActionSpec(id, name, category, input_schema, output_schema, risk, executor_id)` and `build_action_catalog()`.
- `validate_workflow(workflow: WorkflowDraft, catalog: ActionCatalog) -> ValidationResult` returning errors and warnings with node ids.

- [x] Write tests for round-trip serialization, unknown actions, missing required config, disconnected nodes, and invalid conditions; risk metadata does not block validation in the current phase.
- [ ] Run `pytest tests/test_workflow_studio_models.py tests/test_workflow_studio_validation.py -v` and confirm failures.
- [ ] Implement immutable-friendly models and deterministic validation (including cycle detection and variable reference checks).
- [ ] Re-run the focused tests and confirm pass.
- [ ] Commit `feat: add generic workflow studio contracts`.

### Task 2: Add durable workflow definition store

**Files:**
- Create: `device_tui/application/workflow_studio/store.py`
- Modify: `device_tui/infrastructure/persistence/sqlite_workflows.py`
- Modify: `device_tui/application/desktop.py`
- Test: `tests/test_workflow_definition_store.py`

**Interfaces:**
- `WorkflowDefinitionStore.create/save/get/list/delete/publish` with published snapshot retention.
- `SQLiteWorkflowDefinitionStore(path: Path)` using a dedicated `workflow_definitions` table and JSON payloads.
- Desktop composition exposes `desktop.workflow_definitions`.

- [ ] Write tests covering draft CRUD, version increment, published snapshot immutability, and delete protection for referenced published versions.
- [ ] Run the focused test file and confirm failures.
- [ ] Implement store protocol and SQLite adapter without changing existing run/task tables.
- [ ] Wire the store into desktop composition and run focused tests.
- [ ] Commit `feat: persist workflow definitions and versions`.

### Task 3: Expose Workflow Studio APIs and Task compiler

**Files:**
- Modify: `device_tui/interfaces/desktop_api/models.py`
- Create: `device_tui/interfaces/desktop_api/routers/workflows.py`
- Modify: `device_tui/interfaces/desktop_api/app.py`
- Create: `device_tui/application/workflow_studio/compiler.py`
- Test: `tests/test_workflow_studio_api.py`
- Test: `tests/test_workflow_studio_compiler.py`

**Interfaces:**
- `GET /api/v1/workflow-definitions`
- `POST /api/v1/workflow-definitions`
- `GET /api/v1/workflow-definitions/{id}`
- `PUT /api/v1/workflow-definitions/{id}`
- `DELETE /api/v1/workflow-definitions/{id}`
- `POST /api/v1/workflow-definitions/{id}/validate`
- `POST /api/v1/workflow-definitions/{id}/publish`
- `POST /api/v1/workflow-definitions/{id}/run`
- `compile_published_workflow(version, target, inputs) -> TaskCreate`

- [ ] Write API tests for CRUD, validation errors, publish rejection, and run response containing `workflow_id` and `workflow_version`.
- [ ] Write compiler tests proving action ids map only through catalog executors and preserve node ids in metadata.
- [ ] Run focused tests and confirm failures.
- [ ] Implement request/response models, router authorization, compiler adapter, and app registration.
- [ ] Run focused tests plus existing task API tests.
- [ ] Commit `feat: expose workflow studio APIs and task compilation`.

### Task 4: Implement typed renderer API and Workflow Library

**Files:**
- Modify: `desktop/src/renderer/src/types.ts`
- Modify: `desktop/src/renderer/src/transport/api.ts`
- Modify: `desktop/src/renderer/src/stores/workspace.ts`
- Create: `desktop/src/renderer/src/components/WorkflowLibrary.vue`
- Modify: `desktop/src/renderer/src/App.vue`
- Modify: `desktop/src/renderer/src/styles.css`

**Interfaces:**
- `WorkflowDefinition`, `WorkflowSummary`, `ActionSpec`, `ValidationResult` TypeScript types.
- `desktopApi.workflowDefinitions()`, `createWorkflowDefinition()`, `saveWorkflowDefinition()`, `validateWorkflowDefinition()`, `publishWorkflowDefinition()`, `runWorkflowDefinition()`.
- Store actions `refreshWorkflowDefinitions`, `createWorkflowDraft`, `publishWorkflow`, `runWorkflow`.

- [ ] Add typed API methods and store state without breaking current workflow catalog/task state.
- [ ] Add Library view with search, status filter, new/duplicate/delete, and version/status display.
- [ ] Add navigation entry and styles matching existing desktop visual language.
- [x] Run `cd desktop && npm run typecheck` and fix all type errors.
- [ ] Commit `feat: add workflow library UI`.

### Task 5: Implement Workflow Studio editor and validation UX

**Files:**
- Create: `desktop/src/renderer/src/components/WorkflowStudio.vue`
- Create: `desktop/src/renderer/src/components/WorkflowCanvas.vue`
- Create: `desktop/src/renderer/src/components/WorkflowProperties.vue`
- Modify: `desktop/src/renderer/src/components/WorkflowLibrary.vue`
- Modify: `desktop/src/renderer/src/styles.css`

**Interfaces:**
- Studio emits `save`, `validate`, `publish`, `run`, and `close` events with `WorkflowDefinition` payloads.
- Canvas edits `nodes` and `edges` through stable node ids; Properties edits selected node config and input mappings using `ActionSpec` schemas.

- [ ] Implement failing behavior checks for adding an action, connecting sequential nodes, editing config, and rendering validation errors/warnings.
- [ ] Implement three-column Studio with keyboard-accessible controls, explicit start/end nodes, and condition branch handles.
- [ ] Add client-side draft normalization only; server validation remains authoritative.
- [x] Run typecheck and build; automated editor/API flows verified.
- [ ] Commit `feat: add workflow studio editor`.

### Task 6: Integrate execution monitoring and regression validation

**Files:**
- Modify: `desktop/src/renderer/src/components/TaskWorkspace.vue`
- Modify: `desktop/src/renderer/src/stores/workspace.ts`
- Test: `tests/test_workflow_studio_regression.py`

- [ ] Add regression tests proving a published workflow creates a Task that uses the exact published version and that execution failures retain node ids.
- [x] Display Workflow name/version in TaskWorkspace and link to current step when present.
- [x] Ensure cancel/retry use existing TaskService endpoints and do not bypass the compiler.
- [ ] Run `python -m pytest tests/test_workflow_studio_regression.py tests/test_task_service.py tests/test_task_projection.py -v`.
- [ ] Run `python -m compileall -q device_tui`.
- [ ] Run `cd desktop && npm run typecheck` and `npm run build`.
- [ ] Commit `feat: connect published workflows to execution monitoring`.

### Task 7: Final architecture review and documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-09-12-no-code-workflow-mvp-design.md` if implementation decisions materially changed.
- Create: `docs/workflows/no-code-workflow-mvp.md`

- [x] Document extension points for adding an ActionSpec/executor without changing Studio core.
- [x] Document API lifecycle and version guarantees.
- [x] Run the complete Python test suite and desktop checks; record the existing 9-test baseline failures separately from Workflow validation.
- [x] Inspect git diff for credential leakage, renderer privilege expansion, and accidental changes to existing automation rules.
- [ ] Commit `docs: document workflow studio architecture`.
