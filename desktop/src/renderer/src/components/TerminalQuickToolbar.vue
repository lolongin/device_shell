<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { ChevronDown, ChevronUp, KeyRound, Pencil, Plus, Send, Trash2, X } from 'lucide-vue-next'
import { useDialogFocus } from '../composables/useDialogFocus'
import { useWorkspaceStore } from '../stores/workspace'
import type { QuickSendButtonPayload, QuickSendButtonRecord } from '../types'

const workspace = useWorkspaceStore()
const COLLAPSED_KEY = 'device-tui.desktop-v2.quick-toolbar-collapsed'
const collapsed = ref(localStorage.getItem(COLLAPSED_KEY) === '1')
const editing = ref<QuickSendButtonRecord | null>(null)
const dialogOpen = ref(false)
const dialog = ref<HTMLElement | null>(null)
const dialogReturnFocus = ref<HTMLElement | null>(null)
const responseInput = ref<HTMLTextAreaElement | null>(null)
const replacingSecret = ref(false)
const draft = ref<QuickSendButtonPayload>(emptyDraft())
const localError = ref('')
const { handleDialogKeydown } = useDialogFocus(dialog, {
  open: dialogOpen,
  initialFocus: '[data-dialog-initial-focus]',
  restoreFocus: () => dialogReturnFocus.value
})

const protectedResponse = computed(
  () => Boolean(editing.value?.sensitive && draft.value.response_text === '••••••' && !replacingSecret.value)
)

function emptyDraft(): QuickSendButtonPayload {
  return { name: '', response_text: '', append_enter: false, sensitive: false }
}

function setCollapsed(value: boolean): void {
  collapsed.value = value
  localStorage.setItem(COLLAPSED_KEY, value ? '1' : '0')
}

function beginCreate(event: Event): void {
  dialogReturnFocus.value = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  editing.value = null
  draft.value = emptyDraft()
  replacingSecret.value = false
  localError.value = ''
  dialogOpen.value = true
}

function beginEdit(button: QuickSendButtonRecord, event: Event): void {
  dialogReturnFocus.value = event.currentTarget instanceof HTMLElement ? event.currentTarget : null
  editing.value = button
  draft.value = {
    name: button.name,
    response_text: button.response_text,
    append_enter: button.append_enter,
    sensitive: button.sensitive
  }
  replacingSecret.value = false
  localError.value = ''
  dialogOpen.value = true
}

function replaceProtectedResponse(): void {
  draft.value.response_text = ''
  replacingSecret.value = true
  void nextTick(() => responseInput.value?.focus())
}

async function save(): Promise<void> {
  localError.value = ''
  const payload = {
    ...draft.value,
    name: draft.value.name.trim()
  }
  if (!payload.name || !payload.response_text) {
    localError.value = '请输入按钮名称和发送内容。'
    return
  }
  if (await workspace.saveQuickSendButton(payload, editing.value?.id || '')) closeDialog()
}

async function remove(): Promise<void> {
  const button = editing.value
  if (!button || !window.confirm(`确定删除快捷发送“${button.name}”吗？`)) return
  if (await workspace.deleteQuickSendButton(button.id)) closeDialog()
}

function closeDialog(): void {
  dialogOpen.value = false
  editing.value = null
  replacingSecret.value = false
  localError.value = ''
}
</script>

<template>
  <button
    v-if="collapsed"
    class="quick-toolbar-restore"
    type="button"
    title="展开快捷发送"
    @click="setCollapsed(false)"
  >
    <Send :size="13" />快捷发送 {{ workspace.quickSendButtons.length }}<ChevronDown :size="13" />
  </button>
  <section v-else class="terminal-quick-toolbar" aria-label="快捷发送" data-testid="terminal-quick-toolbar">
    <span class="quick-toolbar-label">QUICK SEND</span>
    <div class="quick-send-buttons">
      <span v-for="button in workspace.quickSendButtons" :key="button.id" class="quick-send-group">
        <button
          class="quick-send-button"
          type="button"
          :data-quick-send-id="button.id"
          :title="button.sensitive ? `${button.name}（敏感内容由系统凭据库发送）` : `${button.name}: ${button.response_text}`"
          :disabled="!workspace.activeSession || workspace.automationBusy"
          @click="workspace.sendQuickSendButton(button.id)"
        >
          <KeyRound v-if="button.sensitive" :size="12" />{{ button.name }}
        </button>
        <button class="quick-send-edit" type="button" :aria-label="`编辑 ${button.name}`" @click="beginEdit(button, $event)">
          <Pencil :size="11" />
        </button>
      </span>
      <button class="quick-send-add" data-testid="quick-send-add" type="button" title="新增快捷发送" @click="beginCreate($event)">
        <Plus :size="13" />新增
      </button>
    </div>
    <button class="quick-toolbar-collapse" type="button" title="收起快捷发送" @click="setCollapsed(true)">
      <ChevronUp :size="14" />
    </button>
  </section>

  <Teleport to="body">
  <div v-if="dialogOpen" class="dialog-backdrop quick-send-dialog-backdrop" @mousedown.self="closeDialog">
    <form ref="dialog" class="profile-dialog quick-send-dialog" role="dialog" aria-modal="true" aria-labelledby="quick-send-title" tabindex="-1" @submit.prevent="save" @keydown="handleDialogKeydown" @keydown.esc.prevent="closeDialog">
      <header>
        <div><p class="eyebrow">TERMINAL ACTION</p><h2 id="quick-send-title">{{ editing ? '编辑' : '新增' }}快捷发送</h2></div>
        <button class="icon-button" type="button" title="关闭" @click="closeDialog"><X :size="16" /></button>
      </header>
      <div class="profile-form-body single-column">
        <label class="form-field"><span>按钮名称</span><input v-model="draft.name" data-testid="quick-send-name" maxlength="160" data-dialog-initial-focus /></label>
        <label class="form-field form-field-wide">
          <span>发送内容</span>
          <textarea
            ref="responseInput"
            v-model="draft.response_text"
            data-testid="quick-send-response"
            rows="5"
            maxlength="100000"
            spellcheck="false"
            :readonly="protectedResponse"
            placeholder="例如 Ctrl+B、display version、\x1b"
          ></textarea>
        </label>
        <button v-if="protectedResponse" class="secondary-button" type="button" @click="replaceProtectedResponse">替换敏感内容</button>
        <label class="quick-send-option"><input v-model="draft.append_enter" type="checkbox" />发送后追加 Enter</label>
        <label class="quick-send-option"><input v-model="draft.sensitive" type="checkbox" />敏感内容（仅保存到系统凭据库）</label>
        <p class="secret-hint">支持 Ctrl+A–Z、Enter、Esc、Tab、\r、\n、\xNN。敏感内容返回 Vue 时始终显示为掩码。</p>
        <p v-if="localError || workspace.error" class="automation-error" role="alert">{{ localError || workspace.error }}</p>
      </div>
      <footer>
        <button v-if="editing" class="secondary-button danger-button" type="button" @click="remove"><Trash2 :size="13" />删除</button>
        <span class="dialog-footer-spacer"></span>
        <button class="secondary-button" type="button" @click="closeDialog">取消</button>
        <button class="primary-button" data-testid="quick-send-save" type="submit" :disabled="workspace.automationBusy"><Send :size="13" />保存</button>
      </footer>
    </form>
  </div>
  </Teleport>
</template>
