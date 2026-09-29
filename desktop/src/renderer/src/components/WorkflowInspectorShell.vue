<script setup lang="ts">
import { Braces, Workflow } from 'lucide-vue-next'
type InspectorMode = 'workflow' | 'step'

const props = defineProps<{
  mode: InspectorMode
  flowTestOpen: boolean
  hasSelectedNode: boolean
  previewingAction: boolean
}>()

const emit = defineEmits<{
  'update:mode': [mode: InspectorMode]
}>()
</script>

<template>
  <aside class="workflow-right-rail" :class="{ 'is-flow-test': flowTestOpen }">
    <template v-if="flowTestOpen">
      <div class="workflow-inspector-flow-content">
        <slot name="flow-test" />
      </div>
    </template>
    <template v-else>
      <nav class="workflow-right-rail-switcher" aria-label="配置视图">
        <button type="button" :class="{ active: props.mode === 'workflow' }" @click="emit('update:mode', 'workflow')"><Workflow :size="13" />流程设置</button>
        <button type="button" :disabled="!props.hasSelectedNode" :class="{ active: props.mode === 'step' }" @click="emit('update:mode', 'step')"><Braces :size="13" />{{ props.previewingAction ? '节点预览' : '步骤配置' }}</button>
      </nav>
      <div class="workflow-inspector-content">
        <slot :name="props.mode === 'workflow' ? 'workflow-settings' : 'step-settings'" />
      </div>
    </template>
  </aside>
</template>

<style scoped>
.workflow-right-rail {
  position: relative;
  grid-column: 3;
  grid-row: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border-left: 1px solid var(--workflow-border);
  background: var(--workflow-surface-muted);
}

.workflow-right-rail-switcher {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
  border-bottom: 1px solid var(--workflow-border);
  background: var(--workflow-surface);
}

.workflow-right-rail-switcher button {
  display: inline-flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-width: 0;
  min-height: 30px;
  padding: 0 8px;
  border: 1px solid transparent;
  border-radius: 5px;
  color: var(--workflow-muted);
  background: transparent;
  cursor: pointer;
  font-size: 11px;
}

.workflow-right-rail-switcher button.active {
  border-color: color-mix(in srgb, var(--workflow-focus) 34%, var(--workflow-border));
  color: var(--workflow-focus);
  background: color-mix(in srgb, var(--workflow-focus) 12%, transparent);
  font-weight: 650;
}

.workflow-right-rail-switcher button:disabled { opacity: .4; cursor: default; }

.workflow-inspector-content,
.workflow-inspector-flow-content {
  position: relative;
  z-index: 1;
  min-width: 0;
  min-height: 0;
  flex: 1 1 auto;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: #64748b rgba(15, 23, 42, .28);
  pointer-events: auto;
}

.workflow-inspector-content > :deep(*) { width: 100%; box-sizing: border-box; }
.workflow-inspector-flow-content > :deep(*) { min-height: 100%; box-sizing: border-box; }

/* Keep the inspector controls above the canvas/resizer stacking context. */
.workflow-inspector-content :deep(input),
.workflow-inspector-content :deep(select),
.workflow-inspector-content :deep(textarea),
.workflow-inspector-content :deep(button) {
  position: relative;
  z-index: 2;
  pointer-events: auto;
}

.workflow-inspector-content :deep(select) { cursor: pointer; }

@media (max-width: 980px) {
  .workflow-right-rail { grid-column: 1 / -1; grid-row: 2; border-top: 1px solid var(--workflow-border); border-left: 0; }
}

@media (max-width: 720px) {
  .workflow-right-rail { grid-column: 1; grid-row: 3; }
}

:global(:root[data-theme="light"]) .workflow-right-rail { background: #f1f5f9; }
:global(:root[data-theme="light"]) .workflow-right-rail-switcher { background: #ffffff; }
:global(:root[data-theme="light"]) .workflow-inspector-content,
:global(:root[data-theme="light"]) .workflow-inspector-flow-content { scrollbar-color: #94a3b8 #e2e8f0; }
</style>
