<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Download, Play, RotateCcw, Save, Trash2 } from 'lucide-vue-next'

type PublishedVersion = { id: string; name: string; version: string | number; published_at?: string | null; referenced?: boolean }
const props = defineProps<{
  versions: PublishedVersion[]
  loading: boolean
  error: string
  onRun: (payload: { workflowId: string; version: string | number }) => void
  onExport: (version: any) => void
  onRestore: (version: any) => void
  onSaveAction: (version: any) => void
  onRemove: (version: any) => void
  onRemoveMany: (versions: PublishedVersion[]) => Promise<boolean>
}>()

const selectedVersionKeys = ref(new Set<string>())
const removing = ref(false)

function versionKey(version: PublishedVersion): string {
  return `${version.id}-${version.version}`
}

const selectedVersions = computed(() => props.versions.filter((version) => selectedVersionKeys.value.has(versionKey(version))))
const allSelected = computed(() => props.versions.length > 0 && selectedVersions.value.length === props.versions.length)

watch(() => props.versions, (versions) => {
  const available = new Set(versions.map(versionKey))
  selectedVersionKeys.value = new Set([...selectedVersionKeys.value].filter((key) => available.has(key)))
}, { deep: true })

function toggleVersion(version: PublishedVersion): void {
  const next = new Set(selectedVersionKeys.value)
  const key = versionKey(version)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selectedVersionKeys.value = next
}

function toggleAllVersions(): void {
  selectedVersionKeys.value = allSelected.value
    ? new Set()
    : new Set(props.versions.map(versionKey))
}

async function removeSelectedVersions(): Promise<void> {
  if (!selectedVersions.value.length || removing.value) return
  removing.value = true
  try {
    const removed = await props.onRemoveMany(selectedVersions.value)
    if (removed) selectedVersionKeys.value = new Set()
  } catch {
    // The parent reports the API error in the version panel.
  } finally {
    removing.value = false
  }
}
</script>

<template>
        <section  class="workflow-version-manager" aria-label="发布版本管理">
          <div class="workflow-version-heading">
            <div class="workflow-version-heading-title"><strong>发布版本</strong><small>{{ versions.length }} 个</small></div>
            <div v-if="versions.length" class="workflow-version-selection">
              <label class="workflow-version-select-all">
                <input type="checkbox" :checked="allSelected" :disabled="loading || removing" aria-label="全选发布版本" @change="toggleAllVersions" />
                <span>全选</span>
              </label>
              <button
                type="button"
                class="workflow-version-bulk-delete"
                :disabled="!selectedVersions.length || loading || removing"
                :title="selectedVersions.length ? `清理选中的 ${selectedVersions.length} 个发布版本` : '先选择发布版本'"
                @click="removeSelectedVersions"
              >
                <Trash2 :size="13" />
                <span>{{ removing ? '清理中…' : `清理选中${selectedVersions.length ? `（${selectedVersions.length}）` : ''}` }}</span>
              </button>
            </div>
          </div>
          <p v-if="loading" class="workflow-version-empty">加载版本中…</p>
          <p v-else-if="error" class="workflow-version-error">{{ error }}</p>
          <p v-else-if="!versions.length" class="workflow-version-empty">尚未发布版本</p>
          <div v-else class="workflow-version-list">
            <div v-for="version in versions" :key="versionKey(version)" class="workflow-version-row" :class="{ referenced: version.referenced, selected: selectedVersionKeys.has(versionKey(version)) }">
              <label class="workflow-version-checkbox">
                <input type="checkbox" :checked="selectedVersionKeys.has(versionKey(version))" :disabled="removing" :aria-label="`选择发布版本 v${version.version}`" @click.stop @change="toggleVersion(version)" />
              </label>
              <div class="workflow-version-info">
                <strong>v{{ version.version }}</strong>
                <small>{{ version.published_at ? new Date(version.published_at).toLocaleString() : '发布时间未知' }}</small>
                <span>{{ version.referenced ? '已被任务引用，可删除' : '未被引用，可删除' }}</span>
              </div>
              <div class="workflow-version-actions">
                <button type="button" class="icon-toolbar-button" :disabled="removing" title="运行此发布版本" :aria-label="`运行发布版本 v${version.version}`" @click.stop="onRun({ workflowId: version.id, version: version.version })"><Play :size="13" /></button>
                <button type="button" class="icon-toolbar-button" :disabled="removing" title="导出此发布版本 YAML" :aria-label="`导出发布版本 v${version.version}`" @click.stop="onExport(version)"><Download :size="13" /></button>
                <button type="button" class="icon-toolbar-button" :disabled="removing" title="恢复为当前草稿" :aria-label="`恢复发布版本 v${version.version} 为草稿`" @click.stop="onRestore(version)"><RotateCcw :size="13" /></button>
                <button type="button" class="icon-toolbar-button" :disabled="removing" title="保存为自定义 Action" :aria-label="`将发布版本 v${version.version} 保存为自定义 Action`" @click.stop="onSaveAction(version)"><Save :size="13" /></button>
                <button type="button" class="icon-toolbar-button workflow-version-delete" :disabled="removing" title="删除此发布版本" :aria-label="`删除发布版本 v${version.version}`" @click.stop="onRemove(version)"><Trash2 :size="13" /></button>
              </div>
            </div>
          </div>
        </section>
</template>
<style src="./WorkflowVersionManager.css"></style>
