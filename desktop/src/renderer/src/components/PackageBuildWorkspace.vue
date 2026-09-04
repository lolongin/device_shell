<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CircleStop, FileArchive, LoaderCircle, Play, RefreshCw, X } from 'lucide-vue-next'
import { desktopApi } from '../transport/api'
import type { OperationRecord, PackageBuilder } from '../types'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const builders = ref<PackageBuilder[]>([])
const builderId = ref('internal-vrp')
const mrid = ref('')
const packageType = ref('system')
const model = ref('')
const vrpVersion = ref('')
const outputName = ref('')
const operation = ref<OperationRecord | null>(null)
const error = ref('')
const loading = ref(false)
let refreshTimer: ReturnType<typeof setInterval> | null = null

const running = computed(() => Boolean(operation.value && ['queued', 'running'].includes(operation.value.status)))
const canStart = computed(() => !running.value && !loading.value && Boolean(mrid.value.trim()))
const progress = computed(() => Math.max(0, Math.min(100, operation.value?.progress_percent || 0)))
const selectedBuilder = computed(() => builders.value.find((item) => item.id === builderId.value) || null)

async function loadBuilders(): Promise<void> {
  try {
    const response = await desktopApi.packageBuilders()
    builders.value = response.builders
    if (!builders.value.some((item) => item.id === builderId.value)) {
      builderId.value = builders.value[0]?.id || ''
    }
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}

onMounted(() => { void loadBuilders() })

onBeforeUnmount(() => stopPolling())

function stopPolling(): void {
  if (refreshTimer) clearInterval(refreshTimer)
  refreshTimer = null
}

function startPolling(id: string): void {
  stopPolling()
  refreshTimer = setInterval(() => { void refreshOperation(id) }, 1000)
}

async function refreshOperation(id: string): Promise<void> {
  try {
    const response = await desktopApi.packageBuild(id)
    operation.value = response.operation
    if (!['queued', 'running'].includes(response.operation.status)) stopPolling()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
    stopPolling()
  }
}

async function startBuild(): Promise<void> {
  if (!canStart.value) return
  error.value = ''
  loading.value = true
  try {
    const response = await desktopApi.startPackageBuild({
      builder_id: builderId.value,
      mrid: mrid.value.trim(),
      package_type: packageType.value,
      model: model.value.trim(),
      vrp_version: vrpVersion.value.trim(),
      output_name: outputName.value.trim()
    })
    operation.value = response.operation
    startPolling(response.operation.id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    loading.value = false
  }
}

async function cancelBuild(): Promise<void> {
  const id = operation.value?.id
  if (!id) return
  try {
    const response = await desktopApi.cancelPackageBuild(id)
    operation.value = response.operation
    stopPolling()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }
}
</script>

<template>
  <div class="package-build-backdrop">
    <aside class="package-build-workspace" role="region" aria-label="VRP 编包">
      <header class="package-build-header">
        <div class="package-build-title">
          <div class="package-build-kicker"><FileArchive :size="15" /> BUILD</div>
          <h2>VRP 系统包</h2>
          <p>调用已安装的内部编包 CLI 生成系统包。</p>
        </div>
        <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="workspace.packageBuildPanelOpen = false">
          <X :size="17" />
        </button>
      </header>

      <div class="package-build-body">
        <section class="package-build-target">
          <div class="package-build-target-icon"><FileArchive :size="15" /></div>
          <div><strong>{{ selectedBuilder?.label || '未发现编包器' }}</strong><span>{{ selectedBuilder?.version ? `v${selectedBuilder.version} · ${selectedBuilder.package_types.join(' / ')}` : '请配置内部 VRP 编包 CLI' }}</span></div>
        </section>

        <form class="package-build-form" @submit.prevent="startBuild">
          <label>编包器
            <select v-model="builderId" :disabled="running || loading">
              <option v-for="builder in builders" :key="builder.id" :value="builder.id">{{ builder.label }}</option>
            </select>
          </label>
          <label>MRID<input v-model="mrid" required maxlength="255" :disabled="running || loading" placeholder="输入 MRID" /></label>
          <div class="package-build-grid">
            <label>包类型<select v-model="packageType" :disabled="running || loading"><option value="system">系统包</option><option value="patch">补丁包</option></select></label>
            <label>型号<input v-model="model" maxlength="160" :disabled="running || loading" placeholder="例如 S5735" /></label>
          </div>
          <div class="package-build-grid">
            <label>VRP 版本<input v-model="vrpVersion" maxlength="160" :disabled="running || loading" placeholder="例如 V200R023C00" /></label>
            <label>输出文件名<input v-model="outputName" maxlength="255" :disabled="running || loading" placeholder="自动生成" /></label>
          </div>
          <p v-if="error" class="package-build-error">{{ error }}</p>
          <div class="package-build-actions">
            <button class="primary-action" type="submit" :disabled="!canStart"><LoaderCircle v-if="loading" class="spin" :size="16" /><Play v-else :size="16" />开始编包</button>
            <button v-if="running" class="secondary-action" type="button" @click="cancelBuild"><CircleStop :size="16" />取消</button>
            <button v-else class="secondary-action" type="button" title="刷新编包器列表" @click="loadBuilders"><RefreshCw :size="16" />刷新</button>
          </div>
        </form>

        <section v-if="operation" class="package-build-status" aria-live="polite">
          <div class="package-build-status-head"><strong>{{ operation.message }}</strong><span>{{ progress }}%</span></div>
          <div class="package-build-progress"><span :style="{ width: `${progress}%` }"></span></div>
          <div class="package-build-meta"><span>{{ operation.stage }}</span><span>{{ operation.status }}</span></div>
          <dl v-if="operation.status === 'completed'" class="package-build-result">
            <div><dt>产物</dt><dd>{{ operation.data.artifact_name || '' }}</dd></div>
            <div><dt>SHA-256</dt><dd>{{ operation.data.sha256 || '' }}</dd></div>
          </dl>
        </section>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.package-build-backdrop { position: relative; z-index: 18; grid-column: 2; grid-row: 1; min-width: 0; min-height: 0; height: 100%; overflow: hidden; background: transparent; }
.package-build-workspace { width: 100%; height: 100%; min-width: 0; display: grid; grid-template-rows: 72px minmax(0, 1fr); overflow: hidden; border-right: 1px solid var(--line-strong); background: var(--surface); box-shadow: 10px 0 28px rgba(0, 0, 0, .18); color: var(--text); animation: left-workbench-enter 170ms ease-out; }
.package-build-header { min-width: 0; padding: 0 14px 0 16px; display: flex; align-items: center; justify-content: space-between; gap: 14px; border-bottom: 1px solid var(--line); background: var(--surface-raised); }
.package-build-title { min-width: 0; }
.package-build-kicker { display: inline-flex; align-items: center; gap: 6px; color: var(--blue); font-size: 10px; font-weight: 700; letter-spacing: .1em; }
h2 { margin: 4px 0 2px; color: var(--text); font-size: 17px; line-height: 1.2; }
.package-build-header p { margin: 0; overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.icon-button, .secondary-action, .primary-action { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 1px solid var(--line); border-radius: 7px; color: var(--muted); background: transparent; cursor: pointer; transition: color 160ms ease, border-color 160ms ease, background-color 160ms ease; }
.icon-button { width: 31px; height: 31px; padding: 0; flex: 0 0 auto; }
.icon-button:hover, .icon-button:focus-visible, .secondary-action:hover:not(:disabled), .secondary-action:focus-visible { color: var(--text); border-color: var(--line-strong); outline: none; background: var(--surface-hover); }
.package-build-body { min-height: 0; padding: 14px 16px 16px; display: grid; grid-template-rows: auto auto minmax(0, 1fr); gap: 12px; overflow: auto; }
.package-build-target { padding: 10px 11px; display: grid; grid-template-columns: 28px minmax(0, 1fr); gap: 9px; border: 1px solid color-mix(in srgb, var(--blue) 32%, var(--line)); border-radius: 8px; background: color-mix(in srgb, var(--blue) 8%, var(--surface-raised)); }
.package-build-target-icon { width: 28px; height: 28px; display: grid; place-items: center; color: var(--blue); border-radius: 7px; background: color-mix(in srgb, var(--blue) 16%, transparent); }
.package-build-target strong { display: block; color: var(--text); font-size: 12px; }
.package-build-target span { display: block; margin-top: 2px; overflow: hidden; color: var(--muted); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.package-build-form { display: grid; gap: 11px; }
label { display: grid; gap: 5px; color: var(--muted); font-size: 11px; font-weight: 600; }
input, select { width: 100%; min-height: 34px; box-sizing: border-box; border: 1px solid var(--line); border-radius: 6px; outline: none; background: var(--surface-raised); color: var(--text); padding: 0 9px; font: inherit; font-weight: 400; transition: border-color 160ms ease, box-shadow 160ms ease; }
input:hover, select:hover { border-color: var(--line-strong); }
input:focus, select:focus { border-color: var(--blue); box-shadow: 0 0 0 2px var(--focus); }
input::placeholder { color: var(--soft); }
.package-build-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.package-build-actions { position: sticky; bottom: 0; display: flex; gap: 7px; padding-top: 5px; background: linear-gradient(var(--surface), var(--surface) 60%); }
.primary-action, .secondary-action { min-height: 33px; padding: 0 11px; font-size: 11px; font-weight: 650; }
.primary-action { color: #e9f5ff; border-color: var(--blue); background: var(--blue); }
.primary-action:hover:not(:disabled) { filter: brightness(1.08); }
button:disabled { opacity: .48; cursor: not-allowed; }
.package-build-error { margin: 0; padding: 8px 9px; color: var(--danger, #fca5a5); border: 1px solid color-mix(in srgb, var(--danger, #fca5a5) 34%, var(--line)); border-radius: 6px; background: color-mix(in srgb, var(--danger, #fca5a5) 8%, transparent); font-size: 11px; }
.package-build-status { min-height: 0; align-self: stretch; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-raised); }
.package-build-status-head, .package-build-meta { display: flex; justify-content: space-between; gap: 12px; }
.package-build-status-head strong { min-width: 0; overflow: hidden; color: var(--text); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.package-build-status-head span, .package-build-meta { color: var(--muted); font-size: 10px; }
.package-build-progress { height: 6px; margin: 10px 0 7px; overflow: hidden; border-radius: 4px; background: var(--line); }
.package-build-progress span { display: block; height: 100%; border-radius: inherit; background: var(--blue); transition: width .25s ease; }
.package-build-result { display: grid; gap: 7px; margin: 14px 0 0; font-size: 10px; }
.package-build-result div { display: grid; grid-template-columns: 62px 1fr; gap: 8px; }
.package-build-result dt { color: var(--muted); }
.package-build-result dd { margin: 0; overflow-wrap: anywhere; color: var(--text); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 560px) { .package-build-body { padding-inline: 12px; } .package-build-grid { grid-template-columns: 1fr; } }
</style>
