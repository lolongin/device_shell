# Workflow Studio 改进实施指南

## 📋 项目概览

**目标**：解决 Workflow Studio 的核心可用性问题，提升用户体验和开发效率

**背景**：
- 当前系统有严重的可用性问题（伪画布、无撤销、批量任务混乱）
- 用户期望图形化流程设计，实际得到表单填写
- 代码质量问题（795行单体组件，难以维护）

**策略**：分3个阶段渐进改进，优先解决最痛的问题

---

## 🎯 阶段划分

### 阶段1：后端增强 + 快速体验改进（2周）✅ **当前阶段**

**核心价值**：用户在2周内就能感受到明显改善

**关键交付物**：
1. ✅ 真正的图形编辑器（Vue Flow）
2. ✅ 撤销/重做功能
3. ✅ 批量任务聚合显示
4. ✅ 增强的验证错误信息

**详细计划**：见 [stage1-detailed-plan.md](./stage1-detailed-plan.md)

---

### 阶段2：组件架构重构（2周）

**核心价值**：降低维护成本，提升开发速度

**关键交付物**：
1. Pinia store 状态管理
2. 组件拆分（<300行主组件）
3. TypeScript 类型完善
4. 性能优化（虚拟滚动、防抖）

---

### 阶段3：功能增强（2-4周）

**核心价值**：提升高级用户生产力

**关键交付物**：
1. 智能变量引用（自动补全）
2. 改进的条件构建器
3. 模板库（3-5个内置模板）
4. 快捷键系统
5. 搜索和过滤

---

## 📊 成功指标

### 用户体验指标

| 指标 | 当前 | 阶段1目标 | 最终目标 |
|------|------|-----------|----------|
| 创建10步流程时间 | 15分钟 | 10分钟 | **5分钟** |
| 新用户学习时间 | 2小时 | 1小时 | **30分钟** |
| 配置错误率 | 30% | 20% | **10%** |

### 技术指标

| 指标 | 当前 | 阶段1目标 | 最终目标 |
|------|------|-----------|----------|
| 主组件行数 | 795 | 600 | **<300** |
| 首次渲染时间 | ~200ms | <150ms | **<100ms** |
| 测试覆盖率 | 40% | 60% | **80%** |

---

## 🏗️ 架构设计

### 领域模型

见 [CONTEXT.md](../../CONTEXT.md)，核心概念：

- **Process**（流程）：用户设计的自动化操作序列
- **Batch Task**（批量任务）：针对多台设备的运维操作
- **Node**（节点）：分为 Execution / Control / Coordination 三类
- **Template**（模板）：参数化的流程蓝图

### 架构决策记录（ADR）

- [ADR 0001: Workflow Studio 改进策略](../adr/0001-workflow-studio-improvement-strategy.md)
- [ADR 0002: Batch Task 作为一等公民](../adr/0002-batch-task-as-first-class-entity.md)

---

## 🚀 快速开始

### 开发环境准备

```bash
# 后端依赖（Python 3.11+）
cd device_tui
python -m pip install -e ".[dev]"

# 前端依赖（Node 18+）
cd desktop
npm install

# 新增依赖（阶段1需要）
npm install @vue-flow/core @vue-flow/background @vue-flow/controls @vue-flow/minimap elkjs
```

### 运行测试

```bash
# 后端测试
python -m pytest tests/

# 前端测试
cd desktop
npm run test

# 类型检查
npm run typecheck
```

### 启动开发服务器

```bash
# 终端1：启动后端
python -m device_tui.interfaces.desktop_api

# 终端2：启动前端开发服务器
cd desktop
npm run dev
```

---

## 📁 项目结构

```
device_tui/
├── docs/
│   ├── adr/                          # 架构决策记录
│   │   ├── 0001-workflow-studio-improvement-strategy.md
│   │   └── 0002-batch-task-as-first-class-entity.md
│   └── implementation/               # 实施文档
│       └── stage1-detailed-plan.md  # 阶段1详细计划
│
├── CONTEXT.md                        # 领域模型定义
├── WORKFLOW_STUDIO_IMPROVEMENTS.md  # 改进方案总览
│
├── device_tui/
│   ├── domain/                      # 领域实体
│   │   └── batch_task.py           # BatchTask 实体（新增）
│   │
│   ├── application/
│   │   └── workflow_studio/        # Workflow Studio 应用层
│   │       ├── validation.py       # 验证引擎（待增强）
│   │       └── ...
│   │
│   └── infrastructure/
│       └── persistence/
│           └── sqlite_batch_tasks.py  # BatchTask 仓储（新增）
│
└── desktop/
    └── src/
        └── renderer/
            └── src/
                ├── components/
                │   ├── WorkflowLibrary.vue        # 主组件（待改进）
                │   ├── WorkflowCanvas.vue         # 画布组件（新增）
                │   ├── WorkflowNode.vue           # 节点组件（新增）
                │   └── BatchTaskCard.vue          # 批量卡片（新增）
                │
                ├── composables/
                │   └── useUndoRedo.ts            # 撤销/重做（新增）
                │
                └── utils/
                    └── layoutAlgorithms.ts       # 自动布局（新增）
```

---

## 🔄 开发工作流

### 分支策略

```bash
# 主分支
main                    # 生产环境，只接受合并

# 开发分支
develop                 # 开发主线
feature/stage1-vue-flow # 阶段1功能分支
feature/stage1-undo     # 撤销/重做功能
feature/batch-tasks     # 批量任务功能
```

### 提交规范

```bash
# 格式：<type>(<scope>): <subject>

feat(workflow): integrate Vue Flow canvas
fix(validation): add fix suggestions to errors
refactor(workflow): extract NodePropertyPanel component
test(batch-task): add repository integration tests
docs(adr): add batch task decision record
```

### Code Review 清单

- [ ] 代码符合 TypeScript/Python 规范
- [ ] 新增功能有测试覆盖
- [ ] 性能无明显回退
- [ ] 兼容现有数据
- [ ] 文档已更新

---

## 🧪 测试策略

### 单元测试

```bash
# 后端单元测试
pytest tests/test_workflow_studio_validation.py
pytest tests/test_batch_task_repository.py

# 前端单元测试
npm run test:unit
```

### 集成测试

```bash
# API 集成测试
pytest tests/test_workflow_studio_api.py

# 前端组件测试
npm run test:component
```

### E2E 测试

```bash
# 关键用户流程
npm run test:e2e

# 测试场景：
# 1. 创建新流程 → 添加节点 → 连接 → 保存
# 2. 批量运行 → 查看进度 → 重试失败
# 3. 撤销/重做操作
```

---

## 📈 进度追踪

### 阶段1任务看板

| 任务 | 负责人 | 状态 | 预计完成 |
|------|--------|------|----------|
| 增强验证错误信息 | - | 🔲 待开始 | Day 1 |
| Vue Flow POC | - | 🔲 待开始 | Day 2 |
| 自定义节点组件 | - | 🔲 待开始 | Day 3 |
| 集成到主组件 | - | 🔲 待开始 | Day 4-5 |
| 自动布局功能 | - | 🔲 待开始 | Day 6 |
| 撤销栈实现 | - | 🔲 待开始 | Day 7 |
| 集成撤销/重做 | - | 🔲 待开始 | Day 8 |
| BatchTask 后端 | - | 🔲 待开始 | Day 9 |
| 批量卡片组件 | - | 🔲 待开始 | Day 10 |

状态图例：
- 🔲 待开始
- 🏃 进行中
- ✅ 已完成
- ⚠️ 受阻

---

## ⚠️ 风险管理

### 已识别风险

| 风险 | 概率 | 影响 | 缓解措施 | 负责人 |
|------|------|------|----------|--------|
| Vue Flow 集成失败 | 低 | 高 | Day 2 完成 POC 验证 | - |
| 性能回退 | 中 | 中 | 每日性能测试 | - |
| 数据迁移问题 | 低 | 高 | 灰度发布 + 回滚方案 | - |
| 用户抵触新界面 | 中 | 中 | 提供经典模式切换 | - |

---

## 📞 沟通机制

### 每日站会

**时间**：每天早上 10:00  
**时长**：15分钟

**议程**：
1. 昨天完成了什么？
2. 今天计划做什么？
3. 有什么阻塞？

### 阶段回顾

**时间**：每个阶段结束后  
**时长**：1小时

**议程**：
1. 回顾目标达成情况
2. 讨论遇到的问题
3. 总结经验教训
4. 调整下一阶段计划

---

## 🎓 学习资源

### Vue Flow 文档

- [官方文档](https://vueflow.dev/)
- [示例集合](https://vueflow.dev/examples/)
- [API 参考](https://vueflow.dev/typedocs/)

### 领域驱动设计

- [CONTEXT.md](../../CONTEXT.md) - 项目领域模型
- Eric Evans: Domain-Driven Design
- Vaughn Vernon: Implementing Domain-Driven Design

### 前端架构

- [Vue 3 官方文档](https://vuejs.org/)
- [Pinia 状态管理](https://pinia.vuejs.org/)
- [TypeScript 深入理解](https://www.typescriptlang.org/docs/)

---

## 🤝 贡献指南

### 报告问题

在 GitHub Issues 中创建问题，包含：
- 问题描述
- 复现步骤
- 预期行为
- 实际行为
- 环境信息

### 提交改进

1. Fork 仓库
2. 创建功能分支（`git checkout -b feature/amazing-feature`）
3. 提交变更（`git commit -m 'feat: add amazing feature'`）
4. 推送到分支（`git push origin feature/amazing-feature`）
5. 创建 Pull Request

---

## 📝 常见问题

### Q: 为什么不直接重写？

A: 重写风险太高（8-10周投入），渐进式改进可以快速见效（2周内用户就能感受到改善），同时保持系统稳定性。

### Q: 现有 workflows 会受影响吗？

A: 不会。我们会保持数据兼容性，所有现有 workflows 都能无损迁移到新系统。

### Q: 如果阶段1效果不好怎么办？

A: Vue Flow 集成是孤立的，如果效果不好可以回退到旧版本。我们会在 Day 2 完成 POC 验证，确认可行后再全面推进。

### Q: 批量任务功能会影响现有单任务吗？

A: 不会。单任务和批量任务兼容并存（通过 `batch_id` 字段区分）。现有单任务功能完全不受影响。

---

## 📅 里程碑

- [ ] **2周后**：阶段1完成，用户可使用图形编辑器和撤销/重做
- [ ] **4周后**：阶段2完成，代码架构清晰，维护成本降低
- [ ] **6-8周后**：阶段3完成，完整的改进方案落地

---

## 联系方式

**项目负责人**：待定  
**技术负责人**：待定  
**产品负责人**：待定

---

**文档版本**：v1.0  
**最后更新**：2026-09-13  
**维护者**：Device TUI 开发团队
