<script setup lang="ts">
import { ref } from 'vue'
import { CheckCircle2, XCircle, Clock, Loader2, ChevronDown, ChevronUp, RefreshCw, Download, Pause } from 'lucide-vue-next'

interface BatchTaskSummary {
  total: number
  completed: number
  failed: number
  running: number
  pending: number
}

interface BatchTask {
  batch_id: string
  workflow_name: string
  aggregate_status: string
  summary: BatchTaskSummary
  created_at: string
  child_task_ids: string[]
}

const props = defineProps<{
  batch: BatchTask
}>()

const emit = defineEmits<{
  retryFailed: []
  pause: []
  cancel: []
  exportReport: []
  showDetails: []
}>()

const expanded = ref(false)

const statusConfig = {
  running: { label: '执行中', color: '#3b82f6', icon: Loader2 },
  completed: { label: '已完成', color: '#22c55e', icon: CheckCircle2 },
  partial_failure: { label: '部分失败', color: '#f59e0b', icon: XCircle },
  failed: { label: '失败', color: '#ef4444', icon: XCircle },
  pending: { label: '等待中', color: '#6b7280', icon: Clock },
  cancelled: { label: '已取消', color: '#6b7280', icon: XCircle }
}

const currentStatus = statusConfig[props.batch.aggregate_status as keyof typeof statusConfig] || statusConfig.running

const getProgressPercentage = () => {
  const { completed, failed, total } = props.batch.summary
  return total > 0 ? Math.round(((completed + failed) / total) * 100) : 0
}
</script>

<template>
  <div class="batch-card">
    <!-- 头部 -->
    <div class="batch-header">
      <div class="batch-title-row">
        <component :is="currentStatus.icon" :size="18" :class="{ spinning: batch.aggregate_status === 'running' }" />
        <h3>{{ batch.workflow_name }}</h3>
        <span class="status-badge" :style="{ background: currentStatus.color }">
          {{ currentStatus.label }}
        </span>
      </div>
      <div class="batch-meta">
        <span class="batch-id">{{ batch.batch_id.slice(0, 8) }}</span>
        <span class="batch-time">{{ new Date(batch.created_at).toLocaleString() }}</span>
      </div>
    </div>

    <!-- 进度条 -->
    <div class="progress-section">
      <div class="progress-bar">
        <div
          class="progress-fill"
          :style="{
            width: getProgressPercentage() + '%',
            background: currentStatus.color
          }"
        />
      </div>
      <span class="progress-text">{{ getProgressPercentage() }}%</span>
    </div>

    <!-- 统计摘要 -->
    <div class="batch-summary">
      <div class="stat-item success">
        <CheckCircle2 :size="16" />
        <span>成功：{{ batch.summary.completed }}</span>
      </div>
      <div v-if="batch.summary.failed > 0" class="stat-item error">
        <XCircle :size="16" />
        <span>失败：{{ batch.summary.failed }}</span>
      </div>
      <div v-if="batch.summary.running > 0" class="stat-item running">
        <Loader2 :size="16" class="spinning" />
        <span>进行中：{{ batch.summary.running }}</span>
      </div>
      <div v-if="batch.summary.pending > 0" class="stat-item pending">
        <Clock :size="16" />
        <span>待执行：{{ batch.summary.pending }}</span>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="batch-actions">
      <button @click="expanded = !expanded" class="action-btn secondary">
        <component :is="expanded ? ChevronUp : ChevronDown" :size="14" />
        {{ expanded ? '收起' : '查看详情' }}
      </button>

      <button
        v-if="batch.aggregate_status === 'running'"
        @click="emit('pause')"
        class="action-btn secondary"
      >
        <Pause :size="14" />
        暂停
      </button>

      <button
        v-if="batch.summary.failed > 0"
        @click="emit('retryFailed')"
        class="action-btn primary"
      >
        <RefreshCw :size="14" />
        重试失败
      </button>

      <button
        @click="emit('exportReport')"
        class="action-btn secondary"
      >
        <Download :size="14" />
        导出报告
      </button>
    </div>

    <!-- 展开的详情 -->
    <div v-if="expanded" class="batch-details">
      <div class="details-header">
        <span>子任务列表（{{ batch.child_task_ids.length }}）</span>
      </div>
      <div class="child-tasks-placeholder">
        <p>点击"查看详情"按钮加载完整的子任务信息</p>
        <button @click="emit('showDetails')" class="load-details-btn">
          加载子任务
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.batch-card {
  padding: 18px 20px;
  background: rgba(30, 41, 59, 0.6);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 10px;
  margin-bottom: 12px;
  transition: all 0.2s;
}

.batch-card:hover {
  background: rgba(30, 41, 59, 0.8);
  border-color: rgba(148, 163, 184, 0.4);
}

.batch-header {
  margin-bottom: 16px;
}

.batch-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.batch-title-row svg {
  color: #94a3b8;
  flex-shrink: 0;
}

.batch-title-row h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: #e2e8f0;
  flex: 1;
}

.status-badge {
  padding: 3px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  color: white;
}

.batch-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: #64748b;
  padding-left: 28px;
}

.batch-id {
  font-family: monospace;
}

.progress-section {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.progress-bar {
  flex: 1;
  height: 8px;
  background: rgba(51, 65, 85, 0.5);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  transition: width 0.3s ease;
  border-radius: 4px;
}

.progress-text {
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  min-width: 40px;
  text-align: right;
}

.batch-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 16px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #cbd5e1;
}

.stat-item.success {
  color: #86efac;
}

.stat-item.error {
  color: #fca5a5;
}

.stat-item.running {
  color: #93c5fd;
}

.stat-item.pending {
  color: #fcd34d;
}

.batch-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 14px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  font-size: 12px;
  font-weight: 500;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn.primary {
  background: #3b82f6;
  color: white;
}

.action-btn.primary:hover {
  background: #2563eb;
}

.action-btn.secondary {
  background: rgba(51, 65, 85, 0.5);
  color: #e2e8f0;
  border: 1px solid rgba(148, 163, 184, 0.3);
}

.action-btn.secondary:hover {
  background: rgba(51, 65, 85, 0.8);
  border-color: rgba(148, 163, 184, 0.5);
}

.batch-details {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.1);
}

.details-header {
  font-size: 13px;
  font-weight: 600;
  color: #cbd5e1;
  margin-bottom: 12px;
}

.child-tasks-placeholder {
  padding: 24px;
  text-align: center;
  background: rgba(15, 23, 42, 0.5);
  border: 1px dashed rgba(148, 163, 184, 0.3);
  border-radius: 8px;
  color: #94a3b8;
}

.child-tasks-placeholder p {
  margin: 0 0 12px;
  font-size: 13px;
}

.load-details-btn {
  padding: 8px 16px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.load-details-btn:hover {
  background: #2563eb;
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>
