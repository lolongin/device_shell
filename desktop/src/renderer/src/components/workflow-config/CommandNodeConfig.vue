<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { Save, Braces } from 'lucide-vue-next'
import type { NodeConfigProps, NodeConfigEmits } from './types'

const props = defineProps<NodeConfigProps>()
const emit = defineEmits<NodeConfigEmits>()

const commandEditor = ref<HTMLTextAreaElement | null>(null)
const commandReferenceAnchor = ref<HTMLElement | null>(null)
const showCommandReferenceMenu = ref(false)
const commandReferenceQuery = ref('')
const showAllCommandReferences = ref(false)

const filteredCommandReferences = computed(() => {
  const query = commandReferenceQuery.value.trim().toLocaleLowerCase()
  const references = props.commandReferences || []
  if (!query) return references
  return references.filter((item) => `${item.label} ${item.reference} ${item.hint}`.toLocaleLowerCase().includes(query))
})

const compactCommandReferences = computed(() => filteredCommandReferences.value.filter((item) => {
  const reference = item.reference
  return reference.startsWith('inputs.') || !reference.includes('.')
}))

const visibleCommandReferences = computed(() => {
  if (showAllCommandReferences.value || commandReferenceQuery.value.trim()) return filteredCommandReferences.value
  return compactCommandReferences.value
})

const hiddenCommandReferenceCount = computed(() => {
  if (showAllCommandReferences.value || commandReferenceQuery.value.trim()) return 0
  return Math.max(0, filteredCommandReferences.value.length - compactCommandReferences.value.length)
})

function closeCommandReferenceMenuOnOutsideClick(event: PointerEvent): void {
  if (!commandReferenceAnchor.value?.contains(event.target as Node)) {
    showCommandReferenceMenu.value = false
    commandReferenceQuery.value = ''
    showAllCommandReferences.value = false
  }
}

function toggleCommandReferenceMenu(): void {
  showCommandReferenceMenu.value = !showCommandReferenceMenu.value
  if (!showCommandReferenceMenu.value) {
    commandReferenceQuery.value = ''
    showAllCommandReferences.value = false
  }
}

onMounted(() => document.addEventListener('pointerdown', closeCommandReferenceMenuOnOutsideClick))
onBeforeUnmount(() => document.removeEventListener('pointerdown', closeCommandReferenceMenuOnOutsideClick))

function updateConfig(key: string, value: unknown): void {
  props.node.config[key] = value
  emit('update', props.node)
}

function updateConfigString(key: string, event: Event): void {
  updateConfig(key, (event.target as HTMLInputElement | HTMLTextAreaElement).value)
}

function updateConfigJson(key: string, event: Event): void {
  try {
    const value = (event.target as HTMLTextAreaElement).value
    updateConfig(key, value ? JSON.parse(value) : {})
  } catch {
    // 保持原值
  }
}

function getConfigString(key: string): string {
  return String(props.node.config[key] || '')
}

function insertCommandReference(reference: string): void {
  if (!commandEditor.value) return
  const textarea = commandEditor.value
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const text = textarea.value
  const before = text.substring(0, start)
  const after = text.substring(end)
  const newText = `${before}\${${reference}}${after}`
  updateConfig('command', newText)
  showCommandReferenceMenu.value = false
  setTimeout(() => {
    if (commandEditor.value) {
      const newPosition = start + reference.length + 3
      commandEditor.value.focus()
      commandEditor.value.setSelectionRange(newPosition, newPosition)
    }
  }, 10)
}

const commandPreview = computed(() => {
  const command = getConfigString('command')
  const hasReference = /\$\{[^}]+\}/.test(command)
  return {
    text: hasReference ? command : command || '（尚未配置命令）',
    runtimeOnly: hasReference
  }
})

function eventValue(event: Event): string {
  return (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value
}
</script>

<template>
  <div class="command-node-config">
    <label>
      运行位置
      <select :value="String(node.config.execution_mode || 'device')" @change="updateConfigString('execution_mode', $event)">
        <option value="device">设备终端 / SSH</option>
        <option value="shell">本机 Shell</option>
        <option value="bash">Bash</option>
      </select>
    </label>

    <div class="workflow-command-field">
      <div class="workflow-command-label-row">
        <span>要执行的命令</span>
        <div ref="commandReferenceAnchor" class="workflow-command-insert-anchor">
          <button
            class="workflow-command-insert"
            type="button"
            :aria-expanded="showCommandReferenceMenu"
            title="在光标位置插入变量"
            @mousedown.prevent
            @click="toggleCommandReferenceMenu"
          >
            <Braces :size="13" />插入变量
          </button>
          <div v-if="showCommandReferenceMenu" class="workflow-command-reference-menu" role="menu" aria-label="选择要插入的变量">
            <small class="workflow-command-reference-title">选择引用，插入到当前光标位置</small>
            <input v-model="commandReferenceQuery" class="workflow-command-reference-search" type="search" placeholder="搜索变量或输出字段" aria-label="搜索变量或输出字段" />
            <small v-if="!commandReferenceQuery.trim() && compactCommandReferences.length" class="workflow-command-reference-group">常用变量</small>
            <button
              v-for="item in visibleCommandReferences"
              :key="item.reference"
              type="button"
              role="menuitem"
              @mousedown.prevent
              @click="insertCommandReference(item.reference)"
            >
              <span>
                <strong>{{ item.label }}</strong>
                <small>{{ item.hint }}</small>
              </span>
              <code>${{ '{' }}{{ item.reference }}{{ '}' }}</code>
            </button>
            <button v-if="hiddenCommandReferenceCount" type="button" class="workflow-command-reference-more" @mousedown.prevent @click="showAllCommandReferences = true">
              更多字段（{{ hiddenCommandReferenceCount }}）
            </button>
            <small v-if="commandReferences?.length && !visibleCommandReferences.length" class="workflow-command-reference-empty">
              没有匹配的变量或输出字段。
            </small>
            <small v-if="!commandReferences?.length" class="workflow-command-reference-empty">
              暂无可用变量；请先连接上游步骤或定义流程输入。
            </small>
          </div>
        </div>
      </div>

      <textarea
        ref="commandEditor"
        :value="getConfigString('command')"
        rows="3"
        placeholder="例如：display version；控制键可输入 Ctrl+B"
        @input="updateConfigString('command', $event)"
      />

      <div class="workflow-command-preview" :class="{ 'is-runtime': commandPreview.runtimeOnly }">
        <span>实际命令预览</span>
        <code>{{ commandPreview.text }}</code>
        <small>{{ commandPreview.runtimeOnly ? '运行时解析' : '当前值已解析' }}</small>
      </div>
    </div>

    <label>
      超时时间（秒）
        <input
          :value="node.config.timeout_seconds || ''"
        type="number"
          min="0"
        max="86400"
        @input="updateConfig('timeout_seconds', Number(eventValue($event)))"
      />
        <label class="workflow-inline-toggle"><input type="checkbox" :checked="Number(node.config.timeout_seconds || 0) === 0" @change="updateConfig('timeout_seconds', ($event.target as HTMLInputElement).checked ? 0 : 30)" />永不超时</label>
    </label>

    <details v-if="node.config.execution_mode !== 'device'" class="workflow-command-advanced">
      <summary><strong>高级参数</strong><span>工作目录、环境变量</span></summary>
      <div class="workflow-command-grid">
        <label>
          工作目录
          <input :value="getConfigString('cwd')" placeholder="可选，例如 D:/scripts" @input="updateConfigString('cwd', $event)" />
        </label>
        <label>
          环境变量 JSON
          <textarea
            :value="JSON.stringify(node.config.env || {})"
            rows="2"
            placeholder='可选，例如 {"MODE":"prod"}'
            @change="updateConfigJson('env', $event)"
          />
        </label>
      </div>
    </details>

    <div class="workflow-command-result-contract">
      <span>输出</span>
      <code v-for="field in actions?.find((item) => item.id === node.action_id)?.outputFields || []" :key="field.name">{{ field.label }}</code>
    </div>

    <small class="field-hint">可直接输入文本；填写 Ctrl+A 到 Ctrl+Z 时发送控制字节且不附带回车，也可用“插入变量”生成 `${变量名}`。</small>

    <label>
      失败后的处理
      <select :value="String(node.config.failure_strategy || 'stop')" @change="updateConfigString('failure_strategy', $event)">
        <option value="stop">停止流程</option>
        <option value="continue">继续后续节点</option>
      </select>
    </label>

    <!-- 操作按钮 -->
    <div class="config-actions">
      <button type="button" class="connect-button" @click="emit('save-as-action')">
        <Save :size="13" />保存为自定义 Action
      </button>
      <button class="connect-button" type="button" @click="emit('test')">
        测试此步骤
      </button>
    </div>
  </div>
</template>

<style scoped>
.command-node-config {
  display: flex;
  flex-direction: column;
  gap: 13px;
}

.workflow-command-field {
  display: grid;
  gap: 8px;
}

.workflow-command-advanced {
  padding-top: 8px;
  border-top: 1px solid var(--workflow-border);
}

.workflow-command-advanced summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--workflow-muted);
  cursor: pointer;
  font-size: 10px;
  list-style: none;
}

.workflow-command-advanced summary::-webkit-details-marker { display: none; }
.workflow-command-advanced summary:hover { color: var(--workflow-text); }
.workflow-command-advanced summary span { font-weight: 400; }

.workflow-command-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.workflow-command-label-row > span {
  color: var(--workflow-text);
  font-size: 11px;
}

.workflow-command-insert {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 4px;
  color: var(--workflow-muted);
  background: var(--workflow-surface-input);
  font-size: 10px;
  cursor: pointer;
}

.workflow-command-insert-anchor {
  position: relative;
}

.workflow-command-insert:hover {
  color: var(--workflow-text);
  border-color: rgba(148, 163, 184, .42);
}

.workflow-command-reference-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  z-index: 10;
  display: grid;
  gap: 2px;
  min-width: 280px;
  max-width: 100%;
  max-height: 320px;
  margin-top: 4px;
  padding: 6px;
  overflow-y: auto;
  border: 1px solid var(--workflow-border);
  border-radius: 6px;
  background: #111b2e;
  box-shadow: 0 8px 24px rgba(2, 6, 23, .32);
}

.workflow-command-reference-title {
  display: block;
  padding: 4px 6px;
  color: var(--workflow-muted);
  font-size: 9px;
}

.workflow-command-reference-search {
  box-sizing: border-box;
  width: 100%;
  min-height: 28px;
  padding: 6px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 4px;
  color: var(--workflow-text);
  background: var(--workflow-surface-input);
  font: 10px inherit;
}

.workflow-command-reference-search::placeholder { color: var(--workflow-muted); }
.workflow-command-reference-group { padding: 4px 6px 2px; color: var(--workflow-muted); font-size: 9px; }

.workflow-command-reference-menu > button {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 6px 8px;
  border: 0;
  border-radius: 4px;
  color: var(--workflow-text);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.workflow-command-reference-menu > button:hover {
  background: var(--workflow-surface-muted);
}

.workflow-command-reference-menu > .workflow-command-reference-more {
  justify-content: center;
  border-color: var(--workflow-border);
  color: var(--workflow-focus);
  font-size: 10px;
}

.workflow-command-reference-menu > button > span {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.workflow-command-reference-menu > button strong {
  overflow: hidden;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-command-reference-menu > button small {
  overflow: hidden;
  color: var(--workflow-muted);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-command-reference-menu > button code {
  padding: 2px 5px;
  border-radius: 3px;
  color: #99f6e4;
  background: rgba(15, 118, 110, .12);
  font: 9px ui-monospace, SFMono-Regular, Consolas, monospace;
}

.workflow-command-reference-empty {
  display: block;
  padding: 8px;
  color: var(--workflow-muted);
  font-size: 10px;
  text-align: center;
}

.workflow-command-preview {
  display: grid;
  gap: 4px;
  padding: 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  background: var(--workflow-surface-muted);
}

.workflow-command-preview.is-runtime {
  border-color: rgba(251, 191, 36, .34);
  background: rgba(251, 191, 36, .06);
}

.workflow-command-preview > span {
  color: var(--workflow-muted);
  font-size: 9px;
}

.workflow-command-preview code {
  overflow-wrap: anywhere;
  color: var(--workflow-text);
  font: 10px/1.4 ui-monospace, SFMono-Regular, Consolas, monospace;
}

.workflow-command-preview small {
  color: var(--workflow-muted);
  font-size: 9px;
}

.workflow-command-grid {
  display: grid;
  gap: 10px;
}

.workflow-command-result-contract {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px;
  color: var(--workflow-muted);
  font-size: 10px;
}

.workflow-command-result-contract code {
  padding: 3px 5px;
  border: 1px solid var(--workflow-border);
  border-radius: 4px;
  color: #99f6e4;
  background: rgba(15, 118, 110, .12);
}

.config-actions {
  display: grid;
  gap: 8px;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--workflow-border);
}

.field-hint {
  color: var(--workflow-muted);
  font-size: 10px;
  line-height: 1.4;
}

.field-hint code {
  padding: 1px 4px;
  border-radius: 3px;
  color: #99f6e4;
  background: rgba(15, 118, 110, .12);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 9px;
}
</style>
