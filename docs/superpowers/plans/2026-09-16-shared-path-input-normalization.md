# 共享目录路径输入易用性 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 让 Workflow 文件输入支持任意本机绝对路径，并在后端安全地暂存到文件传输共享目录后执行。

**Architecture:** 前端提供 Windows 文件选择器并保留用户输入；运行 API 在编排前解析上传源路径，绝对路径复制到共享目录下的任务暂存目录，节点使用暂存相对路径。共享目录 containment 校验继续由传输层负责。

**Tech Stack:** Vue 3 + TypeScript、Electron IPC、FastAPI、Python pathlib/pytest。

**Spec:** `docs/superpowers/specs/2026-09-16-shared-path-input-normalization-design.md`

## Global Constraints

- 允许直接填写本机绝对路径、Windows 分隔符和 `./` 前缀。
- 传输执行最终只接收共享目录内的相对路径。
- 禁止 `..` 越界、符号链接和共享目录外的暂存路径。
- 不记录凭据或完整敏感路径到日志。

### Task 1: 后端路径解析与暂存

**Files:**
- Modify: `device_tui/infrastructure/transfers/managed_file_transfer.py`
- Modify: `device_tui/interfaces/desktop_api/routers/workflow_definitions.py`
- Test: `tests/test_managed_file_transfer.py`, `tests/test_workflow_studio_api.py`

- [ ] 添加纯函数，将相对路径规范化；共享目录内绝对路径转换为相对路径；任意外部绝对路径复制到 `.<workflow-staging>/<task-id>/` 并返回相对路径。
- [ ] 在 Workflow 运行 API 创建 TaskPlan 前应用该函数，仅处理字面量上传源；变量引用保留运行时解析。
- [ ] 对不存在、目录、不可读、越界路径返回可理解的 `UnsupportedOperationError`。
- [ ] 添加覆盖 Windows 路径、`./`、共享目录内绝对路径、外部绝对路径和 `..` 的测试。

### Task 2: 前端文件选择和共享目录感知

**Files:**
- Modify: `desktop/src/preload/index.ts`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/renderer/src/env.d.ts`
- Modify: `desktop/src/renderer/src/transport/api.ts`
- Modify: `desktop/src/renderer/src/components/WorkflowLibrary.vue`

- [ ] 增加安全的本机文件选择 IPC，仅返回用户选择的路径。
- [ ] Workflow 运行参数中为 `package_path`/文件输入显示“选择文件”按钮，选择后回填绝对路径。
- [ ] 显示当前共享目录路径和“打开文件传输设置”入口；手动输入路径时即时统一分隔符并去除 `./` 前缀。
- [ ] 节点配置提示改为“可填写本机绝对路径或点击选择文件”。

### Task 3: 验证

**Files:**
- Test: `tests/test_workflow_studio_validation.py`

- [ ] 更新验证测试，确认绝对路径不再在 Studio 保存/运行前被误判为非法。
- [ ] 运行 Python 相关测试、`npm run typecheck` 和 `npm run build`。
