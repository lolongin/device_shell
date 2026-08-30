<script setup lang="ts">
import { computed, ref, toRef, watch } from 'vue'
import {
  CircleAlert,
  CircleCheck,
  Database,
  Eye,
  EyeOff,
  FileSpreadsheet,
  FolderOpen,
  Globe2,
  KeyRound,
  LoaderCircle,
  Moon,
  Plug,
  RefreshCw,
  Save,
  Sun,
  X
} from 'lucide-vue-next'
import { useDialogFocus } from '../composables/useDialogFocus'
import { desktopApi } from '../transport/api'
import type {
  DeviceSourcePlugin,
  DeviceSourcePluginListResponse,
  PluginConfigValue,
  SessionLogSettings
} from '../types'

type ThemeMode = 'dark' | 'light'
type SessionTabLayout = 'top' | 'side'

const props = defineProps<{
  open: boolean
  themeMode: ThemeMode
  alwaysOnTop: boolean
  sessionTabLayout: SessionTabLayout
  sessionTabRailCollapsed: boolean
  allowPluginManagement: boolean
  returnFocus?: HTMLElement | null
}>()
const emit = defineEmits<{
  close: []
  setTheme: [mode: ThemeMode]
  setAlwaysOnTop: [enabled: boolean]
  setSessionTabLayout: [layout: SessionTabLayout]
  setSessionTabRailCollapsed: [collapsed: boolean]
  deviceSourcesChanged: []
}>()

const activeTab = ref<'general' | 'sources'>('general')
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
const pluginResponse = ref<DeviceSourcePluginListResponse | null>(null)
const selectedPluginId = ref('')
const pluginDraft = ref<Record<string, PluginConfigValue>>({})
const pluginEnabled = ref(true)
const pluginSecretDraft = ref<Record<string, string>>({})
const clearedSecrets = ref(new Set<string>())
const visibleSecrets = ref(new Set<string>())
const showAdvanced = ref(false)
const pluginSaving = ref(false)
const pluginTesting = ref(false)
const pluginError = ref('')
const pluginNotice = ref('')
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
const selectedPlugin = computed(() =>
  pluginResponse.value?.plugins.find((plugin) => plugin.id === selectedPluginId.value) || null
)
const standardPluginFields = computed(() =>
  selectedPlugin.value?.config_fields.filter((field) => !field.advanced) || []
)
const advancedPluginFields = computed(() =>
  selectedPlugin.value?.config_fields.filter((field) => field.advanced) || []
)
const pluginDirty = computed(() => {
  const plugin = selectedPlugin.value
  if (!plugin) return false
  if (pluginEnabled.value !== plugin.enabled) return true
  if (Object.keys(pluginSecretDraft.value).some((key) => pluginSecretDraft.value[key] !== '')) {
    return true
  }
  if (clearedSecrets.value.size) return true
  return plugin.config_fields
    .filter((field) => field.kind !== 'secret')
    .some((field) => pluginDraft.value[field.key] !== field.value)
})
const canSavePlugin = computed(() => Boolean(
  selectedPlugin.value && pluginDirty.value && !pluginSaving.value && !pluginTesting.value
))

function readTerminalFontSize(): number {
  const value = Number(localStorage.getItem('odyterm.desktop-v2.terminal-font-size') || 13)
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
    if (props.allowPluginManagement) {
      applyPluginResponse(await desktopApi.deviceSourcePlugins())
    } else {
      activeTab.value = 'general'
      pluginResponse.value = null
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

function applyPluginResponse(response: DeviceSourcePluginListResponse): void {
  pluginResponse.value = response
  const selected = response.plugins.some((plugin) => plugin.id === selectedPluginId.value)
    ? selectedPluginId.value
    : response.plugins.find((plugin) => !plugin.built_in)?.id || response.plugins[0]?.id || ''
  selectPlugin(selected)
}

function selectPlugin(sourceId: string): void {
  selectedPluginId.value = sourceId
  const plugin = pluginResponse.value?.plugins.find((item) => item.id === sourceId)
  pluginDraft.value = Object.fromEntries(
    (plugin?.config_fields || [])
      .filter((field) => field.kind !== 'secret')
      .map((field) => [field.key, field.value])
  )
  pluginEnabled.value = plugin?.enabled ?? true
  pluginSecretDraft.value = {}
  clearedSecrets.value = new Set()
  visibleSecrets.value = new Set()
  showAdvanced.value = false
  pluginError.value = ''
  pluginNotice.value = ''
}

function pluginIcon(plugin: DeviceSourcePlugin): typeof Globe2 {
  if (plugin.icon === 'database') return Database
  if (plugin.icon === 'spreadsheet') return FileSpreadsheet
  if (plugin.icon === 'globe') return Globe2
  return Plug
}

function setPluginSecret(key: string, value: string): void {
  pluginSecretDraft.value = { ...pluginSecretDraft.value, [key]: value }
  const next = new Set(clearedSecrets.value)
  next.delete(key)
  clearedSecrets.value = next
}

function clearPluginSecret(key: string): void {
  pluginSecretDraft.value = { ...pluginSecretDraft.value, [key]: '' }
  const next = new Set(clearedSecrets.value)
  next.add(key)
  clearedSecrets.value = next
}

function toggleSecretVisibility(key: string): void {
  const next = new Set(visibleSecrets.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  visibleSecrets.value = next
}

async function savePlugin(): Promise<boolean> {
  const plugin = selectedPlugin.value
  if (!plugin || !canSavePlugin.value) return !pluginDirty.value
  pluginSaving.value = true
  pluginError.value = ''
  pluginNotice.value = ''
  try {
    const config = Object.fromEntries(
      plugin.config_fields
        .filter((field) => field.kind !== 'secret')
        .map((field) => [field.key, pluginDraft.value[field.key] ?? null])
    )
    const secrets: Record<string, string | null> = {}
    for (const field of plugin.config_fields.filter((item) => item.kind === 'secret')) {
      if (clearedSecrets.value.has(field.key)) secrets[field.key] = null
      else if (pluginSecretDraft.value[field.key]) secrets[field.key] = pluginSecretDraft.value[field.key]
    }
    const response = await desktopApi.updateDeviceSourcePlugin(plugin.id, {
      enabled: pluginEnabled.value,
      config,
      secrets
    })
    applyPluginResponse(response)
    pluginNotice.value = '插件设置已保存并立即生效'
    emit('deviceSourcesChanged')
    return true
  } catch (cause) {
    pluginError.value = cause instanceof Error ? cause.message : String(cause)
    return false
  } finally {
    pluginSaving.value = false
  }
}

async function testPlugin(): Promise<void> {
  const plugin = selectedPlugin.value
  if (!plugin || pluginTesting.value) return
  if (pluginDirty.value && !(await savePlugin())) return
  pluginTesting.value = true
  pluginError.value = ''
  pluginNotice.value = ''
  try {
    const response = await desktopApi.testDeviceSourcePlugin(plugin.id)
    if (response.success) pluginNotice.value = response.message
    else pluginError.value = response.message
  } catch (cause) {
    pluginError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    pluginTesting.value = false
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
    'odyterm.desktop-v2.terminal-font-size',
    String(terminalFontSize.value)
  )
  window.dispatchEvent(
    new CustomEvent('odyterm:terminal-font-size', { detail: terminalFontSize.value })
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

      <nav v-if="allowPluginManagement" class="settings-tabs" aria-label="设置类别">
        <button
          type="button"
          :class="{ active: activeTab === 'general' }"
          :aria-current="activeTab === 'general' ? 'page' : undefined"
          @click="activeTab = 'general'"
        >常规</button>
        <button
          type="button"
          :class="{ active: activeTab === 'sources' }"
          :aria-current="activeTab === 'sources' ? 'page' : undefined"
          @click="activeTab = 'sources'"
        >数据来源与插件</button>
      </nav>

      <div class="settings-scroll">
        <template v-if="activeTab === 'general'">
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
        </template>

        <template v-else>
          <div v-if="loading && !pluginResponse" class="plugin-loading" role="status">
            <LoaderCircle class="spinning-icon" :size="16" />正在发现插件…
          </div>
          <div v-else class="plugin-manager">
            <aside class="plugin-list" aria-label="已安装插件">
              <div class="plugin-list-heading">
                <span>已安装</span>
                <b>{{ pluginResponse?.plugins.length || 0 }}</b>
              </div>
              <button
                v-for="plugin in pluginResponse?.plugins || []"
                :key="plugin.id"
                type="button"
                class="plugin-list-item"
                :class="{ selected: plugin.id === selectedPluginId }"
                :aria-pressed="plugin.id === selectedPluginId"
                @click="selectPlugin(plugin.id)"
              >
                <span class="plugin-list-icon"><component :is="pluginIcon(plugin)" :size="16" /></span>
                <span class="plugin-list-copy">
                  <strong>{{ plugin.label }}</strong>
                  <small>{{ plugin.built_in ? '内置' : `外部 · ${plugin.version}` }}</small>
                </span>
                <i :data-state="plugin.available ? 'ready' : plugin.enabled ? 'error' : 'disabled'" aria-hidden="true"></i>
              </button>
              <p v-if="pluginResponse?.warnings.length" class="plugin-global-warning" role="status">
                <CircleAlert :size="13" />{{ pluginResponse.warnings[0] }}
              </p>
            </aside>

            <section v-if="selectedPlugin" class="plugin-detail" :aria-label="`${selectedPlugin.label} 插件设置`">
              <header class="plugin-detail-header">
                <div class="plugin-title-row">
                  <span class="plugin-detail-icon"><component :is="pluginIcon(selectedPlugin)" :size="19" /></span>
                  <span>
                    <strong>{{ selectedPlugin.label }}</strong>
                    <small>{{ selectedPlugin.publisher || '未知发布者' }} · v{{ selectedPlugin.version }}</small>
                  </span>
                </div>
                <div class="plugin-badges">
                  <b v-if="selectedPlugin.active" data-kind="active">当前来源</b>
                  <b v-if="selectedPlugin.default" data-kind="default">默认</b>
                  <b>{{ selectedPlugin.built_in ? '内置插件' : '外部插件' }}</b>
                </div>
              </header>

              <p class="plugin-description">{{ selectedPlugin.description }}</p>
              <div
                class="plugin-health"
                :data-state="selectedPlugin.available ? 'ready' : selectedPlugin.enabled ? 'error' : 'disabled'"
                role="status"
              >
                <CircleCheck v-if="selectedPlugin.available" :size="15" />
                <CircleAlert v-else :size="15" />
                <span>
                  <strong>{{ selectedPlugin.available ? '插件可用' : selectedPlugin.enabled ? '插件不可用' : '插件已禁用' }}</strong>
                  <small>{{ selectedPlugin.available ? '协议兼容，数据仓库初始化成功。' : selectedPlugin.unavailable_reason || '启用并完成配置后才能使用。' }}</small>
                </span>
              </div>

              <label v-if="!selectedPlugin.built_in" class="plugin-enable-row">
                <span>
                  <strong>启用插件</strong>
                  <small>禁用后不会出现在可选数据来源中。</small>
                </span>
                <input v-model="pluginEnabled" type="checkbox" :disabled="selectedPlugin.active" />
              </label>

              <div v-if="selectedPlugin.config_fields.length" class="plugin-fields">
                <h3>连接配置</h3>
                <template v-for="field in standardPluginFields" :key="field.key">
                  <label v-if="field.kind === 'boolean'" class="plugin-boolean-field">
                    <span><strong>{{ field.label }}</strong><small v-if="field.description">{{ field.description }}</small></span>
                    <input v-model="pluginDraft[field.key]" type="checkbox" />
                  </label>
                  <label v-else class="plugin-config-field">
                    <span>{{ field.label }}<b v-if="field.required">必填</b></span>
                    <select v-if="field.kind === 'select'" v-model="pluginDraft[field.key]">
                      <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
                    </select>
                    <input
                      v-else-if="field.kind === 'number'"
                      v-model.number="pluginDraft[field.key]"
                      type="number"
                      :min="field.minimum ?? undefined"
                      :max="field.maximum ?? undefined"
                    />
                    <div v-else-if="field.kind === 'secret'" class="plugin-secret-control">
                      <KeyRound :size="14" />
                      <input
                        :value="pluginSecretDraft[field.key] || ''"
                        :type="visibleSecrets.has(field.key) ? 'text' : 'password'"
                        :placeholder="field.secret_configured && !clearedSecrets.has(field.key) ? '已安全保存；留空不修改' : field.placeholder"
                        @input="setPluginSecret(field.key, ($event.target as HTMLInputElement).value)"
                      />
                      <button type="button" :title="visibleSecrets.has(field.key) ? '隐藏' : '显示'" @click="toggleSecretVisibility(field.key)">
                        <EyeOff v-if="visibleSecrets.has(field.key)" :size="14" /><Eye v-else :size="14" />
                      </button>
                      <button v-if="field.secret_configured && !clearedSecrets.has(field.key)" type="button" @click="clearPluginSecret(field.key)">清除</button>
                    </div>
                    <input
                      v-else
                      v-model.trim="pluginDraft[field.key]"
                      :type="field.kind === 'url' ? 'url' : 'text'"
                      :placeholder="field.placeholder"
                    />
                    <small v-if="field.description">{{ field.description }}</small>
                  </label>
                </template>

                <button
                  v-if="advancedPluginFields.length"
                  class="plugin-advanced-toggle"
                  type="button"
                  :aria-expanded="showAdvanced"
                  @click="showAdvanced = !showAdvanced"
                >{{ showAdvanced ? '收起高级配置' : `展开高级配置（${advancedPluginFields.length}）` }}</button>
                <div v-if="showAdvanced" class="plugin-advanced-fields">
                  <template v-for="field in advancedPluginFields" :key="field.key">
                    <label v-if="field.kind === 'boolean'" class="plugin-boolean-field">
                      <span><strong>{{ field.label }}</strong><small v-if="field.description">{{ field.description }}</small></span>
                      <input v-model="pluginDraft[field.key]" type="checkbox" />
                    </label>
                    <label v-else class="plugin-config-field">
                      <span>{{ field.label }}<b v-if="field.required">必填</b></span>
                      <select v-if="field.kind === 'select'" v-model="pluginDraft[field.key]">
                        <option v-for="option in field.options" :key="option.value" :value="option.value">{{ option.label }}</option>
                      </select>
                      <input
                        v-else-if="field.kind === 'number'"
                        v-model.number="pluginDraft[field.key]"
                        type="number"
                        :min="field.minimum ?? undefined"
                        :max="field.maximum ?? undefined"
                      />
                      <div v-else-if="field.kind === 'secret'" class="plugin-secret-control">
                        <KeyRound :size="14" />
                        <input
                          :value="pluginSecretDraft[field.key] || ''"
                          :type="visibleSecrets.has(field.key) ? 'text' : 'password'"
                          :placeholder="field.secret_configured && !clearedSecrets.has(field.key) ? '已安全保存；留空不修改' : field.placeholder"
                          @input="setPluginSecret(field.key, ($event.target as HTMLInputElement).value)"
                        />
                        <button type="button" :title="visibleSecrets.has(field.key) ? '隐藏' : '显示'" @click="toggleSecretVisibility(field.key)">
                          <EyeOff v-if="visibleSecrets.has(field.key)" :size="14" /><Eye v-else :size="14" />
                        </button>
                        <button v-if="field.secret_configured && !clearedSecrets.has(field.key)" type="button" @click="clearPluginSecret(field.key)">清除</button>
                      </div>
                      <input
                        v-else
                        v-model.trim="pluginDraft[field.key]"
                        :type="field.kind === 'url' ? 'url' : 'text'"
                        :placeholder="field.placeholder"
                      />
                      <small v-if="field.description">{{ field.description }}</small>
                    </label>
                  </template>
                </div>
              </div>
              <div v-else class="plugin-no-config">
                <Plug :size="16" /><span>这个插件没有可编辑配置。</span>
              </div>

              <button
                class="plugin-test-button"
                type="button"
                :disabled="pluginSaving || pluginTesting || !pluginEnabled"
                @click="testPlugin"
              ><LoaderCircle v-if="pluginTesting" class="spinning-icon" :size="14" /><RefreshCw v-else :size="14" />{{ pluginTesting ? '正在验证…' : '验证配置' }}</button>
            </section>
          </div>
        </template>
      </div>
      <footer class="settings-action-bar">
        <p
          class="settings-dirty-state"
          :data-dirty="activeTab === 'general' ? logSettingsDirty : pluginDirty"
          :data-state="activeTab === 'general' ? (error ? 'error' : loading ? 'loading' : saving ? 'saving' : notice ? 'success' : logSettingsDirty ? 'dirty' : 'saved') : (pluginError ? 'error' : pluginSaving || pluginTesting ? 'saving' : pluginNotice ? 'success' : pluginDirty ? 'dirty' : 'saved')"
          :role="activeTab === 'general' ? (error ? 'alert' : 'status') : (pluginError ? 'alert' : 'status')"
        >
          <LoaderCircle v-if="activeTab === 'general' ? loading || saving : pluginSaving || pluginTesting" class="spinning-icon" :size="13" aria-hidden="true" />
          <i v-else aria-hidden="true"></i>
          <span v-if="activeTab === 'general'">
            <strong>{{ error ? '日志设置操作失败' : loading ? '正在读取日志设置' : saving ? '正在保存日志设置' : notice || (logSettingsDirty ? '日志设置有未保存修改' : '日志设置已保存') }}</strong>
            <small>{{ error || (logSettingsDirty ? '保存后目录和分卷大小才会生效' : '外观、窗口和终端字体即时生效') }}</small>
          </span>
          <span v-else>
            <strong>{{ pluginError ? '插件操作失败' : pluginSaving ? '正在保存插件设置' : pluginTesting ? '正在验证插件' : pluginNotice || (pluginDirty ? '插件设置有未保存修改' : '插件设置已同步') }}</strong>
            <small>{{ pluginError || (pluginDirty ? '保存后立即重建插件数据源' : '敏感配置只保存在系统凭据库') }}</small>
          </span>
        </p>
        <button
          v-if="activeTab === 'general'"
          class="settings-save"
          type="button"
          :disabled="!canSaveLogs || saving || loading"
          @click="saveLogSettings"
        ><LoaderCircle v-if="saving" class="spinning-icon" :size="15" /><Save v-else :size="15" />{{ saving ? '正在保存…' : '保存日志设置' }}</button>
        <button
          v-else
          class="settings-save"
          type="button"
          :disabled="!canSavePlugin"
          @click="savePlugin"
        ><LoaderCircle v-if="pluginSaving" class="spinning-icon" :size="15" /><Save v-else :size="15" />{{ pluginSaving ? '正在保存…' : '保存插件设置' }}</button>
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
  width: min(760px, calc(100vw - 24px));
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
.settings-tabs {
  min-height: 42px;
  padding: 0 14px;
  display: flex;
  align-items: end;
  gap: 18px;
  border-bottom: 1px solid var(--line);
  background: color-mix(in srgb, var(--surface-raised) 38%, transparent);
}
.settings-tabs button {
  position: relative;
  min-height: 41px;
  padding: 0 2px;
  color: var(--muted);
  border: 0;
  background: transparent;
  cursor: pointer;
  font-weight: 650;
}
.settings-tabs button::after {
  content: '';
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: transparent;
}
.settings-tabs button:hover, .settings-tabs button.active { color: var(--text); }
.settings-tabs button.active::after { background: var(--accent); }
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
.plugin-loading {
  min-height: 240px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--muted);
}
.plugin-manager {
  min-height: 450px;
  display: grid;
  grid-template-columns: 205px minmax(0, 1fr);
  gap: 12px;
}
.plugin-list {
  min-width: 0;
  padding: 8px;
  align-self: start;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-raised) 52%, transparent);
}
.plugin-list-heading {
  min-height: 28px;
  padding: 0 5px 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: var(--soft);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.08em;
}
.plugin-list-heading b { color: var(--muted); font-family: Consolas, monospace; }
.plugin-list-item {
  width: 100%;
  min-height: 50px;
  padding: 7px;
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr) 8px;
  align-items: center;
  gap: 7px;
  color: var(--muted);
  text-align: left;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  cursor: pointer;
  transition: color 160ms ease, border-color 160ms ease, background 160ms ease;
}
.plugin-list-item:hover { color: var(--text); background: var(--surface-hover); }
.plugin-list-item.selected { color: var(--text); border-color: color-mix(in srgb, var(--accent) 45%, var(--line)); background: color-mix(in srgb, var(--accent) 8%, var(--surface-raised)); }
.plugin-list-icon, .plugin-detail-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--blue);
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--surface-raised);
}
.plugin-list-icon { width: 30px; height: 30px; }
.plugin-list-copy { min-width: 0; display: grid; gap: 2px; }
.plugin-list-copy strong, .plugin-list-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.plugin-list-copy strong { color: inherit; font-size: 11.5px; }
.plugin-list-copy small { color: var(--soft); font-size: 9.5px; }
.plugin-list-item > i { width: 7px; height: 7px; border-radius: 50%; background: var(--soft); }
.plugin-list-item > i[data-state="ready"] { background: var(--accent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 14%, transparent); }
.plugin-list-item > i[data-state="error"] { background: var(--danger); }
.plugin-global-warning { margin: 8px 4px 2px; display: flex; gap: 5px; color: var(--warning); font-size: 9.5px; line-height: 1.4; }
.plugin-detail {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: color-mix(in srgb, var(--surface-raised) 42%, transparent);
  box-shadow: var(--shadow-card);
}
.plugin-detail-header { min-height: 42px; display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.plugin-title-row { min-width: 0; display: flex; align-items: center; gap: 9px; }
.plugin-detail-icon { width: 38px; height: 38px; flex: 0 0 auto; }
.plugin-title-row > span:last-child { min-width: 0; display: grid; gap: 3px; }
.plugin-title-row strong { color: var(--text); font-size: 14px; }
.plugin-title-row small { color: var(--soft); font-size: 9.5px; }
.plugin-badges { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 4px; }
.plugin-badges b { padding: 3px 6px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; font-size: 8.5px; }
.plugin-badges b[data-kind="active"] { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 35%, var(--line)); }
.plugin-badges b[data-kind="default"] { color: var(--blue); border-color: color-mix(in srgb, var(--blue) 35%, var(--line)); }
.plugin-description { margin: 11px 0; color: var(--muted); font-size: 10.5px; line-height: 1.55; }
.plugin-health {
  padding: 9px 10px;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 25%, var(--line));
  border-radius: 8px;
  background: color-mix(in srgb, var(--accent) 6%, var(--surface));
}
.plugin-health[data-state="error"] { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 30%, var(--line)); background: color-mix(in srgb, var(--danger) 5%, var(--surface)); }
.plugin-health[data-state="disabled"] { color: var(--muted); border-color: var(--line); background: var(--surface-raised); }
.plugin-health > svg { margin-top: 1px; flex: 0 0 auto; }
.plugin-health span { min-width: 0; display: grid; gap: 2px; }
.plugin-health strong { color: currentColor; font-size: 10.5px; }
.plugin-health small { color: var(--muted); font-size: 9.5px; line-height: 1.45; overflow-wrap: anywhere; }
.plugin-enable-row, .plugin-boolean-field {
  margin-top: 11px;
  padding: 9px 10px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface-raised);
  cursor: pointer;
}
.plugin-enable-row > span, .plugin-boolean-field > span { display: grid; gap: 2px; }
.plugin-enable-row strong, .plugin-boolean-field strong { color: var(--text); font-size: 10.5px; }
.plugin-enable-row small, .plugin-boolean-field small { color: var(--soft); font-size: 9px; }
.plugin-enable-row input, .plugin-boolean-field input { width: 15px; height: 15px; accent-color: var(--accent); cursor: pointer; }
.plugin-fields { margin-top: 14px; }
.plugin-fields h3 { margin: 0 0 8px; color: var(--text); font-size: 11px; }
.plugin-config-field { margin-top: 9px; display: grid; gap: 5px; color: var(--muted); }
.plugin-config-field > span { display: flex; align-items: center; gap: 6px; font-size: 10px; font-weight: 650; }
.plugin-config-field > span b { padding: 1px 4px; color: var(--warning); border-radius: 4px; background: color-mix(in srgb, var(--warning) 10%, transparent); font-size: 8px; }
.plugin-config-field > input, .plugin-config-field > select, .plugin-secret-control {
  width: 100%;
  min-width: 0;
  height: 32px;
  padding: 0 9px;
  color: var(--text);
  border: 1px solid var(--line);
  border-radius: 7px;
  background: var(--bg);
}
.plugin-config-field > small { color: var(--soft); font-size: 9px; line-height: 1.4; }
.plugin-config-field > input:focus, .plugin-config-field > select:focus, .plugin-secret-control:focus-within { outline: 2px solid color-mix(in srgb, var(--blue) 38%, transparent); outline-offset: 1px; border-color: var(--blue); }
.plugin-secret-control { padding: 0 4px 0 9px; display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: center; gap: 5px; }
.plugin-secret-control > svg { color: var(--soft); }
.plugin-secret-control input { min-width: 0; height: 28px; padding: 0; color: var(--text); border: 0; outline: 0; background: transparent; }
.plugin-secret-control button, .plugin-advanced-toggle, .plugin-test-button {
  min-height: 27px;
  padding: 0 7px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface-raised);
  cursor: pointer;
}
.plugin-secret-control button:hover, .plugin-advanced-toggle:hover, .plugin-test-button:hover:not(:disabled) { color: var(--text); border-color: var(--line-strong); }
.plugin-advanced-toggle { width: 100%; margin-top: 12px; }
.plugin-advanced-fields { margin-top: 9px; padding-top: 1px; border-top: 1px dashed var(--line); }
.plugin-no-config { margin-top: 14px; min-height: 64px; display: flex; align-items: center; justify-content: center; gap: 7px; color: var(--soft); border: 1px dashed var(--line); border-radius: 8px; font-size: 10px; }
.plugin-test-button { margin-top: 13px; min-width: 104px; }
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
@media (max-width: 680px) {
  .plugin-manager { grid-template-columns: 1fr; }
  .plugin-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 5px; }
  .plugin-list-heading, .plugin-global-warning { grid-column: 1 / -1; }
  .plugin-detail-header { display: grid; }
  .plugin-badges { justify-content: flex-start; }
}
</style>
