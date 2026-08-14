<script setup lang="ts">
import { ref } from 'vue'
import { FolderPlus, X } from 'lucide-vue-next'
import { useDialogFocus } from '../composables/useDialogFocus'

const props = defineProps<{ saving?: boolean; returnFocus?: HTMLElement | null }>()
const emit = defineEmits<{
  close: []
  save: [name: string]
}>()
const name = ref('')
const dialog = ref<HTMLElement | null>(null)
const { handleDialogKeydown } = useDialogFocus(dialog, {
  initialFocus: '[data-dialog-initial-focus]',
  restoreFocus: () => props.returnFocus || null
})

function submit(): void {
  const normalized = name.value.trim()
  if (normalized) emit('save', normalized)
}
</script>

<template>
  <div class="dialog-backdrop" role="presentation" @mousedown.self="emit('close')">
    <form
      class="profile-dialog group-dialog"
      ref="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="group-dialog-title"
      tabindex="-1"
      @submit.prevent="submit"
      @keydown="handleDialogKeydown"
      @keydown.esc.prevent="emit('close')"
    >
      <header>
        <div class="dialog-heading">
          <span class="dialog-icon"><FolderPlus :size="17" /></span>
          <div>
            <p class="eyebrow">SERVER ORGANIZATION</p>
            <h2 id="group-dialog-title">新建服务器分组</h2>
          </div>
        </div>
        <button class="icon-button" type="button" title="关闭" @click="emit('close')">
          <X :size="16" />
        </button>
      </header>

      <div class="profile-form-body single-column">
        <label class="form-field">
          <span>分组名称</span>
          <input v-model="name" required maxlength="160" data-dialog-initial-focus placeholder="例如：生产环境" />
        </label>
        <p class="secret-hint">空分组也会保留，稍后可在添加或编辑服务器时选择。</p>
      </div>

      <footer>
        <button class="secondary-button" type="button" @click="emit('close')">取消</button>
        <button class="primary-button" type="submit" :disabled="saving || !name.trim()">
          {{ saving ? '创建中…' : '创建分组' }}
        </button>
      </footer>
    </form>
  </div>
</template>
