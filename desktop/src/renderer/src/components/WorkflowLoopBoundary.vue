<script setup lang="ts">
import { Handle, Position } from '@vue-flow/core'
import { Repeat2 } from 'lucide-vue-next'

defineProps<{
  data: {
    label?: string
    bodyCount?: number
    iterationLabel?: string
    explicit?: boolean
    entryHandleId?: string
    bodyHandleId?: string
    exitHandleId?: string
  }
}>()
</script>

<template>
  <div class="workflow-loop-boundary" aria-hidden="true">
    <div class="workflow-loop-boundary-label">
      <Repeat2 :size="13" />
      <strong>{{ data.label || '循环体' }}</strong>
      <span>{{ data.bodyCount || 0 }} 步 · {{ data.iterationLabel || '每次迭代' }}</span>
      <em v-if="data.explicit">已设边界</em>
    </div>
    <Handle
      v-if="data.entryHandleId"
      type="target"
      :id="data.entryHandleId"
      :position="Position.Top"
      class="workflow-loop-boundary-entry-handle"
    />
    <Handle
      v-if="data.bodyHandleId"
      type="source"
      :id="data.bodyHandleId"
      :position="Position.Bottom"
      class="workflow-loop-boundary-body-handle"
    />
    <Handle
      v-if="data.exitHandleId"
      type="source"
      :id="data.exitHandleId"
      :position="Position.Bottom"
      class="workflow-loop-boundary-exit-handle"
    />
  </div>
</template>

<style scoped>
.workflow-loop-boundary {
  position: relative;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  border: 1px dashed rgba(96, 165, 250, .66);
  border-radius: 12px;
  background: rgba(30, 64, 175, .07);
  pointer-events: none;
}
.workflow-loop-boundary-label {
  position: absolute;
  box-sizing: border-box;
  top: 10px;
  left: 10px;
  display: inline-flex;
  align-items: center;
  gap: 3px;
  min-height: 24px;
  max-width: calc(50% - 18px);
  padding: 0 5px;
  border: 1px solid rgba(96, 165, 250, .56);
  border-radius: 6px;
  color: #bfdbfe;
  background: #10213b;
  box-shadow: 0 4px 10px rgba(2, 6, 23, .2);
  white-space: nowrap;
  overflow: hidden;
}
.workflow-loop-boundary-label svg { color: #60a5fa; }
.workflow-loop-boundary-label strong,
.workflow-loop-boundary-label span,
.workflow-loop-boundary-label em { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-loop-boundary-label strong { min-width: 0; font-size: 10px; font-weight: 650; }
.workflow-loop-boundary-label span { min-width: 0; color: #93a9c8; font-size: 9px; }
.workflow-loop-boundary-label em { min-width: 0; color: #86efac; font-size: 9px; font-style: normal; }
.workflow-loop-boundary-entry-handle,
.workflow-loop-boundary-body-handle,
.workflow-loop-boundary-exit-handle {
  position: absolute;
  left: 50%;
  right: auto;
  width: 10px;
  height: 10px;
  border: 2px solid #60a5fa;
  border-radius: 50%;
  background: #0f172a;
  transform: translate(-50%, -50%);
}
.workflow-loop-boundary-entry-handle { top: 0; bottom: auto; pointer-events: all; }
.workflow-loop-boundary-body-handle { top: 0; bottom: auto; pointer-events: none; opacity: 0; }
.workflow-loop-boundary-exit-handle { bottom: 0; pointer-events: all; transform: translate(-50%, 50%); border-color: #a78bfa; }
.workflow-loop-boundary-exit-handle:hover { border-color: #c4b5fd; background: #a78bfa; }
:global(:root[data-theme="light"]) .workflow-loop-boundary { border-color: #60a5fa; background: rgba(219, 234, 254, .35); }
:global(:root[data-theme="light"]) .workflow-loop-boundary-label { color: #1e3a8a; background: #eff6ff; border-color: #93c5fd; box-shadow: 0 4px 10px rgba(30, 64, 175, .12); }
:global(:root[data-theme="light"]) .workflow-loop-boundary-label span { color: #475569; }
:global(:root[data-theme="light"]) .workflow-loop-boundary-entry-handle { border-color: #3b82f6; background: #ffffff; }
:global(:root[data-theme="light"]) .workflow-loop-boundary-exit-handle { border-color: #8b5cf6; background: #ffffff; }
</style>
