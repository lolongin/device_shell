<script setup lang="ts">
import TaskWorkspace from './TaskWorkspace.vue'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
</script>

<template>
  <div
    v-if="workspace.upgradePanelOpen"
    class="upgrade-backdrop"
    @mousedown.self="workspace.upgradePanelOpen = false"
  >
    <aside class="upgrade-workspace" role="region" aria-label="任务工作区">
      <TaskWorkspace />
    </aside>
  </div>
</template>
