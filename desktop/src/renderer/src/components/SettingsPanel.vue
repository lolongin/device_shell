<script setup lang="ts">
import { computed, ref, toRef, watch } from 'vue'
import { FolderOpen, LoaderCircle, Moon, Save, Sun, X } from 'lucide-vue-next'
import { useDialogFocus } from '../composables/useDialogFocus'
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
  returnFocus?: HTMLElement | null
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
const savedDirectory = ref('')
const savedRotateSizeMb = ref(24)
const terminalFontSize = ref(readTerminalFontSize())
const panel = ref<HTMLElement | null>(null)
const { handleDialogKeydown } = useDialogFocus(panel, {
  open: toRef(props, 'open'),
  initialFocus: '[data-dialog-initial-focus]',
  restoreFocus: () => props.returnFocus || null
})

const logSettingsDirty = computed(() =>
  directory.value.trim() !== savedDirectory.value ||
  Math.round(rotateSizeMb.value) !== savedRotateSizeMb.value
)
const canSaveLogs = computed(() =>
  Boolean(
    logSettings.value?.configurable && directory.value.trim() && rotateSizeMb.value >= 1 &&
    rotateSizeMb.value <= 1024 && logSettingsDirty.value
  )
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
    savedDirectory.value = settings.directory
    savedRotateSizeMb.value = settings.rotate_size_mb
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
    savedDirectory.value = settings.directory
    savedRotateSizeMb.value = settings.rotate_size_mb
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
      @keydown="handleDialogKeydown"
      @keydown.esc.prevent="emit('close')"
    >
      <header>
        <div>
          <p>WORKSPACE SETTINGS</p>
          <h2 id="desktop-settings-title">工作台设置</h2>
        </div>
        <button class="settings-icon-button" type="button" title="关闭设置" data-dialog-initial-focus @click="emit('close')">
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

        <fieldset :aria-busy="loading">
          <legend>会话日志</legend>
          <div v-if="loading && !logSettings" class="settings-log-skeleton" role="status" aria-label="正在读取日志设置">
            <span></span><span></span><span></span><span></span>
            <small><LoaderCircle class="spinning-icon" :size="12" />正在读取日志设置…</small>
          </div>
          <template v-else>
            <p class="settings-hint">目录切换会迁移当前活动会话日志；密码和终端密钥仍会在 Python 端脱敏。</p>
            <label class="settings-field">
              <span>保存目录</span>
              <div class="directory-control">
                <input v-model="directory" type="text" readonly aria-label="日志保存目录" />
                <button type="button" :disabled="loading" @click="chooseDirectory">选择</button>
                <button type="button" title="打开当前日志目录" :disabled="loading || !directory" @click="openDirectory">
                  <FolderOpen :size="15" />
                </button>
              </div>
            </label>
            <label class="settings-field compact">
              <span>单个日志分卷大小（MB）</span>
              <input v-model.number="rotateSizeMb" type="number" min="1" max="1024" step="1" :disabled="loading" />
            </label>
            <p v-if="logSettings" class="settings-hint">保留 {{ logSettings.backup_count }} 个自动分卷</p>
          </template>
        </fieldset>

        <div class="settings-behavior-note">
          <strong>生效方式</strong>
          <span>主题、窗口和终端字体即时生效；日志目录与分卷大小需点击“保存日志设置”。</span>
        </div>
      </div>
      <footer class="settings-action-bar">
        <p
          class="settings-dirty-state"
          :data-dirty="logSettingsDirty"
          :data-state="error ? 'error' : loading ? 'loading' : saving ? 'saving' : notice ? 'success' : logSettingsDirty ? 'dirty' : 'saved'"
          :role="error ? 'alert' : 'status'"
        >
          <LoaderCircle v-if="loading || saving" class="spinning-icon" :size="13" aria-hidden="true" />
          <i v-else aria-hidden="true"></i>
          <span>
            <strong>{{ error ? '日志设置操作失败' : loading ? '正在读取日志设置' : saving ? '正在保存日志设置' : notice || (logSettingsDirty ? '日志设置有未保存修改' : '日志设置已保存') }}</strong>
            <small>{{ error || (logSettingsDirty ? '保存后目录和分卷大小才会生效' : '外观、窗口和终端字体即时生效') }}</small>
          </span>
        </p>
        <button
          class="settings-save"
          type="button"
          :disabled="!canSaveLogs || saving || loading"
          @click="saveLogSettings"
        ><LoaderCircle v-if="saving" class="spinning-icon" :size="15" /><Save v-else :size="15" />{{ saving ? '正在保存…' : '保存日志设置' }}</button>
      </footer>
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
  overflow: hidden;
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
.settings-scroll { min-height: 0; padding: 14px; flex: 1 1 auto; display: grid; align-content: start; overflow: auto; overscroll-behavior: contain; }
fieldset { margin: 0 0 14px; padding: 13px; border: 1px solid var(--line); border-radius: 10px; background: color-mix(in srgb, var(--surface-raised) 55%, transparent); box-shadow: var(--shadow-card); }
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
.settings-log-skeleton {
  min-height: 156px;
  padding: 8px 0 2px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 76px;
  align-content: start;
  gap: 10px 8px;
}
.settings-log-skeleton > span {
  height: 31px;
  border-radius: 7px;
  background: linear-gradient(90deg, var(--surface-hover), var(--line-strong), var(--surface-hover));
  background-size: 200% 100%;
  animation: settings-loading-shimmer 1.2s ease-in-out infinite;
}
.settings-log-skeleton > span:nth-child(1), .settings-log-skeleton > span:nth-child(4) { grid-column: 1 / -1; }
.settings-log-skeleton > small { grid-column: 1 / -1; display: flex; align-items: center; justify-content: center; gap: 5px; color: var(--soft); }
@keyframes settings-loading-shimmer { to { background-position: -200% 0; } }
.settings-dirty-state {
  min-width: 0; margin: 0; display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 10px;
}
.settings-dirty-state > i { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: var(--accent); }
.settings-dirty-state > svg { flex: 0 0 auto; color: var(--blue); }
.settings-dirty-state > span { min-width: 0; display: grid; gap: 1px; }
.settings-dirty-state strong, .settings-dirty-state small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.settings-dirty-state strong { color: var(--text); font-size: 10.5px; }
.settings-dirty-state small { color: var(--soft); font-size: 9px; font-weight: 400; }
.settings-dirty-state[data-dirty="true"] { color: var(--warning); }
.settings-dirty-state[data-dirty="true"] > i { background: var(--warning); }
.settings-dirty-state[data-state="error"] > i { background: var(--danger); }
.settings-dirty-state[data-state="error"] strong { color: var(--danger); }
.settings-dirty-state[data-state="success"] strong { color: var(--accent); }
.settings-action-bar {
  min-height: 64px;
  padding: 9px 14px;
  flex: 0 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  border-top: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface) 94%, var(--surface-raised));
  box-shadow: 0 -10px 24px rgba(0, 0, 0, 0.08);
}
.settings-save { min-width: 142px; color: #fff; border-color: #31d16c; background: #15803d; font-weight: 650; }
.settings-save:hover:not(:disabled) { background: var(--accent-hover); }
button:disabled { opacity: 0.45; cursor: default; }
.settings-status { margin: 8px 2px 0; color: var(--muted); }
.settings-status.success { color: var(--accent); }
.settings-status.error { color: var(--danger); }
.settings-behavior-note {
  margin-top: 2px;
  padding: 10px 11px;
  display: grid;
  gap: 3px;
  color: var(--muted);
  border: 1px solid rgba(96, 165, 250, 0.24);
  border-radius: 9px;
  background: rgba(96, 165, 250, 0.06);
  font-size: 10.5px;
  line-height: 1.5;
}
.settings-behavior-note strong { color: var(--blue); font-size: 11px; }
@media (prefers-reduced-motion: no-preference) {
  .settings-panel { animation: settings-enter 160ms ease-out; }
  @keyframes settings-enter { from { opacity: 0; transform: translateX(12px); } }
}
@media (max-width: 420px) {
  .settings-backdrop { padding: 6px; }
  .settings-panel { width: calc(100vw - 12px); }
  .settings-action-bar { grid-template-columns: 1fr; gap: 7px; }
  .settings-save { width: 100%; }
}
</style>
