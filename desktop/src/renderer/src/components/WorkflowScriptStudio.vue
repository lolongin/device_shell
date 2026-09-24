<script setup lang="ts">
import type { DeviceSummary } from '../types'
import WorkflowScriptEditor from './WorkflowScriptEditor.vue'
import { useWorkflowScripts, workflowScriptSnapshot, workflowScriptInputTypes, workflowScriptTemplates } from '../composables/useWorkflowScripts'
import { AlertTriangle, Braces, Code2, Copy, Play, Plus, Save, Trash2, X } from 'lucide-vue-next'

const props = defineProps<{
  selectedDeviceId: string
  availableDevices: DeviceSummary[]
  deviceLabel: (device: DeviceSummary) => string
  controller: ReturnType<typeof useWorkflowScripts>
}>()
const emit = defineEmits<{ 'update:selectedDeviceId': [value: string] }>()
const { selectedDeviceId, controller, availableDevices, deviceLabel } = props
</script>

<template>
<div class="workflow-script-studio">
      <aside class="workflow-script-list">
        <div class="workflow-list-title"><span>脚本资源</span><small>{{ controller.scripts.value.length }} 个</small></div>
        <div class="workflow-script-list-actions"><button type="button" class="primary-action" @click="controller.createWorkflowScript"><Plus :size="13" />新建脚本</button><button type="button" class="icon-toolbar-button" :disabled="!controller.selectedScript.value" title="复制脚本" aria-label="复制脚本" @click="controller.duplicateWorkflowScript"><Copy :size="13" /></button></div>
        <button v-for="script in controller.scripts.value" :key="script.id" type="button" class="workflow-script-list-item" :class="{ active: script.id === controller.selectedScriptId.value }" @click="controller.selectedScriptId.value = script.id">
          <span class="workflow-script-list-dot" :data-language="script.language"></span><span><strong>{{ script.name }}</strong><small>{{ script.language }} · {{ workflowScriptSnapshot(script) !== controller.savedScriptSnapshots.value[script.id] ? '未保存' : (script.updated_at ? new Date(script.updated_at).toLocaleDateString() : '未保存') }}</small></span>
        </button>
        <p v-if="!controller.scripts.value.length" class="workflow-empty-list">还没有脚本<br /><span>新建后可单独编辑和测试</span></p>
      </aside>
      <main v-if="controller.selectedScript.value" class="workflow-script-workspace">
        <section class="workflow-script-editor-panel">
          <header class="workflow-script-resource-header"><div><span class="workflow-section-kicker">脚本资源</span><input v-model="controller.selectedScript.value.name" aria-label="脚本名称" maxlength="120" placeholder="输入脚本名称" /><small>{{ controller.selectedScript.value.id }}<template v-if="controller.hasUnsavedScriptChanges.value"> · 未保存</template></small><span v-if="controller.scriptValidationMessage.value" class="workflow-script-validation">{{ controller.scriptValidationMessage.value }}</span></div><div class="workflow-script-resource-actions"><button type="button" :disabled="controller.scriptSaving.value || !controller.hasUnsavedScriptChanges.value || Boolean(controller.scriptValidationMessage.value)" @click="controller.saveWorkflowScript"><Save :size="14" />{{ controller.scriptSaving.value ? '保存中…' : '保存' }}</button><button type="button" class="icon-toolbar-button" title="删除脚本" aria-label="删除脚本" @click="controller.deleteWorkflowScript"><Trash2 :size="14" /></button></div></header>
          <WorkflowScriptEditor v-model="controller.selectedScript.value.script" :language="controller.selectedScript.value.language" placeholder="输入脚本内容…" aria-label="独立脚本编辑器" />
          <section v-if="controller.scriptTestResult.value" class="workflow-script-run-log" aria-label="脚本运行日志">
            <header><div><strong>运行日志</strong><small>{{ controller.scriptTestResult.value.message || (controller.scriptTesting.value ? '正在执行脚本…' : '测试完成') }}</small></div><code v-if="controller.scriptTestResult.value.task?.id" :title="controller.scriptTestResult.value.task.id">{{ controller.scriptTestResult.value.task.id }}</code></header>
            <div v-if="controller.scriptTestDetails.value" class="workflow-script-test-summary"><span>状态</span><b>{{ controller.scriptTestDetails.value.status }}</b><span>退出码</span><b>{{ controller.scriptTestDetails.value.exitCode !== '' ? controller.scriptTestDetails.value.exitCode : '—' }}</b></div>
            <section v-if="controller.scriptTestDetails.value?.stdout"><span>stdout</span><pre>{{ controller.scriptTestDetails.value.stdout }}</pre></section>
            <section v-if="controller.scriptTestDetails.value?.stderr"><span>stderr</span><pre>{{ controller.scriptTestDetails.value.stderr }}</pre></section>
          </section>
        </section>
        <aside class="workflow-script-test-panel">
          <section class="workflow-script-config-section" aria-label="脚本配置">
            <div class="workflow-script-side-heading"><div><strong>配置</strong><small>脚本语言、说明和输入参数</small></div></div>
            <div class="workflow-script-resource-meta"><label>语言<select v-model="controller.selectedScript.value.language"><option value="python">Python</option><option value="powershell">PowerShell</option><option value="bash">Bash</option></select></label><label>说明<input v-model="controller.selectedScript.value.description" placeholder="脚本用途说明" /></label></div>
            <section class="workflow-script-parameters" aria-label="脚本输入参数">
              <header><div><strong>输入参数</strong><small v-if="controller.selectedScript.value.entrypoint">由 {{ controller.selectedScript.value.entrypoint }} 函数签名自动识别；保存脚本后会刷新</small><small v-else>脚本通过 DEVICE_TUI_INPUT_JSON 读取，测试时可直接填入参数</small></div><button v-if="!controller.selectedScript.value.entrypoint" type="button" class="icon-toolbar-button" title="新增输入参数" aria-label="新增输入参数" @click="controller.addScriptInput"><Plus :size="13" /></button></header>
              <p v-if="controller.selectedScript.value.input_schema_error" class="workflow-script-validation">{{ controller.selectedScript.value.input_schema_error }}；当前保留已有参数定义</p>
              <div v-if="controller.selectedScript.value.input_schema.length" class="workflow-script-parameter-list">
                <article v-for="(parameter, index) in controller.selectedScript.value.input_schema" :key="`${controller.selectedScript.value.id}-${index}`" class="workflow-script-parameter-row">
                  <div class="workflow-script-parameter-main"><input :value="parameter.name" :disabled="Boolean(controller.selectedScript.value.entrypoint)" aria-label="参数名" placeholder="参数名" @input="controller.updateScriptInputField(index, 'name', controller.eventValue($event))" /><select :value="parameter.type" :disabled="Boolean(controller.selectedScript.value.entrypoint)" aria-label="参数类型" @change="controller.updateScriptInputField(index, 'type', controller.eventValue($event))"><option v-for="type in workflowScriptInputTypes" :key="type" :value="type">{{ type }}</option></select><label class="workflow-script-required"><input :checked="Boolean(parameter.required)" :disabled="Boolean(controller.selectedScript.value.entrypoint)" type="checkbox" @change="controller.updateScriptInputField(index, 'required', controller.eventChecked($event))" />必填</label><button v-if="!controller.selectedScript.value.entrypoint" type="button" class="icon-toolbar-button" title="删除参数" :aria-label="`删除参数 ${parameter.name}`" @click="controller.removeScriptInput(index)"><Trash2 :size="13" /></button></div>
                  <div class="workflow-script-parameter-details"><input :value="parameter.description || ''" :disabled="Boolean(controller.selectedScript.value.entrypoint)" aria-label="参数说明" placeholder="参数说明（可选）" @input="controller.updateScriptInputField(index, 'description', controller.eventValue($event))" /><input v-if="parameter.type === 'string'" :value="controller.scriptDefaultText(parameter)" :disabled="Boolean(controller.selectedScript.value.entrypoint)" aria-label="默认值" placeholder="默认值（可选）" @input="controller.updateScriptDefault(index, $event)" /><input v-else-if="parameter.type === 'number'" :value="controller.scriptDefaultText(parameter)" :disabled="Boolean(controller.selectedScript.value.entrypoint)" type="number" aria-label="默认值" placeholder="默认值" @input="controller.updateScriptDefault(index, $event)" /><input v-else-if="parameter.type === 'boolean'" :checked="parameter.default === true" :disabled="Boolean(controller.selectedScript.value.entrypoint)" type="checkbox" aria-label="默认值" @change="controller.updateScriptDefault(index, $event)" /><input v-else :value="controller.scriptDefaultText(parameter)" :disabled="Boolean(controller.selectedScript.value.entrypoint)" aria-label="默认 JSON 值" placeholder="默认 JSON 值，例如 {} 或 []" @input="controller.updateScriptDefault(index, $event)" /></div>
                </article>
              </div>
              <p v-else class="workflow-script-parameters-empty">暂无参数。新增参数后，独立测试会自动生成对应输入控件。</p>
            </section>
          </section>
          <section class="workflow-script-test-section" aria-label="脚本测试">
            <div class="workflow-script-side-heading"><div><strong>测试</strong><small>有修改时会先自动保存，再通过后端任务执行</small></div><span class="workflow-risk-chip"><AlertTriangle :size="12" />高风险</span></div>
            <label>目标设备<select :value="selectedDeviceId" @change="emit('update:selectedDeviceId', ($event.target as HTMLSelectElement).value)"><option value="">选择设备</option><option v-for="device in availableDevices" :key="device.row_id || device.id" :value="device.id">{{ deviceLabel(device) }}</option></select></label>
            <div class="workflow-script-test-mode" role="tablist" aria-label="测试输入模式"><button type="button" :class="{ active: controller.scriptTestMode.value === 'form' }" @click="controller.scriptTestMode.value = 'form'">参数表单</button><button type="button" :class="{ active: controller.scriptTestMode.value === 'json' }" @click="controller.scriptTestMode.value = 'json'">JSON</button></div>
            <div v-if="controller.scriptTestMode.value === 'form'" class="workflow-script-test-form">
              <div v-if="controller.selectedScript.value.input_schema.length" v-for="parameter in controller.selectedScript.value.input_schema" :key="`test-${parameter.name}`" class="workflow-script-test-field"><label :for="`script-test-${parameter.name}`">{{ parameter.name }}<span v-if="parameter.required">必填</span></label><small v-if="parameter.description">{{ parameter.description }}</small><input v-if="parameter.type === 'string'" :id="`script-test-${parameter.name}`" :value="controller.scriptTestValueText(parameter)" :placeholder="parameter.required ? '请输入' : '留空表示不传入'" @input="controller.updateScriptTestValue(parameter.name, controller.eventValue($event))" /><input v-else-if="parameter.type === 'number'" :id="`script-test-${parameter.name}`" type="number" :value="controller.scriptTestValueText(parameter)" placeholder="数字" @input="controller.updateScriptTestValue(parameter.name, controller.eventValue($event))" /><label v-else-if="parameter.type === 'boolean'" class="workflow-inline-toggle"><input :id="`script-test-${parameter.name}`" type="checkbox" :checked="controller.scriptTestValues.value[parameter.name] === true" @change="controller.updateScriptTestValue(parameter.name, controller.eventChecked($event))" />启用</label><textarea v-else :id="`script-test-${parameter.name}`" rows="3" :value="controller.scriptTestValueText(parameter)" :placeholder="parameter.type === 'array' ? '例如：[1, 2]' : '例如：{}'" @input="controller.updateScriptTestValue(parameter.name, controller.eventValue($event))" /></div>
              <p v-else class="workflow-script-parameters-empty">此脚本没有定义输入参数。</p>
            </div>
            <label v-else>输入 JSON<textarea v-model="controller.scriptTestInputs.value" rows="8" placeholder='例如：{"mode":"check"}' /></label>
            <p v-if="controller.scriptTestInputError.value" class="workflow-error">{{ controller.scriptTestInputError.value }}</p>
            <label class="workflow-inline-toggle"><input v-model="controller.scriptTestConfirmed.value" type="checkbox" />我已确认脚本将在后端主机执行</label>
            <button type="button" class="primary-action workflow-script-test-button" :disabled="controller.scriptTesting.value || controller.scriptSaving.value || !selectedDeviceId || !controller.scriptTestConfirmed.value || Boolean(controller.scriptValidationMessage.value)" @click="controller.testWorkflowScript"><Play :size="14" />{{ controller.scriptTesting.value ? '测试运行中…' : (controller.hasUnsavedScriptChanges.value ? '保存并测试' : '测试脚本') }}</button>
            <p class="field-hint">测试会创建临时 Workflow 任务，不会修改当前 Flow。</p>
          </section>
        </aside>
      </main>
      <main v-else class="workflow-empty workflow-script-no-selection">选择或新建一个脚本</main>
    </div>
    <div v-if="controller.showScriptTemplateDialog.value" class="workflow-modal-backdrop" @click.self="controller.showScriptTemplateDialog.value = false">
      <form class="workflow-import-dialog workflow-create-dialog workflow-script-template-dialog" role="dialog" aria-modal="true" aria-label="新建脚本" @submit.prevent="controller.confirmCreateWorkflowScript">
        <header><strong>新建脚本</strong><button type="button" title="关闭" @click="controller.showScriptTemplateDialog.value = false"><X :size="16" /></button></header>
        <label>脚本名称<input v-model="controller.scriptCreateName.value" autofocus maxlength="120" placeholder="例如：检查设备状态" /></label>
        <label>脚本说明<textarea v-model="controller.scriptCreateDescription.value" rows="2" maxlength="400" placeholder="可选，说明脚本用途" /></label>
        <section class="workflow-script-template-grid" aria-label="脚本模板">
          <button v-for="template in workflowScriptTemplates" :key="template.id" type="button" class="workflow-script-template-card" :class="{ active: controller.selectedScriptTemplateId.value === template.id }" @click="controller.selectedScriptTemplateId.value = template.id">
            <span class="workflow-script-template-icon"><Code2 :size="15" /></span>
            <span><strong>{{ template.name }}</strong><small>{{ template.description }}</small><em>{{ template.language }}</em></span>
          </button>
        </section>
        <div class="workflow-script-template-preview"><span>预置内容</span><code>{{ controller.selectedScriptTemplate.value.script ? `${controller.selectedScriptTemplate.value.script.split('\n').slice(0, 3).join('\n')}${controller.selectedScriptTemplate.value.script.split('\n').length > 3 ? '\n…' : ''}` : '空白脚本' }}</code></div>
        <footer><button type="button" @click="controller.showScriptTemplateDialog.value = false">取消</button><button type="submit" class="primary-action" :disabled="controller.scriptCreating.value || !controller.scriptCreateName.value.trim()">{{ controller.scriptCreating.value ? '创建中…' : '使用模板创建' }}</button></footer>
      </form>
    </div>
</template>

<style src="./WorkflowScriptStudio.css"></style>
