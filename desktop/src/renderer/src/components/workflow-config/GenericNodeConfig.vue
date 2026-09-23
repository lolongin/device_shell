<script setup lang="ts">
import { Trash2 } from 'lucide-vue-next'
import type { NodeConfigProps, NodeConfigEmits } from './types'

const props = defineProps<NodeConfigProps>()
const emit = defineEmits<NodeConfigEmits>()

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
      <label>
        本机文件绝对路径
        <input
          :value="getConfigString('source')"
          placeholder="例如：D:/packages/image.cc"
          @input="updateConfigString('source', $event)"
        />
        <small class="field-hint">填写或选择本机文件绝对路径；执行时会自动暂存并上传。</small>
      </label>
      <label>
        设备目标路径（可选）
        <input
          :value="getConfigString('destination')"
          placeholder="留空自动使用 flash:/文件名"
          @input="updateConfigString('destination', $event)"
        />
        <small class="field-hint">留空时默认上传到设备 flash:/ 目录，也可手动指定完整路径。</small>
      </label>
      <label class="workflow-inline-toggle">
        <input
          type="checkbox"
          :checked="Boolean(node.config.overwrite)"
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

    <!-- 其他节点的占位说明 -->
    <template v-else>
      <p class="config-placeholder">
        此节点类型 ({{ node.action_id }}) 的配置界面正在开发中。
      </p>
    </template>

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

.config-actions {
  display: grid;
  gap: 8px;
  margin-top: 8px;
  padding-top: 12px;
  border-top: 1px solid var(--workflow-border);
}
</style>
