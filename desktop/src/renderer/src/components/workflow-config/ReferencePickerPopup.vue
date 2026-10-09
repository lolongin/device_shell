<script setup lang="ts">
/**
 * 改进的变量引用选择器
 * 弹出式界面，支持搜索、键盘导航、预览
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Search, ArrowUp, ArrowDown, CornerDownLeft, X } from 'lucide-vue-next'
import type { WorkflowValueReference } from './types'

const props = defineProps<{
  references: WorkflowValueReference[]
  modelValue: string
  placeholder?: string
  mode?: 'single' | 'template'
}>()

const emit = defineEmits<{
  select: [reference: string]
  close: []
}>()

const search = ref('')
const selectedIndex = ref(0)
const popup = ref<HTMLElement | null>(null)

// 分组引用
const groupedReferences = computed(() => {
  const sources = [
    { id: 'input', label: '流程输入', icon: '📥' },
    { id: 'node', label: '步骤输出', icon: '⚙️' },
    { id: 'variable', label: '流程变量', icon: '🔤' },
    { id: 'loop', label: '循环上下文', icon: '🔄' },
    { id: 'context', label: '运行上下文', icon: '🎯' }
  ]

  const needle = search.value.toLowerCase()

  return sources
    .map(source => {
      const items = props.references.filter(ref => {
        if (ref.source !== source.id) return false
        if (!needle) return true
        return `${ref.label} ${ref.reference}`.toLowerCase().includes(needle)
      })

      return { ...source, items, count: items.length }
    })
    .filter(group => group.count > 0)
})

// 扁平化的所有匹配项
const flatMatches = computed(() => {
  return groupedReferences.value.flatMap(group => group.items)
})

const totalMatches = computed(() => flatMatches.value.length)

// 当前选中的引用
const selectedReference = computed(() => {
  return flatMatches.value[selectedIndex.value] || null
})

// 高亮匹配文本
function highlightMatch(text: string): string {
  const needle = search.value.trim()
  if (!needle) return text

  const regex = new RegExp(`(${needle})`, 'gi')
  return text.replace(regex, '<mark>$1</mark>')
}

// 键盘导航
function handleKeydown(event: KeyboardEvent): void {
  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      selectedIndex.value = Math.min(selectedIndex.value + 1, totalMatches.value - 1)
      scrollToSelected()
      break

    case 'ArrowUp':
      event.preventDefault()
      selectedIndex.value = Math.max(selectedIndex.value - 1, 0)
      scrollToSelected()
      break

    case 'Enter':
      event.preventDefault()
      if (selectedReference.value) {
        selectReference(selectedReference.value)
      }
      break

    case 'Escape':
      event.preventDefault()
      emit('close')
      break
  }
}

function scrollToSelected(): void {
  nextTick(() => {
    const selected = popup.value?.querySelector('.reference-item.selected')
    if (selected) {
      selected.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  })
}

function selectReference(reference: WorkflowValueReference): void {
  emit('select', reference.reference)
  emit('close')
}

// 搜索框自动聚焦
onMounted(() => {
  nextTick(() => {
    const input = popup.value?.querySelector('input')
    input?.focus()
  })
})

// 点击外部关闭
function handleClickOutside(event: MouseEvent): void {
  if (popup.value && !popup.value.contains(event.target as Node)) {
    emit('close')
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside, true)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside, true)
})

// 重置选中索引
watch(search, () => {
  selectedIndex.value = 0
})
</script>

<template>
  <div ref="popup" class="reference-picker-popup" @keydown="handleKeydown">
    <!-- 搜索框 -->
    <div class="picker-header">
      <div class="search-box">
        <Search :size="14" class="search-icon" />
        <input
          v-model="search"
          type="text"
          :placeholder="placeholder || '搜索变量或步骤...'"
          class="search-input"
        />
        <button v-if="search" class="clear-btn" @click="search = ''">
          <X :size="14" />
        </button>
      </div>
      <div class="search-meta">
        <span v-if="totalMatches > 0">{{ selectedIndex + 1 }} / {{ totalMatches }}</span>
        <span v-else class="no-results">无匹配项</span>
      </div>
    </div>

    <!-- 引用列表 -->
    <div class="reference-list">
      <div
        v-for="(group, groupIndex) in groupedReferences"
        :key="group.id"
        class="reference-group"
      >
        <div class="group-header">
          <span class="group-icon">{{ group.icon }}</span>
          <strong>{{ group.label }}</strong>
          <span class="group-count">{{ group.count }}</span>
        </div>

        <button
          v-for="(ref, itemIndex) in group.items"
          :key="ref.reference"
          :class="[
            'reference-item',
            {
              selected: flatMatches.indexOf(ref) === selectedIndex
            }
          ]"
          @click="selectReference(ref)"
          @mouseenter="selectedIndex = flatMatches.indexOf(ref)"
        >
          <div class="ref-content">
            <div class="ref-label" v-html="highlightMatch(ref.label)"></div>
            <div class="ref-meta">
              <span class="ref-type">{{ ref.type }}</span>
              <code class="ref-path">${{ ref.reference }}</code>
            </div>
          </div>
          <div v-if="mode === 'template'" class="insert-indicator">插入</div>
        </button>
      </div>

      <div v-if="totalMatches === 0" class="empty-state">
        <Search :size="32" />
        <p>未找到匹配的引用</p>
        <small>尝试其他关键词</small>
      </div>
    </div>

    <!-- 快捷键提示 -->
    <div class="picker-footer">
      <div class="shortcuts">
        <span class="shortcut"><ArrowUp :size="12" /><ArrowDown :size="12" /> 导航</span>
        <span class="shortcut"><CornerDownLeft :size="12" /> 选择</span>
        <span class="shortcut"><kbd>Esc</kbd> 取消</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.reference-picker-popup {
  position: absolute;
  z-index: 1000;
  width: 420px;
  max-height: 480px;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 8px;
  background: var(--workflow-surface, #1e1e1e);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}

/* 搜索框 */
.picker-header {
  padding: 12px;
  border-bottom: 1px solid var(--workflow-border, #3a3a3a);
  background: var(--workflow-surface-input, #0a0a0a);
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 6px;
  background: var(--workflow-surface, #1e1e1e);
  transition: border-color 0.15s ease;
}

.search-box:focus-within {
  border-color: #3b82f6;
}

.search-icon {
  color: var(--workflow-muted, #888);
  flex-shrink: 0;
}

.search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  color: var(--workflow-text, #e0e0e0);
  font-size: 13px;
}

.clear-btn {
  padding: 2px;
  border: none;
  background: transparent;
  color: var(--workflow-muted, #888);
  cursor: pointer;
  border-radius: 3px;
  transition: all 0.15s ease;
}

.clear-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--workflow-text, #e0e0e0);
}

.search-meta {
  margin-top: 6px;
  text-align: right;
  font-size: 11px;
  color: var(--workflow-muted, #888);
}

.no-results {
  color: #f59e0b;
}

/* 引用列表 */
.reference-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  min-height: 200px;
  max-height: 360px;
}

.reference-group {
  margin-bottom: 12px;
}

.group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  margin-bottom: 4px;
  font-size: 11px;
  font-weight: 600;
  color: var(--workflow-muted, #888);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.group-icon {
  font-size: 14px;
}

.group-count {
  margin-left: auto;
  padding: 2px 6px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.1);
  font-size: 10px;
}

.reference-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 10px 12px;
  margin-bottom: 2px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--workflow-text, #e0e0e0);
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
}

.reference-item:hover {
  background: rgba(255, 255, 255, 0.05);
  border-color: var(--workflow-border, #3a3a3a);
}

.reference-item.selected {
  background: rgba(59, 130, 246, 0.15);
  border-color: #3b82f6;
}

.ref-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.ref-label {
  font-size: 12px;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-label :deep(mark) {
  background: #fbbf24;
  color: #000;
  padding: 1px 2px;
  border-radius: 2px;
}

.ref-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
}

.ref-type {
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(59, 130, 246, 0.2);
  color: #60a5fa;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
}

.ref-path {
  padding: 2px 4px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.05);
  color: #a3a3a3;
  font-size: 10px;
  font-family: 'Consolas', 'Monaco', monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ref-description {
  font-size: 10px;
  color: var(--workflow-muted, #888);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.insert-indicator {
  padding: 4px 8px;
  border-radius: 4px;
  background: rgba(16, 185, 129, 0.2);
  color: #10b981;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  color: var(--workflow-muted, #888);
  text-align: center;
}

.empty-state svg {
  margin-bottom: 12px;
  opacity: 0.5;
}

.empty-state p {
  margin: 8px 0 4px;
  font-size: 13px;
}

.empty-state small {
  font-size: 11px;
}

/* 快捷键提示 */
.picker-footer {
  padding: 8px 12px;
  border-top: 1px solid var(--workflow-border, #3a3a3a);
  background: var(--workflow-surface-input, #0a0a0a);
}

.shortcuts {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 10px;
  color: var(--workflow-muted, #888);
}

.shortcut {
  display: flex;
  align-items: center;
  gap: 4px;
}

.shortcut kbd {
  padding: 2px 5px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 3px;
  background: var(--workflow-surface, #1e1e1e);
  font-size: 9px;
  font-family: inherit;
}

/* 滚动条样式 */
.reference-list::-webkit-scrollbar {
  width: 6px;
}

.reference-list::-webkit-scrollbar-track {
  background: transparent;
}

.reference-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.2);
  border-radius: 3px;
}

.reference-list::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.3);
}
</style>
