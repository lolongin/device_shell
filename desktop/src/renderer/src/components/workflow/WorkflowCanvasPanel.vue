<script setup lang="ts">
import { GitBranch, Hand, MousePointer2 } from 'lucide-vue-next'
import WorkflowCanvas from '../WorkflowCanvas.vue'

type Workflow = {
  nodes?: Array<{ id: string }>
  edges?: Array<{ source: string; target: string; source_handle?: string }>
}

defineProps<{
  workflow: Workflow
  issues: Array<{ code: string; message: string; node_id?: string }>
  interactive: boolean
  onToggleInteractive: () => void
  onNodeSelect: (nodeId: string) => void
  onConnect: (source: string, target: string, sourceHandle?: string) => void
  onNodeAdd: (...args: any[]) => void
  onDisconnect: (edgeId: string) => void
  onNodePositionChange: (...args: any[]) => void
}>()
</script>

<template>
  <section class="workflow-canvas">
    <div class="canvas-toolbar">
      <div class="canvas-toolbar-title"><GitBranch :size="15" /><strong>流程画布</strong><span>{{ (workflow.nodes || []).length }} 个步骤</span><span>{{ (workflow.edges || []).length }} 条连接</span></div>
      <div class="canvas-toolbar-actions">
        <button
          type="button"
          class="canvas-interactive-toggle"
          :class="{ active: interactive }"
          :title="interactive ? '交互已开启：可拖动节点和连线' : '交互已关闭'"
          :aria-label="interactive ? '关闭节点交互' : '开启节点交互'"
          :aria-pressed="interactive"
          @click="onToggleInteractive"
        >
          <MousePointer2 v-if="interactive" :size="13" />
          <Hand v-else :size="13" />
          <span>{{ interactive ? '编辑' : '浏览' }}</span>
        </button>
        <span class="canvas-toolbar-hint">左键拖动节点 · 中键平移 · 从端口拉线</span>
      </div>
    </div>
    <div class="workflow-canvas-container">
      <WorkflowCanvas
        :workflow="workflow as any"
        :issues="issues as any"
        :interactive="interactive"
        @node-select="onNodeSelect"
        @connect="({ source, target, sourceHandle }) => onConnect(source, target, sourceHandle || undefined)"
        @node-add="onNodeAdd"
        @disconnect="onDisconnect"
        @node-position-change="onNodePositionChange"
      />
    </div>
  </section>
</template>
