<script setup lang="ts">
import { computed, ref } from 'vue'
import { useContextMenuPlacement } from '../composables/useContextMenuPlacement'
import type { SessionSummary } from '../types'

type MenuPoint = { x: number; y: number }
type DeviceMenu = MenuPoint & { deviceId: string }
type SessionMenu = MenuPoint & { session: SessionSummary; source: string }
type ProfileLike = { name?: string; profile_type?: string; ssh?: { host?: string }; telnet?: { host?: string }; serial?: { host?: string } }
type DeviceLike = { name?: string; can_connect_telnet?: boolean; can_connect_ssh?: boolean; can_connect_serial?: boolean }
type Protocol = 'ssh' | 'telnet' | 'serial'
type CloseMode = 'current' | 'left' | 'right' | 'others' | 'all'
type SplitDirection = 'left' | 'right' | 'top' | 'bottom'

const props = defineProps<{
  deviceMenu: DeviceMenu | null
  sessionMenu: SessionMenu | null
  profileFor: (deviceId: string) => ProfileLike | undefined
  deviceFor: (deviceId: string) => DeviceLike | undefined
  sessionDevice: (session: SessionSummary) => DeviceLike | null | undefined
  profileCanConnect: (profile: ProfileLike, protocol: Protocol) => boolean
  canCloseDeviceSessions: (deviceId: string, mode: CloseMode) => boolean
  canSplitDevice: (deviceId: string) => boolean
  canReconnectSession: (session: SessionSummary) => boolean
  canDisconnectSession: (session: SessionSummary) => boolean
  canCloseSessionRelative: (session: SessionSummary, mode: CloseMode) => boolean
  canSplitSession: (session: SessionSummary) => boolean
  sessionKindLabel: (kind: string) => string
  sessionStatusLabel: (status: string) => string
  opening: boolean
  sessionActionId?: string
  terminalSplitActive: boolean
  handleKeydown: (event: KeyboardEvent, element: HTMLElement | null, restore: () => void) => void
  restoreDeviceMenu: () => void
  restoreSessionMenu: () => void
  openDeviceSession: (protocol: Protocol) => void
  locateDevice: () => void
  closeDevice: (mode: CloseMode) => void
  splitDevice: (direction: SplitDirection) => void
  resetSplit: () => void
  reconnectOrDisconnect: (action: 'reconnect' | 'disconnect') => void
  copySessionInfo: () => void
  openDuplicateSession: (protocol: Protocol) => void
  locateSession: (session: SessionSummary) => void
  closeSession: (mode: CloseMode) => void
  splitSession: (direction: SplitDirection) => void
}>()
const emit = defineEmits<{
  'update:deviceMenu': [value: DeviceMenu | null]
  'update:sessionMenu': [value: SessionMenu | null]
}>()

const deviceMenuElement = ref<HTMLElement | null>(null)
const sessionMenuElement = ref<HTMLElement | null>(null)
const deviceMenuModel = computed({
  get: () => props.deviceMenu,
  set: (value) => emit('update:deviceMenu', value)
})
const sessionMenuModel = computed({
  get: () => props.sessionMenu,
  set: (value) => emit('update:sessionMenu', value)
})
useContextMenuPlacement(deviceMenuModel, deviceMenuElement)
useContextMenuPlacement(sessionMenuModel, sessionMenuElement)
</script>

<template>
  <div v-if="deviceMenu" ref="deviceMenuElement" class="session-context-menu session-device-context-menu" role="menu" :style="{ left: `${deviceMenu.x}px`, top: `${deviceMenu.y}px` }" @click.stop @keydown="handleKeydown($event, deviceMenuElement, restoreDeviceMenu)">
    <p>{{ profileFor(deviceMenu.deviceId)?.name || deviceFor(deviceMenu.deviceId)?.name || deviceMenu.deviceId }}<small>{{ profileFor(deviceMenu.deviceId) ? (profileFor(deviceMenu.deviceId)?.profile_type === 'server' ? '服务器配置' : '临时连接') : '设备会话组' }}</small></p>
    <button type="button" role="menuitem" @click="locateDevice">{{ profileFor(deviceMenu.deviceId) ? '定位到连接配置' : '定位到设备列表' }}</button>
    <template v-if="profileFor(deviceMenu.deviceId)">
      <button v-if="profileFor(deviceMenu.deviceId)?.ssh?.host" type="button" role="menuitem" :disabled="!profileCanConnect(profileFor(deviceMenu.deviceId)!, 'ssh') || opening" @click="openDeviceSession('ssh')">新建 SSH 会话</button>
      <button v-if="profileFor(deviceMenu.deviceId)?.telnet?.host" type="button" role="menuitem" :disabled="!profileCanConnect(profileFor(deviceMenu.deviceId)!, 'telnet') || opening" @click="openDeviceSession('telnet')">新建 Telnet 会话</button>
      <button v-if="profileFor(deviceMenu.deviceId)?.serial?.host" type="button" role="menuitem" :disabled="!profileCanConnect(profileFor(deviceMenu.deviceId)!, 'serial') || opening" @click="openDeviceSession('serial')">新建串口会话</button>
    </template>
    <template v-else-if="deviceFor(deviceMenu.deviceId)">
      <button v-if="deviceFor(deviceMenu.deviceId)?.can_connect_telnet" type="button" role="menuitem" :disabled="opening" @click="openDeviceSession('telnet')">新建设备管理口会话</button>
      <button v-if="deviceFor(deviceMenu.deviceId)?.can_connect_ssh" type="button" role="menuitem" :disabled="opening" @click="openDeviceSession('ssh')">新建 Linux 后台会话</button>
      <button v-if="deviceFor(deviceMenu.deviceId)?.can_connect_serial" type="button" role="menuitem" :disabled="opening" @click="openDeviceSession('serial')">新建串口会话</button>
    </template>
    <hr />
    <button type="button" role="menuitem" :disabled="!canCloseDeviceSessions(deviceMenu.deviceId, 'current')" @click="closeDevice('current')">关闭此设备全部会话</button>
    <button v-if="canCloseDeviceSessions(deviceMenu.deviceId, 'others')" type="button" role="menuitem" @click="closeDevice('others')">关闭其他设备会话</button>
    <button v-if="canCloseDeviceSessions(deviceMenu.deviceId, 'others')" type="button" role="menuitem" @click="closeDevice('all')">关闭所有设备会话</button>
    <template v-if="canSplitDevice(deviceMenu.deviceId)">
      <hr />
      <button v-for="direction in (['left', 'right', 'top', 'bottom'] as SplitDirection[])" :key="direction" type="button" role="menuitem" @click="splitDevice(direction)">{{ { left: '分屏到左侧', right: '分屏到右侧', top: '分屏到上方', bottom: '分屏到下方' }[direction] }}</button>
    </template>
    <button v-if="terminalSplitActive" type="button" role="menuitem" @click="resetSplit">退出分屏</button>
  </div>

  <div v-if="sessionMenu" ref="sessionMenuElement" class="session-context-menu" role="menu" :style="{ left: `${sessionMenu.x}px`, top: `${sessionMenu.y}px` }" @click.stop @keydown="handleKeydown($event, sessionMenuElement, restoreSessionMenu)">
    <p>{{ sessionMenu.session.title }}<small>{{ sessionKindLabel(sessionMenu.session.kind) }} · {{ sessionStatusLabel(sessionMenu.session.status) }}</small></p>
    <button v-if="canReconnectSession(sessionMenu.session)" type="button" role="menuitem" :disabled="sessionActionId === sessionMenu.session.id" @click="reconnectOrDisconnect('reconnect')">重新连接</button>
    <button v-else-if="canDisconnectSession(sessionMenu.session)" type="button" role="menuitem" :disabled="sessionActionId === sessionMenu.session.id" @click="reconnectOrDisconnect('disconnect')">断开连接</button>
    <button type="button" role="menuitem" @click="copySessionInfo">复制会话信息</button>
    <template v-if="profileFor(sessionMenu.session.device_id)">
      <button v-if="profileFor(sessionMenu.session.device_id)?.ssh?.host" type="button" role="menuitem" :disabled="opening" @click="openDuplicateSession('ssh')">新建 SSH 页签</button>
      <button v-if="profileFor(sessionMenu.session.device_id)?.telnet?.host" type="button" role="menuitem" :disabled="opening" @click="openDuplicateSession('telnet')">新建 Telnet 页签</button>
      <button v-if="profileFor(sessionMenu.session.device_id)?.serial?.host" type="button" role="menuitem" :disabled="opening" @click="openDuplicateSession('serial')">新建串口页签</button>
    </template>
    <button v-if="sessionDevice(sessionMenu.session) || profileFor(sessionMenu.session.device_id)" type="button" role="menuitem" @click="locateSession(sessionMenu.session)">{{ profileFor(sessionMenu.session.device_id) ? '定位到连接配置' : '定位到设备列表' }}</button>
    <hr />
    <button type="button" role="menuitem" @click="closeSession('current')">{{ sessionMenu.source === 'tab' ? '关闭当前页签' : '关闭会话' }}</button>
    <button v-if="sessionMenu.source === 'tab' && canCloseSessionRelative(sessionMenu.session, 'left')" type="button" role="menuitem" @click="closeSession('left')">关闭左侧页签</button>
    <button v-if="sessionMenu.source === 'tab' && canCloseSessionRelative(sessionMenu.session, 'right')" type="button" role="menuitem" @click="closeSession('right')">关闭右侧页签</button>
    <button v-if="canCloseSessionRelative(sessionMenu.session, 'others')" type="button" role="menuitem" @click="closeSession('others')">{{ sessionMenu.source === 'tab' ? '关闭其他页签' : '关闭此设备其他会话' }}</button>
    <button v-if="canCloseSessionRelative(sessionMenu.session, 'others')" type="button" role="menuitem" @click="closeSession('all')">{{ sessionMenu.source === 'tab' ? '关闭此设备全部页签' : '关闭此设备全部会话' }}</button>
    <template v-if="canSplitSession(sessionMenu.session)">
      <hr />
      <button v-for="direction in (['left', 'right', 'top', 'bottom'] as SplitDirection[])" :key="direction" type="button" role="menuitem" @click="splitSession(direction)">{{ { left: '分屏到左侧', right: '分屏到右侧', top: '分屏到上方', bottom: '分屏到下方' }[direction] }}</button>
    </template>
    <button v-if="terminalSplitActive" type="button" role="menuitem" @click="resetSplit">退出分屏</button>
  </div>
</template>
