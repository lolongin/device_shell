<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CircleStop, FileArchive, LoaderCircle, Play, RefreshCw, SlidersHorizontal, X } from 'lucide-vue-next'
import { desktopApi } from '../transport/api'
import type { OperationRecord, PackageBuilder } from '../types'
import { useWorkspaceStore } from '../stores/workspace'

const workspace = useWorkspaceStore()
const builders = ref<PackageBuilder[]>([])
const builderId = ref('internal-vrp')
const mrid = ref('')
const compileType = ref<'large' | 'small' | 'component_only'>('large')
const domain = ref('')
const configClass = ref('')
const operation = ref<OperationRecord | null>(null)
const error = ref('')
const loading = ref(false)
let refreshTimer: ReturnType<typeof setInterval> | null = null

// Keep suggestions editable until the internal CLI publishes its final enum values.
const domainOptions = ['通用', '路由交换', '安全', '无线']
const configClassOptions = ['标准配置', '精简配置', '定制配置']

const running = computed(() => Boolean(operation.value && ['queued', 'running'].includes(operation.value.status)))
const canStart = computed(() => (
  !running.value
  && !loading.value
  && Boolean(mrid.value.trim())
  && Boolean(domain.value)
  && Boolean(configClass.value)
))
const progress = computed(() => Math.max(0, Math.min(100, operation.value?.progress_percent || 0)))
const selectedBuilder = computed(() => builders.value.find((item) => item.id === builderId.value) || null)

function selectCompileType(value: string): void {
  if (value === 'large' || value === 'small' || value === 'component_only') compileType.value = value
}

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
      package_type: 'system',
      options: {
        compile_type: compileType.value,
        domain: domain.value,
        config_class: configClass.value
      }
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
          <div class="package-build-kicker"><FileArchive :size="14" /> VRP BUILD</div>
          <h2>编包</h2>
          <p>选择编译参数，生成 VRP 系统包</p>
        </div>
        <button class="icon-button" type="button" title="关闭" aria-label="关闭" @click="workspace.packageBuildPanelOpen = false">
          <X :size="17" />
        </button>
      </header>

      <div class="package-build-body">
        <section class="package-build-engine" aria-label="编包器状态">
          <div class="package-build-engine-icon"><FileArchive :size="15" /></div>
          <div class="package-build-engine-copy">
            <strong>{{ selectedBuilder?.label || '未发现编包器' }}</strong>
            <span>{{ selectedBuilder?.version ? `v${selectedBuilder.version}` : '请配置内部 VRP 编包 CLI' }}</span>
          </div>
          <button v-if="!running" class="icon-button compact" type="button" title="刷新编包器" aria-label="刷新编包器" @click="loadBuilders">
            <RefreshCw :size="14" />
          </button>
        </section>

        <form class="package-build-form" @submit.prevent="startBuild">
          <label>MR ID<input v-model="mrid" required maxlength="255" :disabled="running || loading" placeholder="输入 MR ID" /></label>

          <fieldset class="choice-field">
            <legend>编译类型</legend>
            <div class="segmented-control three-way" role="radiogroup" aria-label="编译类型">
              <button
                v-for="item in [{ value: 'large', label: '大包' }, { value: 'small', label: '小包' }, { value: 'component_only', label: '只编译组件' }]"
                :key="item.value"
                class="segment-option"
                :class="{ selected: compileType === item.value }"
                type="button"
                role="radio"
                :aria-checked="compileType === item.value"
                :disabled="running || loading"
                @click="selectCompileType(item.value)"
              >{{ item.label }}</button>
            </div>
          </fieldset>

          <label>领域
            <select v-model="domain" :disabled="running || loading">
              <option value="" disabled>选择领域</option>
              <option v-for="item in domainOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>

          <label>配置类
            <select v-model="configClass" :disabled="running || loading">
              <option value="" disabled>选择配置类</option>
              <option v-for="item in configClassOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>

          <p class="package-build-hint"><SlidersHorizontal :size="13" />账号、FTP 等持久化配置由编包器配置管理。</p>
          <p v-if="error" class="package-build-error">{{ error }}</p>
          <div class="package-build-actions">
            <button class="primary-action" type="submit" :disabled="!canStart"><LoaderCircle v-if="loading" class="spin" :size="16" /><Play v-else :size="16" />开始编包</button>
            <button v-if="running" class="secondary-action" type="button" @click="cancelBuild"><CircleStop :size="16" />取消</button>
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
.package-build-kicker { display: inline-flex; align-items: center; gap: 6px; color: var(--blue); font-size: 10px; font-weight: 700; letter-spacing: .08em; }
h2 { margin: 4px 0 2px; color: var(--text); font-size: 17px; line-height: 1.2; }
.package-build-header p { margin: 0; overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.icon-button, .secondary-action, .primary-action { display: inline-flex; align-items: center; justify-content: center; gap: 6px; border: 1px solid var(--line); border-radius: 7px; color: var(--muted); background: transparent; cursor: pointer; transition: color 160ms ease, border-color 160ms ease, background-color 160ms ease; }
.icon-button { width: 31px; height: 31px; padding: 0; flex: 0 0 auto; }
.icon-button.compact { width: 27px; height: 27px; border-color: transparent; }
.icon-button:hover, .icon-button:focus-visible, .secondary-action:hover:not(:disabled), .secondary-action:focus-visible { color: var(--text); border-color: var(--line-strong); outline: none; background: var(--surface-hover); }
.package-build-body { min-height: 0; padding: 14px 16px 16px; display: grid; align-content: start; gap: 13px; overflow: auto; }
.package-build-engine { min-width: 0; padding: 9px 10px; display: flex; align-items: center; gap: 9px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface-raised); }
.package-build-engine-icon { width: 28px; height: 28px; display: grid; place-items: center; flex: 0 0 auto; color: var(--blue); border-radius: 6px; background: color-mix(in srgb, var(--blue) 12%, transparent); }
.package-build-engine-copy { min-width: 0; flex: 1; }
.package-build-engine-copy strong { display: block; overflow: hidden; color: var(--text); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.package-build-engine-copy span { display: block; margin-top: 2px; color: var(--muted); font-size: 10px; }
.package-build-form { display: grid; gap: 11px; }
label, .choice-field { display: grid; gap: 5px; margin: 0; padding: 0; border: 0; color: var(--muted); font-size: 11px; font-weight: 600; }
legend { padding: 0; color: var(--muted); font: inherit; }
input, select { width: 100%; min-height: 34px; box-sizing: border-box; border: 1px solid var(--line); border-radius: 6px; outline: none; background: var(--surface-raised); color: var(--text); padding: 0 9px; font: inherit; font-weight: 400; transition: border-color 160ms ease, box-shadow 160ms ease; }
input:hover, select:hover { border-color: var(--line-strong); }
input:focus, select:focus { border-color: var(--blue); box-shadow: 0 0 0 2px var(--focus); }
input::placeholder { color: var(--soft); }
.package-build-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.segmented-control { display: grid; grid-template-columns: 1fr 1fr; padding: 3px; gap: 3px; border: 1px solid var(--line); border-radius: 7px; background: var(--surface-raised); }
.segmented-control.three-way { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.segment-option { min-height: 30px; border: 0; border-radius: 5px; color: var(--muted); background: transparent; font: inherit; font-size: 11px; font-weight: 650; cursor: pointer; transition: color 160ms ease, background-color 160ms ease; }
.segment-option:hover:not(:disabled) { color: var(--text); background: var(--surface-hover); }
.segment-option.selected { color: var(--text); background: color-mix(in srgb, var(--blue) 18%, var(--surface)); box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--blue) 40%, transparent); }
.segment-option:focus-visible { outline: 2px solid var(--focus); outline-offset: 1px; }
.package-build-hint { display: flex; align-items: center; gap: 6px; margin: -1px 0 0; color: var(--muted); font-size: 10px; line-height: 1.4; }
.package-build-actions { display: flex; gap: 7px; padding-top: 2px; }
.primary-action, .secondary-action { min-height: 33px; padding: 0 11px; font-size: 11px; font-weight: 650; }
.primary-action { color: #e9f5ff; border-color: var(--blue); background: var(--blue); }
.primary-action:hover:not(:disabled) { filter: brightness(1.08); }
button:disabled { opacity: .48; cursor: not-allowed; }
.package-build-error { margin: 0; padding: 8px 9px; color: var(--danger, #fca5a5); border: 1px solid color-mix(in srgb, var(--danger, #fca5a5) 34%, var(--line)); border-radius: 6px; background: color-mix(in srgb, var(--danger, #fca5a5) 8%, transparent); font-size: 11px; }
.package-build-status { min-height: 0; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-raised); }
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
