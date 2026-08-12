<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { X } from 'lucide-vue-next'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)

watch(() => props.open, async (open) => {
  if (!open) return
  await nextTick()
  panel.value?.focus()
})

const shortcuts = [
  ['↑ / ↓ / Home / End', '浏览设备列表'],
  ['Enter / Space', '从选中设备打开模拟会话'],
  ['ContextMenu / Shift+F10', '打开当前区域上下文菜单'],
  ['Ctrl+F', '搜索当前聚焦的终端或命令记录'],
  ['Ctrl++ / Ctrl+-', '放大或缩小终端字体'],
  ['Ctrl+Shift+R', '重新连接当前终端'],
  ['Esc', '关闭搜索或上下文浮层']
]
</script>

<template>
  <div v-if="open" class="help-backdrop" @click.self="emit('close')">
    <section
      ref="panel"
      class="help-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="desktop-help-title"
      tabindex="-1"
      @keydown.esc.prevent="emit('close')"
    >
      <header>
        <div>
          <p>DEVICE TUI</p>
          <h2 id="desktop-help-title">操作帮助</h2>
        </div>
        <button type="button" title="关闭帮助" @click="emit('close')"><X :size="17" /></button>
      </header>
      <div class="help-content">
        <p class="intro">设备操作、终端会话和命令工作区均支持鼠标与键盘操作。</p>
        <dl>
          <template v-for="([keys, action]) in shortcuts" :key="keys">
            <dt>{{ keys }}</dt>
            <dd>{{ action }}</dd>
          </template>
        </dl>
        <div class="help-note">
          <strong>安全边界</strong>
          <span>设备密码和后端访问令牌由 Python Backend / Electron Main 保管，不会进入 Vue 页面。</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.help-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1190;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(2, 6, 23, 0.48);
}
.help-panel {
  width: min(560px, calc(100vw - 40px));
  max-height: calc(100vh - 40px);
  color: var(--text);
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: 0 18px 56px rgba(0, 0, 0, 0.34);
  overflow: hidden;
}
.help-panel > header { min-height: 66px; padding: 13px 15px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--line); }
.help-panel header p { margin: 0 0 3px; color: var(--soft); font-size: 10px; font-weight: 750; letter-spacing: 0.12em; }
.help-panel h2 { margin: 0; font-size: 17px; }
.help-panel header button { width: 30px; height: 30px; display: grid; place-items: center; color: var(--muted); border: 1px solid var(--line); border-radius: 7px; background: var(--surface-raised); cursor: pointer; }
.help-panel header button:hover { color: var(--text); border-color: var(--line-strong); }
.help-content { padding: 16px; overflow: auto; }
.intro { margin: 0 0 14px; color: var(--muted); }
dl { margin: 0; display: grid; grid-template-columns: minmax(165px, 0.9fr) minmax(0, 1.1fr); border: 1px solid var(--line); border-radius: 9px; overflow: hidden; }
dt, dd { margin: 0; padding: 9px 11px; border-bottom: 1px solid var(--line); }
dt { color: var(--text); background: var(--surface-raised); font-family: "Cascadia Mono", Consolas, monospace; font-size: 11px; }
dd { color: var(--muted); }
dt:nth-last-of-type(1), dd:nth-last-of-type(1) { border-bottom: 0; }
.help-note { margin-top: 14px; padding: 11px; display: grid; gap: 5px; color: var(--muted); border: 1px solid rgba(34, 197, 94, 0.32); border-radius: 9px; background: rgba(34, 197, 94, 0.08); line-height: 1.5; }
.help-note strong { color: var(--accent); }
</style>
