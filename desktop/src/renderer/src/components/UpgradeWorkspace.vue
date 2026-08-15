<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  Box,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleStop,
  Clipboard,
  Code2,
  FileArchive,
  FolderCog,
  HardDrive,
  RefreshCw,
  RotateCw,
  Send,
  ServerCog,
  ShieldAlert,
  X
} from 'lucide-vue-next'
import { useWorkspaceStore } from '../stores/workspace'
import { desktopApi } from '../transport/api'

const workspace = useWorkspaceStore()
const packagePath = ref('')
const includeSlave = ref(true)
const autoDelete = ref(true)
const requestReboot = ref(false)
const localError = ref('')
const manualOpen = ref(false)
const manualTerminalText = ref('')
const manualTerminalTruncated = ref(false)
const manualScript = ref('')
const manualNotes = ref<string[]>([])
const manualBusy = ref(false)
const manualConfirmed = ref(false)
let pollingTimer: ReturnType<typeof setInterval> | null = null

const packageFiles = computed(() =>
  workspace.transferFiles.filter((file) => file.name.toLocaleLowerCase().endsWith('.cc'))
)
const currentOperation = computed(() =>
  workspace.upgradeOperations.find((operation) =>
    operation.status === 'running' || operation.status === 'waiting_approval'
  ) || workspace.upgradeOperations[0] || null
)
const activeSessionConnected = computed(() => workspace.activeSession?.status === 'connected')
const upgradeActionHint = computed(() => {
  if (!workspace.activeSession) return '请先打开并选择一个终端会话'
  if (!activeSessionConnected.value) return '当前终端未连接，请先重连终端'
  if (!packagePath.value) return '请先从上方列表选择一个 .cc 系统包'
  return '已具备预检条件，提交后不会立即重启设备'
})
const upgradeErrorMessage = computed(() => {
  const message = localError.value || workspace.error
  if (/terminal session is not connected/i.test(message)) return ''
  if (/no connected terminal session is available/i.test(message)) return ''
  return message
})
const stages = [
  ['prechecking', '安全预检', 5],
  ['cleanup', '空间清理', 20],
  ['downloading', '下载主控', 38],
  ['verifying', '核对主控', 62],
  ['synchronizing', '同步备控', 72],
  ['setting_startup', '设置启动项', 86],
  ['reboot_approval', '重启批准', 95],
  ['completed', '完成', 100]
] as const

watch(
  packageFiles,
  (files) => {
    if (!files.some((file) => file.relative_path === packagePath.value)) {
      packagePath.value = files[0]?.relative_path || ''
    }
  },
  { immediate: true }
)

watch(
  () => workspace.upgradePanelOpen,
  (open) => {
    if (pollingTimer) clearInterval(pollingTimer)
    pollingTimer = null
    if (!open) return
    void workspace.refreshUpgradeOperations()
    pollingTimer = setInterval(() => {
      void workspace.refreshUpgradeOperations()
    }, 1_000)
  },
  { immediate: true }
)

watch(
  () => workspace.activeSessionId,
  () => {
    manualTerminalText.value = ''
    manualTerminalTruncated.value = false
    manualScript.value = ''
    manualNotes.value = []
    manualConfirmed.value = false
  }
)

watch(manualScript, () => {
  manualConfirmed.value = false
})

function selectPackage(relativePath: string): void {
  packagePath.value = relativePath
  localError.value = ''
}

async function startUpgrade(): Promise<void> {
  localError.value = ''
  if (!workspace.activeSession) {
    localError.value = '请先打开并选中一个已连接终端。'
    return
  }
  if (!packagePath.value) {
    localError.value = '共享目录中没有可用的 .cc 系统包。'
    return
  }
  await workspace.startPackageUpgrade({
    package_path: packagePath.value,
    include_slave: includeSlave.value,
    auto_delete_old_packages: autoDelete.value,
    reboot_after_setting: requestReboot.value
  })
}

async function readManualTerminal(): Promise<void> {
  localError.value = ''
  workspace.notice = ''
  if (!workspace.activeSessionId) {
    localError.value = '请先打开并选中一个终端会话。'
    return
  }
  manualBusy.value = true
  try {
    const response = await desktopApi.packageUpgradeManualTerminal(workspace.activeSessionId)
    manualTerminalText.value = response.content
    manualTerminalTruncated.value = response.truncated
    workspace.notice = response.content
      ? (response.truncated ? '已读取终端尾部内容，较早输出已截断。' : '已读取当前终端内容。')
      : '当前终端暂无可读取内容。'
  } catch (cause) {
    localError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    manualBusy.value = false
  }
}

async function generateManualScript(): Promise<void> {
  localError.value = ''
  workspace.notice = ''
  if (!workspace.activeSessionId) {
    localError.value = '请先打开并选中一个终端会话。'
    return
  }
  if (!packagePath.value) {
    localError.value = '请先从共享目录选择一个 .cc 系统包。'
    return
  }
  manualBusy.value = true
  try {
    const response = await desktopApi.generatePackageUpgradeManualPlan({
      session_id: workspace.activeSessionId,
      package_path: packagePath.value,
      startup_output: manualTerminalText.value,
      master_dir_output: manualTerminalText.value,
      slave_dir_output: manualTerminalText.value,
      include_slave: includeSlave.value,
      auto_delete_old_packages: autoDelete.value,
      reboot_after_setting: requestReboot.value,
      master_storage: 'flash:/',
      slave_storage: 'slave#flash:/'
    })
    manualScript.value = response.script
    manualNotes.value = response.notes
    workspace.notice = `已生成 ${response.package_name} 的安全脚本；密码保留为 Python 占位符。`
  } catch (cause) {
    localError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    manualBusy.value = false
  }
}

async function copyManualScript(): Promise<void> {
  if (!manualScript.value) return
  try {
    await navigator.clipboard.writeText(manualScript.value)
    workspace.notice = '已复制脚本；复制内容不包含文件服务明文密码。'
  } catch (cause) {
    localError.value = cause instanceof Error ? cause.message : String(cause)
  }
}

async function sendManualScript(): Promise<void> {
  localError.value = ''
  workspace.notice = ''
  if (!workspace.activeSessionId || !manualScript.value.trim()) return
  if (!manualConfirmed.value) {
    localError.value = '请先确认已检查脚本和目标终端。'
    return
  }
  manualBusy.value = true
  try {
    const response = await desktopApi.sendPackageUpgradeManualScript({
      session_id: workspace.activeSessionId,
      script: manualScript.value,
      interval_ms: 900
    })
    workspace.notice = `已向当前终端发送 ${response.command_count} 条命令。`
    manualConfirmed.value = false
  } catch (cause) {
    localError.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    manualBusy.value = false
  }
}

function manageTransferRoot(): void {
  workspace.upgradePanelOpen = false
  workspace.transferPanelOpen = true
}

function stageState(threshold: number): string {
  const operation = currentOperation.value
  if (!operation) return 'pending'
  if (operation.status === 'failed' && operation.progress_percent < threshold) return 'pending'
  if (operation.progress_percent >= threshold) return 'completed'
  return operation.status === 'running' || operation.status === 'waiting_approval'
    ? 'active'
    : 'pending'
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

onBeforeUnmount(() => {
  if (pollingTimer) clearInterval(pollingTimer)
})
</script>

<template>
  <div
    v-if="workspace.upgradePanelOpen"
    class="upgrade-backdrop"
    @mousedown.self="workspace.upgradePanelOpen = false"
  >
    <aside class="upgrade-workspace" role="region" aria-labelledby="upgrade-title">
      <header class="upgrade-header">
        <div class="upgrade-heading">
          <span class="upgrade-icon"><Box :size="18" /></span>
          <div>
            <p class="eyebrow">VERIFIED OPERATION</p>
            <h2 id="upgrade-title">系统包升级</h2>
          </div>
        </div>
        <div class="upgrade-header-actions">
          <span>{{ workspace.activeSession?.title || '未选择终端' }}</span>
          <button class="icon-button" type="button" aria-label="关闭升级任务" @click="workspace.upgradePanelOpen = false"><X :size="16" /></button>
        </div>
      </header>

      <div class="upgrade-body">
        <section class="upgrade-safety-banner">
          <ShieldAlert :size="17" />
          <div>
            <strong>后端托管安全流程</strong>
            <span>保护当前/下次启动包；源文件、空间、主备字节数和最终启动项必须全部确认。</span>
          </div>
          <button class="secondary-button" type="button" @click="manageTransferRoot"><FolderCog :size="13" />文件服务设置</button>
        </section>

        <section class="upgrade-main-grid">
          <div class="upgrade-package-card">
            <header>
              <div><FileArchive :size="15" /><strong>选择系统包</strong><span>{{ packageFiles.length }} 个 .cc</span></div>
              <button class="icon-button" type="button" title="刷新系统包" @click="workspace.refreshUpgradeOperations"><RefreshCw :size="14" /></button>
            </header>
            <div class="upgrade-package-list">
              <button
                v-for="file in packageFiles"
                :key="file.relative_path"
                data-testid="upgrade-package"
                type="button"
                :class="{ selected: packagePath === file.relative_path }"
                @click="selectPackage(file.relative_path)"
              >
                <FileArchive :size="15" />
                <span><strong>{{ file.name }}</strong><small>{{ file.relative_path }}</small></span>
                <b>{{ formatBytes(file.size_bytes) }}</b>
              </button>
              <div v-if="!packageFiles.length" class="upgrade-empty">
                <FileArchive :size="20" />
                <strong>没有可用系统包</strong>
                <span>请先在文件服务共享目录中放入 .cc 文件，然后刷新列表。</span>
              </div>
            </div>
          </div>

          <form class="upgrade-config-card" data-testid="upgrade-form" @submit.prevent="startUpgrade">
            <header><ServerCog :size="15" /><strong>升级策略</strong></header>
            <div class="upgrade-target">
              <HardDrive :size="16" />
              <span><strong>{{ workspace.activeSession?.title || '未选择终端' }}</strong><small>{{ workspace.activeSession?.device_id || '请先建立终端会话' }}</small></span>
            </div>
            <label class="upgrade-option"><input v-model="includeSlave" type="checkbox" /><span><strong>自动探测备控</strong><small>备控不存在时安全降级为单主控</small></span></label>
            <label class="upgrade-option"><input v-model="autoDelete" type="checkbox" /><span><strong>安全清理旧包</strong><small>绝不删除当前、下次和目标系统包</small></span></label>
            <label class="upgrade-option"><input v-model="requestReboot" data-testid="upgrade-reboot" type="checkbox" /><span><strong>完成后请求重启</strong><small>设置启动项后仍需人工批准</small></span></label>
            <p v-if="upgradeErrorMessage" class="upgrade-error" role="alert">{{ upgradeErrorMessage }}</p>
            <p class="operation-readiness" :data-ready="activeSessionConnected && Boolean(packagePath)">
              <i aria-hidden="true"></i>{{ upgradeActionHint }}
            </p>
            <button class="primary-button upgrade-start-button" data-testid="upgrade-start" type="submit" :disabled="workspace.upgradeBusy || !activeSessionConnected || !packagePath">
              <RotateCw :size="14" />开始验证升级
            </button>
          </form>
        </section>

        <section class="upgrade-manual-card" data-testid="upgrade-manual-fallback">
          <button
            class="upgrade-manual-toggle"
            type="button"
            :aria-expanded="manualOpen"
            aria-controls="upgrade-manual-content"
            @click="manualOpen = !manualOpen"
          >
            <span><Code2 :size="15" /><strong>手动脚本兜底</strong><small>读取终端 · 生成 · 编辑 · 复制 · 发送</small></span>
            <ChevronUp v-if="manualOpen" :size="15" />
            <ChevronDown v-else :size="15" />
          </button>
          <div v-if="manualOpen" id="upgrade-manual-content" class="upgrade-manual-content">
            <div class="upgrade-manual-security" role="note">
              <ShieldAlert :size="15" />
              <span><strong>密码不会进入界面</strong><small>脚本仅显示 <code v-pre>{{file_transfer.password}}</code>；发送时由 Python 从系统凭据库解析并过滤终端回显。</small></span>
            </div>
            <div class="upgrade-manual-grid">
              <label class="upgrade-manual-field">
                <span><strong>终端预检文本</strong><small v-if="manualTerminalTruncated">仅包含日志尾部</small></span>
                <textarea
                  v-model="manualTerminalText"
                  data-testid="upgrade-manual-terminal"
                  spellcheck="false"
                  placeholder="读取当前终端，或粘贴 display startup / dir 输出"
                ></textarea>
              </label>
              <label class="upgrade-manual-field upgrade-manual-script-field">
                <span><strong>可编辑升级脚本</strong><small>以 # 开头的说明行不会发送</small></span>
                <textarea
                  v-model="manualScript"
                  data-testid="upgrade-manual-script"
                  spellcheck="false"
                  placeholder="读取终端并生成安全脚本后，可在发送前人工调整"
                ></textarea>
              </label>
            </div>
            <ul v-if="manualNotes.length" class="upgrade-manual-notes">
              <li v-for="note in manualNotes" :key="note">{{ note }}</li>
            </ul>
            <div class="upgrade-manual-actions">
              <button class="secondary-button" data-testid="upgrade-manual-read" type="button" :disabled="manualBusy || !workspace.activeSessionId" @click="readManualTerminal">
                <RefreshCw :size="13" />读取当前终端
              </button>
              <button class="secondary-button" data-testid="upgrade-manual-generate" type="button" :disabled="manualBusy || !workspace.activeSessionId || !packagePath" @click="generateManualScript">
                <Code2 :size="13" />生成脚本
              </button>
              <button class="secondary-button" data-testid="upgrade-manual-copy" type="button" :disabled="!manualScript" @click="copyManualScript">
                <Clipboard :size="13" />复制脚本
              </button>
              <label class="upgrade-manual-confirm"><input v-model="manualConfirmed" data-testid="upgrade-manual-confirm" type="checkbox" :disabled="!manualScript" />已检查脚本与目标终端</label>
              <button class="primary-button" data-testid="upgrade-manual-send" type="button" :disabled="manualBusy || !manualConfirmed || !manualScript || !workspace.activeSessionId" @click="sendManualScript">
                <Send :size="13" />发送脚本
              </button>
            </div>
          </div>
        </section>

        <section class="upgrade-pipeline-card">
          <header>
            <strong>执行流水线</strong>
            <span v-if="currentOperation">{{ currentOperation.progress_percent }}% · {{ currentOperation.message }}</span>
            <span v-else>等待任务</span>
          </header>
          <div class="upgrade-stage-list">
            <div v-for="([key, label, threshold], index) in stages" :key="key" :data-state="stageState(threshold)">
              <span><CheckCircle2 :size="14" /></span>
              <strong>{{ label }}</strong>
              <i v-if="index < stages.length - 1"></i>
            </div>
          </div>
          <div v-if="currentOperation" class="upgrade-current-operation" data-testid="upgrade-operation" :data-status="currentOperation.status">
            <div>
              <strong>{{ String(currentOperation.data.package_name || '系统包升级') }}</strong>
              <span>{{ currentOperation.stage }} · {{ currentOperation.message }}</span>
            </div>
            <span class="operation-progress"><i :style="{ width: `${currentOperation.progress_percent}%` }"></i></span>
            <button
              v-if="currentOperation.status === 'waiting_approval'"
              class="primary-button"
              data-testid="upgrade-approve"
              type="button"
              @click="workspace.approvePackageUpgrade(currentOperation.id)"
            ><RotateCw :size="13" />批准重启</button>
            <button
              v-else-if="currentOperation.cancellable"
              class="secondary-button"
              type="button"
              @click="workspace.cancelOperation(currentOperation.id)"
            ><CircleStop :size="13" />取消任务</button>
          </div>
        </section>

        <section class="upgrade-history-card">
          <header><strong>升级记录</strong><span>仅展示安全元数据，不包含本机绝对路径或文件服务凭据</span></header>
          <div>
            <article v-for="operation in workspace.upgradeOperations" :key="operation.id" :data-status="operation.status">
              <span><Box :size="14" /></span>
              <div><strong>{{ String(operation.data.package_name || '系统包') }}</strong><small>{{ operation.message }}</small></div>
              <b>{{ operation.status }}</b>
            </article>
            <div v-if="!workspace.upgradeOperations.length" class="upgrade-empty">
              <Box :size="19" />
              <strong>暂无升级记录</strong>
              <span>完成安全预检并启动升级后，执行结果会显示在这里。</span>
            </div>
          </div>
        </section>
      </div>
    </aside>
  </div>
</template>
