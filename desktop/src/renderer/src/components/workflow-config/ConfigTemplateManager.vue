<script setup lang="ts">
/**
 * 配置模板管理器
 * 保存、加载、分享配置模板
 */
import { computed, ref } from 'vue'
import { Layers, Save, Trash2, Copy, Check, Star, Clock } from 'lucide-vue-next'
import type { NodeItem } from './types'

interface ConfigTemplate {
  id: string
  name: string
  description: string
  actionId: string
  config: Record<string, unknown>
  category: 'personal' | 'team' | 'system'
  useCount: number
  createdAt: Date
  updatedAt: Date
  isFavorite: boolean
}

const props = defineProps<{
  node: NodeItem
  actions?: Array<{ id: string; label: string }>
}>()

const emit = defineEmits<{
  apply: [config: Record<string, unknown>]
  close: []
}>()

const TEMPLATES_STORAGE_KEY = 'device-tui.workflow-config-templates'

// 加载模板
function loadTemplates(): ConfigTemplate[] {
  try {
    const stored = window.localStorage.getItem(TEMPLATES_STORAGE_KEY)
    if (!stored) return getSystemTemplates()

    const personal = JSON.parse(stored) as ConfigTemplate[]
    return [...personal, ...getSystemTemplates()]
  } catch {
    return getSystemTemplates()
  }
}

// 系统推荐模板
function getSystemTemplates(): ConfigTemplate[] {
  const actionId = props.node.action_id

  if (actionId === 'device.connect') {
    return [
      {
        id: 'connect-quick',
        name: '快速连接',
        description: '30秒超时，适合测试',
        actionId,
        config: { timeout_seconds: 30 },
        category: 'system',
        useCount: 0,
        createdAt: new Date(),
        updatedAt: new Date(),
        isFavorite: false
      },
      {
        id: 'connect-stable',
        name: '稳定连接',
        description: '5分钟超时，失败重试3次',
        actionId,
        config: { timeout_seconds: 300, retry_attempts: 3, retry_backoff_seconds: 5 },
        category: 'system',
        useCount: 0,
        createdAt: new Date(),
        updatedAt: new Date(),
        isFavorite: false
      }
    ]
  }

  if (actionId === 'terminal.execute') {
    return [
      {
        id: 'terminal-quick',
        name: '快速命令',
        description: '30秒超时，适合简单命令',
        actionId,
        config: { timeout_seconds: 30, send_enter: true },
        category: 'system',
        useCount: 0,
        createdAt: new Date(),
        updatedAt: new Date(),
        isFavorite: false
      },
      {
        id: 'terminal-long',
        name: '长时命令',
        description: '10分钟超时，适合耗时操作',
        actionId,
        config: { timeout_seconds: 600, send_enter: true },
        category: 'system',
        useCount: 0,
        createdAt: new Date(),
        updatedAt: new Date(),
        isFavorite: false
      }
    ]
  }

  return []
}

// 保存模板
function saveTemplates(templates: ConfigTemplate[]): void {
  try {
    const personal = templates.filter(t => t.category === 'personal')
    window.localStorage.setItem(TEMPLATES_STORAGE_KEY, JSON.stringify(personal))
  } catch {
    // localStorage 失败
  }
}

const templates = ref<ConfigTemplate[]>(loadTemplates())
const currentCategory = ref<'personal' | 'team' | 'system' | 'favorite'>('favorite')
const savingTemplate = ref(false)
const templateName = ref('')
const templateDescription = ref('')
const copiedId = ref('')

// 过滤模板
const filteredTemplates = computed(() => {
  let filtered = templates.value.filter(t => t.actionId === props.node.action_id)

  if (currentCategory.value === 'favorite') {
    filtered = filtered.filter(t => t.isFavorite)
  } else {
    filtered = filtered.filter(t => t.category === currentCategory.value)
  }

  // 按使用次数和收藏排序
  return filtered.sort((a, b) => {
    if (a.isFavorite !== b.isFavorite) return a.isFavorite ? -1 : 1
    return b.useCount - a.useCount
  })
})

const categories = computed(() => {
  const counts = {
    favorite: templates.value.filter(t => t.isFavorite && t.actionId === props.node.action_id).length,
    personal: templates.value.filter(t => t.category === 'personal' && t.actionId === props.node.action_id).length,
    system: templates.value.filter(t => t.category === 'system' && t.actionId === props.node.action_id).length
  }

  return [
    { id: 'favorite', label: '收藏', icon: Star, count: counts.favorite },
    { id: 'personal', label: '我的模板', icon: Layers, count: counts.personal },
    { id: 'system', label: '系统推荐', icon: Check, count: counts.system }
  ]
})

// 应用模板
function applyTemplate(template: ConfigTemplate): void {
  // 增加使用次数
  template.useCount++
  template.updatedAt = new Date()
  saveTemplates(templates.value)

  emit('apply', JSON.parse(JSON.stringify(template.config)))
  emit('close')
}

// 保存当前配置为模板
function saveCurrentConfig(): void {
  if (!templateName.value.trim()) return

  const newTemplate: ConfigTemplate = {
    id: `template-${Date.now()}`,
    name: templateName.value.trim(),
    description: templateDescription.value.trim(),
    actionId: props.node.action_id,
    config: JSON.parse(JSON.stringify(props.node.config)),
    category: 'personal',
    useCount: 0,
    createdAt: new Date(),
    updatedAt: new Date(),
    isFavorite: false
  }

  templates.value.push(newTemplate)
  saveTemplates(templates.value)

  // 重置表单
  templateName.value = ''
  templateDescription.value = ''
  savingTemplate.value = false
  currentCategory.value = 'personal'
}

// 删除模板
function deleteTemplate(templateId: string): void {
  const index = templates.value.findIndex(t => t.id === templateId)
  if (index >= 0) {
    templates.value.splice(index, 1)
    saveTemplates(templates.value)
  }
}

// 切换收藏
function toggleFavorite(template: ConfigTemplate): void {
  template.isFavorite = !template.isFavorite
  saveTemplates(templates.value)
}

// 复制配置
async function copyConfig(config: Record<string, unknown>, templateId: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(JSON.stringify(config, null, 2))
    copiedId.value = templateId
    setTimeout(() => {
      copiedId.value = ''
    }, 2000)
  } catch {
    // 复制失败
  }
}

// 格式化配置预览
function formatConfig(config: Record<string, unknown>): string {
  const lines: string[] = []
  for (const [key, value] of Object.entries(config)) {
    if (value !== undefined && value !== null && value !== '') {
      lines.push(`${key}: ${JSON.stringify(value)}`)
    }
  }
  return lines.join('\n') || '空配置'
}

// 格式化时间
function formatTime(date: Date): string {
  const now = new Date()
  const diff = now.getTime() - new Date(date).getTime()
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))

  if (days === 0) return '今天'
  if (days === 1) return '昨天'
  if (days < 7) return `${days} 天前`
  return new Date(date).toLocaleDateString()
}
</script>

<template>
  <div class="config-template-manager">
    <header class="template-header">
      <h3><Layers :size="18" />配置模板</h3>
      <button class="close-btn" @click="emit('close')">×</button>
    </header>

    <!-- 分类标签 -->
    <div class="template-categories">
      <button
        v-for="category in categories"
        :key="category.id"
        :class="['category-btn', { active: currentCategory === category.id }]"
        @click="currentCategory = category.id as any"
      >
        <component :is="category.icon" :size="14" />
        <span>{{ category.label }}</span>
        <span v-if="category.count > 0" class="category-count">{{ category.count }}</span>
      </button>
    </div>

    <!-- 模板列表 -->
    <div class="template-list">
      <div v-if="filteredTemplates.length === 0" class="empty-state">
        <Layers :size="32" />
        <p>暂无模板</p>
        <small>保存当前配置作为模板，下次快速应用</small>
      </div>

      <div
        v-for="template in filteredTemplates"
        :key="template.id"
        class="template-card"
      >
        <div class="template-card-header">
          <div class="template-info">
            <strong>{{ template.name }}</strong>
            <small>{{ template.description }}</small>
          </div>
          <button
            class="favorite-btn"
            :class="{ active: template.isFavorite }"
            @click.stop="toggleFavorite(template)"
          >
            <Star :size="14" :fill="template.isFavorite ? 'currentColor' : 'none'" />
          </button>
        </div>

        <div class="template-preview">
          <pre>{{ formatConfig(template.config) }}</pre>
        </div>

        <div class="template-meta">
          <span class="meta-item">
            <Clock :size="12" />
            {{ formatTime(template.updatedAt) }}
          </span>
          <span v-if="template.useCount > 0" class="meta-item">
            使用 {{ template.useCount }} 次
          </span>
        </div>

        <div class="template-actions">
          <button class="apply-btn" @click="applyTemplate(template)">
            <Check :size="14" />
            应用
          </button>
          <button
            class="icon-btn"
            :class="{ copied: copiedId === template.id }"
            @click="copyConfig(template.config, template.id)"
          >
            <Check v-if="copiedId === template.id" :size="14" />
            <Copy v-else :size="14" />
          </button>
          <button
            v-if="template.category === 'personal'"
            class="icon-btn danger"
            @click="deleteTemplate(template.id)"
          >
            <Trash2 :size="14" />
          </button>
        </div>
      </div>
    </div>

    <!-- 保存新模板 -->
    <div class="save-template-section">
      <button
        v-if="!savingTemplate"
        class="save-template-btn"
        @click="savingTemplate = true"
      >
        <Save :size="14" />
        保存当前配置为模板
      </button>

      <div v-else class="save-template-form">
        <input
          v-model="templateName"
          type="text"
          placeholder="模板名称（必填）"
          maxlength="50"
        />
        <textarea
          v-model="templateDescription"
          rows="2"
          placeholder="模板描述（可选）"
          maxlength="200"
        />
        <div class="form-actions">
          <button class="secondary-btn" @click="savingTemplate = false">取消</button>
          <button
            class="primary-btn"
            :disabled="!templateName.trim()"
            @click="saveCurrentConfig"
          >
            <Save :size="14" />
            保存
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.config-template-manager {
  display: flex;
  flex-direction: column;
  width: 480px;
  max-height: 600px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 8px;
  background: var(--workflow-surface, #1e1e1e);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}

.template-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--workflow-border, #3a3a3a);
  background: var(--workflow-surface-input, #0a0a0a);
}

.template-header h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--workflow-text, #e0e0e0);
}

.close-btn {
  padding: 4px 8px;
  border: none;
  background: transparent;
  color: var(--workflow-muted, #888);
  font-size: 20px;
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s ease;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--workflow-text, #e0e0e0);
}

.template-categories {
  display: flex;
  gap: 4px;
  padding: 12px;
  border-bottom: 1px solid var(--workflow-border, #3a3a3a);
  background: var(--workflow-surface-input, #0a0a0a);
}

.category-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 6px;
  background: var(--workflow-surface, #1e1e1e);
  color: var(--workflow-muted, #888);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.category-btn:hover {
  border-color: #3b82f6;
  color: var(--workflow-text, #e0e0e0);
}

.category-btn.active {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.15);
  color: #3b82f6;
}

.category-count {
  padding: 2px 6px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.1);
  font-size: 10px;
  font-weight: 600;
}

.template-list {
  flex: 1;
  padding: 12px;
  overflow-y: auto;
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

.template-card {
  padding: 12px;
  margin-bottom: 8px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 6px;
  background: var(--workflow-surface-input, #0a0a0a);
  transition: all 0.15s ease;
}

.template-card:hover {
  border-color: rgba(59, 130, 246, 0.4);
  transform: translateY(-1px);
}

.template-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.template-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.template-info strong {
  font-size: 12px;
  color: var(--workflow-text, #e0e0e0);
}

.template-info small {
  font-size: 10px;
  color: var(--workflow-muted, #888);
}

.favorite-btn {
  padding: 4px;
  border: none;
  background: transparent;
  color: var(--workflow-muted, #888);
  cursor: pointer;
  border-radius: 4px;
  transition: all 0.15s ease;
}

.favorite-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fbbf24;
}

.favorite-btn.active {
  color: #fbbf24;
}

.template-preview {
  margin-bottom: 8px;
  padding: 8px;
  border-radius: 4px;
  background: var(--workflow-surface, #1e1e1e);
  overflow: hidden;
}

.template-preview pre {
  margin: 0;
  font-size: 10px;
  font-family: 'Consolas', 'Monaco', monospace;
  color: #a3a3a3;
  overflow-x: auto;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.template-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
  font-size: 10px;
  color: var(--workflow-muted, #888);
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.template-actions {
  display: flex;
  gap: 6px;
}

.apply-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid #10b981;
  border-radius: 4px;
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.apply-btn:hover {
  background: rgba(16, 185, 129, 0.2);
  transform: translateY(-1px);
}

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 4px;
  background: var(--workflow-surface, #1e1e1e);
  color: var(--workflow-muted, #888);
  cursor: pointer;
  transition: all 0.15s ease;
}

.icon-btn:hover {
  border-color: #3b82f6;
  color: #3b82f6;
}

.icon-btn.copied {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.icon-btn.danger:hover {
  border-color: #ef4444;
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.save-template-section {
  padding: 12px;
  border-top: 1px solid var(--workflow-border, #3a3a3a);
  background: var(--workflow-surface-input, #0a0a0a);
}

.save-template-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 10px;
  border: 1px solid #3b82f6;
  border-radius: 6px;
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.save-template-btn:hover {
  background: rgba(59, 130, 246, 0.2);
  transform: translateY(-1px);
}

.save-template-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.save-template-form input,
.save-template-form textarea {
  padding: 8px 10px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 4px;
  background: var(--workflow-surface, #1e1e1e);
  color: var(--workflow-text, #e0e0e0);
  font-size: 11px;
  font-family: inherit;
}

.save-template-form textarea {
  resize: vertical;
}

.form-actions {
  display: flex;
  gap: 8px;
}

.secondary-btn,
.primary-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 16px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.secondary-btn {
  background: var(--workflow-surface, #1e1e1e);
  color: var(--workflow-text, #e0e0e0);
}

.secondary-btn:hover {
  background: rgba(255, 255, 255, 0.05);
}

.primary-btn {
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.primary-btn:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.2);
}

.primary-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
