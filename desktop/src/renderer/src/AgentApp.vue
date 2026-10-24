<script setup lang="ts">
import { onBeforeUnmount } from 'vue'
import AiWorkspace from './components/AiWorkspace.vue'

function syncTheme(): void {
  document.documentElement.dataset.theme = localStorage.getItem('odyterm.desktop-v2.theme') === 'light' ? 'light' : 'dark'
}
syncTheme()
window.addEventListener('storage', syncTheme)
onBeforeUnmount(() => window.removeEventListener('storage', syncTheme))
const initialConversationId = new URLSearchParams(window.location.search).get('conversation') || undefined
</script>

<template>
  <AiWorkspace standalone :initial-conversation-id="initialConversationId" />
</template>
