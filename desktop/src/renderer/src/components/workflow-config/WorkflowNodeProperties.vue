<script setup lang="ts">
import { computed } from 'vue'
import BaseNodeConfig from './BaseNodeConfig.vue'
import ScriptNodeConfig from './ScriptNodeConfig.vue'
import CommandNodeConfig from './CommandNodeConfig.vue'
import GenericNodeConfig from './GenericNodeConfig.vue'
import type { NodeItem, DeviceSummary, CommandReference, ResultSource, ActionItem, WorkflowScript } from './types'

const props = defineProps<{
  node: NodeItem | null
  availableDevices?: DeviceSummary[]
  commandReferences?: CommandReference[]
  resultSources?: ResultSource[]
  scripts?: WorkflowScript[]
  actions?: ActionItem[]
  nodeOptions: Array<{ id: string; label: string }>
  predecessorId?: string
  successorId?: string
  scriptSaving?: boolean
}>()

const emit = defineEmits<{
  'update:node': [node: NodeItem]
  'update:predecessorId': [value: string]
  'update:successorId': [value: string]
  rename: [event: Event]
  remove: []
  test: []
  'save-as-action': []
  'open-script-studio': [scriptId: string]
  'save-script': []
}>()

const selectedAction = computed(() => {
  if (!props.node) return undefined
  return props.actions?.find(a => a.id === props.node?.action_id)
})

function handleNodeUpdate(node: NodeItem): void {
  emit('update:node', node)
}
</script>

<template>
  <section v-if="node" class="workflow-properties" aria-label="步骤设置">
    <!-- 基础配置：步骤名称、上下游连接 -->
    <BaseNodeConfig
      :node="node"
      :node-options="nodeOptions"
      :predecessor-id="predecessorId"
      :successor-id="successorId"
      :selected-action="selectedAction"
      @rename="emit('rename', $event)"
      @update:predecessor-id="emit('update:predecessorId', $event)"
      @update:successor-id="emit('update:successorId', $event)"
    />

    <!-- 节点特定配置 -->
    <ScriptNodeConfig
      v-if="node.action_id === 'script.run'"
      :node="node"
      :scripts="scripts"
      :command-references="commandReferences"
      :script-saving="scriptSaving"
      @update="handleNodeUpdate"
      @remove="emit('remove')"
      @test="emit('test')"
      @save-as-action="emit('save-as-action')"
      @open-script-studio="emit('open-script-studio', $event)"
      @save-script="emit('save-script')"
    />

    <CommandNodeConfig
      v-else-if="node.action_id === 'device.command'"
      :node="node"
      :command-references="commandReferences"
      @update="handleNodeUpdate"
      @remove="emit('remove')"
      @test="emit('test')"
      @save-as-action="emit('save-as-action')"
    />

    <GenericNodeConfig
      v-else
      :node="node"
      :available-devices="availableDevices"
      :command-references="commandReferences"
      :result-sources="resultSources"
      :actions="actions"
      @update="handleNodeUpdate"
      @remove="emit('remove')"
      @test="emit('test')"
    />
  </section>
  <section v-else class="workflow-properties workflow-empty">
    选择一个步骤编辑参数
  </section>
</template>

<style scoped>
.workflow-properties {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--workflow-border);
  border-radius: 6px;
  align-self: start;
}

.workflow-empty {
  display: grid;
  place-items: center;
  min-height: 200px;
  color: var(--workflow-muted);
  font-size: 12px;
}
</style>
