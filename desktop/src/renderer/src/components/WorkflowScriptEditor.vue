<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { BookOpen, Maximize2, Minimize2, WrapText } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  modelValue: string
  language?: string
  placeholder?: string
  ariaLabel?: string
}>(), {
  language: 'python',
  placeholder: '输入脚本内容…',
  ariaLabel: '脚本编辑器'
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const editorRef = ref<HTMLTextAreaElement | null>(null)
const isFullscreen = ref(false)
const softWrap = ref(true)
const showDeviceApi = ref(false)
const lineCount = computed(() => Math.max(1, props.modelValue.split('\n').length))
const lineNumbers = computed(() => Array.from({ length: lineCount.value }, (_, index) => index + 1))

function updateValue(event: Event): void {
  emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key !== 'Tab') return
  event.preventDefault()
  const textarea = editorRef.value
  if (!textarea) return
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  const value = props.modelValue
  const nextValue = `${value.slice(0, start)}    ${value.slice(end)}`
  emit('update:modelValue', nextValue)
  void nextTick(() => {
    textarea.selectionStart = start + 4
    textarea.selectionEnd = start + 4
  })
}

function syncScroll(event: Event): void {
  const textarea = event.target as HTMLTextAreaElement
  const lineNumbersElement = textarea.parentElement?.querySelector<HTMLElement>('.workflow-script-line-numbers')
  if (lineNumbersElement) lineNumbersElement.scrollTop = textarea.scrollTop
}

function toggleFullscreen(): void {
  isFullscreen.value = !isFullscreen.value
  void nextTick(() => editorRef.value?.focus())
}

function handleEscape(event: KeyboardEvent): void {
  if (event.key === 'Escape' && isFullscreen.value) toggleFullscreen()
}

watch(isFullscreen, (active) => {
  document.body.classList.toggle('workflow-script-editor-open', active)
})

onBeforeUnmount(() => {
  document.body.classList.remove('workflow-script-editor-open')
})
</script>

<template>
  <section class="workflow-script-editor" :class="{ fullscreen: isFullscreen }" @keydown="handleEscape">
    <header class="workflow-script-editor-toolbar">
      <div class="workflow-script-editor-title">
        <span class="workflow-script-language-dot" aria-hidden="true"></span>
        <strong>脚本编辑器</strong>
        <code>{{ language }}</code>
      </div>
      <div class="workflow-script-editor-actions">
        <button v-if="language === 'python'" type="button" class="workflow-script-api-toggle" :class="{ active: showDeviceApi }" title="查看设备脚本 API" aria-label="查看设备脚本 API" :aria-expanded="showDeviceApi" @click="showDeviceApi = !showDeviceApi"><BookOpen :size="14" /><span>设备 API</span></button>
        <button type="button" :class="{ active: softWrap }" title="切换自动换行" aria-label="切换自动换行" :aria-pressed="softWrap" @click="softWrap = !softWrap"><WrapText :size="14" /></button>
        <button type="button" :title="isFullscreen ? '退出专注编辑' : '专注编辑'" :aria-label="isFullscreen ? '退出专注编辑' : '专注编辑'" @click="toggleFullscreen">
          <Minimize2 v-if="isFullscreen" :size="14" />
          <Maximize2 v-else :size="14" />
        </button>
      </div>
    </header>
    <aside v-if="showDeviceApi && language === 'python'" class="workflow-script-device-api" aria-label="Python 设备 API 参考">
      <header><strong>设备命令 API</strong><button type="button" aria-label="关闭 API 参考" @click="showDeviceApi = false">收起</button></header>
      <p><code>device.run(command, timeout=30, connection=None)</code></p>
      <ul>
        <li><code>command</code>：要发送的终端命令，必填。</li>
        <li><code>timeout</code>：等待秒数，默认 30，范围大于 0 且不超过 86400。</li>
        <li><code>connection</code>：可选连接协议（如 <code>ssh</code>）或会话 ID；不传则使用本次工作流选定的会话。</li>
      </ul>
      <p><code>device.connections</code> 可查看当前设备的会话及其 <code>connection</code>、<code>session_id</code>、<code>title</code>、<code>status</code>。同协议有多个已连接会话时，请传会话 ID。</p>
      <pre><code>def main(device):
    connections = device.connections
    result = device.run("display version", connection="ssh")
    return result</code></pre>
      <small>返回字典包含命令输出和执行状态。也可在脚本中运行 <code>help(device.run)</code> 查看签名。</small>
    </aside>
    <div class="workflow-script-editor-body">
      <div class="workflow-script-line-numbers" aria-hidden="true">
        <span v-for="line in lineNumbers" :key="line">{{ line }}</span>
      </div>
      <textarea
        ref="editorRef"
        class="workflow-script-textarea"
        :value="modelValue"
        :placeholder="placeholder"
        :aria-label="ariaLabel"
        :data-language="language"
        :wrap="softWrap ? 'soft' : 'off'"
        spellcheck="false"
        autocapitalize="off"
        autocomplete="off"
        autocorrect="off"
        @input="updateValue"
        @keydown="handleKeydown"
        @scroll="syncScroll"
      />
    </div>
    <footer class="workflow-script-editor-status">
      <span>{{ lineCount }} 行</span>
      <span>{{ softWrap ? '自动换行' : '不换行' }}</span>
    </footer>
  </section>
</template>
