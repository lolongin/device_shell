<script setup lang="ts">
import { ref } from 'vue'
import { Save, Trash2, AlertTriangle } from 'lucide-vue-next'
import type { NodeConfigProps, NodeConfigEmits } from './types'
import WorkflowScriptEditor from '../WorkflowScriptEditor.vue'

const props = defineProps<NodeConfigProps & { scriptSaving?: boolean }>()
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
  }
}

function updateScriptContent(value: string): void {
  updateConfig('script', value)
  if (props.node.config.script_id) {
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

const selectedNodeScript = ref(props.scripts?.find((s) => s.id === props.node.config.script_id))
const scriptPlaceholder = `# 示例：通过函数签名定义输入参数
def main(device_id: str, timeout: int = 30):
    # 脚本逻辑
    return {"status": "success"}`

function eventValue(event: Event): string {
  return (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value
}
</script>

<template>
  <div class="script-node-config">
    <div class="workflow-script-heading">
      <div><strong>本机脚本</strong><small>在后端主机执行，不会在设备终端运行</small></div>
      <span class="workflow-risk-chip"><AlertTriangle :size="12" />高风险</span>
    </div>

    <label>
      脚本资源
      <select :value="String(node.config.script_id || '')" @change="selectScriptForNode(eventValue($event))">
        <option value="">兼容模式：使用节点内联脚本</option>
        <option v-for="script in scripts" :key="script.id" :value="script.id">
          {{ script.name }} · {{ script.language }}
        </option>
      </select>
    </label>

    <label v-if="!node.config.script_id">
      脚本语言
      <select :value="String(node.config.language || 'python')" @change="updateConfigString('language', $event)">
        <option value="python">Python</option>
        <option value="powershell">PowerShell</option>
        <option value="bash">Bash</option>
      </select>
    </label>

    <div v-if="node.config.script_id" class="workflow-script-reference-notice">
      <span><Save :size="14" />引用脚本资源</span>
      <strong>{{ selectedNodeScript?.name || node.config.script_id }}</strong>
      <small>参数名和类型由脚本函数签名决定；修改脚本代码后需单独保存脚本资源。</small>
      <div class="workflow-script-resource-actions-inline">
        <button type="button" class="secondary-button" @click="emit('open-script-studio', String(node.config.script_id))">
          <Save :size="13" />打开脚本工作区
        </button>
        <button
          v-if="selectedNodeScript"
          type="button"
          class="primary-action"
          :disabled="scriptSaving"
          @click="emit('save-script')"
        >
          <Save :size="13" />{{ scriptSaving ? '保存中…' : '保存脚本' }}
        </button>
      </div>
    </div>

    <WorkflowScriptEditor
      :model-value="selectedNodeScript?.script || getConfigString('script')"
      :language="String(node.config.language || selectedNodeScript?.language || 'python')"
      :placeholder="scriptPlaceholder"
      aria-label="步骤脚本编辑器"
      @update:model-value="updateScriptContent"
    />

    <small class="field-hint">脚本在后端主机执行；引用资源时，编辑内容会同步到对应脚本资源。</small>

    <!-- 脚本输入参数配置 -->
    <div v-if="selectedNodeScript?.input_schema?.length" class="workflow-script-node-inputs">
      <div class="workflow-script-node-input-heading">
        <div><strong>脚本输入</strong><small>按脚本定义配置参数</small></div>
        <div class="workflow-script-test-mode" role="tablist" aria-label="脚本输入模式">
          <button type="button" :class="{ active: scriptNodeInputMode === 'form' }" @click="scriptNodeInputMode = 'form'">
            参数表单
          </button>
          <button type="button" :class="{ active: scriptNodeInputMode === 'json' }" @click="scriptNodeInputMode = 'json'">
            JSON
          </button>
        </div>
      </div>

      <div v-if="scriptNodeInputMode === 'form'" class="workflow-script-node-input-form">
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

      <small class="field-hint">
        参数会以 JSON 写入 <code>DEVICE_TUI_INPUT_JSON</code>；支持使用 <code>${inputs.xxx}</code> 引用流程输入。
      </small>
    </div>

    <!-- 没有输入参数时的 JSON 配置 -->
    <label v-else>
      输入 JSON
      <textarea
        :value="typeof node.config.input_json === 'string' ? String(node.config.input_json) : JSON.stringify(node.config.input_json || {})"
        rows="3"
        placeholder='例如：{"device_id":"router-1"}'
        @change="updateScriptNodeInputJsonEditor($event)"
      />
      <small class="field-hint">
        脚本通过环境变量 <code>DEVICE_TUI_INPUT_JSON</code> 读取；变量引用必须单独作为完整值。
      </small>
    </label>

    <!-- 工作目录和环境变量 -->
    <div class="workflow-command-grid">
      <label>
        工作目录
        <input :value="getConfigString('cwd')" placeholder="可选，例如 D:/scripts" @input="updateConfigString('cwd', $event)" />
      </label>
      <label>
        环境变量 JSON
        <textarea
          :value="JSON.stringify(node.config.env || {})"
          rows="3"
          placeholder='例如：{"MODE":"prod"}'
          @change="updateConfigJson('env', $event)"
        />
      </label>
    </div>

    <!-- 超时和输出限制 -->
    <div class="workflow-command-grid">
      <label>
        超时时间（秒）
        <input
          :value="node.config.timeout_seconds || ''"
          type="number"
          min="0"
          max="86400"
          @input="updateConfig('timeout_seconds', Number(eventValue($event)))"
        />
        <label class="workflow-inline-toggle"><input type="checkbox" :checked="Number(node.config.timeout_seconds || 0) === 0" @change="updateConfig('timeout_seconds', ($event.target as HTMLInputElement).checked ? 0 : 300)" />永不超时</label>
      </label>
      <label>
        最大输出长度
        <input
          :value="node.config.max_output_chars || 1048576"
          type="number"
          min="1024"
          max="16777216"
          step="1024"
          @input="updateConfig('max_output_chars', Number(eventValue($event)))"
        />
        <small class="field-hint">stdout 和 stderr 分别保留，避免日志失控。</small>
      </label>
    </div>

    <!-- 输出说明 -->
    <div class="workflow-command-result-contract">
      <span>输出</span>
      <code v-for="field in actions?.find((item) => item.id === node.action_id)?.outputFields || []" :key="field.name">{{ field.label }}</code>
    </div>
    <small class="field-hint">
      脚本 stdout 最后一行若是 JSON，会解析为 <code>result</code>；退出码非 0 时步骤失败。
    </small>

    <!-- 操作按钮 -->
    <div class="config-actions">
      <button type="button" class="connect-button" @click="emit('save-as-action')">
        <Save :size="13" />保存为自定义 Action
      </button>
      <button class="remove-node-button" type="button" @click="emit('remove')">
        <Trash2 :size="13" />删除步骤
      </button>
      <button class="connect-button" type="button" @click="emit('test')">
        测试此步骤
      </button>
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

.workflow-script-heading strong {
  color: var(--workflow-text);
  font-size: 13px;
}

.workflow-script-heading small {
  color: var(--workflow-muted);
  font-size: 10px;
}

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
  display: grid;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--workflow-border);
  border-radius: 6px;
  background: var(--workflow-surface-muted);
}

.workflow-script-node-input-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
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


