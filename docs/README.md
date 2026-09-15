# Device TUI 文档中心

欢迎来到 Device TUI 项目文档中心。这里包含了项目的所有技术文档、设计决策和实施指南。

---

## 🚀 最新项目：Workflow Studio 改进

**状态**：✅ 设计完成，待启动  
**目标**：解决 Workflow Studio 核心可用性问题，提升用户体验  
**预计周期**：3个阶段共6-8周，第一阶段2周

### 快速入口

| 你想了解... | 请阅读 | 时间 |
|-------------|--------|------|
| **项目概况** | [执行摘要](./WORKFLOW_STUDIO_IMPROVEMENT_SUMMARY.md) | 10分钟 |
| **如何开始** | [快速启动清单](./WORKFLOW_STUDIO_CHECKLIST.md) | 30分钟 |
| **所有文档** | [文档索引](./WORKFLOW_STUDIO_INDEX.md) | 5分钟 |
| **交付总结** | [交付文档](./WORKFLOW_STUDIO_DELIVERY.md) | 15分钟 |

---

## 📚 文档分类

### 核心概念

- **[CONTEXT.md](../CONTEXT.md)** - 领域模型和通用语言
  - Process、Node、Batch Task 等核心概念
  - 通用语言约定
  - 边界上下文划分

### 架构设计

- **[architecture/desktop-v2.md](./architecture/desktop-v2.md)** - Desktop 架构说明
  - Electron + Vue + Python FastAPI 架构
  - 层次边界和职责划分
  
- **[device-source-plugins.md](./device-source-plugins.md)** - 设备数据源插件系统

### 架构决策记录（ADR）

- **[adr/0001-workflow-studio-improvement-strategy.md](./adr/0001-workflow-studio-improvement-strategy.md)**
  - Workflow Studio 改进策略
  - 为什么选择分层改进而非重写
  
- **[adr/0002-batch-task-as-first-class-entity.md](./adr/0002-batch-task-as-first-class-entity.md)**
  - Batch Task 设计决策
  - 为什么作为一等公民

### 实施指南

- **[implementation/README.md](./implementation/README.md)** - 开发指南
  - 环境准备
  - 开发工作流
  - 测试策略
  
- **[implementation/stage1-detailed-plan.md](./implementation/stage1-detailed-plan.md)** - 阶段1详细计划
  - Day-by-day 任务清单
  - 代码示例
  - 验收标准

### 改进方案

- **[WORKFLOW_STUDIO_IMPROVEMENTS.md](../WORKFLOW_STUDIO_IMPROVEMENTS.md)** - 详细改进方案
  - 问题深度分析
  - 技术选型对比
  - 完整实施路线图

---

## 🎯 按角色导航

### 项目经理 / 产品经理

推荐阅读顺序：
1. [执行摘要](./WORKFLOW_STUDIO_IMPROVEMENT_SUMMARY.md) - 了解项目背景和目标
2. [快速启动清单](./WORKFLOW_STUDIO_CHECKLIST.md) - 启动项目所需的准备
3. [ADR 0001](./adr/0001-workflow-studio-improvement-strategy.md) - 理解关键决策

**预计时间**：30-45分钟

---

### 前端开发工程师

推荐阅读顺序：
1. [阶段1详细计划](./implementation/stage1-detailed-plan.md) - 了解具体任务
2. [CONTEXT.md](../CONTEXT.md) - 理解领域模型
3. [实施指南](./implementation/README.md) - 开发工作流和规范

**关键技术**：Vue 3、TypeScript、Vue Flow、Pinia

**预计时间**：1小时

---

### 后端开发工程师

推荐阅读顺序：
1. [CONTEXT.md](../CONTEXT.md) - 理解领域模型
2. [ADR 0002](./adr/0002-batch-task-as-first-class-entity.md) - Batch Task 设计
3. [阶段1详细计划](./implementation/stage1-detailed-plan.md) - Day 9 后端任务

**关键技术**：Python、FastAPI、SQLite、Dataclasses

**预计时间**：1小时

---

### 技术负责人 / 架构师

推荐阅读顺序：
1. [执行摘要](./WORKFLOW_STUDIO_IMPROVEMENT_SUMMARY.md) - 项目全貌
2. [详细改进方案](../WORKFLOW_STUDIO_IMPROVEMENTS.md) - 深度技术分析
3. [CONTEXT.md](../CONTEXT.md) - 领域模型
4. [ADR 0001](./adr/0001-workflow-studio-improvement-strategy.md) + [ADR 0002](./adr/0002-batch-task-as-first-class-entity.md)
5. [实施指南](./implementation/README.md)

**预计时间**：2小时

---

## 🗂️ 文档结构

```
docs/
├── README.md                                    # 本文档
├── WORKFLOW_STUDIO_IMPROVEMENT_SUMMARY.md      # 执行摘要 ⭐
├── WORKFLOW_STUDIO_CHECKLIST.md                # 快速启动清单 ✅
├── WORKFLOW_STUDIO_INDEX.md                    # 文档索引 📑
├── WORKFLOW_STUDIO_DELIVERY.md                 # 交付总结 📦
│
├── adr/                                         # 架构决策记录 🏛️
│   ├── 0001-workflow-studio-improvement-strategy.md
│   └── 0002-batch-task-as-first-class-entity.md
│
├── architecture/                                # 架构文档 🏗️
│   └── desktop-v2.md
│
├── implementation/                              # 实施指南 🛠️
│   ├── README.md
│   └── stage1-detailed-plan.md
│
├── superpowers/                                 # 功能设计 💡
│   ├── specs/                                   # 规格说明
│   └── plans/                                   # 实施计划
│
└── device-source-plugins.md                     # 插件系统 🔌

根目录/
├── CONTEXT.md                                   # 领域模型 📖
├── WORKFLOW_STUDIO_IMPROVEMENTS.md             # 详细改进方案 📊
└── CLAUDE.md                                    # 项目开发指南
```

---

## 🔍 快速查找

### 常见问题

- **Q: 如何理解项目的领域模型？**  
  A: 阅读 [CONTEXT.md](../CONTEXT.md)

- **Q: 为什么要改进 Workflow Studio？**  
  A: 阅读 [执行摘要 - 现状分析](./WORKFLOW_STUDIO_IMPROVEMENT_SUMMARY.md#-现状分析)

- **Q: 如何开始开发？**  
  A: 按照 [快速启动清单](./WORKFLOW_STUDIO_CHECKLIST.md) 操作

- **Q: Batch Task 是什么？**  
  A: 阅读 [ADR 0002](./adr/0002-batch-task-as-first-class-entity.md)

- **Q: 项目需要多久？**  
  A: 3个阶段共6-8周，详见 [执行摘要 - 路线图](./WORKFLOW_STUDIO_IMPROVEMENT_SUMMARY.md#️-实施路线图)

### 技术细节

- **Vue Flow 集成**：[阶段1详细计划 - Day 2-6](./implementation/stage1-detailed-plan.md#week-1-day-2---vue-flow-poc)
- **撤销/重做实现**：[阶段1详细计划 - Day 7-8](./implementation/stage1-detailed-plan.md#week-2-day-7---撤销栈实现)
- **BatchTask 数据模型**：[ADR 0002 - 实现架构](./adr/0002-batch-task-as-first-class-entity.md#实现架构)
- **性能优化策略**：[详细改进方案 - 性能瓶颈](../WORKFLOW_STUDIO_IMPROVEMENTS.md)

---

## 📝 文档规范

### 创建新文档

1. **ADR（架构决策记录）**
   - 命名：`adr/NNNN-decision-title.md`
   - 格式参考：现有 ADR 文档
   - 包含：背景、决策、替代方案、影响

2. **实施计划**
   - 放在：`implementation/`
   - 包含：任务清单、代码示例、验收标准

3. **设计规格**
   - 放在：`superpowers/specs/`
   - 命名：`YYYY-MM-DD-feature-name.md`

### 更新现有文档

- 重大变更：更新版本号和修改历史
- 小修正：直接更新，commit message 说明
- 废弃：在文档顶部标注 `[已废弃]`

---

## 🤝 贡献指南

### 改进文档

1. Fork 仓库
2. 在 `docs/` 目录下修改或新增文档
3. 确保链接正确，格式统一
4. 提交 PR，描述改进内容

### 报告问题

如果文档有以下问题，请反馈：
- 链接失效
- 内容过时
- 描述不清
- 示例错误

---

## 🔗 外部资源

### 技术文档

- [Vue 3 官方文档](https://vuejs.org/)
- [Vue Flow 文档](https://vueflow.dev/)
- [Pinia 状态管理](https://pinia.vuejs.org/)
- [FastAPI 文档](https://fastapi.tiangolo.com/)

### 方法论

- [Domain-Driven Design](https://martinfowler.com/bliki/DomainDrivenDesign.html)
- [Architecture Decision Records](https://adr.github.io/)
- [C4 Model](https://c4model.com/) - 软件架构可视化

---

## 📊 文档状态

| 文档 | 状态 | 最后更新 | 维护者 |
|------|------|----------|--------|
| CONTEXT.md | ✅ 完成 | 2026-09-13 | - |
| Workflow Studio 改进文档 | ✅ 完成 | 2026-09-13 | - |
| 架构文档 | ✅ 稳定 | - | - |
| 插件系统文档 | ✅ 稳定 | - | - |

---

## 📞 联系方式

**项目负责人**：待分配  
**文档维护**：项目负责人  
**技术支持**：技术负责人团队

---

**欢迎阅读，祝开发顺利！** 🚀

---

_最后更新：2026-09-13_
