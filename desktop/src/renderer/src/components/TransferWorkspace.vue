<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ArrowDownToLine,
  ArrowDownUp,
  ArrowUpFromLine,
  ChevronDown,
  CircleStop,
  Copy,
  Eye,
  EyeOff,
  File,
  FileUp,
  FolderOpen,
  LoaderCircle,
  Play,
  RefreshCw,
  Save,
  Search,
  Server,
  ShieldCheck,
  Trash2,
  X
} from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import { desktopApi } from '../transport/api'
import type { TransferSettings } from '../types'

const workspace = useWorkspaceStore()
const direction = ref<'upload' | 'download'>('upload')
const commandMode = ref<'ftp' | 'ftpget'>('ftp')
const sourcePath = ref('')
const destinationPath = ref('')
const commandText = ref('')
const commandEdited = ref(false)
const localError = ref('')
const fileQuery = ref('')
const fileSort = ref<'name' | 'size' | 'modified'>('name')
const fileOrder = ref<'asc' | 'desc'>('asc')
const settingsOpen = ref(true)
const networkAddresses = ref<string[]>([])
const networkAddressesLoading = ref(false)
const networkAddressError = ref('')
const logsOpen = ref(false)
const passwordVisible = ref(false)
const passwordDirty = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null
const savedPasswordPlaceholder = '{{file_transfer.password}}'
const savedPasswordShellPlaceholder = '{{file_transfer.password.shell}}'

const settingsDraft = ref<Pick<TransferSettings, 'protocol' | 'host' | 'advertised_host' | 'port' | 'root' | 'username' | 'writable'> & { password: string }>({
  protocol: 'ftp',
  host: '0.0.0.0',
  advertised_host: '',
  port: 0,
  root: '',
  username: 'device',
  password: '',
  writable: true
})
const settingsDirty = computed(() => {
  const saved = workspace.transferSettings
  const draft = settingsDraft.value
  if (!saved) return false
  return passwordDirty.value
    || draft.protocol !== saved.protocol
    || draft.host.trim() !== saved.host
    || draft.advertised_host.trim() !== saved.advertised_host
    || Number(draft.port) !== saved.port
    || draft.root.trim() !== saved.root
    || draft.username.trim() !== saved.username
    || draft.writable !== saved.writable
})

const effectiveServiceHost = computed(() => settingsDraft.value.advertised_host.trim())
const sourceError = computed(() => !sourcePath.value.trim() ? (direction.value === 'upload' ? '请从共享文件中选择源文件' : '请输入设备源文件路径') : '')
const destinationError = computed(() => !destinationPath.value.trim() ? '请输入目标路径' : '')
const activeSessionConnected = computed(() => workspace.activeSession?.status === 'connected')
const addressError = computed(() => !effectiveServiceHost.value ? '请选择设备可访问的 FTP 地址' : '')
const hasUsablePassword = computed(() => Boolean(
  settingsDraft.value.password.trim() || workspace.transferSettings?.has_password
))
const credentialError = computed(() => !settingsDraft.value.username.trim()
  ? '请在上方 FTP 配置中填写用户名'
  : !hasUsablePassword.value
    ? '请在上方 FTP 配置中输入并保存密码'
    : '')
function quoteShellArgument(value: string, fallback: string): string {
  const normalized = value.trim() || fallback
  if (/^[A-Za-z0-9_./:#@+-]+$/.test(normalized)) return normalized
  return `'${normalized.replace(/'/g, `'"'"'`)}'`
}
const generatedCommand = computed(() => {
  const host = effectiveServiceHost.value
  const port = Number(settingsDraft.value.port) || workspace.transferSettings?.bound_port || 21
  const source = sourcePath.value.trim() || '<选择文件>'
  const destination = destinationPath.value.trim() || '<设备路径>'
  if (commandMode.value === 'ftpget') {
    const passwordArgument = settingsDraft.value.password.trim()
      ? quoteShellArgument(settingsDraft.value.password, '<FTP 密码>')
      : savedPasswordShellPlaceholder
    return [
      'ftpget',
      '-u', quoteShellArgument(settingsDraft.value.username, '<FTP 用户名>'),
      '-p', passwordArgument,
      '-P', String(port),
      quoteShellArgument(host, '<设备访问 IP>'),
      quoteShellArgument(destination, '<设备路径>'),
      quoteShellArgument(source, '<共享文件>')
    ].join(' ')
  }
  const transfer = direction.value === 'upload'
    ? `get ${source} ${destination}`
    : `put ${source} ${destination}`
  const passwordLine = settingsDraft.value.password || savedPasswordPlaceholder
  return [`ftp ${host || '<设备访问 IP>'} ${port}`, settingsDraft.value.username.trim() || '<FTP 用户名>', passwordLine, 'binary', transfer, 'quit'].join('\n')
})
const serviceLabel = computed(() => {
  const settings = workspace.transferSettings
  if (!settings?.service_running) return '服务未启动'
  return `FTP · :${settings.bound_port}`
})

watch(
  () => workspace.transferSettings,
  (settings) => {
    if (!settings) return
    settingsDraft.value = {
      protocol: 'ftp',
      host: settings.host,
      advertised_host: settings.advertised_host,
      port: settings.port,
      root: settings.root,
      username: settings.username,
      password: '',
      writable: settings.writable
    }
    passwordDirty.value = false
    passwordVisible.value = false
  },
  { immediate: true, deep: true }
)

watch(direction, () => {
  sourcePath.value = ''
  destinationPath.value = ''
  localError.value = ''
})

watch(commandMode, (mode) => {
  if (mode === 'ftpget' && direction.value === 'download') direction.value = 'upload'
  commandEdited.value = false
  localError.value = ''
})

watch(
  generatedCommand,
  (command) => {
    if (!commandEdited.value) commandText.value = command
  },
  { immediate: true }
)

watch(
  () => workspace.transferPanelOpen,
  (open) => {
    if (!open) return
    void loadFiles()
    void workspace.loadTransferServiceLog()
    void loadNetworkAddresses()
  },
  { immediate: true }
)

watch(() => workspace.activeSession?.id, () => {
  if (workspace.transferPanelOpen) void loadNetworkAddresses()
})

watch([fileQuery, fileSort, fileOrder], () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { void loadFiles() }, 250)
})

async function loadFiles(offset = 0, append = false): Promise<void> {
  await workspace.loadTransferFiles({
    query: fileQuery.value.trim(),
    sort: fileSort.value,
    order: fileOrder.value,
    offset,
    append
  })
}

async function loadNetworkAddresses(): Promise<void> {
  networkAddressesLoading.value = true
  networkAddressError.value = ''
  try {
    const response = await desktopApi.transferNetworkAddresses(workspace.activeSession?.id || '')
    networkAddresses.value = response.addresses
    const current = settingsDraft.value.advertised_host.trim()
    if (!current && response.recommended) settingsDraft.value.advertised_host = response.recommended
    if (!settingsDraft.value.advertised_host && response.addresses.length === 1) {
      settingsDraft.value.advertised_host = response.addresses[0]
    }
  } catch (cause) {
    networkAddressError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    networkAddressesLoading.value = false
  }
}

function selectUploadFile(relativePath: string, name: string): void {
  direction.value = 'upload'
  sourcePath.value = relativePath
  destinationPath.value = `flash:/${name}`
  localError.value = ''
}

async function chooseRoot(): Promise<void> {
  const selected = await window.desktopApi.chooseTransferRoot()
  if (selected) settingsDraft.value.root = selected
}

async function saveSettings(): Promise<boolean> {
  localError.value = ''
  if (!settingsDraft.value.root.trim()) {
    localError.value = '请选择共享目录。'
    return false
  }
  const { password, ...settings } = settingsDraft.value
  const saved = await workspace.saveTransferSettings({
    ...settings,
    port: Math.max(0, Math.min(65535, Number(settings.port) || 0)),
    ...(passwordDirty.value && password ? { password } : {})
  })
  if (saved) {
    settingsDraft.value.password = password
    passwordDirty.value = false
    await loadFiles()
  }
  return saved
}

async function saveAndPrepare(): Promise<void> {
  localError.value = ''
  if (settingsDirty.value && !await saveSettings()) return
  if (addressError.value || credentialError.value || sourceError.value || destinationError.value) {
    localError.value = addressError.value || credentialError.value || sourceError.value || destinationError.value
    return
  }
  try {
    await window.desktopApi.copyTransferCommand(commandText.value)
    workspace.notice = 'FTP 命令已复制，可在终端手工执行'
  } catch (cause) {
    localError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function copyGeneratedCommand(): Promise<void> {
  if (settingsDirty.value && !await saveSettings()) return
  if (addressError.value || credentialError.value || sourceError.value || destinationError.value) {
    localError.value = addressError.value || credentialError.value || sourceError.value || destinationError.value
    return
  }
  try {
    await window.desktopApi.copyTransferCommand(commandText.value)
    workspace.notice = 'FTP 命令已复制，已自动填入保存的密码'
  } catch (cause) {
    localError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

function resetCommand(): void {
  commandEdited.value = false
  commandText.value = generatedCommand.value
}

async function copyServiceLog(): Promise<void> {
  const content = workspace.transferServiceLog.join('\n')
  if (!content) return
  await navigator.clipboard.writeText(content)
  workspace.notice = '已复制文件服务日志'
}

async function copyClientCommand(): Promise<void> {
  if (!workspace.transferClientCommand) return
  await navigator.clipboard.writeText(workspace.transferClientCommand)
  workspace.notice = '已复制设备侧客户端命令'
}

function toggleLogs(): void {
  logsOpen.value = !logsOpen.value
  if (logsOpen.value) void workspace.loadTransferServiceLog()
}

function formatBytes(value: unknown): string {
  const bytes = Number(value) || 0
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

onBeforeUnmount(() => {
  if (searchTimer) clearTimeout(searchTimer)
})
</script>

<template>
  <div v-if="workspace.transferPanelOpen" class="transfer-backdrop" @mousedown.self="workspace.transferPanelOpen = false">
    <aside class="transfer-workspace" role="region" aria-labelledby="transfer-title">
      <header class="transfer-header">
        <div class="transfer-heading">
          <span class="transfer-icon"><FileUp :size="18" /></span>
          <div><p class="eyebrow">MANAGED TRANSFER</p><h2 id="transfer-title">托管文件传输</h2></div>
        </div>
        <div class="transfer-header-actions">
          <span class="service-state" :data-running="workspace.transferSettings?.service_running"><i></i>{{ serviceLabel }}</span>
          <span class="transfer-session-chip" :data-connected="activeSessionConnected">{{ workspace.activeSession?.title || '未选择终端' }}</span>
          <button class="icon-button" type="button" aria-label="关闭文件传输" @click="workspace.transferPanelOpen = false"><X :size="16" /></button>
        </div>
      </header>

      <div class="transfer-body">
        <section class="transfer-server-section" aria-labelledby="transfer-server-title">
          <form class="transfer-settings-card" data-testid="transfer-settings" :data-open="settingsOpen" :aria-busy="workspace.transferBusy" @submit.prevent="saveSettings">
            <header class="transfer-settings-header">
              <div class="transfer-settings-heading">
                <button class="transfer-settings-toggle" type="button" :aria-expanded="settingsOpen" aria-controls="transfer-settings-fields" :title="settingsOpen ? '收起 FTP 配置' : '展开 FTP 配置'" :aria-label="settingsOpen ? '收起 FTP 配置' : '展开 FTP 配置'" @click="settingsOpen = !settingsOpen"><ChevronDown :size="14" /></button>
                <Server :size="15" /><strong id="transfer-server-title">FTP 服务器配置</strong>
              </div>
              <span class="service-state" :data-running="workspace.transferSettings?.service_running"><i></i>{{ serviceLabel }}</span>
            </header>
            <template v-if="settingsOpen">
              <div id="transfer-settings-fields" class="transfer-settings-grid">
                <label class="form-field"><span>监听地址</span><input v-model.trim="settingsDraft.host" autocomplete="off" /></label>
                <label class="form-field"><span>服务端口</span><input v-model.number="settingsDraft.port" type="number" min="0" max="65535" /><small>留空或 0 表示自动分配。</small></label>
                <label class="form-field"><span>登录账号</span><input v-model.trim="settingsDraft.username" autocomplete="off" /></label>
                <label class="form-field"><span class="transfer-password-label">登录密码 <em :data-set="workspace.transferSettings?.has_password">{{ workspace.transferSettings?.has_password ? '已保存，复制时自动填入' : '未设置' }}</em></span><span class="transfer-password-input"><input v-model="settingsDraft.password" :type="passwordVisible ? 'text' : 'password'" :placeholder="workspace.transferSettings?.has_password ? '已保存；输入新密码可替换' : '输入登录密码'" autocomplete="new-password" @input="passwordDirty = true" /><button class="icon-button" type="button" :title="passwordVisible ? '隐藏密码' : '显示密码'" :aria-label="passwordVisible ? '隐藏密码' : '显示密码'" :aria-pressed="passwordVisible" @click="passwordVisible = !passwordVisible"><EyeOff v-if="passwordVisible" :size="14" /><Eye v-else :size="14" /></button></span></label>
                <label class="form-field transfer-root-field"><span>共享目录</span><span class="transfer-root-input"><input v-model="settingsDraft.root" data-testid="transfer-root" readonly /><button class="icon-button" type="button" title="选择共享目录" @click="chooseRoot"><FolderOpen :size="15" /></button></span></label>
                <label class="transfer-write-toggle"><input v-model="settingsDraft.writable" type="checkbox" />允许设备上传文件到共享目录</label>
              </div>
              <footer>
                <span><ShieldCheck :size="13" />临时身份传输，连接端点全程可见</span>
                <div class="transfer-settings-actions">
                  <button class="secondary-button" type="submit" :disabled="workspace.transferBusy"><Save :size="13" />保存配置</button>
                  <button :class="workspace.transferSettings?.service_running ? 'secondary-button danger-button' : 'secondary-button'" type="button" :disabled="workspace.transferBusy" @click="workspace.toggleTransferService"><CircleStop v-if="workspace.transferSettings?.service_running" :size="13" /><Play v-else :size="13" />{{ workspace.transferSettings?.service_running ? '停止服务' : '启动服务' }}</button>
                </div>
              </footer>
              <div class="transfer-client-hint" data-testid="transfer-client-command"><span><strong>设备连接入口</strong><small>{{ effectiveServiceHost }} · FTP · 端口 {{ settingsDraft.port || '自动' }}</small></span><code>{{ workspace.transferClientCommand || '保存配置后生成连接命令' }}</code><button class="icon-button" type="button" title="复制客户端命令" :disabled="!workspace.transferClientCommand" @click="copyClientCommand"><Copy :size="13" /></button></div>
            </template>
          </form>

          <div class="transfer-log-disclosure" :data-open="logsOpen">
            <button type="button" :aria-expanded="logsOpen" @click="toggleLogs"><span><Server :size="13" />FTP 服务运行日志 <em>{{ workspace.transferServiceLog.length }} 条</em></span><ChevronDown :size="14" /></button>
            <div v-if="logsOpen" class="transfer-service-log-card" data-testid="transfer-service-log"><header><span>显示启动、连接、登录和文件收发事件，不记录凭据。</span><div><button class="icon-button" type="button" title="刷新日志" @click="workspace.loadTransferServiceLog"><RefreshCw :size="13" /></button><button class="icon-button" type="button" title="复制日志" :disabled="!workspace.transferServiceLog.length" @click="copyServiceLog"><Copy :size="13" /></button><button class="icon-button" type="button" title="清空日志" :disabled="!workspace.transferServiceLog.length" @click="workspace.clearTransferServiceLog"><Trash2 :size="13" /></button></div></header><pre>{{ workspace.transferServiceLog.join('\n') || '暂无服务日志。' }}</pre></div>
          </div>
        </section>

        <section class="transfer-primary-grid">
          <div class="transfer-files-card">
            <header>
              <div><FolderOpen :size="14" /><strong>选择共享文件</strong><span>{{ workspace.transferFileTotal }}</span></div>
              <button class="icon-button" type="button" title="刷新文件" :disabled="workspace.transferFilesLoading" @click="loadFiles()"><RefreshCw :class="{ 'spinning-icon': workspace.transferFilesLoading }" :size="14" /></button>
            </header>
            <div class="transfer-file-tools">
              <label><Search :size="13" /><input v-model="fileQuery" aria-label="搜索共享文件" placeholder="搜索名称或路径" /></label>
              <select v-model="fileSort" aria-label="文件排序字段"><option value="name">名称</option><option value="size">大小</option><option value="modified">时间</option></select>
              <button class="transfer-sort-order" type="button" :title="fileOrder === 'asc' ? '当前升序，点击切换为降序' : '当前降序，点击切换为升序'" :aria-label="fileOrder === 'asc' ? '当前升序，切换为降序' : '当前降序，切换为升序'" @click="fileOrder = fileOrder === 'asc' ? 'desc' : 'asc'"><ArrowDownUp :size="12" />{{ fileOrder === 'asc' ? '升序' : '降序' }}</button>
            </div>
            <div class="transfer-file-list" :aria-busy="workspace.transferFilesLoading">
              <button
                v-for="file in workspace.transferFiles"
                :key="file.relative_path"
                data-testid="transfer-file"
                type="button"
                :title="file.relative_path"
                :class="{ selected: direction === 'upload' && sourcePath === file.relative_path }"
                @click="selectUploadFile(file.relative_path, file.name)"
              >
                <File :size="14" /><span><strong>{{ file.name }}</strong><small>{{ file.relative_path }}</small></span><b>{{ formatBytes(file.size_bytes) }}</b>
              </button>
              <div v-if="workspace.transferFilesLoading && !workspace.transferFiles.length" class="transfer-file-loading" role="status"><LoaderCircle class="spinning-icon" :size="18" />正在读取共享目录…</div>
              <div v-else-if="!workspace.transferFiles.length" class="transfer-empty transfer-empty-files"><FolderOpen :size="20" /><strong>没有匹配文件</strong><span>调整搜索条件或在上方 FTP 服务器配置中更换共享目录。</span></div>
              <button v-if="workspace.transferFileNextOffset !== null" class="transfer-load-more" type="button" :disabled="workspace.transferFilesLoading" @click="loadFiles(workspace.transferFileNextOffset || 0, true)">加载更多</button>
            </div>
          </div>

          <form class="transfer-run-card" data-testid="transfer-run" @submit.prevent="saveAndPrepare">
            <header><div><strong>手工 FTP 命令</strong><span>生成后复制到当前终端执行</span></div><ShieldCheck :size="15" /></header>
            <div class="transfer-direction-tabs" role="tablist" aria-label="传输方向">
              <button type="button" role="tab" :aria-selected="direction === 'upload'" :class="{ active: direction === 'upload' }" @click="direction = 'upload'"><ArrowUpFromLine :size="14" />PC → 设备</button>
              <button type="button" role="tab" :aria-selected="direction === 'download'" :class="{ active: direction === 'download' }" :disabled="commandMode === 'ftpget'" :title="commandMode === 'ftpget' ? 'ftpget 仅支持 PC → 设备' : ''" @click="direction = 'download'"><ArrowDownToLine :size="14" />设备 → PC</button>
            </div>
            <label class="form-field transfer-command-mode-field"><span>命令模式</span><select v-model="commandMode" aria-label="FTP 命令模式"><option value="ftp">FTP 交互式</option><option value="ftpget">ftpget 单命令</option></select></label>
            <label class="form-field transfer-command-address"><span class="transfer-setting-label">设备访问 IP <em v-if="networkAddressesLoading">正在探测路由</em><em v-else-if="networkAddressError">自动探测失败</em><em v-else-if="effectiveServiceHost">用于当前命令</em></span><span class="transfer-address-input"><select v-if="networkAddresses.length" v-model="settingsDraft.advertised_host" :disabled="networkAddressesLoading" aria-label="设备访问 IP"><option value="" disabled>请选择设备可访问的 IP</option><option v-if="settingsDraft.advertised_host && !networkAddresses.includes(settingsDraft.advertised_host)" :value="settingsDraft.advertised_host">{{ settingsDraft.advertised_host }} · 已配置</option><option v-for="address in networkAddresses" :key="address" :value="address">{{ address }}</option></select><input v-else v-model.trim="settingsDraft.advertised_host" placeholder="例如 192.168.1.20" autocomplete="off" /><button class="icon-button" type="button" title="重新按当前终端路由探测 IP" aria-label="重新探测设备访问 IP" :disabled="networkAddressesLoading" @click="loadNetworkAddresses"><RefreshCw :class="{ 'spinning-icon': networkAddressesLoading }" :size="14" /></button></span></label>
            <label class="form-field">
              <span>{{ direction === 'upload' ? '共享目录源文件' : '设备源文件' }}</span>
              <input v-model="sourcePath" data-testid="transfer-source" :readonly="direction === 'upload'" :placeholder="direction === 'upload' ? '从左侧选择文件' : '例如 flash:/backup.cfg'" autocomplete="off" />
              <small v-if="sourceError && localError" class="field-error">{{ sourceError }}</small>
            </label>
            <label class="form-field">
              <span>{{ direction === 'upload' ? '设备目标路径' : '共享目录目标路径' }}</span>
              <input v-model="destinationPath" data-testid="transfer-destination" :placeholder="direction === 'upload' ? '例如 flash:/target.cc' : '例如 downloads/backup.cfg'" autocomplete="off" />
              <small v-if="destinationError && localError" class="field-error">{{ destinationError }}</small>
            </label>
            <div class="transfer-command-preview" data-testid="transfer-command-preview">
              <span><strong>命令预览</strong><small>可直接编辑；不会自动发送；保存的密码复制时填入</small><button class="icon-button" type="button" title="恢复自动生成命令" aria-label="恢复自动生成命令" @click="resetCommand"><RefreshCw :size="13" /></button></span>
              <textarea v-model="commandText" aria-label="可编辑 FTP 命令" spellcheck="false" @input="commandEdited = true"></textarea>
            </div>
            <p v-if="localError || workspace.transferError" class="transfer-error" role="alert">{{ localError || workspace.transferError }}</p>
            <p class="operation-readiness" :data-ready="!addressError && !credentialError && !sourceError && !destinationError"><i></i>{{ addressError || credentialError || sourceError || destinationError || '命令已填好，可编辑后复制到终端手工执行' }}</p>
            <div class="transfer-command-actions"><button class="secondary-button" type="submit" :disabled="workspace.transferBusy || Boolean(addressError) || Boolean(credentialError) || Boolean(sourceError) || Boolean(destinationError)"><Save :size="14" />生成并复制命令</button><button class="primary-button" type="button" :disabled="Boolean(addressError) || Boolean(credentialError) || Boolean(sourceError) || Boolean(destinationError)" @click="copyGeneratedCommand"><Copy :size="14" />复制命令</button></div>
          </form>
        </section>

      </div>
    </aside>
  </div>
</template>
