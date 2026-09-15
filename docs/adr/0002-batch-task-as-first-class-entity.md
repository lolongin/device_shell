# ADR 0002: Batch Task 作为一等公民

## 状态

已接受 (Accepted) - 2026-09-13

## 背景

当前系统支持批量执行：用户选择多台设备运行一个 workflow。实现方式是：

```python
# workflow_definitions.py:418-421
records = [
    ctx.desktop.task_service.create(TaskCreate(...))
    for target_id in device_ids
]
```

这会创建 N 个独立的 Task 记录，每个对应一台设备。

### 问题

**用户视角**：
- "我执行了一次批量升级操作"
- "这次操作升级了20台设备"
- "我需要一份这次操作的报告"

**系统视角**（当前）：
- 创建了20个独立 Task
- 任务列表显示20条记录
- 没有"批次"的概念

**导致的问题**：
1. 任务列表混乱（100台设备 = 100条任务记录）
2. 无法批量控制（暂停/取消需要逐个操作）
3. 报告生成困难（需要手动汇总20个任务的结果）
4. 失败重试粒度不清晰（整个批次 vs 单台设备）

## 决策

**将 Batch Task 设计为一等公民**，作为独立的领域实体。

### 核心概念

```typescript
interface BatchTask {
  batch_id: string              // 批次唯一标识
  workflow_id: string           // 关联的 Process
  created_by: string
  created_at: timestamp
  
  // 目标设备
  target_devices: string[]      // 设备 ID 列表
  
  // 子任务
  child_task_ids: string[]      // 每台设备的 Task ID
  
  // 聚合状态
  aggregate_status: BatchStatus
  summary: {
    total: number
    completed: number
    failed: number
    running: number
    pending: number
  }
  
  // 批量配置
  concurrency: number           // 并发度（同时执行多少台）
  failure_strategy: "continue" | "stop_on_first_failure" | "stop_on_threshold"
  failure_threshold?: number    // 失败率阈值（如 10%）
}

enum BatchStatus {
  PENDING = "pending",
  RUNNING = "running",
  COMPLETED = "completed",
  PARTIAL_FAILURE = "partial_failure",  // 部分失败
  FAILED = "failed",                     // 全部失败
  CANCELLED = "cancelled"
}
```

### 实现架构

**数据库层**：
```sql
CREATE TABLE batch_tasks (
  batch_id TEXT PRIMARY KEY,
  workflow_id TEXT NOT NULL,
  target_devices JSON NOT NULL,
  concurrency INTEGER DEFAULT 5,
  failure_strategy TEXT DEFAULT 'continue',
  aggregate_status TEXT NOT NULL,
  summary JSON NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 修改现有 tasks 表
ALTER TABLE tasks ADD COLUMN batch_id TEXT REFERENCES batch_tasks(batch_id);
```

**后端 API**：
```python
# 新增批量任务创建接口
@router.post("/api/v1/batch-tasks")
async def create_batch_task(payload: BatchTaskCreate) -> BatchTaskResponse:
    batch = BatchTask(
        batch_id=generate_batch_id(),
        workflow_id=payload.workflow_id,
        target_devices=payload.device_ids,
        concurrency=payload.concurrency or 5
    )
    
    # 创建子任务（按并发度控制）
    child_tasks = []
    for device_id in payload.device_ids[:payload.concurrency]:
        task = task_service.create(TaskCreate(..., batch_id=batch.batch_id))
        child_tasks.append(task)
    
    batch.child_task_ids = [t.id for t in child_tasks]
    batch_repository.save(batch)
    
    # 启动批量调度器
    batch_scheduler.schedule(batch)
    
    return BatchTaskResponse(batch=batch, child_tasks=child_tasks)

# 批量任务控制接口
@router.post("/api/v1/batch-tasks/{batch_id}/pause")
@router.post("/api/v1/batch-tasks/{batch_id}/cancel")
@router.post("/api/v1/batch-tasks/{batch_id}/retry-failed")
```

**前端 UI**：
```vue
<template>
  <div class="task-list">
    <!-- 批量任务卡片 -->
    <div v-for="batch in batchTasks" :key="batch.batch_id" class="batch-card">
      <div class="batch-header">
        <h3>{{ batch.workflow_name }}</h3>
        <badge :status="batch.aggregate_status">{{ statusLabel(batch) }}</badge>
      </div>
      
      <div class="batch-summary">
        <div class="stat">
          <span class="icon">✓</span>
          <span>成功：{{ batch.summary.completed }}</span>
        </div>
        <div class="stat error">
          <span class="icon">✗</span>
          <span>失败：{{ batch.summary.failed }}</span>
        </div>
        <div class="stat">
          <span class="icon">⏳</span>
          <span>进行中：{{ batch.summary.running }}</span>
        </div>
      </div>
      
      <!-- 展开查看子任务 -->
      <button @click="toggleExpand(batch)">
        {{ batch.expanded ? '收起' : '查看详情' }}
      </button>
      
      <div v-if="batch.expanded" class="child-tasks">
        <task-item
          v-for="task in batch.child_tasks"
          :key="task.id"
          :task="task"
          :compact="true"
        />
      </div>
      
      <!-- 批量操作 -->
      <div class="batch-actions">
        <button @click="pauseBatch(batch)" v-if="batch.aggregate_status === 'running'">
          暂停批次
        </button>
        <button @click="retryFailed(batch)" v-if="batch.summary.failed > 0">
          重试失败的设备
        </button>
        <button @click="exportReport(batch)">
          导出报告
        </button>
      </div>
    </div>
  </div>
</template>
```

## 为什么这样设计？

### 考虑的替代方案

**方案A：保持当前设计，UI 层聚合**
```typescript
// 不创建 BatchTask 实体，只在前端按 workflow_id + created_at 分组
function groupTasks(tasks: Task[]): GroupedView[] {
  // 启发式分组逻辑
}
```
- 优点：无需修改后端，实现简单
- 缺点：
  - 分组逻辑不可靠（如何区分"同一批次"？）
  - 无法批量控制（暂停需要逐个 API 调用）
  - 报告生成困难（前端汇总有限）

**方案B：BatchTask 是 Task 的特殊类型**
```python
class Task:
    type: Literal["single", "batch"]
    target_devices: list[str]  # 批量任务才有
```
- 优点：复用现有 Task 表和逻辑
- 缺点：
  - Task 概念被污染（单一职责原则）
  - 批量特有逻辑（并发控制、失败策略）难以融入
  - 状态机复杂（单任务 vs 批量任务的状态转换不同）

**方案C：BatchTask 是一等公民**（选中）
- 优点：
  - **清晰的领域边界**：Batch 是独立的业务概念
  - **独立的状态管理**：不干扰单任务逻辑
  - **强大的批量能力**：并发控制、失败策略、批量操作
  - **更好的报告支持**：聚合数据直接持久化
- 缺点：
  - 需要新增表和 API（开发成本）
  - 数据模型复杂度略增

### 关键权衡

1. **业务语义优先**：运维操作的单元是"批次"而非"单台设备"
2. **报告需求**：用户需要"本次升级报告"而非"20个设备的报告"
3. **批量控制**：暂停/取消必须原子化，不能分散为N个操作
4. **性能考虑**：聚合查询（统计成功/失败数）应在写入时计算，而非每次查询时汇总

## 影响

### 用户体验变化

**之前**：
```
任务列表：
- Task #abc - 设备A 升级
- Task #def - 设备B 升级
- Task #ghi - 设备C 升级（失败）
... (共20条，需滚动查看)
```

**之后**：
```
任务列表：
- 批量升级 #batch123
  ├─ 成功：15台
  ├─ 失败：3台
  └─ 进行中：2台
  [查看详情] [重试失败] [导出报告]
```

### 开发影响

**需要修改的模块**：
1. ✅ 后端：新增 BatchTask 实体和 Repository
2. ✅ 后端：修改 workflow 运行接口，返回 BatchTask
3. ✅ 前端：任务列表组件支持批量卡片
4. ✅ 前端：批量控制操作（暂停/重试）
5. ✅ 报告生成：基于 BatchTask 聚合数据

**兼容性**：
- 旧的单台设备任务：`batch_id = null`（兼容）
- 新的批量任务：`batch_id != null`（新功能）

### 迁移路径

**阶段1**：数据库迁移
```sql
-- 添加 batch_tasks 表
-- 为 tasks 表添加 batch_id 列（nullable）
```

**阶段2**：后端实现
```python
# 实现 BatchTaskService
# 修改 workflow_definitions.py 的 run 接口
# 添加批量控制 API
```

**阶段3**：前端适配
```typescript
// 任务列表支持批量卡片
// 批量操作按钮
// 详情展开/收起
```

**阶段4**：灰度发布
- 仅对新创建的批量任务启用（batch_id != null）
- 旧任务仍按原方式显示
- 观察1周，收集反馈

## 验收标准

- [ ] 数据库 schema 迁移完成，所有测试通过
- [ ] 批量任务创建 API 可用，返回正确的 BatchTask
- [ ] 任务列表正确显示批量卡片和聚合状态
- [ ] 批量控制操作（暂停/取消/重试）功能正常
- [ ] 报告导出基于 BatchTask 生成，包含聚合统计
- [ ] 性能测试：100台设备批量任务<3秒创建，列表加载<200ms
- [ ] 兼容性：旧的单任务记录正常显示和操作

## 参考资料

- [CONTEXT.md](../../CONTEXT.md) - Batch Task 领域定义
- Domain-Driven Design: Tackling Complexity in the Heart of Software (Eric Evans)
