<script setup lang="ts">
import type { NodeItem, ActionItem } from './types'

defineProps<{
  node: NodeItem
  nodeOptions: Array<{ id: string; label: string }>
  predecessorId?: string
  successorId?: string
  selectedAction?: ActionItem
}>()

const emit = defineEmits<{
  'update:predecessorId': [value: string]
  'update:successorId': [value: string]
  rename: [event: Event]
}>()
</script>

<template>
  <div class="base-node-config">
    <div class="panel-heading">
      <div>
        <strong>{{ node.action_id === 'variable.set' ? '设置变量' : '步骤设置' }}</strong>
        <small v-if="node.action_id !== 'variable.set' && selectedAction">{{ selectedAction.label }}</small>
      </div>
      <span class="properties-node-index">{{ node.id }}</span>
    </div>

    <template v-if="node.action_id !== 'variable.set'">
      <label>
        步骤名称
        <input :value="node.id" @change="emit('rename', $event)" />
      </label>

      <label>
        上游步骤
        <select :value="predecessorId" @change="emit('update:predecessorId', ($event.target as HTMLSelectElement).value)">
          <option value="">无（流程起点）</option>
          <option v-for="n in nodeOptions" :key="n.id" :value="n.id">{{ n.label }}</option>
        </select>
      </label>

      <label>
        下游步骤
        <select :value="successorId" @change="emit('update:successorId', ($event.target as HTMLSelectElement).value)">
          <option value="">无（流程终点）</option>
          <option v-for="n in nodeOptions" :key="`${n.id}-successor`" :value="n.id">{{ n.label }}</option>
        </select>
      </label>
    </template>
  </div>
</template>

<style scoped>
.base-node-config {
  display: flex;
  flex-direction: column;
  gap: 13px;
}

.panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--workflow-border);
}

.panel-heading > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.panel-heading strong {
  color: var(--workflow-text);
  font-size: 13px;
}

.panel-heading small {
  overflow: hidden;
  color: var(--workflow-muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.properties-node-index {
  padding: 3px 7px;
  border: 1px solid var(--workflow-border);
  border-radius: 4px;
  color: var(--workflow-muted);
  background: var(--workflow-surface-muted);
  font: 600 10px ui-monospace, SFMono-Regular, Consolas, monospace;
}

label {
  display: grid;
  gap: 5px;
  color: var(--workflow-text);
  font-size: 11px;
}

input,
select {
  box-sizing: border-box;
  width: 100%;
  padding: 7px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  color: inherit;
  background: var(--workflow-surface-input);
  font: inherit;
}

input::placeholder {
  color: var(--workflow-muted);
}
</style>
