<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  ArrowDownToLine,
  ArrowUpFromLine,
  CircleStop,
  Copy,
  File,
  FileUp,
  FolderOpen,
  Play,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Trash2,
  X
} from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import type { TransferSettings } from '../types'

const workspace = useWorkspaceStore()
const direction = ref<'upload' | 'download'>('upload')
const sourcePath = ref('')
const destinationPath = ref('')
const overwrite = ref(false)
const localError = ref('')
const settingsDraft = ref<Pick<TransferSettings, 'protocol' | 'host' | 'port' | 'root' | 'username' | 'writable'>>({
  protocol: 'ftp',
  host: '0.0.0.0',
  port: 0,
  root: '',
  username: 'device',
  writable: true
})
let pollingTimer: ReturnType<typeof setInterval> | null = null

const activeOperations = computed(() =>
  workspace.operations.filter((operation) => operation.status === 'running')
)

watch(
  () => workspace.transferSettings,
  (settings) => {
    if (!settings) return
    settingsDraft.value = {
      protocol: settings.protocol,
      host: settings.host,
      port: settings.port,
      root: settings.root,
      username: settings.username,
      writable: settings.writable
    }
  },
  { immediate: true, deep: true }
)

watch(direction, (next) => {
  sourcePath.value = ''
  destinationPath.value = next === 'upload' ? 'flash:/' : ''
  localError.value = ''
})

watch(
  () => workspace.transferPanelOpen,
  (open) => {
    if (pollingTimer) clearInterval(pollingTimer)
    pollingTimer = null
    if (!open) return
    void workspace.loadTransferFiles()
    void workspace.loadTransferServiceLog()
    void workspace.refreshOperations()
    pollingTimer = setInterval(() => {
      void workspace.refreshOperations()
      void workspace.loadTransferServiceLog()
    }, 1_000)
  },
  { immediate: true }
)

function selectUploadFile(relativePath: string, name: string): void {
  direction.value = 'upload'
  sourcePath.value = relativePath
  destinationPath.value = `flash:/${name}`
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
  await workspace.saveTransferSettings({
    ...settingsDraft.value,
    port: Math.max(0, Math.min(65535, Number(settingsDraft.value.port) || 0))
  })
}

async function startTransfer(): Promise<void> {
  localError.value = ''
  if (!workspace.activeSession) {
    localError.value = '请先打开并选中一个已连接终端。'
    return
  }
  if (!sourcePath.value.trim() || !destinationPath.value.trim()) {
    localError.value = '请填写源路径和目标路径。'
    return
  }
  const started = await workspace.startManagedTransfer({
    direction: direction.value,
    source_path: sourcePath.value.trim(),
    destination_path: destinationPath.value.trim(),
    overwrite: overwrite.value
  })
  if (started) await workspace.refreshOperations()
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

function formatBytes(value: unknown): string {
  const bytes = Number(value) || 0
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

onBeforeUnmount(() => {
  if (pollingTimer) clearInterval(pollingTimer)
})
</script>

<template>
  <div
    v-if="workspace.transferPanelOpen"
    class="transfer-backdrop"
    @mousedown.self="workspace.transferPanelOpen = false"
  >
    <aside class="transfer-workspace" role="region" aria-labelledby="transfer-title">
      <header class="transfer-header">
        <div class="transfer-heading">
          <span class="transfer-icon"><FileUp :size="18" /></span>
          <div>
            <p class="eyebrow">MANAGED OPERATION</p>
            <h2 id="transfer-title">托管文件传输</h2>
          </div>
        </div>
        <div class="transfer-header-actions">
          <span v-if="activeOperations.length">{{ activeOperations.length }} 项运行中</span>
          <button class="icon-button" type="button" aria-label="关闭文件传输" @click="workspace.transferPanelOpen = false">
            <X :size="16" />
          </button>
        </div>
      </header>

      <div class="transfer-body">
        <form class="transfer-settings-card" data-testid="transfer-settings" @submit.prevent="saveSettings">
          <header>
            <div><Server :size="15" /><strong>本机文件服务</strong></div>
            <span class="service-state" :data-running="workspace.transferSettings?.service_running">
              <i></i>{{ workspace.transferSettings?.service_running ? `${workspace.transferSettings.protocol.toUpperCase()} :${workspace.transferSettings.bound_port}` : '未运行' }}
            </span>
          </header>
          <div class="transfer-settings-grid">
            <label class="form-field">
              <span>协议</span>
              <select v-model="settingsDraft.protocol" :disabled="workspace.transferSettings?.service_running">
                <option value="ftp">FTP</option>
                <option value="sftp">SFTP</option>
              </select>
            </label>
            <label class="form-field">
              <span>监听地址</span>
              <input v-model="settingsDraft.host" :disabled="workspace.transferSettings?.service_running" autocomplete="off" />
            </label>
            <label class="form-field">
              <span>端口（0=自动）</span>
              <input v-model.number="settingsDraft.port" type="number" min="0" max="65535" :disabled="workspace.transferSettings?.service_running" />
            </label>
            <label class="form-field">
              <span>服务用户</span>
              <input v-model="settingsDraft.username" :disabled="workspace.transferSettings?.service_running" autocomplete="off" />
            </label>
            <label class="form-field transfer-root-field">
              <span>共享目录</span>
              <span class="transfer-root-input">
                <input v-model="settingsDraft.root" data-testid="transfer-root" readonly :disabled="workspace.transferSettings?.service_running" />
                <button class="icon-button" type="button" title="选择共享目录" :disabled="workspace.transferSettings?.service_running" @click="chooseRoot">
                  <FolderOpen :size="15" />
                </button>
              </span>
            </label>
            <label class="transfer-write-toggle">
              <input v-model="settingsDraft.writable" type="checkbox" :disabled="workspace.transferSettings?.service_running" />允许设备写入共享目录
            </label>
          </div>
          <footer>
            <span><ShieldCheck :size="13" />服务密码由系统凭据库生成并保管</span>
            <button class="secondary-button" type="submit" :disabled="workspace.transferBusy || workspace.transferSettings?.service_running">
              <Save :size="13" />保存设置
            </button>
            <button class="primary-button" type="button" :disabled="workspace.transferBusy" @click="workspace.toggleTransferService">
              <CircleStop v-if="workspace.transferSettings?.service_running" :size="13" />
              <Play v-else :size="13" />
              {{ workspace.transferSettings?.service_running ? '停止服务' : '启动服务' }}
            </button>
          </footer>
          <div class="transfer-client-hint" data-testid="transfer-client-command">
            <span><strong>设备侧客户端命令</strong><small>命令不包含服务密码；监听全部地址时请替换本机 IP。</small></span>
            <code>{{ workspace.transferClientCommand || '保存设置后生成连接命令' }}</code>
            <button class="icon-button" type="button" title="复制客户端命令" :disabled="!workspace.transferClientCommand" @click="copyClientCommand"><Copy :size="13" /></button>
          </div>
        </form>

        <section class="transfer-content-grid">
          <div class="transfer-files-card">
            <header>
              <div><FolderOpen :size="14" /><strong>共享文件</strong><span>{{ workspace.transferFiles.length }}</span></div>
              <button class="icon-button" type="button" title="刷新文件" @click="workspace.loadTransferFiles"><RefreshCw :size="14" /></button>
            </header>
            <div class="transfer-file-list">
              <button
                v-for="file in workspace.transferFiles"
                :key="file.relative_path"
                data-testid="transfer-file"
                type="button"
                :class="{ selected: direction === 'upload' && sourcePath === file.relative_path }"
                @click="selectUploadFile(file.relative_path, file.name)"
              >
                <File :size="14" />
                <span><strong>{{ file.name }}</strong><small>{{ file.relative_path }}</small></span>
                <b>{{ formatBytes(file.size_bytes) }}</b>
              </button>
              <p v-if="!workspace.transferFiles.length" class="transfer-empty">共享目录中没有文件。</p>
            </div>
          </div>

          <form class="transfer-run-card" data-testid="transfer-run" @submit.prevent="startTransfer">
            <header><strong>新建传输</strong><span>{{ workspace.activeSession?.title || '未选择终端' }}</span></header>
            <div class="transfer-direction-tabs" role="tablist">
              <button type="button" :class="{ active: direction === 'upload' }" @click="direction = 'upload'">
                <ArrowUpFromLine :size="14" />PC → 设备
              </button>
              <button type="button" :class="{ active: direction === 'download' }" @click="direction = 'download'">
                <ArrowDownToLine :size="14" />设备 → PC
              </button>
            </div>
            <label class="form-field">
              <span>{{ direction === 'upload' ? '共享目录源文件' : '设备源文件' }}</span>
              <input v-model="sourcePath" data-testid="transfer-source" :readonly="direction === 'upload'" :placeholder="direction === 'upload' ? '从左侧选择文件' : '例如 flash:/backup.cfg'" autocomplete="off" />
            </label>
            <label class="form-field">
              <span>{{ direction === 'upload' ? '设备目标路径' : '共享目录目标路径' }}</span>
              <input v-model="destinationPath" data-testid="transfer-destination" :placeholder="direction === 'upload' ? '例如 flash:/target.cc' : '例如 downloads/backup.cfg'" autocomplete="off" />
            </label>
            <label class="transfer-write-toggle"><input v-model="overwrite" type="checkbox" />允许覆盖已存在文件</label>
            <p v-if="localError || workspace.error" class="transfer-error" role="alert">{{ localError || workspace.error }}</p>
            <button class="primary-button" data-testid="transfer-start" type="submit" :disabled="workspace.transferBusy || !workspace.activeSession">
              <FileUp :size="14" />开始托管传输
            </button>
          </form>
        </section>

        <section class="transfer-service-log-card" data-testid="transfer-service-log">
          <header>
            <div><Server :size="14" /><strong>文件服务运行日志</strong><span>{{ workspace.transferServiceLog.length }} 条</span></div>
            <div>
              <button class="icon-button" type="button" title="刷新服务日志" @click="workspace.loadTransferServiceLog"><RefreshCw :size="13" /></button>
              <button class="icon-button" type="button" title="复制服务日志" :disabled="!workspace.transferServiceLog.length" @click="copyServiceLog"><Copy :size="13" /></button>
              <button class="icon-button" type="button" title="清空服务日志" :disabled="!workspace.transferServiceLog.length" @click="workspace.clearTransferServiceLog"><Trash2 :size="13" /></button>
            </div>
          </header>
          <pre>{{ workspace.transferServiceLog.join('\n') || '服务启动、登录、上传和下载事件会显示在这里。' }}</pre>
        </section>

        <section class="transfer-operation-card">
          <header><strong>操作记录</strong><span>手工终端输入会优先接管并取消当前操作</span></header>
          <div class="transfer-operation-list">
            <article v-for="operation in workspace.operations" :key="operation.id" data-testid="transfer-operation" :data-status="operation.status">
              <span class="operation-direction">
                <ArrowUpFromLine v-if="operation.direction === 'upload'" :size="14" />
                <ArrowDownToLine v-else :size="14" />
              </span>
              <div>
                <strong>{{ String(operation.data.source_name || operation.data.source_path || operation.kind) }}</strong>
                <small>{{ operation.stage }} · {{ operation.message }}</small>
                <span class="operation-progress"><i :style="{ width: `${operation.progress_percent}%` }"></i></span>
              </div>
              <b>{{ operation.status === 'running' ? `${operation.progress_percent}%` : operation.status }}</b>
              <button
                v-if="operation.cancellable"
                class="icon-button"
                type="button"
                title="取消操作"
                @click="workspace.cancelOperation(operation.id)"
              ><CircleStop :size="14" /></button>
            </article>
            <p v-if="!workspace.operations.length" class="transfer-empty">暂无文件传输记录。</p>
          </div>
        </section>
      </div>
    </aside>
  </div>
</template>
