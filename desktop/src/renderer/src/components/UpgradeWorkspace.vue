<script setup lang="ts">
import TaskWorkspace from './TaskWorkspace.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const emit = defineEmits<{ runWorkflow: [] }>()
</script>

<template>
  <div
    v-if="workspace.upgradePanelOpen"
    class="upgrade-backdrop"
    @mousedown.self="workspace.upgradePanelOpen = false"
  >
    <aside class="upgrade-workspace" role="region" aria-label="任务工作区">
      <TaskWorkspace @run-workflow="emit('runWorkflow')" />
    </aside>
  </div>
</template>
