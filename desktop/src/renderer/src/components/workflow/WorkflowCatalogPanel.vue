<script setup lang="ts">
import { Eye, Search, Trash2 } from 'lucide-vue-next'
import type { ActionItem } from '../workflow-config/types'

type ActionGroup = { category: string; label: string; actions: ActionItem[] }

defineProps<{
  actions: ActionItem[]
  groups: ActionGroup[]
  error: string
  selectedActionId?: string
  searchQuery: string
  onPreview: (actionId: string) => void
  onDragStart: (event: DragEvent, actionId: string) => void
  onDelete: (action: ActionItem) => void | Promise<void>
}>()

const emit = defineEmits<{ 'update:searchQuery': [value: string] }>()
</script>

<template>
  <section class="workflow-action-catalog">
    <div class="panel-heading">
      <div><strong>节点库</strong><small>点击查看配置，拖入画布添加</small></div>
      <span class="catalog-count">{{ actions.length }}</span>
    </div>
    <p v-if="error" class="catalog-error" role="alert">{{ error }}</p>
    <label class="workflow-search">
      <Search :size="13" />
      <input :value="searchQuery" placeholder="搜索动作" aria-label="搜索动作" @input="emit('update:searchQuery', ($event.target as HTMLInputElement).value)" />
    </label>
    <div v-for="group in groups" :key="group.category" class="action-category-group">
      <div class="action-category-heading"><span>{{ group.label }}</span><small>{{ group.actions.length }}</small></div>
      <button
        v-for="action in group.actions"
        :key="action.id"
        type="button"
        draggable="true"
        :class="`action-tile tone-${action.tone}`"
        :aria-pressed="selectedActionId === action.id"
        title="点击查看配置，拖入画布添加"
        @dragstart="onDragStart($event, action.id)"
        @click="onPreview(action.id)"
      >
        <span class="action-icon"><Eye :size="12" /></span>
        <span><b>{{ action.label }}</b><small>{{ action.hint }}</small></span>
        <Trash2 v-if="action.preset" :size="12" class="custom-action-delete" title="删除自定义 Action" @click.stop="onDelete(action)" />
      </button>
    </div>
    <p v-if="!actions.length" class="catalog-empty">没有匹配的动作</p>
    <p class="node-library-hint">点击查看节点配置；拖入画布创建步骤。</p>
  </section>
</template>
