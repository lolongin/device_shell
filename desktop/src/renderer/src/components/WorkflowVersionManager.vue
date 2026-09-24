<script setup lang="ts">
import { Download, Play, RotateCcw, Save, Trash2 } from 'lucide-vue-next'

type PublishedVersion = { id: string; name: string; version: string | number; published_at?: string | null; referenced?: boolean }
defineProps<{ versions: PublishedVersion[]; loading: boolean; error: string; onRun: (payload: { workflowId: string; version: string | number }) => void; onExport: (version: any) => void; onRestore: (version: any) => void; onSaveAction: (version: any) => void; onRemove: (version: any) => void }>()
</script>

<template>
        <section  class="workflow-version-manager" aria-label="发布版本管理">
          <div class="workflow-version-heading"><strong>发布版本</strong><small>{{ versions.length }} 个</small></div>
          <p v-if="loading" class="workflow-version-empty">加载版本中…</p>
          <p v-else-if="error" class="workflow-version-error">{{ error }}</p>
          <p v-else-if="!versions.length" class="workflow-version-empty">尚未发布版本</p>
          <div v-else class="workflow-version-list">
            <div v-for="version in versions" :key="`${version.id}-${version.version}`" class="workflow-version-row" :class="{ referenced: version.referenced }">
              <div class="workflow-version-info">
                <strong>v{{ version.version }}</strong>
                <small>{{ version.published_at ? new Date(version.published_at).toLocaleString() : '发布时间未知' }}</small>
                <span>{{ version.referenced ? '已被任务引用' : '未被引用，可删除' }}</span>
              </div>
              <div class="workflow-version-actions">
                <button type="button" class="icon-toolbar-button" title="运行此发布版本" :aria-label="`运行发布版本 v${version.version}`" @click.stop="onRun({ workflowId: version.id, version: version.version })"><Play :size="13" /></button>
                <button type="button" class="icon-toolbar-button" title="导出此发布版本 YAML" :aria-label="`导出发布版本 v${version.version}`" @click.stop="onExport(version)"><Download :size="13" /></button>
                <button type="button" class="icon-toolbar-button" title="恢复为当前草稿" :aria-label="`恢复发布版本 v${version.version} 为草稿`" @click.stop="onRestore(version)"><RotateCcw :size="13" /></button>
                <button type="button" class="icon-toolbar-button" title="保存为自定义 Action" :aria-label="`将发布版本 v${version.version} 保存为自定义 Action`" @click.stop="onSaveAction(version)"><Save :size="13" /></button>
                <button type="button" class="icon-toolbar-button workflow-version-delete" :disabled="version.referenced" :title="version.referenced ? '已被任务引用，不能删除' : '删除此发布版本'" :aria-label="version.referenced ? '已被任务引用，不能删除' : `删除发布版本 v${version.version}`" @click.stop="onRemove(version)"><Trash2 :size="13" /></button>
              </div>
            </div>
          </div>
        </section>
</template>
<style src="./WorkflowVersionManager.css"></style>
