<script setup lang="ts">
import { computed } from 'vue'
import { Bot, ShieldAlert, X } from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const selectedAction = computed(() => workspace.aiPlan?.actions || [])

async function plan(): Promise<void> {
  await workspace.buildAiPlan()
}
</script>

<template>
  <div v-if="workspace.aiPanelOpen" class="ai-backdrop" @mousedown.self="workspace.aiPanelOpen = false">
    <aside class="ai-workspace" role="dialog" aria-modal="true" aria-labelledby="ai-title">
      <header class="ai-header">
        <div class="ai-heading"><span class="ai-icon"><Bot :size="18" /></span><div><p class="eyebrow">PYTHON AI SERVICE</p><h2 id="ai-title">AI 操作助手</h2></div></div>
        <button class="icon-button" type="button" aria-label="关闭 AI 助手" @click="workspace.aiPanelOpen = false"><X :size="16" /></button>
      </header>
      <div class="ai-body">
        <section class="ai-card">
          <label for="ai-objective">目标</label>
          <textarea id="ai-objective" v-model="workspace.aiObjective" rows="3" placeholder="例如：查看当前设备版本" @keydown.ctrl.enter="plan"></textarea>
          <button class="primary-button" type="button" :disabled="workspace.aiBusy || !workspace.aiObjective.trim()" @click="plan"><Bot :size="14" />生成受控计划</button>
        </section>
        <section v-if="workspace.aiPlan" class="ai-card">
          <header><strong>执行计划</strong><span>{{ workspace.aiPlan.actions.length }} 个步骤</span></header>
          <p>{{ workspace.aiPlan.summary }}</p>
          <ol class="ai-action-list"><li v-for="(action, index) in selectedAction" :key="index"><span>{{ String(action.risk || 'OBSERVE') }}</span><div><strong>{{ String(action.label || action.kind) }}</strong><small>{{ String(action.command || action.device_id || '') }}</small></div></li></ol>
          <p v-if="workspace.aiPlan.warnings.length" class="ai-warning"><ShieldAlert :size="14" />{{ workspace.aiPlan.warnings.join('；') }}</p>
        </section>
        <p class="ai-empty">AI 请求会按受控工具直接执行；操作过程仍会记录审计日志。</p>
      </div>
    </aside>
  </div>
</template>
