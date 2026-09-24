<script setup lang="ts">
import { ChevronDown, Play, X } from 'lucide-vue-next'

type FlowPanelProps = {
  selected: any
  status: { label: string; tone: string }
  task: any
  taskTerminal: boolean
  currentStep: string
  error: string
  inputEntries: any[]
  stepLogs: any[]
  expandedStepIds: string[]
  running: boolean
  stepStatusLabel: (status: string) => string
  outputText: (value: string) => string
  onClose: () => void
  onToggleStep: (stepId: string) => void
  onRetry: () => void
  onResume: () => void
}
const props = defineProps<FlowPanelProps>()
</script>

<template>
<section class="workflow-flow-test-panel" aria-label="Flow 测试运行">
          <header class="workflow-flow-test-header">
            <div><span class="workflow-section-kicker">FLOW TEST</span><strong>测试运行</strong><small>{{ selected.name }}</small></div>
            <button type="button" class="icon-toolbar-button" title="返回步骤设置" aria-label="返回步骤设置" @click="onClose"><X :size="14" /></button>
          </header>
          <div class="workflow-flow-test-status" :class="`status-${status.tone}`"><span class="workflow-flow-test-dot"></span><strong>{{ status.label }}</strong><small v-if="task?.progress_percent != null">{{ Math.round(task.progress_percent) }}%</small></div>
          <div v-if="currentStep" class="workflow-flow-test-current"><span>{{ taskTerminal ? '最后执行步骤' : '当前步骤' }}</span><strong>{{ currentStep }}</strong></div>
          <p v-if="error" class="workflow-error workflow-flow-test-error">{{ error }}</p>
          <section class="workflow-flow-test-section workflow-test-data-section" aria-label="本次输入">
            <div class="workflow-flow-test-section-title"><strong>本次输入</strong><small>{{ inputEntries.length }} 个参数</small></div>
            <dl v-if="inputEntries.length" class="workflow-test-value-list"><div v-for="item in inputEntries" :key="item.name"><dt>{{ item.name }}<small>{{ item.type }}</small></dt><dd>{{ typeof item.value === 'object' ? JSON.stringify(item.value, null, 2) : String(item.value) }}</dd></div></dl>
            <p v-else class="workflow-test-empty">此流程没有定义输入参数。</p>
          </section>
          <section class="workflow-flow-test-section workflow-test-process-section"><div class="workflow-flow-test-section-title"><strong>执行过程</strong><small>{{ stepLogs.length }} 个步骤 · 展开查看详情</small></div><ol v-if="stepLogs.length" class="workflow-flow-test-log"><li v-for="item in stepLogs" :key="item.id" :class="`log-${item.status}`"><span class="workflow-flow-test-log-mark"></span><div class="workflow-flow-test-log-content"><button type="button" class="workflow-flow-step-toggle" :aria-expanded="expandedStepIds.includes(item.id)" @click="onToggleStep(item.id)"><span class="workflow-flow-step-heading"><span class="workflow-flow-step-id">{{ item.id }}</span><strong class="workflow-flow-step-title">{{ item.label }}</strong></span><span class="workflow-flow-step-status">{{ stepStatusLabel(item.status) }}</span><ChevronDown :size="14" class="workflow-flow-step-chevron" :class="{ expanded: expandedStepIds.includes(item.id) }" /></button><small v-if="item.status === 'pending'">等待任务调度</small><div v-if="expandedStepIds.includes(item.id)" class="workflow-flow-step-details"><div v-if="item.command" class="workflow-flow-command"><span>执行命令</span><code>{{ item.command }}</code></div><div v-if="item.script" class="workflow-flow-command"><span>{{ item.script }}</span></div><div v-if="item.exitCode !== undefined || item.resultStatus" class="workflow-flow-step-metrics"><span v-if="item.resultStatus">状态 <b>{{ item.resultStatus }}</b></span><span v-if="item.exitCode !== undefined">退出码 <b>{{ item.exitCode }}</b></span></div><section v-if="item.stdout" class="workflow-flow-terminal-output"><header><span>标准输出</span></header><pre>{{ outputText(item.stdout) }}</pre></section><section v-if="item.stderr" class="workflow-flow-terminal-output is-error"><header><span>错误输出</span></header><pre>{{ outputText(item.stderr) }}</pre></section><section v-if="item.dataText" class="workflow-flow-terminal-output"><header><span>执行结果</span></header><pre>{{ item.dataText }}</pre></section><section v-if="item.output && !item.stdout && !item.dataText" class="workflow-flow-terminal-output"><header><span>执行输出</span></header><pre>{{ outputText(item.output) }}</pre></section><p v-if="item.error && !item.stderr" class="workflow-flow-step-error">{{ item.error }}</p><small v-if="!item.stdout && !item.stderr && !item.dataText && !item.output && !item.error" class="workflow-flow-no-output">此步骤没有返回输出</small></div></div></li></ol><p v-else class="workflow-test-empty">测试开始后会逐步显示各步骤的状态与输出。</p></section>
          <button v-if="task && !running" type="button" class="connect-button workflow-flow-test-retry" @click="taskTerminal ? onRetry() : onResume()"><Play :size="13" />{{ taskTerminal ? '重新测试' : '继续监控' }}</button>
        </section>
</template>

<style src="./WorkflowFlowTestPanel.css"></style>
