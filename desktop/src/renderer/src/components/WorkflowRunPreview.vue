<script setup lang="ts">
import { AlertTriangle } from 'lucide-vue-next'

type RunPreviewProps = {
  workflowName: string
  targetCount: number
  stepCount: number
  taskGoal: string
  parallelGroups: string[]
  steps: any[]
  hasRisk: boolean
  confirmedRisks: boolean
  dryRunning: boolean
  onCancel: () => void
  onDryRun: () => void
  onConfirm: () => void
}
defineProps<RunPreviewProps>()
const emit = defineEmits<{ 'update:confirmedRisks': [value: boolean] }>()
</script>

<template>
<div class="workflow-preview-backdrop"><div class="workflow-preview"><h3>执行预览</h3><p><b>流程名称：</b>{{ workflowName }}</p><p><b>目标数量：</b>{{ targetCount }} 台</p><p><b>步骤数量：</b>{{ stepCount }} 步</p><p><b>任务目标：</b>{{ taskGoal }}</p><p v-if="parallelGroups.length" class="preview-parallel-summary"><b>并行执行：</b>{{ parallelGroups.join('；') }}</p><ol class="preview-step-list"><li v-for="(step, index) in steps" :key="`${step.label}-${index}`">{{ index + 1 }}. {{ step.label }}<small v-if="step.detail">{{ step.detail }}</small></li></ol><p class="preview-check">✓ 目标设备已选择　✓ 必填字段已填写　✓ 条件配置完整</p><p v-if="hasRisk" class="preview-risk-warning"><AlertTriangle :size="14" />包含脚本执行、重启或文件传输操作，请确认影响后继续。</p><label v-if="hasRisk" class="preview-risk-confirm"><input :checked="confirmedRisks" type="checkbox" @change="emit('update:confirmedRisks', ($event.target as HTMLInputElement).checked)" />我已确认高风险操作的影响</label><div class="preview-actions"><button type="button" @click="onCancel">取消</button><button type="button" :disabled="dryRunning" @click="onDryRun">模拟运行</button><button class="primary-action" type="button" :disabled="hasRisk && !confirmedRisks" @click="onConfirm">确认开始</button></div></div></div>
</template>

<style src="./WorkflowRunPreview.css"></style>
