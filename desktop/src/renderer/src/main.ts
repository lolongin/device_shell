import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import AgentApp from './AgentApp.vue'
import '@xterm/xterm/css/xterm.css'
import './styles.css'

const root = new URLSearchParams(window.location.search).get('workspace') === 'agent' ? AgentApp : App
createApp(root).use(createPinia()).mount('#app')
