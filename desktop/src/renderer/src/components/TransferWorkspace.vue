<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ChevronDown,
  CircleStop,
  Clock3,
  Copy,
  Eye,
  EyeOff,
  File,
  FileUp,
  FolderOpen,
  LoaderCircle,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Server,
  Settings2,
  ShieldCheck,
  TriangleAlert,
  Trash2,
  X
} from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import type { OperationRecord, TransferSettings } from '../types'

const workspace = useWorkspaceStore()
const direction = ref<'upload' | 'download'>('upload')
const sourcePath = ref('')
const destinationPath = ref('')
const overwrite = ref(false)
const terminalEnvironment = ref<'auto' | 'linux' | 'vrp'>('auto')
const localError = ref('')
const fileQuery = ref('')
const fileSort = ref<'name' | 'size' | 'modified'>('name')
const fileOrder = ref<'asc' | 'desc'>('asc')
const historyFilter = ref<'all' | 'completed' | 'failed' | 'cancelled' | 'interrupted'>('all')
const historyOpen = ref(false)
const advancedOpen = ref(false)
const logsOpen = ref(false)
const passwordVisible = ref(false)
const passwordDirty = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null

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

const currentOperations = computed(() =>
  workspace.operations.filter((operation) => ['queued', 'running'].includes(operation.status))
)
const historyOperations = computed(() => workspace.operations.filter((operation) => {
  if (!['completed', 'failed', 'cancelled', 'interrupted'].includes(operation.status)) return false
  return historyFilter.value === 'all' || operation.status === historyFilter.value
}))
const latestTransferOutcome = computed(() =>
  workspace.operations.find((operation) => ['completed', 'failed', 'cancelled', 'interrupted'].includes(operation.status)) || null
)
const latestFailedOperation = computed(() =>
  latestTransferOutcome.value?.status === 'failed' || latestTransferOutcome.value?.status === 'interrupted'
    ? latestTransferOutcome.value
    : null
)
const latestFailureSessionConnected = computed(() => {
  const operation = latestFailedOperation.value
  return Boolean(operation && workspace.sessions.some(
    (session) => session.id === operation.session_id && session.status === 'connected'
  ))
})
const pausedSessionIds = computed(() => [...new Set(
  currentOperations.value.filter((operation) => operation.stage === 'paused').map((operation) => operation.session_id)
)])
const hasRunningTransfer = computed(() => currentOperations.value.some((operation) => operation.status === 'running'))
const activeSessionConnected = computed(() => workspace.activeSession?.status === 'connected')
const preferredTerminalEnvironment = computed<'linux' | 'vrp'>(() => {
  if (terminalEnvironment.value !== 'auto') return terminalEnvironment.value
  return workspace.activeSession?.kind === 'ssh' ? 'linux' : 'vrp'
})
const terminalEnvironmentHint = computed(() => {
  if (terminalEnvironment.value === 'linux') return 'Linux 绝对路径，例如 /tmp/image.cc'
  if (terminalEnvironment.value === 'vrp') return 'VRP 存储路径，例如 flash:/image.cc'
  return `自动判断，当前预计为 ${preferredTerminalEnvironment.value === 'linux' ? 'Linux Shell' : 'Huawei VRP'}`
})
const devicePathPlaceholder = computed(() => (
  preferredTerminalEnvironment.value === 'linux' ? '例如 /tmp/target.cc' : '例如 flash:/target.cc'
))
const sourceError = computed(() => !sourcePath.value.trim() ? (direction.value === 'upload' ? '请从共享文件中选择源文件' : '请输入设备源文件路径') : '')
const destinationError = computed(() => !destinationPath.value.trim() ? '请输入目标路径' : '')
const serviceLabel = computed(() => {
  const settings = workspace.transferSettings
  if (!settings?.service_running) return '按需自动启动'
  return `${settings.protocol.toUpperCase()} · :${settings.bound_port}`
})

watch(
  () => workspace.transferSettings,
  (settings) => {
    if (!settings) return
    settingsDraft.value = {
      protocol: settings.protocol,
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

watch(terminalEnvironment, () => {
  if (direction.value !== 'upload' || !sourcePath.value) return
  const name = sourcePath.value.split('/').pop() || 'target.bin'
  destinationPath.value = preferredTerminalEnvironment.value === 'linux'
    ? `/tmp/${name}`
    : `flash:/${name}`
  localError.value = ''
})

watch(
  () => workspace.transferPanelOpen,
  (open) => {
    if (!open) return
    void loadFiles()
    void workspace.loadTransferServiceLog()
    void workspace.refreshOperations()
  },
  { immediate: true }
)

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

function selectUploadFile(relativePath: string, name: string): void {
  direction.value = 'upload'
  sourcePath.value = relativePath
  destinationPath.value = preferredTerminalEnvironment.value === 'linux'
    ? `/tmp/${name}`
    : `flash:/${name}`
  localError.value = ''
}

async function chooseRoot(): Promise<void> {
  const selected = await window.desktopApi.chooseTransferRoot()
  if (selected) settingsDraft.value.root = selected
}

async function saveSettings(): Promise<void> {
  localError.value = ''
  if (!settingsDraft.value.root.trim()) {
    localError.value = '请选择共享目录。'
    return
  }
  const { password, ...settings } = settingsDraft.value
  const saved = await workspace.saveTransferSettings({
    ...settings,
    port: Math.max(0, Math.min(65535, Number(settings.port) || 0)),
    ...(passwordDirty.value && password ? { password } : {})
  })
  if (saved) await loadFiles()
}

async function startTransfer(): Promise<void> {
  localError.value = ''
  if (!activeSessionConnected.value) {
    localError.value = '请先打开并选中一个已连接终端。'
    return
  }
  if (sourceError.value || destinationError.value) {
    localError.value = sourceError.value || destinationError.value
    return
  }
  const started = await workspace.startManagedTransfer({
    direction: direction.value,
    source_path: sourcePath.value.trim(),
    destination_path: destinationPath.value.trim(),
    overwrite: overwrite.value,
    terminal_environment: terminalEnvironment.value
  })
  if (started) localError.value = ''
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

async function clearHistory(): Promise<void> {
  if (!window.confirm('清理所有已完成、失败、取消和中断的传输记录？')) return
  await workspace.clearTransferHistory()
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

function formatEta(seconds: number | null): string {
  if (seconds === null) return '计算中'
  if (seconds < 60) return `约 ${seconds} 秒`
  return `约 ${Math.ceil(seconds / 60)} 分钟`
}

function operationTitle(operation: OperationRecord): string {
  return String(operation.data.source_name || operation.data.source_path || '文件传输')
}

function operationStatus(operation: OperationRecord): string {
  const labels: Record<string, string> = {
    queued: operation.stage === 'paused' ? '已暂停' : `排队 #${operation.queue_position || 1}`,
    running: operation.stage === 'verifying' ? '校验中' : `${operation.progress_percent}%`,
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    interrupted: '已中断'
  }
  return labels[operation.status] || operation.status
}

function recoveryHint(operation: OperationRecord): string {
  const hints: Record<string, string> = {
    service_endpoint_unavailable: '无法确定设备可访问的本机地址。请填写“设备访问地址”，并确认它与设备管理网互通。',
    transfer_client_unavailable: `设备缺少 ${workspace.transferSettings?.protocol.toUpperCase() || 'FTP/SFTP'} 客户端。请安装客户端或切换传输协议。`,
    transfer_timeout: '设备未在超时前完成交互。请检查本机防火墙、端口放行、设备到本机的路由，以及终端是否停在正常提示符。',
    transfer_command_failed: '设备返回了非预期提示。请展开服务日志，并确认终端环境和设备路径类型选择正确。',
    transfer_verification_failed: '传输命令已结束，但设备端文件大小不匹配。请检查中间网络、磁盘空间后重试。',
    insufficient_space: '设备可用空间不足。请清理目标存储，或改用其他目标路径。',
    destination_exists: '目标文件已经存在。确认可覆盖后勾选“允许覆盖已存在文件”再重试。',
    session_unavailable: '原终端会话已断开。请重连并选中目标终端后重新提交任务。'
  }
  return hints[operation.error_code] || '请查看任务消息和文件服务日志；确认终端连接、协议、设备路径与网络可达性后重试。'
}

function openTransferDiagnostics(): void {
  advancedOpen.value = true
  logsOpen.value = true
  void workspace.loadTransferServiceLog()
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
        <section class="transfer-primary-grid">
          <div class="transfer-files-card">
            <header>
              <div><FolderOpen :size="14" /><strong>选择共享文件</strong><span>{{ workspace.transferFileTotal }}</span></div>
              <button class="icon-button" type="button" title="刷新文件" :disabled="workspace.transferFilesLoading" @click="loadFiles()"><RefreshCw :class="{ 'spinning-icon': workspace.transferFilesLoading }" :size="14" /></button>
            </header>
            <div class="transfer-file-tools">
              <label><Search :size="13" /><input v-model="fileQuery" aria-label="搜索共享文件" placeholder="搜索名称或路径" /></label>
              <select v-model="fileSort" aria-label="文件排序字段"><option value="name">名称</option><option value="size">大小</option><option value="modified">时间</option></select>
              <button class="icon-button" type="button" :title="fileOrder === 'asc' ? '当前升序' : '当前降序'" @click="fileOrder = fileOrder === 'asc' ? 'desc' : 'asc'"><ChevronDown :class="{ 'sort-desc': fileOrder === 'desc' }" :size="14" /></button>
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
              <div v-else-if="!workspace.transferFiles.length" class="transfer-empty transfer-empty-files"><FolderOpen :size="20" /><strong>没有匹配文件</strong><span>调整搜索条件或在高级设置中更换共享目录。</span></div>
              <button v-if="workspace.transferFileNextOffset !== null" class="transfer-load-more" type="button" :disabled="workspace.transferFilesLoading" @click="loadFiles(workspace.transferFileNextOffset || 0, true)">加载更多</button>
            </div>
          </div>

          <form class="transfer-run-card" data-testid="transfer-run" @submit.prevent="startTransfer">
            <header><div><strong>新建传输</strong><span>服务会在需要时自动启动</span></div><ShieldCheck :size="15" /></header>
            <div class="transfer-direction-tabs" role="tablist" aria-label="传输方向">
              <button type="button" role="tab" :aria-selected="direction === 'upload'" :class="{ active: direction === 'upload' }" @click="direction = 'upload'"><ArrowUpFromLine :size="14" />PC → 设备</button>
              <button type="button" role="tab" :aria-selected="direction === 'download'" :class="{ active: direction === 'download' }" @click="direction = 'download'"><ArrowDownToLine :size="14" />设备 → PC</button>
            </div>
            <label class="form-field transfer-environment-field">
              <span>终端环境 <em>{{ terminalEnvironmentHint }}</em></span>
              <select v-model="terminalEnvironment" data-testid="transfer-terminal-environment">
                <option value="auto">自动判断</option>
                <option value="linux">Linux Shell</option>
                <option value="vrp">Huawei VRP</option>
              </select>
            </label>
            <label class="form-field">
              <span>{{ direction === 'upload' ? '共享目录源文件' : '设备源文件' }}</span>
              <input v-model="sourcePath" data-testid="transfer-source" :readonly="direction === 'upload'" :placeholder="direction === 'upload' ? '从左侧选择文件' : devicePathPlaceholder" autocomplete="off" />
              <small v-if="sourceError && localError" class="field-error">{{ sourceError }}</small>
            </label>
            <label class="form-field">
              <span>{{ direction === 'upload' ? '设备目标路径' : '共享目录目标路径' }}</span>
              <input v-model="destinationPath" data-testid="transfer-destination" :placeholder="direction === 'upload' ? devicePathPlaceholder : '例如 downloads/backup.cfg'" autocomplete="off" />
              <small v-if="destinationError && localError" class="field-error">{{ destinationError }}</small>
            </label>
            <label class="transfer-write-toggle"><input v-model="overwrite" type="checkbox" />允许覆盖已存在文件</label>
            <p v-if="localError || workspace.error" class="transfer-error" role="alert">{{ localError || workspace.error }}</p>
            <p class="operation-readiness" :data-ready="activeSessionConnected && !sourceError && !destinationError"><i></i>{{ activeSessionConnected ? '提交后可在当前任务中查看实时进度' : '请先选择一个已连接终端' }}</p>
            <button class="primary-button transfer-start-button" data-testid="transfer-start" type="submit" :disabled="workspace.transferBusy || !activeSessionConnected || Boolean(sourceError) || Boolean(destinationError)"><LoaderCircle v-if="workspace.transferBusy" class="spinning-icon" :size="14" /><FileUp v-else :size="14" />加入传输队列</button>
          </form>
        </section>

        <section v-if="currentOperations.length" class="transfer-operation-card transfer-current-card" aria-live="polite">
          <header><div><strong>当前任务</strong><span>{{ currentOperations.length }} 项</span></div><span>同一终端串行，不同终端可并行</span></header>
          <div v-for="sessionId in pausedSessionIds" :key="sessionId" class="transfer-queue-paused"><Pause :size="14" /><span>手工输入已接管终端，剩余队列已暂停。</span><button class="secondary-button" type="button" @click="workspace.resumeTransferQueue(sessionId)"><Play :size="12" />继续队列</button></div>
          <div class="transfer-operation-list">
            <article v-for="operation in currentOperations" :key="operation.id" data-testid="transfer-operation" :data-status="operation.status">
              <span class="operation-direction"><ArrowUpFromLine v-if="operation.direction === 'upload'" :size="14" /><ArrowDownToLine v-else :size="14" /></span>
              <div class="operation-main">
                <div class="operation-title"><strong>{{ operationTitle(operation) }}</strong><small>{{ operation.message }}</small></div>
                <span v-if="operation.status === 'running' && operation.stage === 'transferring'" class="operation-progress"><i :style="{ width: `${operation.progress_percent}%` }"></i></span>
                <span v-else-if="operation.status === 'running'" class="operation-progress indeterminate"><i></i></span>
                <div class="operation-metrics">
                  <span v-if="operation.total_bytes">{{ formatBytes(operation.bytes_transferred) }} / {{ formatBytes(operation.total_bytes) }}</span>
                  <span v-if="operation.bytes_per_second">{{ formatBytes(operation.bytes_per_second) }}/s</span>
                  <span v-if="operation.status === 'running' && operation.stage === 'transferring'"><Clock3 :size="11" />{{ formatEta(operation.eta_seconds) }}</span>
                  <span v-if="operation.queue_position">队列位置 {{ operation.queue_position }}</span>
                </div>
              </div>
              <b>{{ operationStatus(operation) }}</b>
              <button v-if="operation.cancellable" class="icon-button" type="button" title="取消任务" @click="workspace.cancelOperation(operation.id)"><CircleStop :size="14" /></button>
            </article>
          </div>
        </section>

        <section v-if="latestFailedOperation" class="transfer-recovery-card" role="alert" data-testid="transfer-recovery">
          <TriangleAlert :size="17" />
          <div>
            <strong>最近一次传输未完成</strong>
            <span>{{ latestFailedOperation.message }}</span>
            <small>{{ recoveryHint(latestFailedOperation) }}</small>
            <code v-if="latestFailedOperation.error_code">{{ latestFailedOperation.error_code }}</code>
          </div>
          <div class="transfer-recovery-actions">
            <button class="secondary-button" type="button" @click="openTransferDiagnostics"><Settings2 :size="12" />检查设置与日志</button>
            <button class="secondary-button" type="button" :title="latestFailureSessionConnected ? '使用原终端会话重新执行' : '原终端会话未连接，请重连后重新提交任务'" :disabled="workspace.transferBusy || !latestFailureSessionConnected" @click="workspace.retryManagedTransfer(latestFailedOperation.id)"><RotateCcw :size="12" />重新预检并重试</button>
          </div>
        </section>

        <section class="transfer-collapsible" :data-open="historyOpen">
          <button class="transfer-section-toggle" type="button" :aria-expanded="historyOpen" @click="historyOpen = !historyOpen"><span><Clock3 :size="14" /><strong>传输历史</strong><em>{{ historyOperations.length }} 条</em></span><ChevronDown :size="15" /></button>
          <div v-if="historyOpen" class="transfer-collapsible-body">
            <div class="transfer-history-toolbar">
              <select v-model="historyFilter" aria-label="筛选传输历史"><option value="all">全部状态</option><option value="completed">已完成</option><option value="failed">失败</option><option value="cancelled">已取消</option><option value="interrupted">已中断</option></select>
              <button class="secondary-button danger-button" type="button" :disabled="!historyOperations.length || workspace.transferBusy" @click="clearHistory"><Trash2 :size="12" />清理历史</button>
            </div>
            <div class="transfer-operation-list transfer-history-list">
              <details v-for="operation in historyOperations" :key="operation.id" :data-status="operation.status">
                <summary><span class="operation-direction"><ArrowUpFromLine v-if="operation.direction === 'upload'" :size="13" /><ArrowDownToLine v-else :size="13" /></span><span><strong>{{ operationTitle(operation) }}</strong><small>{{ operation.message }}</small></span><b>{{ operationStatus(operation) }}</b><ChevronDown :size="13" /></summary>
                <div class="transfer-history-details"><span>源：{{ String(operation.data.source_path || '-') }}</span><span>目标：{{ String(operation.data.destination_path || '-') }}</span><span v-if="operation.total_bytes">大小：{{ formatBytes(operation.total_bytes) }}</span><span v-if="operation.error_code">错误码：{{ operation.error_code }}</span><button v-if="['failed', 'cancelled', 'interrupted'].includes(operation.status)" class="secondary-button" type="button" @click="workspace.retryManagedTransfer(operation.id)"><RotateCcw :size="12" />重新预检并重试</button></div>
              </details>
              <div v-if="!historyOperations.length" class="transfer-empty"><Clock3 :size="18" /><strong>暂无匹配记录</strong></div>
            </div>
          </div>
        </section>

        <section class="transfer-collapsible" :data-open="advancedOpen">
          <button class="transfer-section-toggle" type="button" :aria-expanded="advancedOpen" @click="advancedOpen = !advancedOpen"><span><Settings2 :size="14" /><strong>高级设置</strong><em>服务、共享目录与日志</em></span><ChevronDown :size="15" /></button>
          <div v-if="advancedOpen" class="transfer-collapsible-body">
            <form class="transfer-settings-card" data-testid="transfer-settings" :aria-busy="workspace.transferBusy" @submit.prevent="saveSettings">
              <header><div><Server :size="15" /><strong>本机文件服务</strong></div><span class="service-state" :data-running="workspace.transferSettings?.service_running"><i></i>{{ serviceLabel }}</span></header>
              <div class="transfer-settings-grid">
                <label class="form-field"><span>协议</span><select v-model="settingsDraft.protocol" :disabled="hasRunningTransfer"><option value="ftp">FTP</option><option value="sftp">SFTP</option></select></label>
                <label class="form-field"><span>监听地址</span><input v-model="settingsDraft.host" :disabled="hasRunningTransfer" autocomplete="off" /></label>
                <label class="form-field" title="留空时，根据当前终端的远端 IP 查询系统路由，选择该路由使用的本机 IP"><span class="transfer-setting-label">设备访问地址 <em>留空自动</em></span><input v-model="settingsDraft.advertised_host" :disabled="hasRunningTransfer" placeholder="自动：按当前终端路由选择" autocomplete="off" /></label>
                <label class="form-field"><span>端口（0=自动）</span><input v-model.number="settingsDraft.port" type="number" min="0" max="65535" :disabled="hasRunningTransfer" /></label>
                <label class="form-field"><span>登录账号</span><input v-model="settingsDraft.username" :disabled="hasRunningTransfer" autocomplete="off" /></label>
                <label class="form-field"><span class="transfer-password-label">登录密码 <em :data-set="workspace.transferSettings?.has_password">{{ workspace.transferSettings?.has_password ? '已安全保存' : '未设置' }}</em></span><span class="transfer-password-input"><input v-model="settingsDraft.password" :type="passwordVisible ? 'text' : 'password'" :placeholder="workspace.transferSettings?.has_password ? '留空保持现有密码' : '输入登录密码'" :disabled="hasRunningTransfer" autocomplete="new-password" @input="passwordDirty = true" /><button class="icon-button" type="button" :title="passwordVisible ? '隐藏密码' : '显示密码'" :aria-label="passwordVisible ? '隐藏登录密码' : '显示登录密码'" :aria-pressed="passwordVisible" :disabled="hasRunningTransfer" @click="passwordVisible = !passwordVisible"><EyeOff v-if="passwordVisible" :size="14" /><Eye v-else :size="14" /></button></span></label>
                <label class="form-field transfer-root-field"><span>共享目录</span><span class="transfer-root-input"><input v-model="settingsDraft.root" data-testid="transfer-root" readonly :disabled="hasRunningTransfer" /><button class="icon-button" type="button" title="选择共享目录" :disabled="hasRunningTransfer" @click="chooseRoot"><FolderOpen :size="15" /></button></span></label>
                <label class="transfer-write-toggle"><input v-model="settingsDraft.writable" type="checkbox" :disabled="hasRunningTransfer" />允许设备写入共享目录</label>
              </div>
              <footer><span><ShieldCheck :size="13" />托管任务使用独立临时身份，完成后立即撤销</span><button class="secondary-button" type="submit" :disabled="workspace.transferBusy || hasRunningTransfer"><Save :size="13" />保存设置</button><button :class="workspace.transferSettings?.service_running ? 'secondary-button danger-button' : 'secondary-button'" type="button" :disabled="workspace.transferBusy || hasRunningTransfer" @click="workspace.toggleTransferService"><CircleStop v-if="workspace.transferSettings?.service_running" :size="13" /><Play v-else :size="13" />{{ workspace.transferSettings?.service_running ? '立即停止' : '手动启动' }}</button></footer>
              <div class="transfer-client-hint" data-testid="transfer-client-command"><span><strong>手工客户端命令</strong><small>托管传输无需复制此命令。</small></span><code>{{ workspace.transferClientCommand || '保存设置后生成连接命令' }}</code><button class="icon-button" type="button" title="复制客户端命令" :disabled="!workspace.transferClientCommand" @click="copyClientCommand"><Copy :size="13" /></button></div>
            </form>

            <div class="transfer-log-disclosure" :data-open="logsOpen">
              <button type="button" :aria-expanded="logsOpen" @click="toggleLogs"><span><Server :size="13" />文件服务运行日志 <em>{{ workspace.transferServiceLog.length }} 条</em></span><ChevronDown :size="14" /></button>
              <div v-if="logsOpen" class="transfer-service-log-card" data-testid="transfer-service-log"><header><span>仅显示服务状态和连接事件，不记录临时凭据。</span><div><button class="icon-button" type="button" title="刷新日志" @click="workspace.loadTransferServiceLog"><RefreshCw :size="13" /></button><button class="icon-button" type="button" title="复制日志" :disabled="!workspace.transferServiceLog.length" @click="copyServiceLog"><Copy :size="13" /></button><button class="icon-button" type="button" title="清空日志" :disabled="!workspace.transferServiceLog.length" @click="workspace.clearTransferServiceLog"><Trash2 :size="13" /></button></div></header><pre>{{ workspace.transferServiceLog.join('\n') || '暂无服务日志。' }}</pre></div>
            </div>
          </div>
        </section>
      </div>
    </aside>
  </div>
</template>
