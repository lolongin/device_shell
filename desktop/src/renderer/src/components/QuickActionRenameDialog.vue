<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useDialogFocus } from '../composables/useDialogFocus'

const props = defineProps<{ name: string; returnFocus: HTMLElement | null }>()
const emit = defineEmits<{ close: []; save: [name: string] }>()
const name = ref(props.name)
const dialog = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const { handleDialogKeydown } = useDialogFocus(dialog, { restoreFocus: () => props.returnFocus })
onMounted(() => input.value?.select())
</script>

<template>
  <Teleport to="body">
    <div class="dialog-backdrop" @mousedown.self="emit('close')">
      <form ref="dialog" class="profile-dialog group-dialog" role="dialog" aria-modal="true"
        aria-labelledby="quick-rename-title" tabindex="-1"
        @submit.prevent="name.trim() && emit('save', name.trim())"
        @keydown="handleDialogKeydown" @keydown.esc.prevent.stop="emit('close')">
        <header><h2 id="quick-rename-title">重命名快捷项</h2></header>
        <div class="profile-form-body single-column">
          <label class="form-field"><span>快捷项名称</span>
            <input ref="input" v-model="name" required maxlength="80" aria-label="快捷项名称" data-dialog-initial-focus />
          </label>
        </div>
        <footer>
          <button type="button" class="secondary-button" @click="emit('close')">取消</button>
          <button type="submit" class="primary-button" :disabled="!name.trim()">保存名称</button>
        </footer>
      </form>
    </div>
  </Teleport>
</template>
