<script setup lang="ts">
import { ref } from 'vue'
import { CircleAlert, FileSpreadsheet, ShieldCheck, X } from 'lucide-vue-next'
import { useDialogFocus } from '../composables/useDialogFocus'
import type { DeviceImportPreview } from '../types'

const props = defineProps<{
  preview: DeviceImportPreview
  busy?: boolean
  returnFocus?: HTMLElement | null
}>()
const emit = defineEmits<{ close: []; commit: [] }>()
const confirmed = ref(false)
const dialog = ref<HTMLElement | null>(null)
const { handleDialogKeydown } = useDialogFocus(dialog, {
  initialFocus: '[data-dialog-initial-focus]',
  restoreFocus: () => props.returnFocus || null
})
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="emit('close')">
    <section
      ref="dialog"
      class="profile-dialog device-import-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="device-import-title"
      tabindex="-1"
      @keydown="handleDialogKeydown"
      @keydown.esc.prevent="emit('close')"
    >
      <header>
        <div class="dialog-heading">
          <span class="dialog-icon"><FileSpreadsheet :size="18" /></span>
          <div>
            <p class="eyebrow">DEVICE INVENTORY IMPORT</p>
            <h2 id="device-import-title">确认覆盖导入设备</h2>
          </div>
        </div>
        <button class="icon-button" type="button" title="关闭" @click="emit('close')"><X :size="16" /></button>
      </header>

      <div class="device-import-body">
        <div class="device-import-file">
          <span><strong>{{ preview.file_name }}</strong><small>{{ preview.sheet_name || '默认工作表' }}</small></span>
          <span><b>{{ preview.valid_rows }}</b> 有效</span>
          <span :data-warning="preview.skipped_rows > 0"><b>{{ preview.skipped_rows }}</b> 跳过</span>
          <span><b>{{ preview.total_rows }}</b> 总行数</span>
        </div>

        <p class="device-import-security"><ShieldCheck :size="15" />密码列会被忽略；确认前不会修改当前设备数据。</p>
        <p v-for="warning in preview.warnings" :key="warning" class="device-import-warning"><CircleAlert :size="14" />{{ warning }}</p>

        <div class="device-import-table-wrap">
          <table class="device-import-table">
            <thead><tr><th>ID</th><th>名称</th><th>领域</th><th>类型</th><th>连接地址</th><th>状态</th></tr></thead>
            <tbody>
              <tr v-for="(row, index) in preview.preview_rows" :key="`${row.id}-${index}`">
                <td>{{ row.id || '-' }}</td><td>{{ row.name || '-' }}</td><td>{{ row.domain || '-' }}</td>
                <td>{{ row.device_type || '-' }}</td><td>{{ row.host || '-' }}</td><td>{{ row.status || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <details v-if="preview.errors.length" class="device-import-errors">
          <summary>{{ preview.skipped_rows }} 行未导入（显示前 {{ preview.errors.length }} 条）</summary>
          <ul><li v-for="issue in preview.errors" :key="`${issue.row}-${issue.message}`">第 {{ issue.row }} 行：{{ issue.message }}</li></ul>
        </details>

        <label class="device-import-confirm">
          <input v-model="confirmed" data-dialog-initial-focus type="checkbox" />
          <span><strong>我确认覆盖当前导入数据</strong><small>示例数据和内部网站数据不会被删除，但当前活动源会切换为本次导入。</small></span>
        </label>
      </div>

      <footer>
        <button class="secondary-button" type="button" :disabled="busy" @click="emit('close')">取消</button>
        <button class="primary-button" type="button" :disabled="busy || !confirmed" @click="emit('commit')">
          {{ busy ? '导入中…' : `覆盖并导入 ${preview.valid_rows} 台` }}
        </button>
      </footer>
    </section>
  </div>
</template>
