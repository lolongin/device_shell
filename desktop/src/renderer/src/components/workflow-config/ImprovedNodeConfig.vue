<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ChevronDown, ChevronRight, Info, AlertCircle, CheckCircle, Play } from 'lucide-vue-next'
import type { NodeConfigProps, NodeConfigEmits } from './types'
import ValueBindingField from './ValueBindingField.vue'
import { buildWorkflowReferences } from '../../composables/workflowReferences'

const props = defineProps<NodeConfigProps>()
const emit = defineEmits<NodeConfigEmits & { test: [] }>()

const EXPANDED_SECTIONS_KEY = 'device-tui.workflow-expanded-sections'

function loadExpandedSections(): Set<string> {
  try {
    const stored = window.localStorage.getItem(EXPANDED_SECTIONS_KEY)
    return stored ? new Set(JSON.parse(stored)) : new Set(['basic'])
  } catch {
    return new Set(['basic'])
  }
}

function saveExpandedSections(sections: Set<string>): void {
  try {
    window.localStorage.setItem(EXPANDED_SECTIONS_KEY, JSON.stringify([...sections]))
  } catch {
    // localStorage 可选
  }
}

const expandedSections = ref<Set<string>>(loadExpandedSections())

function toggleSection(section: string): void {
  if (expandedSections.value.has(section)) {
    expandedSections.value.delete(section)
  } else {
    expandedSections.value.add(section)
  }
  saveExpandedSections(expandedSections.value)
}

const workflowReferences = computed(() => buildWorkflowReferences(props))

type ConfigField = {
  name: string
  label: string
  type: string
  required: boolean
  description?: string
  placeholder?: string
  unit?: string
  enum?: unknown[]
  schema?: Record<string, unknown>
}

const configSections = computed(() => {
  const actionId = props.node.action_id
  const sections: Array<{ id: string; title: string; fields: ConfigField[]; required: boolean }> = []

  // 获取 schema
  const actionSchema = props.actions?.find(a => a.id === actionId)?.inputSchema
  const properties = actionSchema?.properties as Record<string, any> || {}
  const requiredFields = Array.isArray(actionSchema?.required) ? actionSchema.required : []

  // 分离必填和可选字段
  const basicFields: ConfigField[] = []
  const advancedFields: ConfigField[] = []

  for (const [name, prop] of Object.entries(properties)) {
    if (prop.deprecated) continue

    const field: ConfigField = {
      name,
      label: getFieldLabel(actionId, name),
      type: getFieldType(prop),
      required: requiredFields.includes(name),
      description: prop.description,
      placeholder: prop.placeholder,
      enum: prop.enum,
      schema: prop
    }

    if (field.required) {
      basicFields.push(field)
    } else {
      advancedFields.push(field)
    }
  }

  // 基础配置
  if (basicFields.length > 0) {
    sections.push({
      id: 'basic',
      title: '基础配置',
      fields: basicFields,
      required: true
    })
  }

  // 高级配置
  if (advancedFields.length > 0) {
    sections.push({
      id: 'advanced',
      title: '高级选项',
      fields: advancedFields,
      required: false
    })
  }

  return sections
})

function getFieldLabel(actionId: string, name: string): string {
  const labels: Record<string, string> = {
    device_id: '目标设备',
    timeout_seconds: '超时时间',
    session_id: '终端会话',
    seconds: '等待秒数',
    source: actionId === 'file.upload' ? '本机文件路径' : '设备源路径',
    destination: actionId === 'file.upload' ? '设备目标路径' : '本机保存路径',
    overwrite: '覆盖已有文件',
    command: '命令内容',
    mode: '匹配模式',
    pattern: '匹配内容',
    case_sensitive: '区分大小写',
    send_enter: '发送回车',
    execution_mode: '执行方式',
    retry_attempts: '失败重试次数',
    retry_backoff_seconds: '重试间隔（秒）',
    failure_strategy: '失败处理方式',
  }
  return labels[name] || name
}

function getFieldType(prop: any): string {
  if (prop.enum) return 'enum'
  const type = Array.isArray(prop.type) ? prop.type.find((t: string) => t !== 'null') : prop.type
  if (type === 'boolean') return 'boolean'
  if (type === 'integer' || type === 'number') return 'number'
  if (type === 'array' || type === 'object') return 'json'
  return 'text'
}

function updateConfig(key: string, value: unknown): void {
  props.node.config[key] = value
  emit('update', props.node)
}

function getConfigValue(name: string): any {
  return props.node.config[name]
}

// 配置完整度计算
const configCompleteness = computed(() => {
  const schema = props.actions?.find(a => a.id === props.node.action_id)?.inputSchema
  if (!schema) return { percent: 100, filled: 0, total: 0 }

  const required = Array.isArray(schema.required) ? schema.required : []
  const filled = required.filter(name => {
    const value = props.node.config[name]
    return value !== undefined && value !== null && value !== ''
  }).length

  return {
    percent: required.length > 0 ? Math.round((filled / required.length) * 100) : 100,
    filled,
    total: required.length
  }
})

const isConfigComplete = computed(() => configCompleteness.value.percent === 100)

// 字段值转换
function getFieldValue(field: ConfigField): any {
  const value = getConfigValue(field.name)
  if (field.type === 'json' && value && typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }
  return value ?? ''
}

function setFieldValue(field: ConfigField, event: Event): void {
  const target = event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
  let value: any = target.value

  if (field.type === 'boolean') {
    value = (target as HTMLInputElement).checked
  } else if (field.type === 'number') {
    value = value === '' ? undefined : Number(value)
  } else if (field.type === 'json') {
    try {
      value = value === '' ? undefined : JSON.parse(value)
    } catch {
      return // 保持旧值
    }
  }

  updateConfig(field.name, value)
}
</script>

<template>
  <div class="improved-node-config">
    <!-- 配置进度指示器 -->
    <div class="config-progress-indicator" :class="{ complete: isConfigComplete }">
      <div class="progress-bar">
        <div class="progress-fill" :style="{ width: `${configCompleteness.percent}%` }"></div>
      </div>
      <div class="progress-info">
        <CheckCircle v-if="isConfigComplete" :size="14" class="check-icon" />
        <AlertCircle v-else :size="14" class="alert-icon" />
        <span v-if="configCompleteness.total > 0">
          {{ configCompleteness.filled }} / {{ configCompleteness.total }} 必填项已配置
        </span>
        <span v-else>无必填项</span>
      </div>
    </div>

    <!-- 分组配置区域 -->
    <div class="config-sections">
      <section
        v-for="section in configSections"
        :key="section.id"
        class="config-section"
        :class="{ expanded: expandedSections.has(section.id), required: section.required }"
      >
        <header class="section-header" @click="toggleSection(section.id)">
          <div class="section-title">
            <ChevronRight v-if="!expandedSections.has(section.id)" :size="16" class="chevron" />
            <ChevronDown v-else :size="16" class="chevron" />
            <strong>{{ section.title }}</strong>
            <span v-if="section.required" class="required-badge">必填</span>
          </div>
          <span class="field-count">{{ section.fields.length }} 项</span>
        </header>

        <div v-if="expandedSections.has(section.id)" class="section-content">
          <div v-for="field in section.fields" :key="field.name" class="config-field">
            <label class="field-label">
              <span>{{ field.label }}</span>
              <em v-if="field.required" class="required-mark">*</em>
              <Info v-if="field.description" :size="12" class="info-icon" :title="field.description" />
            </label>

            <!-- 根据字段类型渲染不同的输入组件 -->
            <div class="field-input">
              <!-- 布尔值 -->
              <label v-if="field.type === 'boolean'" class="checkbox-label">
                <input
                  type="checkbox"
                  :checked="getConfigValue(field.name)"
                  @change="setFieldValue(field, $event)"
                />
                <span>{{ field.description || '启用' }}</span>
              </label>

              <!-- 枚举值 -->
              <select
                v-else-if="field.type === 'enum'"
                :value="getConfigValue(field.name)"
                @change="setFieldValue(field, $event)"
              >
                <option value="">请选择</option>
                <option v-for="option in field.enum" :key="String(option)" :value="option">
                  {{ option }}
                </option>
              </select>

              <!-- JSON 对象/数组 -->
              <textarea
                v-else-if="field.type === 'json'"
                :value="getFieldValue(field)"
                rows="3"
                :placeholder="field.placeholder || 'JSON 格式'"
                @change="setFieldValue(field, $event)"
              />

              <!-- 使用 ValueBindingField 处理运行时绑定 -->
              <ValueBindingField
                v-else-if="field.schema && typeof field.schema === 'object' && (field.schema as any).binding?.mode === 'runtime'"
                :model-value="getConfigValue(field.name)"
                :label="field.label"
                :schema="field.schema"
                :references="workflowReferences"
                :rows="1"
                :placeholder="field.placeholder"
                @update:model-value="updateConfig(field.name, $event)"
              />

              <!-- 普通文本/数字输入 -->
              <template v-else>
                <input
                  :type="field.type === 'number' ? 'number' : 'text'"
                  :value="getFieldValue(field)"
                  :placeholder="field.placeholder"
                  @input="setFieldValue(field, $event)"
                />
                <span v-if="field.unit" class="field-unit">{{ field.unit }}</span>
              </template>
            </div>
          </div>
        </div>
      </section>
    </div>

    <!-- 快速操作栏 -->
    <div class="quick-actions">
      <button type="button" class="quick-action-btn test-btn" @click="$emit('test')">
        <Play :size="14" />
        <span>测试此步骤</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.improved-node-config {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 12px;
}

/* 进度指示器 */
.config-progress-indicator {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: 8px;
  background: var(--workflow-surface, #1e1e1e);
  border: 1px solid var(--workflow-border, #3a3a3a);
  transition: all 0.3s ease;
}

.config-progress-indicator.complete {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.05);
}

.progress-bar {
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #10b981);
  border-radius: 3px;
  transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
}

.config-progress-indicator.complete .progress-fill {
  background: #10b981;
}

.progress-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--workflow-text, #e0e0e0);
}

.check-icon {
  color: #10b981;
  flex-shrink: 0;
}

.alert-icon {
  color: #f59e0b;
  flex-shrink: 0;
}

/* 配置分组 */
.config-sections {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-section {
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 8px;
  background: var(--workflow-surface, #1e1e1e);
  overflow: hidden;
  transition: all 0.2s ease;
}

.config-section.required {
  border-left: 3px solid #3b82f6;
}

.config-section:hover {
  border-color: rgba(59, 130, 246, 0.4);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s ease;
}

.section-header:hover {
  background: rgba(255, 255, 255, 0.03);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 500;
  color: var(--workflow-text, #e0e0e0);
}

.chevron {
  color: var(--workflow-muted, #888);
  flex-shrink: 0;
  transition: transform 0.2s ease;
}

.required-badge {
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(59, 130, 246, 0.15);
  color: #60a5fa;
  font-size: 9px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.field-count {
  font-size: 10px;
  color: var(--workflow-muted, #888);
  font-weight: 400;
}

.section-content {
  padding: 0 14px 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  animation: slideDown 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 配置字段 */
.config-field {
  display: grid;
  gap: 6px;
}

.field-label {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: 500;
  color: var(--workflow-text, #e0e0e0);
}

.required-mark {
  color: #ef4444;
  font-style: normal;
  font-weight: 600;
}

.info-icon {
  color: var(--workflow-muted, #888);
  cursor: help;
  transition: color 0.15s ease;
}

.info-icon:hover {
  color: #3b82f6;
}

.field-input {
  display: flex;
  align-items: center;
  gap: 8px;
}

.field-input input[type="text"],
.field-input input[type="number"],
.field-input select,
.field-input textarea {
  flex: 1;
  min-width: 0;
  padding: 8px 10px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 6px;
  background: var(--workflow-surface-input, #0a0a0a);
  color: var(--workflow-text, #e0e0e0);
  font-size: 11px;
  font-family: inherit;
  transition: all 0.15s ease;
}

.field-input input:focus,
.field-input select:focus,
.field-input textarea:focus {
  outline: none;
  border-color: #3b82f6;
  background: rgba(59, 130, 246, 0.05);
}

.field-input input::placeholder,
.field-input textarea::placeholder {
  color: var(--workflow-muted, #666);
}

.field-input textarea {
  resize: vertical;
  min-height: 60px;
  line-height: 1.5;
}

.field-unit {
  font-size: 11px;
  color: var(--workflow-muted, #888);
  white-space: nowrap;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 11px;
  color: var(--workflow-text, #e0e0e0);
}

.checkbox-label input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
  accent-color: #3b82f6;
}

/* 快速操作 */
.quick-actions {
  display: flex;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--workflow-border, #3a3a3a);
}

.quick-action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px 16px;
  border: 1px solid var(--workflow-border, #3a3a3a);
  border-radius: 6px;
  background: var(--workflow-surface, #1e1e1e);
  color: var(--workflow-text, #e0e0e0);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s ease;
}

.quick-action-btn:hover {
  background: rgba(59, 130, 246, 0.1);
  border-color: #3b82f6;
  color: #3b82f6;
  transform: translateY(-1px);
}

.quick-action-btn:active {
  transform: translateY(0);
}

.test-btn {
  border-color: #10b981;
  color: #10b981;
}

.test-btn:hover {
  background: rgba(16, 185, 129, 0.1);
  border-color: #10b981;
  color: #10b981;
}

/* 响应式 */
@media (max-width: 768px) {
  .improved-node-config {
    padding: 12px 8px;
    gap: 12px;
  }

  .section-header {
    padding: 10px 12px;
  }

  .section-content {
    padding: 0 12px 12px;
  }
}
</style>
