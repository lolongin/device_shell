<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { ChevronDown, Search } from 'lucide-vue-next'
import { filterWorkflowDevices } from './workflow/device-filter'

export type WorkflowTargetOption = {
  id: string
  label: string
  detail?: string
}

const props = defineProps<{
  modelValue: string[]
  devices: WorkflowTargetOption[]
  ownedDeviceIds?: readonly string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const isOpen = ref(false)
const searchQuery = ref('')
const mineOnly = ref(false)

const selectedDevices = computed(() => props.devices.filter((device) => props.modelValue.includes(device.id)))
const selectedLabel = computed(() => {
  const names = selectedDevices.value.map((device) => device.label)
  if (!names.length) return props.devices.length ? '选择设备' : '暂无可用设备'
  if (names.length <= 2) return names.join('、')
  return `${names[0]} 等 ${names.length} 台`
})
const filteredDevices = computed(() => filterWorkflowDevices(props.devices, searchQuery.value, mineOnly.value ? props.ownedDeviceIds || [] : undefined))

function toggleDevice(id: string, checked: boolean): void {
  const selected = new Set(props.modelValue)
  if (checked) selected.add(id)
  else selected.delete(id)
  emit('update:modelValue', props.devices.filter((device) => selected.has(device.id)).map((device) => device.id))
}

function clearSelection(): void {
  emit('update:modelValue', [])
}

function closePicker(restoreFocus = false): void {
  isOpen.value = false
  searchQuery.value = ''
  if (restoreFocus) void nextTick(() => trigger.value?.focus())
}

function onDocumentPointerDown(event: PointerEvent): void {
  if (root.value && !root.value.contains(event.target as Node)) closePicker()
}

function onDocumentKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && isOpen.value) {
    event.preventDefault()
    closePicker(true)
  }
}

function onFocusOut(event: FocusEvent): void {
  // relatedTarget identifies the next focused control before Vue rerenders the option list.
  // Reading document.activeElement in the next tick can transiently return body after a
  // checkbox update, which closes the picker even though focus remains inside it.
  const nextTarget = event.relatedTarget as Node | null
  if (nextTarget && root.value?.contains(nextTarget)) return
  void nextTick(() => {
    if (root.value && !root.value.contains(document.activeElement)) closePicker()
  })
}

function togglePicker(): void {
  isOpen.value = !isOpen.value
  if (isOpen.value) void nextTick(() => searchInput.value?.focus())
  else searchQuery.value = ''
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onDocumentKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})
</script>

<template>
  <div ref="root" class="workflow-target-picker" @focusout="onFocusOut">
    <button
      ref="trigger"
      class="workflow-target-trigger"
      type="button"
      aria-label="选择运行目标设备"
      :aria-expanded="isOpen"
      aria-haspopup="dialog"
      :aria-controls="isOpen ? 'workflow-target-picker-options' : undefined"
      @click="togglePicker"
    >
      <span class="workflow-target-trigger-copy">
        <small>执行目标</small>
        <strong :title="selectedLabel">{{ selectedLabel }}</strong>
      </span>
      <span class="workflow-target-count" :class="{ empty: !selectedDevices.length }">{{ selectedDevices.length }}</span>
      <ChevronDown :size="14" :class="{ rotated: isOpen }" />
    </button>

    <section
      v-if="isOpen"
      id="workflow-target-picker-options"
      class="workflow-target-popover"
      role="dialog"
      aria-label="选择运行目标设备"
    >
      <label class="workflow-target-search">
        <Search :size="14" aria-hidden="true" />
        <input ref="searchInput" v-model="searchQuery" type="search" aria-label="搜索设备" placeholder="搜索设备名称、ID 或地址" />
      </label>
      <div class="workflow-target-popover-heading">
        <label class="workflow-target-mine"><input v-model="mineOnly" type="checkbox" aria-label="运行目标仅显示我的占用" />我的占用</label>
        <button type="button" :disabled="!selectedDevices.length" @click="clearSelection">清空</button>
      </div>
      <div class="workflow-target-options" role="group" aria-label="可用设备">
        <label v-for="device in filteredDevices" :key="device.id" class="workflow-target-option">
          <input
            type="checkbox"
            :checked="props.modelValue.includes(device.id)"
            @change="toggleDevice(device.id, ($event.target as HTMLInputElement).checked)"
          />
          <span>
            <strong>{{ device.label }}</strong>
            <small v-if="device.detail">{{ device.detail }}</small>
          </span>
        </label>
        <p v-if="!props.devices.length" class="workflow-target-empty">暂无可用设备，请先添加或导入设备。</p>
        <p v-else-if="!filteredDevices.length" class="workflow-target-empty">没有匹配的设备。</p>
      </div>
      <div class="workflow-target-popover-footer">
        <span>已选 {{ selectedDevices.length }} 台</span>
        <button type="button" class="workflow-target-done" @click="closePicker(true)">完成</button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.workflow-target-picker { position: relative; min-width: 0; }
.workflow-target-mine { display: flex; align-items: center; gap: 5px; cursor: pointer; }
.workflow-target-mine input { width: 14px; height: 14px; margin: 0; accent-color: var(--workflow-focus); }
.workflow-target-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 210px;
  min-width: 150px;
  min-height: 36px;
  padding: 4px 8px;
  border: 1px solid var(--workflow-border);
  border-radius: 7px;
  color: var(--workflow-text);
  text-align: left;
  background: var(--workflow-surface);
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease;
}
.workflow-target-trigger:hover,
.workflow-target-trigger[aria-expanded="true"] { border-color: color-mix(in srgb, var(--blue) 58%, var(--workflow-border)); background: var(--workflow-surface-muted); }
.workflow-target-trigger:focus-visible { outline: 2px solid var(--blue); outline-offset: 2px; }
.workflow-target-trigger-copy { display: grid; flex: 1; min-width: 0; gap: 1px; }
.workflow-target-trigger-copy small { color: var(--workflow-muted); font-size: 9px; line-height: 1.1; }
.workflow-target-trigger-copy strong { overflow: hidden; font-size: 11px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.workflow-target-count { display: inline-grid; flex: 0 0 auto; min-width: 20px; height: 20px; padding: 0 5px; place-items: center; border: 1px solid rgba(96, 165, 250, .3); border-radius: 999px; color: #bfdbfe; background: rgba(37, 99, 235, .15); font-size: 10px; font-variant-numeric: tabular-nums; }
.workflow-target-count.empty { color: var(--workflow-muted); background: transparent; border-color: var(--workflow-border); }
.workflow-target-trigger > svg { flex: 0 0 auto; color: var(--workflow-muted); transition: transform 160ms ease; }
.workflow-target-trigger > svg.rotated { transform: rotate(180deg); }
.workflow-target-popover { position: absolute; z-index: 80; top: calc(100% + 6px); right: 0; display: grid; gap: 8px; width: min(320px, calc(100vw - 28px)); padding: 10px; border: 1px solid var(--workflow-border); border-radius: 9px; color: var(--workflow-text); background: var(--workflow-surface); box-shadow: 0 16px 36px rgba(0, 0, 0, .32); }
.workflow-target-search { display: flex; align-items: center; gap: 7px; min-height: 34px; padding: 0 8px; border: 1px solid var(--workflow-border); border-radius: 6px; color: var(--workflow-muted); background: var(--workflow-surface-input); }
.workflow-target-search:focus-within { border-color: var(--blue); }
.workflow-target-search input { min-width: 0; width: 100%; height: 32px; padding: 0; border: 0; outline: 0; color: var(--workflow-text); background: transparent; font-size: 11px; }
.workflow-target-search input:focus-visible { outline: 0; }
.workflow-target-search input::placeholder { color: var(--workflow-muted); }
.workflow-target-popover-heading,
.workflow-target-popover-footer { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.workflow-target-popover-heading { color: var(--workflow-muted); font-size: 10px; font-weight: 650; }
.workflow-target-popover-heading button { padding: 3px 5px; border: 0; color: var(--blue); background: transparent; font-size: 10px; cursor: pointer; }
.workflow-target-popover-heading button:disabled { opacity: .45; cursor: default; }
.workflow-target-options { display: grid; max-height: min(38vh, 260px); overflow: auto; overscroll-behavior: contain; }
.workflow-target-option { display: flex; align-items: center; gap: 8px; min-width: 0; min-height: 38px; padding: 5px 6px; border-radius: 5px; cursor: pointer; }
.workflow-target-option:hover { background: var(--workflow-surface-muted); }
.workflow-target-option input { flex: 0 0 auto; width: 15px; height: 15px; margin: 0; accent-color: var(--blue); }
.workflow-target-option > span { display: grid; min-width: 0; gap: 1px; }
.workflow-target-option strong,
.workflow-target-option small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.workflow-target-option strong { font-size: 11px; font-weight: 550; }
.workflow-target-option small { color: var(--workflow-muted); font-size: 9px; }
.workflow-target-empty { margin: 0; padding: 12px 6px; color: var(--workflow-muted); font-size: 11px; line-height: 1.45; }
.workflow-target-popover-footer { padding-top: 7px; border-top: 1px solid var(--workflow-border); color: var(--workflow-muted); font-size: 10px; }
.workflow-target-done { min-height: 28px; padding: 4px 10px; border: 1px solid rgba(96, 165, 250, .35); border-radius: 5px; color: #dbeafe; background: rgba(37, 99, 235, .2); cursor: pointer; }
.workflow-target-done:hover { background: rgba(37, 99, 235, .32); }
:global(:root[data-theme="light"]) .workflow-target-count { color: #1d4ed8; }
:global(:root[data-theme="light"]) .workflow-target-done { color: #1d4ed8; background: #eff6ff; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition-duration: 0.01ms !important; }
}
</style>
