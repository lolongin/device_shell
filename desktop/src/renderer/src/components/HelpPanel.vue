<script setup lang="ts">
import { computed, ref, toRef, watch } from 'vue'
import {
  Cable,
  Keyboard,
  LayoutPanelLeft,
  Monitor,
  MousePointer2,
  Search,
  ShieldCheck,
  X
} from 'lucide-vue-next'
import { useDialogFocus } from '../composables/useDialogFocus'

const props = defineProps<{ open: boolean; returnFocus?: HTMLElement | null }>()
const emit = defineEmits<{ close: [] }>()
const panel = ref<HTMLElement | null>(null)
const query = ref('')
const activeCategory = ref('all')
const { handleDialogKeydown } = useDialogFocus(panel, {
  open: toRef(props, 'open'),
  initialFocus: '[data-dialog-initial-focus]',
  restoreFocus: () => props.returnFocus || null
})

const shortcutGroups = [
  {
    id: 'navigation',
    title: '设备与菜单',
    icon: Keyboard,
    items: [
      ['↑ / ↓ / Home / End', '浏览设备列表'],
      ['Enter / Space', '打开选中设备的默认连接'],
      ['ContextMenu / Shift+F10', '打开当前设备、会话或命令菜单'],
      ['Esc', '关闭搜索、菜单或当前弹窗']
    ]
  },
  {
    id: 'terminal',
    title: '终端与命令',
    icon: Monitor,
    items: [
      ['Ctrl+F', '搜索当前聚焦的终端或命令记录'],
      ['Ctrl++ / Ctrl+-', '放大或缩小终端字体'],
      ['Ctrl+Shift+R', '重新连接当前终端'],
      ['Enter / Ctrl+Enter', '按当前发送模式执行选中或当前命令']
    ]
  },
  {
    id: 'layout',
    title: '布局调整',
    icon: LayoutPanelLeft,
    items: [
      ['← / →', '聚焦分隔线时调整左侧工作台或右侧会话栏宽度'],
      ['↑ / ↓ / Home / End', '聚焦命令区分隔线时调整或快速切换高度'],
      ['Shift + 方向键', '以更大步长调整左侧工作台或命令区'],
      ['双击分隔线', '恢复左侧工作台或命令区默认尺寸'],
      ['方向键', '聚焦终端分屏线时调整两个窗格比例']
    ]
  },
  {
    id: 'sessions',
    title: '会话组织',
    icon: MousePointer2,
    items: [
      ['拖动会话页签', '放到终端边缘创建左、右、上或下分屏'],
      ['会话右键菜单', '关闭相邻页签、定位设备或选择分屏方向'],
      ['右侧会话栏', '按设备搜索、折叠和切换终端会话']
    ]
  },
  {
    id: 'operations',
    title: '托管操作',
    icon: Cable,
    items: [
      ['终端底部工具栏', '打开当前设备的文件传输、升级或自动响应'],
      ['文件传输', '启动 FTP/SFTP 服务并监控传输与服务日志'],
      ['系统包升级', '完成安全预检、脚本兜底和升级阶段跟踪']
    ]
  }
]

const categories = computed(() => [
  { id: 'all', label: '全部', count: shortcutGroups.reduce((total, group) => total + group.items.length, 0) },
  ...shortcutGroups.map((group) => ({ id: group.id, label: group.title, count: group.items.length }))
])
const visibleGroups = computed(() => {
  const needle = query.value.trim().toLocaleLowerCase()
  return shortcutGroups.flatMap((group) => {
    if (activeCategory.value !== 'all' && activeCategory.value !== group.id) return []
    const items = group.items.filter(([keys, action]) =>
      !needle || `${keys} ${action} ${group.title}`.toLocaleLowerCase().includes(needle)
    )
    return items.length ? [{ ...group, items }] : []
  })
})
const visibleShortcutCount = computed(() =>
  visibleGroups.value.reduce((total, group) => total + group.items.length, 0)
)

function clearHelpFilters(): void {
  query.value = ''
  activeCategory.value = 'all'
}

watch(() => props.open, (open) => {
  if (!open) clearHelpFilters()
})
</script>

<template>
  <div v-if="open" class="help-backdrop" @click.self="emit('close')">
    <section
      ref="panel"
      class="help-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="desktop-help-title"
      tabindex="-1"
      @keydown="handleDialogKeydown"
      @keydown.esc.prevent="emit('close')"
    >
      <header>
        <div>
          <p>DEVICE TUI</p>
          <h2 id="desktop-help-title">操作帮助</h2>
        </div>
        <button type="button" title="关闭帮助" aria-label="关闭操作帮助" @click="emit('close')"><X :size="17" /></button>
      </header>
      <div class="help-search-bar">
        <label class="help-search-field">
          <Search :size="15" aria-hidden="true" />
          <input
            v-model="query"
            type="search"
            placeholder="搜索快捷键或操作，例如 分屏、FTP、日志"
            aria-label="搜索操作帮助"
            data-dialog-initial-focus
          />
          <button v-if="query" type="button" aria-label="清除帮助搜索" title="清除搜索" @click="query = ''"><X :size="13" /></button>
        </label>
        <span role="status">{{ visibleShortcutCount }} 项操作</span>
      </div>
      <nav class="help-categories" aria-label="帮助分类">
        <button
          v-for="category in categories"
          :key="category.id"
          type="button"
          :class="{ active: activeCategory === category.id }"
          :aria-pressed="activeCategory === category.id"
          @click="activeCategory = category.id"
        >{{ category.label }} <small>{{ category.count }}</small></button>
      </nav>
      <div class="help-content">
        <p class="intro">设备操作、终端会话和命令工作区均支持鼠标与键盘操作。</p>
        <section v-for="group in visibleGroups" :key="group.id" class="help-shortcut-group">
          <h3><component :is="group.icon" :size="15" aria-hidden="true" />{{ group.title }}</h3>
          <dl>
            <template v-for="([keys, action]) in group.items" :key="keys">
              <dt>{{ keys }}</dt>
              <dd>{{ action }}</dd>
            </template>
          </dl>
        </section>
        <div v-if="!visibleGroups.length" class="help-empty" role="status">
          <Search :size="21" aria-hidden="true" />
          <strong>没有匹配的操作</strong>
          <span>尝试“终端”“分屏”“FTP”或切换帮助分类。</span>
          <button type="button" @click="clearHelpFilters">查看全部操作</button>
        </div>
        <div class="help-note">
          <ShieldCheck :size="16" aria-hidden="true" />
          <strong>安全边界</strong>
          <span>设备密码和后端访问令牌由 Python Backend / Electron Main 保管，不会进入 Vue 页面。</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.help-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1190;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(2, 6, 23, 0.48);
}
.help-panel {
  width: min(720px, calc(100vw - 40px));
  max-height: calc(100vh - 40px);
  display: grid;
  grid-template-rows: auto auto auto minmax(0, 1fr);
  color: var(--text);
  border: 1px solid var(--line-strong);
  border-radius: 13px;
  background: var(--surface);
  box-shadow: 0 18px 56px rgba(0, 0, 0, 0.34);
  overflow: hidden;
}
.help-panel > header { min-height: 66px; padding: 13px 16px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--line); }
.help-panel header p { margin: 0 0 3px; color: var(--soft); font-size: 10px; font-weight: 750; letter-spacing: 0.12em; }
.help-panel h2 { margin: 0; font-size: 17px; }
.help-panel header button, .help-search-field button { display: grid; place-items: center; color: var(--muted); border: 1px solid var(--line); border-radius: 7px; background: var(--surface-raised); cursor: pointer; }
.help-panel header button { width: 30px; height: 30px; }
.help-panel header button:hover, .help-search-field button:hover { color: var(--text); border-color: var(--line-strong); }
.help-search-bar { padding: 12px 16px 8px; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 10px; }
.help-search-bar > span { color: var(--soft); font-size: 10px; white-space: nowrap; }
.help-search-field { min-width: 0; height: 36px; padding: 0 7px 0 10px; display: flex; align-items: center; gap: 8px; color: var(--soft); border: 1px solid var(--line); border-radius: 8px; background: var(--bg); }
.help-search-field:focus-within { border-color: var(--blue); box-shadow: 0 0 0 3px var(--focus); }
.help-search-field input { min-width: 0; width: 100%; color: var(--text); border: 0; outline: 0; background: transparent; }
.help-search-field input::placeholder { color: var(--soft); }
.help-search-field button { width: 24px; height: 24px; flex: 0 0 auto; }
.help-categories { padding: 0 16px 11px; display: flex; gap: 6px; overflow-x: auto; border-bottom: 1px solid var(--line); scrollbar-width: thin; }
.help-categories button { min-height: 27px; padding: 2px 8px; display: inline-flex; align-items: center; gap: 5px; color: var(--muted); border: 1px solid var(--line); border-radius: 999px; background: var(--surface-raised); cursor: pointer; white-space: nowrap; }
.help-categories button:hover, .help-categories button.active { color: var(--text); border-color: rgba(96, 165, 250, 0.45); background: rgba(96, 165, 250, 0.08); }
.help-categories button.active { color: var(--blue); }
.help-categories small { color: var(--soft); font-size: 9px; }
.help-content { min-height: 0; padding: 15px 16px 16px; overflow: auto; overscroll-behavior: contain; }
.intro { margin: 0 0 13px; color: var(--muted); }
.help-shortcut-group + .help-shortcut-group { margin-top: 13px; }
.help-shortcut-group h3 { margin: 0 0 6px; display: flex; align-items: center; gap: 7px; color: var(--blue); font-size: 11px; }
dl { margin: 0; display: grid; grid-template-columns: minmax(205px, 0.85fr) minmax(0, 1.15fr); border: 1px solid var(--line); border-radius: 9px; overflow: hidden; }
dt, dd { margin: 0; padding: 8px 11px; border-bottom: 1px solid var(--line); }
dt { color: var(--text); background: var(--surface-raised); font-family: "Cascadia Mono", Consolas, monospace; font-size: 10.5px; }
dd { color: var(--muted); }
dt:nth-last-of-type(1), dd:nth-last-of-type(1) { border-bottom: 0; }
.help-empty { min-height: 180px; padding: 24px; display: grid; place-content: center; justify-items: center; gap: 6px; color: var(--muted); text-align: center; }
.help-empty > svg { color: var(--soft); }
.help-empty strong { color: var(--text); }
.help-empty span { color: var(--soft); }
.help-empty button { min-height: 30px; margin-top: 5px; padding: 0 11px; color: var(--blue); border: 1px solid rgba(96, 165, 250, 0.4); border-radius: 7px; background: rgba(96, 165, 250, 0.08); cursor: pointer; }
.help-note { margin-top: 14px; padding: 11px; display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 3px 7px; color: var(--muted); border: 1px solid rgba(34, 197, 94, 0.32); border-radius: 9px; background: rgba(34, 197, 94, 0.08); line-height: 1.5; }
.help-note > svg { grid-row: 1 / 3; color: var(--accent); }
.help-note strong { color: var(--accent); }
@media (max-width: 620px) {
  .help-panel { width: min(100%, calc(100vw - 20px)); max-height: calc(100vh - 20px); }
  .help-search-bar { padding-inline: 11px; }
  .help-categories { padding-inline: 11px; }
  .help-content { padding-inline: 11px; }
  dl { grid-template-columns: 1fr; }
  dt { border-bottom: 0; padding-bottom: 3px; }
  dd { padding-top: 3px; }
}
</style>
