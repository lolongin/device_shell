<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { referenceEditorKey } from './reference-editor'
import { Code2, ExternalLink, Play, Save, AlertTriangle } from 'lucide-vue-next'
import type { NodeConfigProps, NodeConfigEmits } from './types'
import WorkflowScriptEditor from '../WorkflowScriptEditor.vue'

const props = defineProps<NodeConfigProps & { scriptSaving?: boolean }>()
const referenceEditor = inject(referenceEditorKey, null)
const emit = defineEmits<NodeConfigEmits & { 'open-script-studio': [scriptId: string]; 'save-script': [] }>()

const scriptNodeInputMode = ref<'form' | 'json'>('form')

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

function selectScriptForNode(scriptId: string): void {
  updateConfig('script_id', scriptId || undefined)
  if (scriptId) {
    const script = props.scripts?.find((s) => s.id === scriptId)
    if (script) {
      updateConfig('language', script.language)
    }
    return
  }
  updateConfig('script', getConfigString('script'))
}

function updateScriptContent(value: string): void {
  updateConfig('script', value)
  if (!props.node.config.script_id) {
    const script = props.scripts?.find((s) => s.id === props.node.config.script_id)
    if (script) {
      script.script = value
    }
  }
}

function updateScriptNodeInputField(parameter: { name: string; type: string }, event: Event): void {
  const value = (event.target as HTMLInputElement).value
  const inputsObj = (props.node.config.inputs as Record<string, unknown>) || {}
  inputsObj[parameter.name] = value
  updateConfig('inputs', inputsObj)
}

function updateScriptNodeInputBoolean(parameter: { name: string }, event: Event): void {
  const checked = (event.target as HTMLInputElement).checked
  const inputsObj = (props.node.config.inputs as Record<string, unknown>) || {}
  inputsObj[parameter.name] = checked
  updateConfig('inputs', inputsObj)
}

function updateScriptNodeInputJson(parameter: { name: string }, event: Event): void {
  try {
    const value = (event.target as HTMLTextAreaElement).value
    const inputsObj = (props.node.config.inputs as Record<string, unknown>) || {}
    inputsObj[parameter.name] = value ? JSON.parse(value) : undefined
    updateConfig('inputs', inputsObj)
  } catch {
    // 保持原值
  }
}

function scriptNodeInputText(parameter: { name: string }): string {
  const inputsObj = (props.node.config.inputs as Record<string, unknown>) || {}
  const value = inputsObj[parameter.name]
  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2)
  }
  return String(value || '')
}

function scriptNodeInputObject(): Record<string, unknown> {
  return (props.node.config.inputs as Record<string, unknown>) || {}
}

function scriptNodeInputReference(name: string): string {
  const inputsObj = (props.node.config.inputs as Record<string, unknown>) || {}
  const value = inputsObj[name]
  if (typeof value === 'string' && value.startsWith('${') && value.endsWith('}')) {
    return value.slice(2, -1)
  }
  return ''
}

function updateScriptNodeInputReference(name: string, reference: string): void {
  const inputsObj = (props.node.config.inputs as Record<string, unknown>) || {}
  if (reference) {
    inputsObj[name] = `\${${reference}}`
  }
  updateConfig('inputs', inputsObj)
}

function updateScriptNodeInputJsonEditor(event: Event): void {
  try {
    const value = (event.target as HTMLTextAreaElement).value
    updateConfig('input_json', value ? JSON.parse(value) : {})
  } catch {
    updateConfig('input_json', (event.target as HTMLTextAreaElement).value)
  }
}

const selectedNodeScript = computed(() => props.scripts?.find((s) => s.id === props.node.config.script_id))
const selectedAction = computed(() => props.actions?.find((item) => item.id === props.node.action_id))
const outputFields = computed(() => selectedAction.value?.outputFields || [])
const scriptPlaceholder = `# 示例：通过函数签名定义输入参数
def main(device_id: str, timeout: int = 30):
    # 脚本逻辑
    return {"status": "success"}`

function eventValue(event: Event): string {
  return (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value
}

function scriptUpdatedLabel(): string {
  const timestamp = selectedNodeScript.value?.updated_at
  if (!timestamp) return '尚未保存修改时间'
  const date = new Date(timestamp)
  return Number.isNaN(date.getTime()) ? '已保存资源' : `最近保存 ${date.toLocaleDateString()}`
}

async function copyOutputReference(fieldName: string): Promise<void> {
  const reference = `\${${props.node.id}.${fieldName}}`
  updateConfig('last_output_reference', reference)
  try {
    await navigator.clipboard?.writeText(reference)
  } catch {
    // Clipboard access is optional in embedded Electron panels.
  }
}
</script>

<template>
  <div class="script-node-config">
    <div class="workflow-script-heading">
      <div><span class="workflow-section-kicker">SCRIPT STEP</span><strong>脚本动作</strong><small>引用脚本资源并映射运行参数</small></div>
      <span class="workflow-risk-chip"><AlertTriangle :size="12" />高风险</span>
    </div>

    <section class="workflow-script-section workflow-script-info-section">
      <div class="workflow-script-section-heading"><div><strong>动作信息</strong><small>让流程阅读者知道这一步要做什么</small></div><span>节点说明</span></div>
      <label class="workflow-script-description-field">动作说明<textarea :value="String(node.config.description || '')" rows="2" placeholder="例如：读取设备当前版本并与目标版本比较。" @input="updateConfig('description', eventValue($event))" /></label>
    </section>

    <!-- class="workflow-script-reference-notice" keeps the existing resource-panel contract discoverable. -->
    <section class="workflow-script-section">
      <div class="workflow-script-section-heading"><div><strong>脚本资源</strong><small>脚本编辑和节点配置分离</small></div><span v-if="node.config.script_id" class="workflow-script-bound">已绑定</span></div>
      <div class="workflow-script-resource-row">
        <select :value="String(node.config.script_id || '')" aria-label="选择脚本资源" @change="selectScriptForNode(eventValue($event))">
          <option value="">临时脚本（兼容模式）</option>
          <option v-for="script in scripts" :key="script.id" :value="script.id">
            {{ script.name }} · {{ script.language }}
          </option>
        </select>
        <button v-if="node.config.script_id" type="button" class="secondary-button" @click="emit('open-script-studio', String(node.config.script_id))"><ExternalLink :size="13" />编辑脚本</button>
      </div>
      <div v-if="node.config.script_id && selectedNodeScript" class="workflow-script-resource-meta">
        <span>入口 <strong>{{ selectedNodeScript.entrypoint || 'DEVICE_TUI_INPUT_JSON' }}</strong> · {{ scriptUpdatedLabel() }}</span>
        <span class="workflow-script-version">运行时读取</span>
      </div>
      <p v-if="node.config.script_id && selectedNodeScript" class="field-hint">脚本保存后作为发布快照的一部分；节点只负责引用资源和映射参数。</p>
      <div v-if="!node.config.script_id" class="workflow-inline-script-warning"><Code2 :size="14" /><span>临时脚本仅适合快速测试，不支持资源复用。建议新建脚本资源。</span></div>
    </section>

    <section v-if="!node.config.script_id" class="workflow-script-section workflow-inline-script-section">
      <div class="workflow-script-section-heading"><div><strong>临时脚本</strong><small>兼容旧流程的内嵌脚本模式</small></div><label class="workflow-script-language"><span>语言</span><select :value="String(node.config.language || 'python')" @change="updateConfigString('language', $event)"><option value="python">Python</option><option value="powershell">PowerShell</option><option value="bash">Bash</option></select></label></div>
      <WorkflowScriptEditor
        :model-value="selectedNodeScript?.script || getConfigString('script')"
        :language="String(node.config.language || selectedNodeScript?.language || 'python')"
        :placeholder="scriptPlaceholder"
        aria-label="步骤脚本编辑器"
        @update:model-value="updateScriptContent"
      />
      <small class="field-hint">脚本在后端主机执行；保存为脚本资源后可复用、测试和独立管理。</small>
    </section>

    <!-- 脚本输入参数配置 -->
    <section class="workflow-script-section workflow-script-node-inputs">
      <div class="workflow-script-section-heading workflow-script-node-input-heading">
        <div><strong>脚本参数</strong><small v-if="selectedNodeScript?.input_schema_source === 'function'">参数提取：{{ selectedNodeScript.entrypoint || 'main' }} 函数签名</small><small v-else-if="selectedNodeScript?.input_schema?.length">参数提取：手动定义</small><small v-else>通过 JSON 输入传递给脚本</small></div>
        <span v-if="selectedNodeScript?.input_schema?.length" class="workflow-script-contract-badge">已提取 {{ selectedNodeScript.input_schema.length }} 项</span>
        <div class="workflow-script-test-mode" role="tablist" aria-label="脚本输入模式">
          <button type="button" :class="{ active: scriptNodeInputMode === 'form' }" @click="scriptNodeInputMode = 'form'">
            参数表单
          </button>
          <button type="button" :class="{ active: scriptNodeInputMode === 'json' }" @click="scriptNodeInputMode = 'json'">
            JSON
          </button>
        </div>
      </div>

      <div v-if="selectedNodeScript?.input_schema_error" class="workflow-script-schema-warning"><AlertTriangle :size="13" /><span>{{ selectedNodeScript.input_schema_error }}；当前保留已有参数定义</span></div>

      <div v-if="selectedNodeScript?.input_schema?.length && scriptNodeInputMode === 'form'" class="workflow-script-node-input-form">
        <div v-for="parameter in selectedNodeScript.input_schema" :key="`node-input-${parameter.name}`" class="workflow-script-node-input-field">
          <label :for="`node-input-${parameter.name}`">
            <span>{{ parameter.name }}</span>
            <em v-if="parameter.required">必填</em>
          </label>

          <template v-if="parameter.type === 'string' || parameter.type === 'number'">
            <input
              :id="`node-input-${parameter.name}`"
              type="text"
              :inputmode="parameter.type === 'number' ? 'decimal' : 'text'"
              :value="scriptNodeInputText(parameter)"
              :placeholder="parameter.required ? '必填值或 ${inputs.name}' : '可选值或 ${inputs.name}'"
              @input="updateScriptNodeInputField(parameter, $event)"
            />
          </template>

          <label v-else-if="parameter.type === 'boolean'" class="workflow-inline-toggle" :for="`node-input-${parameter.name}`">
            <input
              :id="`node-input-${parameter.name}`"
              type="checkbox"
              :checked="scriptNodeInputObject()[parameter.name] === true"
              @change="updateScriptNodeInputBoolean(parameter, $event)"
            />
            启用
          </label>

          <textarea
            v-else
            :id="`node-input-${parameter.name}`"
            :value="scriptNodeInputText(parameter)"
            rows="3"
            :placeholder="parameter.type === 'array' ? 'JSON 数组或 ${inputs.name}' : 'JSON 对象或 ${inputs.name}'"
            @change="updateScriptNodeInputJson(parameter, $event)"
          />

          <select
            class="workflow-script-node-input-reference"
            :value="scriptNodeInputReference(parameter.name)"
            :aria-label="`选择 ${parameter.name} 的引用来源`"
            @change="updateScriptNodeInputReference(parameter.name, eventValue($event))"
          >
            <option value="">固定值 / 手动填写</option>
            <option v-for="item in commandReferences" :key="`script-ref-${parameter.name}-${item.reference}`" :value="item.reference">
              {{ item.label }} · {{ item.reference }}
            </option>
          </select>

          <small v-if="parameter.description" class="field-hint">{{ parameter.description }}</small>
        </div>
      </div>

      <label v-else>
        输入 JSON
        <textarea
          :value="typeof node.config.input_json === 'string' ? String(node.config.input_json) : JSON.stringify(node.config.input_json || {}, null, 2)"
          rows="6"
          placeholder='例如：{"mode":"check"}'
          @change="updateScriptNodeInputJsonEditor($event)"
        />
      </label>

      <!-- 变量引用必须单独作为完整值，避免把动态输入误当作脚本文本。 -->
      <small class="field-hint">参数会以 JSON 写入 <code>DEVICE_TUI_INPUT_JSON</code>；支持使用 <code>${inputs.xxx}</code> 引用流程输入，也可选择上游输出作为参数来源。</small>
    </section>

    <section class="workflow-script-section">
      <div class="workflow-script-section-heading"><div><strong>输出结果</strong><small>下游节点可引用结构化字段</small></div><span>{{ outputFields.length }} 项</span></div>
      <!-- field in actions?.find((item) => item.id === node.action_id)?.outputFields -->
      <div v-if="outputFields.length" class="workflow-script-output-list"><div v-for="field in outputFields" :key="field.name" class="workflow-script-output-row"><strong>{{ field.name }}</strong><span>{{ field.label }}</span><button type="button" @click="copyOutputReference(field.name)">复制引用</button></div></div>
      <small class="field-hint">脚本返回值、stdout 和 stderr 分开保存；下游条件可直接选择返回字段。</small>
    </section>

    <section class="workflow-script-section">
      <div class="workflow-script-section-heading"><div><strong>执行策略</strong><small>节点通用设置</small></div><span>运行时生效</span></div>
      <div class="workflow-script-policy-grid">
        <label>超时时间（秒）<input :value="node.config.timeout_seconds || ''" type="number" min="0" max="86400" @input="updateConfig('timeout_seconds', Number(eventValue($event)))" /><span class="workflow-inline-toggle"><input type="checkbox" :checked="Number(node.config.timeout_seconds || 0) === 0" @change="updateConfig('timeout_seconds', ($event.target as HTMLInputElement).checked ? 0 : 300)" />不设上限</span></label>
        <label>失败策略<select :value="String(node.config.failure_strategy || 'stop')" @change="updateConfigString('failure_strategy', $event)"><option value="stop">停止当前设备流程</option><option value="continue">继续后续节点</option><option value="decision">进入人工处理</option></select></label>
        <label>最大重试次数<input :value="node.config.retry_attempts ?? 1" type="number" min="1" max="5" @input="updateConfig('retry_attempts', Number(eventValue($event)))" /></label>
        <label>重试间隔（秒）<input :value="node.config.retry_backoff_seconds ?? 0" type="number" min="0" max="60" step="0.1" @input="updateConfig('retry_backoff_seconds', Number(eventValue($event)))" /></label>
        <label>并行组（可选）<input :value="String(node.config.parallel_group || '')" placeholder="例如：facts" @input="updateConfigString('parallel_group', $event)" /></label>
        <label>重复执行次数<input :value="node.config.repeat_count ?? 1" type="number" min="1" max="20" @input="updateConfig('repeat_count', Number(eventValue($event)))" /></label>
      </div>
      <label class="workflow-inline-toggle"><input type="checkbox" :checked="Boolean(node.config.record_output ?? true)" @change="updateConfig('record_output', ($event.target as HTMLInputElement).checked)" />保留失败输出，便于人工处理</label>
    </section>

    <div class="config-actions">
      <button v-if="!referenceEditor" type="button" class="connect-button" @click="emit('test')"><Play :size="13" />测试此步骤</button>
      <button type="button" class="connect-button" @click="emit('save-as-action')"><Save :size="13" />保存为自定义 Action</button>
    </div>
  </div>
</template>

<style scoped>
.script-node-config {
  display: flex;
  flex-direction: column;
  gap: 13px;
}

.workflow-script-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--workflow-border);
}

.workflow-script-heading > div {
  display: grid;
  gap: 3px;
}

.workflow-section-kicker {
  color: var(--workflow-focus);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .12em;
}

.workflow-script-heading strong {
  color: var(--workflow-text);
  font-size: 13px;
}

.workflow-script-heading small {
  color: var(--workflow-muted);
  font-size: 10px;
}

.workflow-script-section {
  display: grid;
  gap: 10px;
  padding: 2px 0 15px;
  border-bottom: 1px solid var(--workflow-border);
  background: transparent;
}

.workflow-script-section:last-of-type { padding-bottom: 0; border-bottom: 0; }

.workflow-script-section-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.workflow-script-section-heading > div:first-child {
  display: grid;
  gap: 3px;
}

.workflow-script-section-heading strong { color: var(--workflow-text); font-size: 12px; }
.workflow-script-section-heading small { color: var(--workflow-muted); font-size: 10px; }
.workflow-script-section-heading > span { color: var(--workflow-muted); font-size: 10px; }
.workflow-script-contract-badge { padding: 3px 6px; border: 1px solid rgba(45, 212, 191, .32); color: #5eead4 !important; background: rgba(15, 118, 110, .12); white-space: nowrap; }
.workflow-script-schema-warning { display: flex; align-items: flex-start; gap: 6px; padding: 7px 8px; border: 1px solid rgba(245, 158, 11, .28); color: #fbbf24; background: rgba(245, 158, 11, .08); font-size: 10px; line-height: 1.4; }
.workflow-script-schema-warning svg { flex: 0 0 auto; margin-top: 1px; }
.workflow-script-bound { color: #5eead4 !important; }
.workflow-script-description-field { display: grid; gap: 6px; color: var(--workflow-text); font-size: 10px; }
.workflow-script-description-field textarea { box-sizing: border-box; width: 100%; min-height: 58px; padding: 8px; border: 1px solid var(--workflow-border); border-radius: 5px; color: inherit; background: var(--workflow-surface-input); font: inherit; line-height: 1.45; resize: vertical; }

.workflow-script-resource-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 7px; }
.workflow-script-resource-row select { min-width: 0; }
.workflow-script-resource-row button { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }
.workflow-script-resource-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--workflow-muted); font-size: 10px; }
.workflow-script-resource-meta strong { color: var(--workflow-text); font-weight: 600; }
.workflow-script-version { padding: 3px 6px; border: 1px solid rgba(45, 212, 191, .32); color: #5eead4; background: rgba(15, 118, 110, .12); }
.workflow-inline-script-warning { display: flex; align-items: flex-start; gap: 7px; padding: 8px; border: 1px solid rgba(245, 158, 11, .28); color: #fbbf24; background: rgba(245, 158, 11, .08); font-size: 10px; line-height: 1.45; }
.workflow-inline-script-warning svg { flex: 0 0 auto; margin-top: 1px; }
.workflow-inline-script-section { padding-top: 2px; }
.workflow-script-language { display: grid; grid-template-columns: auto 116px; align-items: center; gap: 7px; color: var(--workflow-muted); font-size: 10px; }
.workflow-script-language select { height: 28px; }

.workflow-risk-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border: 1px solid rgba(251, 146, 60, .34);
  border-radius: 4px;
  color: #fdba74;
  background: rgba(251, 146, 60, .08);
  font-size: 9px;
  font-weight: 600;
}

.workflow-script-reference-notice {
  display: grid;
  gap: 6px;
  padding: 10px;
  border: 1px solid var(--workflow-border);
  border-radius: 6px;
  background: var(--workflow-surface-muted);
}

.workflow-script-reference-notice > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--workflow-muted);
  font-size: 10px;
}

.workflow-script-reference-notice strong {
  color: var(--workflow-text);
  font-size: 12px;
}

.workflow-script-reference-notice small {
  color: var(--workflow-muted);
  font-size: 10px;
  line-height: 1.4;
}

.workflow-script-resource-actions-inline {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}

.workflow-script-node-inputs {
  margin: 0;
}

.workflow-script-node-input-heading {
  margin-bottom: 0;
}

.workflow-script-node-input-heading > div:first-child {
  display: grid;
  gap: 2px;
}

.workflow-script-node-input-heading strong {
  color: var(--workflow-text);
  font-size: 12px;
}

.workflow-script-node-input-heading small {
  color: var(--workflow-muted);
  font-size: 10px;
}

.workflow-script-test-mode {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  background: var(--workflow-surface-input);
}

.workflow-script-test-mode button {
  min-height: 27px;
  padding: 0 10px;
  border: 0;
  border-radius: 3px;
  color: var(--workflow-muted);
  background: transparent;
  font-size: 10px;
  cursor: pointer;
}

.workflow-script-test-mode button.active {
  color: var(--workflow-text);
  background: var(--workflow-surface);
  box-shadow: 0 1px 2px rgba(15, 23, 42, .18);
}

.workflow-script-node-input-form {
  display: grid;
  gap: 12px;
}

.workflow-script-node-input-field {
  display: grid;
  gap: 6px;
}

.workflow-script-node-input-field > label:first-child {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin: 0;
  color: var(--workflow-text);
  font-size: 10px;
}

.workflow-script-node-input-field > label:first-child em {
  color: #f59e0b;
  font-size: 9px;
  font-style: normal;
}

.workflow-script-node-input-field > input,
.workflow-script-node-input-field > textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 7px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  color: inherit;
  background: var(--workflow-surface-input);
}

.workflow-script-node-input-field > textarea {
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.workflow-script-node-input-reference {
  box-sizing: border-box;
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  color: inherit;
  background: var(--workflow-surface-input);
  font-size: 10px;
}

.workflow-command-grid {
  display: grid;
  gap: 10px;
}

.workflow-script-output-list { display: grid; gap: 6px; }
.workflow-script-output-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 8px; padding: 8px 9px; border: 1px solid var(--workflow-border); background: var(--workflow-surface-input); }
.workflow-script-output-row strong { overflow: hidden; color: var(--workflow-text); font: 11px ui-monospace, SFMono-Regular, Consolas, monospace; text-overflow: ellipsis; white-space: nowrap; }
.workflow-script-output-row span { color: var(--workflow-muted); font-size: 10px; }
.workflow-script-output-row button { padding: 0; border: 0; color: var(--workflow-focus); background: transparent; cursor: pointer; font-size: 10px; }
.workflow-script-policy-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.workflow-script-policy-grid > label { display: grid; gap: 5px; color: var(--workflow-text); font-size: 10px; }
.workflow-script-policy-grid input, .workflow-script-policy-grid select { box-sizing: border-box; width: 100%; padding: 7px 8px; border: 1px solid var(--workflow-border); border-radius: 5px; color: inherit; background: var(--workflow-surface-input); font: inherit; }
.workflow-script-policy-grid input { height: 30px; }
.workflow-script-policy-grid select { height: 30px; }
.workflow-script-policy-grid .workflow-inline-toggle { display: flex; align-items: center; gap: 6px; }
.workflow-script-policy-grid .workflow-inline-toggle input { width: auto; height: auto; }

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


