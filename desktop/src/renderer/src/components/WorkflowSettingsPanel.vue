<script setup lang="ts">
import { Plus, Trash2, FileUp } from 'lucide-vue-next'

export type WorkflowSettingsInput = {
  name: string
  type?: string
  semanticType?: string
  required?: boolean
  default?: unknown
  description?: string
}

export type WorkflowSettingsOutput = {
  name: string
  type?: string
  value?: unknown
  description?: string
  presentation?: string
}

export type WorkflowSettingsReference = {
  reference: string
  label: string
}

const props = defineProps<{
  workflow: { name: string; description?: string; inputs?: WorkflowSettingsInput[]; outputs?: WorkflowSettingsOutput[] }
  hasUnsavedChanges: boolean
  inputValues: Record<string, unknown>
  inputsExpanded: boolean
  outputsExpanded: boolean
  runtimeInputsExpanded: boolean
  transferRoot?: string
  workflowInputHasIssue: (name: string) => boolean
  workflowInputDisplay: (input: WorkflowSettingsInput) => string
  isWorkflowFileInput: (input: WorkflowSettingsInput) => boolean
  updateWorkflowInputDefinition: (index: number, key: string, value: unknown) => void
  removeWorkflowInput: (index: number) => void
  addWorkflowInput: () => void
  updateWorkflowOutput: (index: number, key: string, value: unknown) => void
  removeWorkflowOutput: (index: number) => void
  addWorkflowOutput: () => void
  outputReferences: WorkflowSettingsReference[]
  updateWorkflowInput: (name: string, event: Event) => void
  normalizeWorkflowInputJson: (name: string) => void
  chooseWorkflowRuntimeFile: (input: WorkflowSettingsInput) => void | Promise<void>
  onOpenTransferSettings: () => void
}>()

const emit = defineEmits<{
  'update:inputsExpanded': [value: boolean]
  'update:outputsExpanded': [value: boolean]
  'update:runtimeInputsExpanded': [value: boolean]
}>()

function outputReferenceValue(value: unknown): string {
  const text = String(value ?? '')
  return text.startsWith('${') && text.endsWith('}') ? text.slice(2, -1) : ''
}

function setOutputReference(index: number, reference: string): void {
  props.updateWorkflowOutput(index, 'value', reference ? `\${${reference}}` : '')
}

const outputPresentationOptions = '文本、JSON、表格、下载、设备信息、隐藏'
</script>

<template>
  <div class="workflow-settings-panel">
  <section class="workflow-metadata-editor" aria-label="流程基本信息">
    <div class="workflow-contract-heading">
      <span class="workflow-section-kicker">当前流程</span>
      <strong>{{ workflow.name || '未命名流程' }}</strong>
      <span class="workflow-contract-status" :class="{ dirty: hasUnsavedChanges }">{{ hasUnsavedChanges ? '草稿有修改' : '已保存' }}</span>
    </div>
    <label>流程名称<input v-model="workflow.name" maxlength="120" placeholder="请输入流程名称" /></label>
    <label>流程说明<input v-model="workflow.description" maxlength="500" placeholder="说明这个流程的用途（可选）" /></label>
    <small v-if="!workflow.name.trim()">流程名称不能为空</small>
  </section>

  <section class="workflow-input-editor workflow-input-compact" :class="{ expanded: inputsExpanded }" aria-label="流程输入定义">
    <div class="panel-heading">
      <button type="button" class="workflow-section-toggle" :aria-expanded="inputsExpanded" @click="emit('update:inputsExpanded', !inputsExpanded)">
        <strong>流程输入</strong><small>{{ workflow.inputs?.length || 0 }} 个参数</small><span>{{ inputsExpanded ? '收起' : '展开' }}</span>
      </button>
      <button type="button" class="icon-toolbar-button" title="添加流程输入" aria-label="添加流程输入" @click="addWorkflowInput(); emit('update:inputsExpanded', true)"><Plus :size="14" /></button>
    </div>
    <div v-if="inputsExpanded && workflow.inputs?.length" class="workflow-input-definitions">
      <div v-for="(input, index) in workflow.inputs" :key="index" class="workflow-input-definition">
        <label>名称<input :value="input.name" placeholder="例如：package_path" @input="updateWorkflowInputDefinition(index, 'name', ($event.target as HTMLInputElement).value)" /></label>
        <label>基础类型<select :value="input.type || 'string'" @change="updateWorkflowInputDefinition(index, 'type', ($event.target as HTMLSelectElement).value)"><option value="string">文本</option><option value="file">本地文件</option><option value="device">设备</option><option value="devices">设备列表</option><option value="number">数字</option><option value="integer">整数</option><option value="boolean">布尔值</option><option value="array">数组</option><option value="object">对象</option></select></label>
        <label>业务语义<select :value="input.semanticType || ({ file: 'file', device: 'device', devices: 'device_list' }[input.type || ''] || (input.type === 'string' ? 'text' : input.type || 'text'))" @change="updateWorkflowInputDefinition(index, 'semanticType', ($event.target as HTMLSelectElement).value)"><option value="text">文本</option><option value="file">文件</option><option value="file_path">文件路径</option><option value="directory">目录</option><option value="device">设备</option><option value="device_list">设备列表</option><option value="enum">枚举</option><option value="image">图片</option><option value="json">JSON</option><option value="date">日期</option><option value="time">时间</option></select></label>
        <label class="workflow-input-required"><input type="checkbox" :checked="input.required === true" @change="updateWorkflowInputDefinition(index, 'required', ($event.target as HTMLInputElement).checked)" />必填</label>
        <label>默认值<input :value="input.default == null ? '' : String(input.default)" placeholder="可选" @input="updateWorkflowInputDefinition(index, 'default', ($event.target as HTMLInputElement).value)" /></label>
        <label class="workflow-input-description">说明<input :value="input.description || ''" placeholder="给执行者的提示" @input="updateWorkflowInputDefinition(index, 'description', ($event.target as HTMLInputElement).value)" /></label>
        <button type="button" class="icon-toolbar-button workflow-input-delete" title="删除流程输入" aria-label="删除流程输入" @click="removeWorkflowInput(index)"><Trash2 :size="14" /></button>
      </div>
    </div>
    <p v-else-if="inputsExpanded" class="field-hint">尚未定义输入。点击右上角加号后，执行时会出现运行参数。</p>
  </section>

  <section class="workflow-input-editor workflow-output-editor workflow-input-compact" :class="{ expanded: outputsExpanded }" aria-label="流程输出定义">
    <div class="panel-heading">
      <button type="button" class="workflow-section-toggle" :aria-expanded="outputsExpanded" @click="emit('update:outputsExpanded', !outputsExpanded)">
        <strong>流程输出</strong><small>{{ workflow.outputs?.length || 0 }} 个结果</small><span>{{ outputsExpanded ? '收起' : '展开' }}</span>
      </button>
      <button type="button" class="icon-toolbar-button" title="添加流程输出" aria-label="添加流程输出" @click="addWorkflowOutput(); emit('update:outputsExpanded', true)"><Plus :size="14" /></button>
    </div>
    <p class="workflow-output-help">在这里设置执行结果的显示方式：{{ outputPresentationOptions }}。未明确指定时，会根据结果数据自动选择。</p>
    <div v-if="outputsExpanded && workflow.outputs?.length" class="workflow-input-definitions">
      <div v-for="(output, index) in workflow.outputs" :key="index" class="workflow-input-definition workflow-output-definition">
        <label>名称<input :value="output.name" placeholder="例如：software_version" @input="updateWorkflowOutput(index, 'name', ($event.target as HTMLInputElement).value)" /></label>
        <label>类型<select :value="output.type || 'any'" @change="updateWorkflowOutput(index, 'type', ($event.target as HTMLSelectElement).value)"><option value="any">任意</option><option value="string">文本</option><option value="number">数字</option><option value="integer">整数</option><option value="boolean">布尔值</option><option value="array">数组</option><option value="object">对象</option></select></label>
        <label>呈现<select :value="output.presentation || 'text'" @change="updateWorkflowOutput(index, 'presentation', ($event.target as HTMLSelectElement).value)"><option value="text">文本</option><option value="json">JSON</option><option value="table">表格</option><option value="download">下载</option><option value="device">设备</option><option value="hidden">隐藏</option></select></label>
        <label class="workflow-output-value">值或引用
          <select :value="outputReferenceValue(output.value)" aria-label="选择流程输出来源" @change="setOutputReference(index, ($event.target as HTMLSelectElement).value)">
            <option value="">手动填写或表达式</option>
            <option v-for="item in outputReferences" :key="`workflow-output-${index}-${item.reference}`" :value="item.reference">{{ item.label }}</option>
          </select>
          <input :value="String(output.value ?? '')" placeholder="例如：${probe.software_version}" @input="updateWorkflowOutput(index, 'value', ($event.target as HTMLInputElement).value)" />
        </label>
        <label class="workflow-input-description">说明<input :value="output.description || ''" placeholder="供调用者理解此输出" @input="updateWorkflowOutput(index, 'description', ($event.target as HTMLInputElement).value)" /></label>
        <button type="button" class="icon-toolbar-button workflow-input-delete" title="删除流程输出" aria-label="删除流程输出" @click="removeWorkflowOutput(index)"><Trash2 :size="14" /></button>
      </div>
    </div>
    <p v-else-if="outputsExpanded" class="field-hint">尚未定义输出。发布后作为子流程使用时，显式输出会出现在调用节点上。</p>
  </section>

  <section v-if="workflow.inputs?.length" class="workflow-runtime-inputs workflow-input-compact" :class="{ expanded: runtimeInputsExpanded }" aria-label="运行参数">
    <div class="panel-heading"><button type="button" class="workflow-section-toggle" :aria-expanded="runtimeInputsExpanded" @click="emit('update:runtimeInputsExpanded', !runtimeInputsExpanded)"><strong>运行参数</strong><small>{{ workflow.inputs.length }} 个参数</small><span>{{ runtimeInputsExpanded ? '收起' : '展开' }}</span></button></div>
    <div v-if="runtimeInputsExpanded" class="workflow-input-values">
      <label v-for="input in workflow.inputs" :key="input.name" :class="{ 'workflow-input-invalid': workflowInputHasIssue(input.name) }">
        <span class="workflow-input-label">{{ input.name }}<b v-if="input.required"> · 必填</b></span>
        <small v-if="input.description" class="field-hint">{{ input.description }}</small>
        <textarea v-if="input.type === 'object' || input.type === 'array'" :data-workflow-input-name="input.name" :value="workflowInputDisplay(input)" rows="2" :placeholder="input.type === 'array' ? '例如：[a, b]' : '例如：{key: value}'" @input="updateWorkflowInput(input.name, $event)" @blur="normalizeWorkflowInputJson(input.name)" />
        <div v-else class="workflow-runtime-input-row">
          <input :data-workflow-input-name="input.name" :type="input.type === 'boolean' ? 'checkbox' : input.type === 'number' || input.type === 'integer' ? 'number' : 'text'" :step="input.type === 'integer' ? '1' : 'any'" :checked="input.type === 'boolean' ? inputValues[input.name] === true : undefined" :value="input.type === 'boolean' ? undefined : workflowInputDisplay(input)" :placeholder="isWorkflowFileInput(input) ? '选择本机文件，或填写路径' : input.default == null ? `请输入${input.name}` : ''" @input="updateWorkflowInput(input.name, $event)" @change="updateWorkflowInput(input.name, $event)" />
          <button v-if="isWorkflowFileInput(input)" type="button" class="workflow-file-button" @click="chooseWorkflowRuntimeFile(input)"><FileUp :size="14" />选择文件</button>
        </div>
        <small v-if="isWorkflowFileInput(input)" class="field-hint workflow-shared-root-hint">这是本机源文件输入；执行上传时会自动暂存到共享目录，用户无需关心暂存目录，不要把设备目标路径填在这里。<button v-if="!transferRoot" type="button" class="text-button" @click="onOpenTransferSettings">打开设置</button></small>
      </label>
    </div>
  </section>
  </div>
</template>

<style scoped>
.workflow-settings-panel { display: flex; flex-direction: column; min-width: 0; container-type: inline-size; }
.workflow-metadata-editor, .workflow-input-editor, .workflow-runtime-inputs { min-width: 0; background: var(--workflow-surface); border-bottom: 1px solid var(--workflow-border); }
.workflow-metadata-editor { display: grid; grid-template-columns: minmax(220px,.75fr) minmax(280px,1.25fr); gap: 8px 16px; padding: 10px 18px; }
.workflow-contract-heading { grid-column: 1 / -1; display: flex; align-items: center; gap: 9px; min-width: 0; }
.workflow-contract-heading strong { overflow: hidden; min-width: 0; color: var(--workflow-text); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.workflow-contract-status { margin-left: auto; padding: 3px 7px; border: 1px solid rgba(45,212,163,.26); border-radius: 999px; color: #86efac; background: rgba(16,185,129,.1); font-size: 10px; white-space: nowrap; }
.workflow-contract-status.dirty { border-color: rgba(240,180,77,.34); color: #fcd34d; background: rgba(180,83,9,.12); }
.workflow-metadata-editor label { min-width: 0; margin: 0; color: var(--workflow-muted); font-size: 10px; }
.workflow-metadata-editor input { min-height: 30px; margin-top: 4px; }
.workflow-metadata-editor small { grid-column: 1 / -1; color: #fca5a5; font-size: 10px; }
.workflow-input-editor { display: grid; gap: 8px; padding: 9px 16px; overflow: visible; }
.workflow-output-help { margin: 0; color: var(--workflow-muted); font-size: 10px; line-height: 1.5; }
.workflow-input-editor .panel-heading { display: flex; align-items: center; gap: 8px; min-height: 26px; margin-bottom: 0; }
.workflow-input-editor .panel-heading small { flex: 1; }
.workflow-input-definitions { display: grid; gap: 6px; }
.workflow-input-definition { display: grid; grid-template-columns: minmax(110px, 1fr) 100px 120px auto minmax(110px, 1fr) minmax(150px, 1.4fr) auto; align-items: end; gap: 6px; padding: 6px; border: 1px solid var(--workflow-border); border-radius: 6px; background: var(--workflow-surface); }
.workflow-output-definition { grid-template-columns: minmax(110px, .8fr) 100px 100px minmax(180px, 1.4fr) minmax(150px, 1fr) auto; }
.workflow-input-definition label { display: grid; gap: 4px; color: var(--workflow-muted); font-size: 10px; }
.workflow-input-definition label { min-width: 0; }
.workflow-input-definition input:not([type='checkbox']), .workflow-input-definition select { width: 100%; }
.workflow-input-definition input:not([type='checkbox']), .workflow-input-definition select { box-sizing: border-box; min-width: 0; min-height: 28px; padding: 5px 6px; border: 1px solid var(--workflow-border); border-radius: 4px; color: inherit; background: var(--workflow-surface-input); }
.workflow-input-definition .workflow-input-required { display: flex; align-items: center; gap: 5px; height: 29px; white-space: nowrap; }
.workflow-runtime-inputs { display: grid; gap: 8px; padding: 9px 16px; overflow: visible; }
.workflow-runtime-inputs .workflow-input-values { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px 12px; }
.workflow-runtime-inputs .workflow-input-values > label { min-width: 0; margin: 0; }
.workflow-runtime-input-row { display: flex; align-items: stretch; gap: 6px; }
.workflow-runtime-input-row > input { min-width: 0; flex: 1; }
.workflow-file-button { display: inline-flex; align-items: center; gap: 4px; padding: 6px 9px; border: 1px solid var(--workflow-border); border-radius: 4px; color: inherit; background: var(--workflow-surface); cursor: pointer; white-space: nowrap; }
.workflow-shared-root-hint { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 4px; }
.workflow-settings-panel .workflow-input-description, .workflow-settings-panel .workflow-output-value { min-width: 0; }
@media (max-width: 900px) { .workflow-input-definition, .workflow-output-definition { grid-template-columns: repeat(2, minmax(0, 1fr)); } .workflow-input-definition .workflow-input-description, .workflow-output-definition .workflow-input-description { grid-column: 1 / -1; } }
@media (max-width: 720px) { .workflow-metadata-editor { grid-template-columns: 1fr; } }
@container (max-width: 850px) {
  .workflow-output-definition { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(0, 1fr) 28px; }
  .workflow-output-value, .workflow-output-definition .workflow-input-description { grid-column: 1 / -1; }
  .workflow-output-definition .workflow-input-delete { grid-column: 4; grid-row: 1; }
  .workflow-metadata-editor { grid-template-columns: minmax(0, 1fr); }
}
@container (max-width: 420px) {
  .workflow-output-definition { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) 28px; }
  .workflow-output-definition > label:first-child { grid-column: 1 / 3; }
  .workflow-output-definition .workflow-input-delete { grid-column: 3; }
}
</style>
