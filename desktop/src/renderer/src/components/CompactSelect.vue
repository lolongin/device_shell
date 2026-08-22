<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Check, ChevronDown } from 'lucide-vue-next'

interface SelectOption {
  value: string
  label: string
}

const props = defineProps<{
  modelValue: string
  options: SelectOption[]
  label: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const root = ref<HTMLElement | null>(null)
const trigger = ref<HTMLButtonElement | null>(null)
const open = ref(false)
const activeIndex = ref(0)
const selectedIndex = computed(() => {
  const index = props.options.findIndex((option) => option.value === props.modelValue)
  return index < 0 ? 0 : index
})
const selectedLabel = computed(() => props.options[selectedIndex.value]?.label || '')

watch(() => props.modelValue, () => {
  activeIndex.value = selectedIndex.value
})

function openMenu(): void {
  open.value = true
  activeIndex.value = selectedIndex.value
  void nextTick(() => {
    root.value?.querySelector<HTMLElement>(`[data-option-index="${activeIndex.value}"]`)?.scrollIntoView({ block: 'nearest' })
  })
}

function closeMenu(restoreFocus = false): void {
  open.value = false
  if (restoreFocus) void nextTick(() => trigger.value?.focus())
}

function toggleMenu(): void {
  if (open.value) closeMenu()
  else openMenu()
}

function selectOption(index: number): void {
  const option = props.options[index]
  if (!option) return
  emit('update:modelValue', option.value)
  closeMenu(true)
}

function moveActive(offset: number): void {
  if (!props.options.length) return
  if (!open.value) openMenu()
  activeIndex.value = (activeIndex.value + offset + props.options.length) % props.options.length
  void nextTick(() => {
    root.value?.querySelector<HTMLElement>(`[data-option-index="${activeIndex.value}"]`)?.scrollIntoView({ block: 'nearest' })
  })
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    closeMenu(true)
    return
  }
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    moveActive(event.key === 'ArrowDown' ? 1 : -1)
    return
  }
  if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    if (!open.value) openMenu()
    activeIndex.value = event.key === 'Home' ? 0 : Math.max(0, props.options.length - 1)
    return
  }
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    if (open.value) selectOption(activeIndex.value)
    else openMenu()
  }
}

function handleDocumentPointerDown(event: PointerEvent): void {
  if (!root.value?.contains(event.target as Node)) closeMenu()
}

onMounted(() => document.addEventListener('pointerdown', handleDocumentPointerDown, true))
onBeforeUnmount(() => document.removeEventListener('pointerdown', handleDocumentPointerDown, true))
</script>

<template>
  <div ref="root" class="compact-select" :class="{ open }" @keydown="handleKeydown">
    <button
      ref="trigger"
      class="compact-select-trigger"
      type="button"
      role="combobox"
      aria-haspopup="listbox"
      :aria-label="label"
      :aria-expanded="open"
      @click="toggleMenu"
    >
      <span>{{ selectedLabel }}</span>
      <ChevronDown :size="13" aria-hidden="true" />
    </button>
    <div v-if="open" class="compact-select-menu" role="listbox" :aria-label="label">
      <button
        v-for="(option, index) in options"
        :key="option.value || '__all__'"
        class="compact-select-option"
        :class="{ active: index === activeIndex, selected: option.value === modelValue }"
        type="button"
        role="option"
        :aria-selected="option.value === modelValue"
        :data-option-index="index"
        tabindex="-1"
        @pointerenter="activeIndex = index"
        @click="selectOption(index)"
      >
        <span>{{ option.label }}</span>
        <Check v-if="option.value === modelValue" :size="13" aria-hidden="true" />
      </button>
    </div>
  </div>
</template>
