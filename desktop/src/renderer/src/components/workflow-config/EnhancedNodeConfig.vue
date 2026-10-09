<script setup lang="ts">
/**
 * 增强版节点配置组件
 * 提供改进的 UI 布局和交互体验
 * 逐步替换 GenericNodeConfig
 */
import { computed } from 'vue'
import ImprovedNodeConfig from './ImprovedNodeConfig.vue'
import GenericNodeConfig from './GenericNodeConfig.vue'
import type { NodeConfigProps, NodeConfigEmits } from './types'

const props = defineProps<NodeConfigProps>()
const emit = defineEmits<NodeConfigEmits & { 'choose-upload-source': [], test: [] }>()

// 使用改进 UI 的动作类型
const useImprovedUI = computed(() => {
  const actionId = props.node.action_id

  // 这些动作类型使用新的改进 UI
  const improvedActions = new Set([
    'device.connect',
    'device.disconnect',
    'device.select',
    'utility.wait',
    'utility.confirm',
    'result.save',
    'terminal.execute',
    'terminal.interact',
    'terminal.batch'
  ])

  return improvedActions.has(actionId)
})

function handleUpdate(node: any): void {
  emit('update', node)
}

function handleTest(): void {
  emit('test')
}
</script>

<template>
  <!-- 使用改进的 UI -->
  <ImprovedNodeConfig
    v-if="useImprovedUI"
    v-bind="props"
    @update="handleUpdate"
    @test="handleTest"
  />

  <!-- 保留原有的 UI 作为后备 -->
  <GenericNodeConfig
    v-else
    v-bind="props"
    @update="handleUpdate"
    @choose-upload-source="$emit('choose-upload-source')"
  />
</template>

<style scoped>
/* 无需额外样式，由子组件处理 */
</style>
