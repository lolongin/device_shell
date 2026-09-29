<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { FileUp, Trash2 } from 'lucide-vue-next'
import type { NodeConfigProps, NodeConfigEmits } from './types'

const props = defineProps<NodeConfigProps>()
const emit = defineEmits<NodeConfigEmits & { 'choose-upload-source': [] }>()

type SchemaProperty = { name: string; required: boolean; type: string; enum?: unknown[]; description?: string }
const schemaProperties = computed<SchemaProperty[]>(() => {
  const schema = props.actions?.find((item) => item.id === props.node.action_id)?.inputSchema
  const properties = schema?.properties
  if (!properties || typeof properties !== 'object' || Array.isArray(properties)) return []
  const required = Array.isArray(schema.required) ? schema.required as string[] : []
  return Object.entries(properties as Record<string, unknown>).map(([name, value]) => {
    const definition = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
    const rawType = Array.isArray(definition.type) ? definition.type.find((item) => item !== 'null') : definition.type
    return {
      name,
      required: required.includes(name),
      type: typeof rawType === 'string' ? rawType : 'string',
      enum: Array.isArray(definition.enum) ? definition.enum : undefined,
      description: typeof definition.description === 'string' ? definition.description : undefined,
    }
  })
})

const uploadInputs = computed(() => (props.workflowInputs || [])
  .filter((input) => String(input.name || '').trim() && ['file', 'string'].includes(input.type || 'string')))
const uploadDestinationInputs = computed(() => uploadInputs.value.filter((input) => (input.type || 'string') === 'string'))
const uploadOverwriteInputs = computed(() => (props.workflowInputs || [])
  .filter((input) => String(input.name || '').trim() && input.type === 'boolean'))

const UPLOAD_PATH_HISTORY_KEY = 'device-tui.workflow-upload-paths'
const uploadPathHistory = ref<string[]>(loadUploadPathHistory())

function loadUploadPathHistory(): string[] {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(UPLOAD_PATH_HISTORY_KEY) || '[]')
    return Array.isArray(parsed) ? parsed.filter((value): value is string => typeof value === 'string' && Boolean(value.trim())).slice(0, 12) : []
  } catch {
    return []
  }
}

function normalizeUploadPath(value: string): string {
  const normalized = value.trim().replace(/\\/g, '/')
  if (!normalized) return ''
  return normalized.length > 1 ? normalized.replace(/\/+$/, '') : normalized
}

function uploadSourceParts(): { path: string; name: string } {
  const configuredPath = String(props.node.config.source_path || '').trim()
  const configuredName = String(props.node.config.source_name || '').trim()
  if (configuredPath || configuredName) return { path: configuredPath, name: configuredName }
  const source = String(props.node.config.source || '').replace(/\\/g, '/').trim()
  if (!source || source.startsWith('${')) return { path: '', name: '' }
  const separator = source.lastIndexOf('/')
  if (separator < 0) return { path: '.', name: source }
  return { path: source.slice(0, separator) || '/', name: source.slice(separator + 1) }
}

const uploadSourcePath = computed(() => uploadSourceParts().path)
const uploadFileName = computed(() => uploadSourceParts().name)
const uploadPathInput = computed(() => uploadInputReference('source_path', uploadInputs.value) || (uploadSourceInput.value && !String(props.node.config.source || '').includes('/')) ? uploadSourceInput.value : '')
const uploadNameInput = computed(() => uploadInputReference('source_name', uploadDestinationInputs.value))

function rememberUploadPath(value: string): void {
  const path = normalizeUploadPath(value)
  if (!path || path === '.') return
  uploadPathHistory.value = [path, ...uploadPathHistory.value.filter(item => item !== path)].slice(0, 12)
  try { window.localStorage.setItem(UPLOAD_PATH_HISTORY_KEY, JSON.stringify(uploadPathHistory.value)) } catch { /* storage is optional */ }
}

watch(uploadSourcePath, (path) => {
  if (path && path !== '.') rememberUploadPath(path)
})

function updateUploadSourcePart(part: 'path' | 'name', value: string): void {
  const current = uploadSourceParts()
  const nextPath = part === 'path' ? normalizeUploadPath(value) : current.path
  const nextName = part === 'name' ? value.trim() : current.name
  const source = nextPath && nextPath !== '.' ? `${nextPath.replace(/\/$/, '')}/${nextName}` : nextName
  updateConfig(part === 'path' ? 'source_path' : 'source_name', value.trim())
  updateConfig('source', source)
}

function updateUploadPath(event: Event): void { updateUploadSourcePart('path', eventValue(event)) }
function updateUploadFileName(event: Event): void { updateUploadSourcePart('name', eventValue(event)) }

function setUploadPartInput(part: 'path' | 'name', name: string): void {
  const key = part === 'path' ? 'source_path' : 'source_name'
  const current = uploadSourceParts()
  const value = name ? '${inputs.' + name + '}' : ''
  const path = part === 'path' ? value : current.path
  const fileName = part === 'name' ? value : current.name
  const source = path && fileName ? `${path.replace(/\/$/, '')}/${fileName}` : path || fileName
  updateConfig(key, value)
  updateConfig('source', source)
}

function uploadInputReference(key: string, inputs: Array<{ name: string }>): string {
  const value = String(props.node.config[key] ?? '')
  if (!value.startsWith('${') || !value.endsWith('}')) return ''
  const reference = value.slice(2, -1)
  const name = reference.startsWith('inputs.') ? reference.slice(7) : reference
  return inputs.some((input) => input.name === name) ? name : ''
}

const uploadSourceInput = computed(() => uploadInputReference('source', uploadInputs.value))
const uploadDestinationInput = computed(() => uploadInputReference('destination', uploadDestinationInputs.value))
const uploadOverwriteInput = computed(() => uploadInputReference('overwrite', uploadOverwriteInputs.value))

function setUploadInput(key: string, name: string): void {
  updateConfig(key, name ? '${inputs.' + name + '}' : key === 'overwrite' ? true : '')
}

function updateConfig(key: string, value: unknown): void {
  props.node.config[key] = value
  emit('update', props.node)
}

function updateConfigString(key: string, event: Event): void {
  updateConfig(key, (event.target as HTMLInputElement | HTMLTextAreaElement).value)
}

function getConfigString(key: string): string {
  return String(props.node.config[key] || '')
}

function eventValue(event: Event): string {
  return (event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement).value
}

function updateSchemaField(field: SchemaProperty, event: Event): void {
  const target = event.target as HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
  if (field.type === 'boolean') updateConfig(field.name, (target as HTMLInputElement).checked)
  else if (field.type === 'number' || field.type === 'integer') updateConfig(field.name, target.value === '' ? '' : Number(target.value))
  else if (field.type === 'object' || field.type === 'array') {
    try { updateConfig(field.name, target.value === '' ? '' : JSON.parse(target.value)) } catch { /* Keep the last valid value. */ }
  }
  else updateConfig(field.name, target.value)
}

function schemaValue(field: SchemaProperty): string {
  const value = props.node.config[field.name]
  return value === undefined || value === null ? '' : typeof value === 'string' ? value : JSON.stringify(value)
}

function schemaInputCandidates(field: SchemaProperty): Array<{ name: string; type?: string }> {
  return (props.workflowInputs || []).filter((input) => {
    const type = input.type || 'string'
    if (field.type === 'string') return type === 'string' || type === 'file'
    return type === field.type
  })
}

function schemaReference(field: SchemaProperty): string {
  const value = schemaValue(field)
  if (!value.startsWith('${') || !value.endsWith('}')) return ''
  const reference = value.slice(2, -1)
  const name = reference.startsWith('inputs.') ? reference.slice(7) : reference
  return schemaInputCandidates(field).some((input) => input.name === name) ? name : ''
}

function setSchemaReference(field: SchemaProperty, name: string): void {
  updateConfig(field.name, name ? '${inputs.' + name + '}' : '')
}

function fieldLabel(name: string): string {
  return ({
    mode: '匹配模式',
    pattern: '匹配内容',
    case_sensitive: '区分大小写',
    send_enter: '发送回车',
    timeout_seconds: '超时时间',
    after_sequence: '起始序号',
    execution_mode: '执行方式',
    retry_attempts: '失败重试次数',
    retry_backoff_seconds: '重试间隔（秒）',
    failure_strategy: '失败处理方式',
  } as Record<string, string>)[name] || name
}

function enumLabel(value: unknown): string {
  return ({
    contains: '包含文本',
    regex: '正则表达式',
    device: '设备命令',
    shell: 'Shell 命令',
    bash: 'Bash 命令',
    stop: '停止流程',
    continue: '继续执行',
  } as Record<string, string>)[String(value)] || String(value)
}
</script>

<template>
  <div class="generic-node-config">
    <!-- Device Select -->
    <template v-if="node.action_id === 'device.select'">
      <label>
        目标设备
        <select :value="String(node.config.device_id || '')" @change="updateConfigString('device_id', $event)">
          <option value="">选择设备</option>
          <option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">
            {{ device.name }} ({{ device.address }})
          </option>
        </select>
      </label>
    </template>

    <!-- Device Connect -->
    <template v-else-if="node.action_id === 'device.connect'">
      <label>
        目标设备
        <select :value="String(node.config.device_id || '')" @change="updateConfigString('device_id', $event)">
          <option value="">选择设备</option>
          <option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">
            {{ device.name }} ({{ device.address }})
          </option>
        </select>
      </label>
      <label>
        超时时间
        <input
          :value="node.config.timeout_seconds || 30"
          type="number"
          min="1"
          max="300"
          @input="updateConfig('timeout_seconds', Number(eventValue($event)))"
        />
        秒
      </label>
    </template>

    <!-- Device Info -->
    <template v-else-if="node.action_id === 'device.info'">
      <label>
        采集字段
        <select :value="node.config.fields" multiple size="4" @change="updateConfig('fields', Array.from(($event.target as HTMLSelectElement).selectedOptions).map(o => o.value))">
          <option value="name">名称</option>
          <option value="address">地址</option>
          <option value="model">型号</option>
          <option value="software_version">软件版本</option>
          <option value="status">状态</option>
          <option value="output">原始输出</option>
        </select>
        <small class="field-hint">可多选，后续条件和保存结果可使用这些字段。</small>
      </label>
    </template>

    <!-- Utility Wait -->
    <template v-else-if="node.action_id === 'utility.wait'">
      <label>
        等待秒数
        <input
          :value="node.config.seconds || 5"
          type="number"
          min="1"
          max="3600"
          @input="updateConfig('seconds', Number(eventValue($event)))"
        />
      </label>
    </template>

    <!-- File Upload -->
    <template v-else-if="node.action_id === 'file.upload'">
      <p class="transfer-minimum">最小输入：指定本机文件或选择文件入参；运行流程时选择目标设备。VRP 设备目标路径留空时使用 flash:/文件名。</p>
      <label>
        <!-- 上传文件来源 <em>必填</em>：兼容旧版配置语义 -->
        本机文件路径 <em>必填</em>
        <select :value="uploadPathInput" aria-label="选择本机文件路径来源" @change="setUploadPartInput('path', eventValue($event))">
          <option value="">固定路径</option>
          <option v-for="input in uploadInputs" :key="`path-${input.name}`" :value="input.name">流程入参 · {{ input.name }}</option>
        </select>
        <div class="workflow-upload-file-fields">
          <div class="workflow-file-input">
            <code v-if="uploadPathInput" class="workflow-upload-reference">${{ '{' }}inputs.{{ uploadPathInput }}{{ '}' }}</code>
            <input v-else :value="uploadSourcePath" list="workflow-upload-path-history" placeholder="本机文件路径，例如 D:/packages" aria-label="本机文件路径" @input="updateUploadPath" @blur="rememberUploadPath(eventValue($event))" />
            <button v-if="!uploadPathInput" type="button" class="workflow-file-button workflow-upload-picker" title="选择本机文件" @click="emit('choose-upload-source')"><FileUp :size="14" />选择文件</button>
          </div>
          <datalist id="workflow-upload-path-history"><option v-for="path in uploadPathHistory" :key="path" :value="path" /></datalist>
        </div>
        <small class="field-hint">可固定填写，也可绑定外部流程入参。</small>
      </label>
      <label>
        文件名 <em>必填</em>
        <select :value="uploadNameInput" aria-label="选择上传文件名来源" @change="setUploadPartInput('name', eventValue($event))">
          <option value="">固定文件名</option>
          <option v-for="input in uploadDestinationInputs" :key="`name-${input.name}`" :value="input.name">流程入参 · {{ input.name }}</option>
        </select>
        <code v-if="uploadNameInput" class="workflow-upload-reference">${{ '{' }}inputs.{{ uploadNameInput }}{{ '}' }}</code>
        <input v-else :value="uploadFileName" placeholder="文件名，例如 image.cc" aria-label="上传文件名" @input="updateUploadFileName" />
        <small class="field-hint">路径和文件名都支持外部入参引用。</small>
      </label>
      <!-- 上传文件来源 <em>必填</em>；选择上传文件的流程入参；路径、文件名分别支持选择流程入参 -->
      <label>
        设备目标路径（可选）
        <select :value="uploadDestinationInput" aria-label="选择设备目标路径的流程入参" @change="setUploadInput('destination', eventValue($event))">
          <option value="">固定路径 / 使用默认路径</option>
          <option v-for="input in uploadDestinationInputs" :key="input.name" :value="input.name">流程入参 · {{ input.name }}</option>
        </select>
        <input v-if="!uploadDestinationInput"
          :value="getConfigString('destination')"
          placeholder="留空自动使用 flash:/文件名"
          @input="updateConfigString('destination', $event)"
        />
        <code v-else class="workflow-upload-reference">{{ getConfigString('destination') }}</code>
        <small class="field-hint">VRP 设备留空时默认上传到 flash:/ 目录，也可手动指定完整路径。</small>
      </label>
      <label>
        覆盖已有文件
        <select :value="uploadOverwriteInput" aria-label="选择覆盖开关的流程入参" @change="setUploadInput('overwrite', eventValue($event))">
          <option value="">固定值</option>
          <option v-for="input in uploadOverwriteInputs" :key="input.name" :value="input.name">流程入参 · {{ input.name }}</option>
        </select>
        <code v-if="uploadOverwriteInput" class="workflow-upload-reference">{{ getConfigString('overwrite') }}</code>
      </label>
      <label v-if="!uploadOverwriteInput" class="workflow-inline-toggle">
        <input
          type="checkbox"
          :checked="node.config.overwrite !== false"
          @change="updateConfig('overwrite', ($event.target as HTMLInputElement).checked)"
        />
        文件已存在时覆盖
      </label>
    </template>

    <!-- File Download -->
    <template v-else-if="node.action_id === 'file.download'">
      <label>
        设备源路径
        <input
          :value="getConfigString('source')"
          placeholder="例如：flash:/image.cc"
          @input="updateConfigString('source', $event)"
        />
      </label>
      <label>
        本地保存位置
        <input
          :value="getConfigString('destination')"
          placeholder="共享目录中的相对路径"
          @input="updateConfigString('destination', $event)"
        />
      </label>
    </template>

    <div v-else class="schema-node-fields">
      <label v-for="field in schemaProperties" :key="field.name">
        {{ fieldLabel(field.name) }}<em v-if="field.required">必填</em>
        <select
          v-if="schemaInputCandidates(field).length"
          :value="schemaReference(field)"
          :aria-label="`选择${fieldLabel(field.name)}来源`"
          @change="setSchemaReference(field, eventValue($event))"
        >
          <option value="">固定值</option>
          <option v-for="input in schemaInputCandidates(field)" :key="input.name" :value="input.name">流程入参 · {{ input.name }}</option>
        </select>
        <code v-if="schemaReference(field)" class="workflow-upload-reference">{{ schemaValue(field) }}</code>
        <template v-if="field.name === 'timeout_seconds'">
          <input v-if="!schemaReference(field) && Number(node.config.timeout_seconds || 0) > 0" :value="schemaValue(field)" type="number" min="1" max="86400" @input="updateSchemaField(field, $event)" />
          <label class="workflow-inline-toggle"><input type="checkbox" :checked="Number(node.config.timeout_seconds || 0) === 0" @change="updateConfig('timeout_seconds', ($event.target as HTMLInputElement).checked ? 0 : 30)" />永不超时</label>
        </template>
        <select v-else-if="!schemaReference(field) && field.enum?.length" :value="schemaValue(field)" @change="updateSchemaField(field, $event)">
          <option value="">请选择</option><option v-for="option in field.enum" :key="String(option)" :value="String(option)">{{ enumLabel(option) }}</option>
        </select>
        <input v-else-if="!schemaReference(field) && field.type === 'boolean'" type="checkbox" :checked="node.config[field.name] === true" @change="updateSchemaField(field, $event)" />
        <input v-else-if="!schemaReference(field) && ['string', 'number', 'integer'].includes(field.type)" :value="schemaValue(field)" :type="field.type === 'string' ? 'text' : 'number'" @input="updateSchemaField(field, $event)" />
        <textarea v-else-if="!schemaReference(field)" :value="schemaValue(field)" rows="3" @change="updateSchemaField(field, $event)" />
        <small v-if="field.description" class="field-hint">{{ field.description }}</small>
      </label>
      <p v-if="!schemaProperties.length" class="config-placeholder">此动作没有额外配置项。</p>
    </div>

    <!-- 通用操作按钮 -->
    <div class="config-actions">
      <button class="remove-node-button" type="button" @click="emit('remove')">
        <Trash2 :size="13" />删除步骤
      </button>
      <button v-if="node.action_id !== 'variable.set'" class="connect-button" type="button" @click="emit('test')">
        测试此步骤
      </button>
    </div>
  </div>
</template>

<style scoped>
.generic-node-config {
  display: flex;
  flex-direction: column;
  gap: 13px;
}

label {
  display: grid;
  gap: 5px;
  color: var(--workflow-text);
  font-size: 11px;
}

input,
select,
textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 7px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  color: inherit;
  background: var(--workflow-surface-input);
  font: inherit;
}

input::placeholder,
textarea::placeholder {
  color: var(--workflow-muted);
}

.workflow-inline-toggle {
  display: flex !important;
  align-items: center;
  gap: 7px;
  margin: 1px 0 2px !important;
  color: var(--workflow-muted);
  cursor: pointer;
}

.workflow-inline-toggle input {
  width: auto !important;
  margin: 0 !important;
  accent-color: var(--accent);
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

.config-placeholder {
  padding: 20px;
  text-align: center;
  color: var(--workflow-muted);
  font-size: 11px;
}

.transfer-minimum {
  margin: 0;
  padding: 8px 10px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  color: var(--workflow-muted);
  font-size: 11px;
  line-height: 1.5;
}

.workflow-upload-file-fields {
  display: grid;
  gap: 6px;
}

.workflow-file-input {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 6px;
}

.workflow-file-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 9px;
  color: var(--workflow-text);
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  background: var(--workflow-surface-input);
  cursor: pointer;
  font: inherit;
  white-space: nowrap;
}

.workflow-file-button:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.workflow-upload-reference {
  padding: 7px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 5px;
  color: var(--workflow-text);
  background: var(--workflow-surface-input);
  font-size: 11px;
}

.config-actions {
  display: grid;
  gap: 8px;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--workflow-border);
}
</style>
