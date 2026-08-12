<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { FolderOpen, Moon, Save, Sun, X } from 'lucide-vue-next'
import { desktopApi } from '../transport/api'
import type { SessionLogSettings } from '../types'

type ThemeMode = 'dark' | 'light'
type SessionTabLayout = 'top' | 'side'

const props = defineProps<{
  open: boolean
  themeMode: ThemeMode
  alwaysOnTop: boolean
  sessionTabLayout: SessionTabLayout
  sessionTabRailCollapsed: boolean
}>()
const emit = defineEmits<{
  close: []
  setTheme: [mode: ThemeMode]
  setAlwaysOnTop: [enabled: boolean]
  setSessionTabLayout: [layout: SessionTabLayout]
  setSessionTabRailCollapsed: [collapsed: boolean]
}>()

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const logSettings = ref<SessionLogSettings | null>(null)
const directory = ref('')
const rotateSizeMb = ref(24)
const terminalFontSize = ref(readTerminalFontSize())
const panel = ref<HTMLElement | null>(null)

const canSaveLogs = computed(() =>
  Boolean(logSettings.value?.configurable && directory.value.trim() && rotateSizeMb.value >= 1)
)

function readTerminalFontSize(): number {
  const value = Number(localStorage.getItem('device-tui.desktop-v2.terminal-font-size') || 13)
  return Math.max(9, Math.min(28, Number.isFinite(value) ? value : 13))
}

async function loadSettings(): Promise<void> {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const settings = await desktopApi.sessionLogSettings()
    logSettings.value = settings
    directory.value = settings.directory
    rotateSizeMb.value = settings.rotate_size_mb
    terminalFontSize.value = readTerminalFontSize()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function chooseDirectory(): Promise<void> {
  error.value = ''
  const selected = await window.desktopApi.chooseSessionLogDirectory()
  if (selected) directory.value = selected
}

async function openDirectory(): Promise<void> {
  error.value = ''
  notice.value = ''
  try {
    await window.desktopApi.openSessionLogDirectory()
    notice.value = '已打开当前日志目录'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function saveLogSettings(): Promise<void> {
  if (!canSaveLogs.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const settings = await desktopApi.updateSessionLogSettings({
      directory: directory.value.trim(),
      rotate_size_mb: Math.max(1, Math.min(1024, Math.round(rotateSizeMb.value)))
    })
    logSettings.value = settings
    directory.value = settings.directory
    rotateSizeMb.value = settings.rotate_size_mb
    notice.value = settings.moved_active_logs
      ? `日志设置已保存，并迁移 ${settings.moved_active_logs} 个活动会话日志`
      : '日志设置已保存'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    saving.value = false
  }
}

function updateTerminalFontSize(value: number): void {
  terminalFontSize.value = Math.max(9, Math.min(28, Math.round(value)))
  localStorage.setItem(
    'device-tui.desktop-v2.terminal-font-size',
    String(terminalFontSize.value)
  )
  window.dispatchEvent(
    new CustomEvent('device-tui:terminal-font-size', { detail: terminalFontSize.value })
  )
}

watch(() => props.open, async (open) => {
  if (!open) return
  await nextTick()
  panel.value?.focus()
  await loadSettings()
})
</script>

<template>
  <div v-if="open" class="settings-backdrop" @click.self="emit('close')">
    <section
      ref="panel"
      class="settings-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="desktop-settings-title"
      tabindex="-1"
      @keydown.esc.prevent="emit('close')"
    >
      <header>
        <div>
          <p>WORKSPACE SETTINGS</p>
          <h2 id="desktop-settings-title">工作台设置</h2>
        </div>
        <button class="settings-icon-button" type="button" title="关闭设置" @click="emit('close')">
          <X :size="17" />
        </button>
      </header>

      <div class="settings-scroll">
        <fieldset>
          <legend>外观与窗口</legend>
          <div class="theme-options" role="group" aria-label="主题">
            <button
              type="button"
              :class="{ active: themeMode === 'dark' }"
              :aria-pressed="themeMode === 'dark'"
              @click="emit('setTheme', 'dark')"
            ><Moon :size="15" /> 深色</button>
            <button
              type="button"
              :class="{ active: themeMode === 'light' }"
              :aria-pressed="themeMode === 'light'"
              @click="emit('setTheme', 'light')"
            ><Sun :size="15" /> 浅色</button>
          </div>
          <label class="settings-check">
            <input
              type="checkbox"
              :checked="alwaysOnTop"
              @change="emit('setAlwaysOnTop', ($event.target as HTMLInputElement).checked)"
            />
            <span>窗口始终置顶</span>
          </label>
          <div class="settings-field">
            <span>会话页签布局</span>
            <div class="theme-options compact-options" role="group" aria-label="会话页签布局">
              <button
                type="button"
                :class="{ active: sessionTabLayout === 'top' }"
                :aria-pressed="sessionTabLayout === 'top'"
                @click="emit('setSessionTabLayout', 'top')"
              >顶部</button>
              <button
                type="button"
                :class="{ active: sessionTabLayout === 'side' }"
                :aria-pressed="sessionTabLayout === 'side'"
                @click="emit('setSessionTabLayout', 'side')"
              >右侧</button>
            </div>
          </div>
          <label class="settings-check session-collapse-setting">
            <input
              type="checkbox"
              :checked="sessionTabRailCollapsed"
              @change="emit('setSessionTabRailCollapsed', ($event.target as HTMLInputElement).checked)"
            />
            <span>右侧会话栏默认折叠</span>
          </label>
          <p class="settings-hint">右侧模式按设备组织会话，支持搜索、分组折叠和拖动调整管理器宽度。</p>
          <label class="settings-field">
            <span>终端字体大小 <b>{{ terminalFontSize }} px</b></span>
            <input
              :value="terminalFontSize"
              type="range"
              min="9"
              max="28"
              step="1"
              @input="updateTerminalFontSize(Number(($event.target as HTMLInputElement).value))"
            />
          </label>
        </fieldset>

        <fieldset>
          <legend>会话日志</legend>
          <p class="settings-hint">目录切换会迁移当前活动会话日志；密码和终端密钥仍会在 Python 端脱敏。</p>
          <label class="settings-field">
            <span>保存目录</span>
            <div class="directory-control">
              <input v-model="directory" type="text" readonly aria-label="日志保存目录" />
              <button type="button" :disabled="loading" @click="chooseDirectory">选择</button>
              <button type="button" title="打开当前日志目录" @click="openDirectory">
                <FolderOpen :size="15" />
              </button>
            </div>
          </label>
          <label class="settings-field compact">
            <span>单个日志分卷大小（MB）</span>
            <input v-model.number="rotateSizeMb" type="number" min="1" max="1024" step="1" />
          </label>
          <p v-if="logSettings" class="settings-hint">保留 {{ logSettings.backup_count }} 个自动分卷</p>
          <button
            class="settings-save"
            type="button"
            :disabled="!canSaveLogs || saving"
            @click="saveLogSettings"
          ><Save :size="15" />{{ saving ? '正在保存…' : '保存日志设置' }}</button>
        </fieldset>

        <p v-if="loading" class="settings-status">正在读取设置…</p>
        <p v-if="notice" class="settings-status success" role="status">{{ notice }}</p>
        <p v-if="error" class="settings-status error" role="alert">{{ error }}</p>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settings-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1200;
  display: flex;
  justify-content: flex-end;
  padding: 12px;
  background: rgba(2, 6, 23, 0.42);
}
.settings-panel {
  width: min(440px, calc(100vw - 24px));
  height: 100%;
  display: flex;
  flex-direction: column;
  color: var(--text);
  border: 1px solid var(--line-strong);
  border-radius: 12px;
  background: var(--surface);
  box-shadow: 0 18px 56px rgba(0, 0, 0, 0.34);
}
.settings-panel > header {
  min-height: 66px;
  padding: 13px 15px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--line);
}
.settings-panel header p { margin: 0 0 3px; color: var(--soft); font-size: 10px; font-weight: 750; letter-spacing: 0.12em; }
.settings-panel header h2 { margin: 0; font-size: 17px; }
.settings-icon-button, .directory-control button {
  min-width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-raised);
  cursor: pointer;
}
.settings-icon-button:hover, .directory-control button:hover:not(:disabled) { color: var(--text); border-color: var(--line-strong); }
.settings-scroll { min-height: 0; padding: 14px; overflow: auto; }
fieldset { margin: 0 0 14px; padding: 13px; border: 1px solid var(--line); border-radius: 10px; }
legend { padding: 0 6px; color: var(--text); font-weight: 700; }
.theme-options { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; margin-bottom: 12px; }
.theme-options button, .settings-save {
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-raised);
  cursor: pointer;
}
.theme-options button:hover, .theme-options button.active { color: var(--text); border-color: rgba(34, 197, 94, 0.55); }
.theme-options button.active { color: var(--accent); background: rgba(34, 197, 94, 0.1); }
.compact-options { margin: 0; }
.settings-check { margin-bottom: 13px; display: flex; align-items: center; gap: 9px; color: var(--muted); cursor: pointer; }
.session-collapse-setting { margin-top: 10px; }
.settings-field { display: grid; gap: 7px; margin-top: 11px; color: var(--muted); }
.settings-field > span { display: flex; justify-content: space-between; gap: 8px; }
.settings-field b { color: var(--text); font-family: Consolas, monospace; }
.settings-field input[type="range"] { width: 100%; accent-color: var(--accent); }
.settings-field input[type="text"], .settings-field input[type="number"] {
  min-width: 0;
  height: 32px;
  padding: 0 9px;
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--bg);
}
.settings-field.compact { grid-template-columns: minmax(0, 1fr) 92px; align-items: center; }
.directory-control { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 6px; }
.directory-control button { padding: 0 9px; }
.settings-hint { margin: 0 0 8px; color: var(--soft); font-size: 11px; line-height: 1.55; }
.settings-save { width: 100%; margin-top: 12px; color: #fff; border-color: #31d16c; background: #15803d; font-weight: 650; }
.settings-save:hover:not(:disabled) { background: var(--accent-hover); }
button:disabled { opacity: 0.45; cursor: default; }
.settings-status { margin: 8px 2px 0; color: var(--muted); }
.settings-status.success { color: var(--accent); }
.settings-status.error { color: var(--danger); }
@media (prefers-reduced-motion: no-preference) {
  .settings-panel { animation: settings-enter 160ms ease-out; }
  @keyframes settings-enter { from { opacity: 0; transform: translateX(12px); } }
}
</style>
