<script setup lang="ts">
import {
  Cable, CircleAlert, CircleCheck, KeyRound, MonitorDot, Plug, Plus, RefreshCw,
  ServerCog, SquareTerminal, X
} from 'lucide-vue-next'
import QuickActionsBar from './QuickActionsBar.vue'
import CommandWorkspace from './CommandWorkspace.vue'
import SessionContextMenus from './SessionContextMenus.vue'
import TerminalSplitWorkspace from './TerminalSplitWorkspace.vue'

type SessionWorkspaceContext = Record<string, any>
const props = defineProps<{ context: SessionWorkspaceContext }>()
const {
  workflowPanelOpen, terminalSplitActive, sessionTabLayout, sessionTabRailCollapsed,
  workspace, liveWorkspaceTitle, sessionDeviceGroups, activeSessionDeviceId,
  startDeviceTabDrag, openDeviceSessionTabContextMenu, sessionHealthLabel,
  sessionHealthShortLabel, activateSessionDevice, handleDeviceSessionTabKeydown,
  closeSessionDevice, backendFailure, retryWorkspaceRecovery, workspaceRecoveryBusy,
  activeDeviceSessions, activeProtocolLabels, startSessionTabDrag,
  openSessionContextMenu, handleSessionTabKeydown, activateSession,
  sessionManagerDeviceContextMenu, sessionContextMenu, profileById, deviceById,
  sessionDevice, profileCanConnect, canCloseDeviceSessions, canSplitDevice,
  canReconnectSession, canDisconnectSession, canCloseSessionRelative,
  canSplitSession, sessionKindLabel, sessionStatusLabel, handleContextMenuKeydown,
  closeSessionManagerDeviceContextMenuAndRestoreFocus,
  closeSessionContextMenuAndRestoreFocus, openSessionManagerDeviceSession,
  locateSessionManagerDevice, runSessionManagerDeviceClose, splitDeviceFromContext,
  resetTerminalSplit, runSessionConnectionAction, copySessionInfoFromContext,
  openDuplicateProfileSessionFromContext, locateSessionDevice, runSessionContextClose,
  splitSessionFromContext, workspaceRecoveryBusy: recoveryBusy,
  setTerminalSplitWorkspace, protocolActionsBySession, openOrActivateDeviceProtocol,
  updateTerminalSplitState, openSessionTransfer, openSessionUpgrade,
  activeSection, availableDeviceProtocols, openDeviceProtocolSession, selectedProfile,
  profileCanConnect: canConnectProfile, openWorkflowRunDialog
} = props.context
</script>

<template>
<main v-show="!workflowPanelOpen" class="workspace-stage">
  <header
    v-if="!terminalSplitActive"
    class="workspace-header"
    :class="{ 'has-device-tabs': workspace.sessions.length && sessionTabLayout === 'top' }"
  >
    <div
      v-if="!workspace.sessions.length || sessionTabLayout !== 'top'"
      class="workspace-title-block"
    >
      <p class="eyebrow">LIVE WORKSPACE</p>
      <h2 data-testid="live-workspace-title">{{ liveWorkspaceTitle }}</h2>
    </div>
    <div
      v-if="workspace.sessions.length && sessionTabLayout === 'top' && !terminalSplitActive"
      class="device-session-tabs"
      role="tablist"
      aria-label="设备会话"
    >
      <div
        v-for="group in sessionDeviceGroups"
        :key="group.id"
        class="device-session-tab"
        :class="{ active: group.id === activeSessionDeviceId }"
        :data-device-tab-id="group.id"
        draggable="true"
        @dragstart="startDeviceTabDrag($event, group.id)"
        @contextmenu.prevent="openDeviceSessionTabContextMenu($event, group.id)"
      >
        <button
          class="device-session-tab-select"
          type="button"
          role="tab"
          :title="`${group.sourceLabel} · ${group.label} · ${group.sessions.length} 个终端 · ${sessionHealthLabel(group.health)}`"
          :aria-label="`${group.sourceLabel}，${group.label}，${group.sessions.length} 个终端，${sessionHealthLabel(group.health)}`"
          :aria-selected="group.id === activeSessionDeviceId"
          @click="activateSessionDevice(group.id)"
          @keydown="handleDeviceSessionTabKeydown($event, group.id)"
        >
          <span
            class="device-session-source"
            :data-source="group.sourceKind"
            :title="group.sourceLabel"
            :aria-label="group.sourceLabel"
          >
            <MonitorDot v-if="group.sourceKind === 'device'" :size="11" />
            <Cable v-else-if="group.sourceKind === 'temporary'" :size="11" />
            <ServerCog v-else-if="group.sourceKind === 'server'" :size="11" />
            <SquareTerminal v-else :size="11" />
          </span>
          <span class="device-session-label" :data-testid="group.id === activeSessionDeviceId ? 'live-workspace-title' : undefined">{{ group.label }}</span>
          <em class="device-session-health-label" :data-state="group.health">{{ sessionHealthShortLabel(group.health) }}</em>
          <small>{{ group.sessions.length }}</small>
        </button>
        <button
          class="tab-close"
          type="button"
          :aria-label="`关闭 ${group.label} 的全部终端`"
          @click.stop="closeSessionDevice(group.id)"
        ><X :size="13" /></button>
      </div>
    </div>
  </header>

  <div v-if="backendFailure" class="system-banner" data-state="backend" role="alert">
    <CircleAlert :size="15" aria-hidden="true" />
    <div>
      <strong>Python 后端连接中断</strong>
      <span>{{ backendFailure }}。应用正在自动恢复服务，也可以立即重试。</span>
    </div>
    <button type="button" title="立即重试工作区" :disabled="workspaceRecoveryBusy" @click="retryWorkspaceRecovery">
      <RefreshCw :class="{ 'spinning-icon': workspaceRecoveryBusy }" :size="13" aria-hidden="true" />
      {{ workspaceRecoveryBusy ? '重试中…' : '立即重试' }}
    </button>
  </div>
  <div v-if="workspace.error && !backendFailure" class="system-banner" role="alert">
    <CircleAlert :size="15" aria-hidden="true" />
    <div>
      <strong>工作区载入失败</strong>
      <span>{{ workspace.error }}</span>
    </div>
    <button type="button" title="立即重试工作区" :disabled="workspaceRecoveryBusy" @click="retryWorkspaceRecovery">
      <RefreshCw :class="{ 'spinning-icon': workspaceRecoveryBusy }" :size="13" aria-hidden="true" />
      {{ workspaceRecoveryBusy ? '重试中…' : '重新载入' }}
    </button>
  </div>
  <div
    class="session-workspace"
    :class="{ empty: !workspace.sessions.length }"
    :data-tab-layout="terminalSplitActive ? 'split' : sessionTabLayout"
    :data-tab-collapsed="sessionTabLayout === 'side' && sessionTabRailCollapsed ? 'true' : 'false'"
  >
  <template v-if="workspace.sessions.length && sessionTabLayout === 'top' && !terminalSplitActive">
  <div class="session-tabs session-child-tabs" role="tablist" :aria-label="`${liveWorkspaceTitle} 的终端会话`">
    <div
      v-for="session in activeDeviceSessions"
      :key="session.id"
      class="session-tab"
      :class="{ active: session.id === workspace.activeSessionId }"
      :data-session-tab-id="session.id"
      draggable="true"
      @dragstart="startSessionTabDrag($event, session)"
      @contextmenu.prevent="openSessionContextMenu($event, session)"
    >
      <button
        class="session-tab-select"
        type="button"
        role="tab"
        :aria-label="`${liveWorkspaceTitle} ${activeProtocolLabels[session.id]}，${sessionStatusLabel(session.status)}`"
        :title="`${liveWorkspaceTitle} · ${activeProtocolLabels[session.id]} · ${sessionStatusLabel(session.status)}`"
        :aria-selected="session.id === workspace.activeSessionId"
        @click="activateSession(session.id)"
        @keydown="handleSessionTabKeydown($event, session)"
      >
        <i :data-state="session.status" aria-hidden="true"></i>
        <span>{{ activeProtocolLabels[session.id] }}</span>
      </button>
      <button
        class="tab-close"
        type="button"
        aria-label="关闭会话"
        @click="workspace.closeSession(session.id)"
      ><X :size="13" /></button>
    </div>
  </div>
  </template>
  <SessionContextMenus
    v-model:device-menu="sessionManagerDeviceContextMenu"
    v-model:session-menu="sessionContextMenu"
    :profile-for="(deviceId) => profileById.get(deviceId)"
    :device-for="(deviceId) => deviceById.get(deviceId)"
    :session-device="sessionDevice"
    :profile-can-connect="(profile, protocol) => profileCanConnect(profile as any, protocol)"
    :can-close-device-sessions="canCloseDeviceSessions"
    :can-split-device="canSplitDevice"
    :can-reconnect-session="canReconnectSession"
    :can-disconnect-session="canDisconnectSession"
    :can-close-session-relative="canCloseSessionRelative"
    :can-split-session="canSplitSession"
    :session-kind-label="sessionKindLabel"
    :session-status-label="sessionStatusLabel"
    :opening="Boolean(workspace.openingKind)"
    :session-action-id="workspace.sessionActionId"
    :terminal-split-active="terminalSplitActive"
    :handle-keydown="handleContextMenuKeydown"
    :restore-device-menu="closeSessionManagerDeviceContextMenuAndRestoreFocus"
    :restore-session-menu="closeSessionContextMenuAndRestoreFocus"
    :open-device-session="openSessionManagerDeviceSession"
    :locate-device="locateSessionManagerDevice"
    :close-device="runSessionManagerDeviceClose"
    :split-device="splitDeviceFromContext"
    :reset-split="resetTerminalSplit"
    :reconnect-or-disconnect="runSessionConnectionAction"
    :copy-session-info="copySessionInfoFromContext"
    :open-duplicate-session="openDuplicateProfileSessionFromContext"
    :locate-session="locateSessionDevice"
    :close-session="runSessionContextClose"
    :split-session="splitSessionFromContext"
  />

  <TerminalSplitWorkspace
    v-if="workspace.activeSession"
    :ref="setTerminalSplitWorkspace"
    :active="Boolean(workspace.activeSession)"
    :sessions="workspace.sessions"
    :active-session-id="workspace.activeSessionId"
    :protocol-actions-by-session="protocolActionsBySession"
    @activate="activateSession"
    @open-protocol="openOrActivateDeviceProtocol"
    @status="workspace.updateSessionStatus"
    @transfer="openSessionTransfer"
    @upgrade="openSessionUpgrade"
    @close="workspace.closeSession"
    @session-context="openSessionContextMenu"
    @device-context="openDeviceSessionTabContextMenu"
    @split-change="updateTerminalSplitState"
  />
  <section v-if="!workspace.activeSession" class="empty-workspace">
    <div class="empty-icon">
      <MonitorDot v-if="activeSection === 'devices'" :size="26" />
      <ServerCog v-else :size="26" />
    </div>
    <h3 v-if="activeSection === 'devices'">{{ workspace.selectedDevice ? `${workspace.selectedDevice.name} 已就绪` : '准备开始设备会话' }}</h3>
    <h3 v-else>准备打开连接配置</h3>
    <p v-if="activeSection === 'devices'">{{ workspace.selectedDevice ? '选择连接方式，终端将在右侧打开。' : '从左侧选择设备并创建终端。' }}</p>
    <p v-else>从左侧选择连接配置。凭据由 Python 后端从操作系统凭据库读取，不会随配置列表返回。</p>
    <div v-if="activeSection === 'devices'" class="empty-workspace-context" aria-label="首个终端目标">
      <span>连接目标</span>
      <strong>{{ workspace.selectedDevice?.name || '尚未选择设备' }}</strong>
      <div v-if="availableDeviceProtocols.length" class="empty-workspace-endpoints" aria-label="可用连接协议">
        <small v-for="protocol in availableDeviceProtocols" :key="protocol.kind" class="empty-workspace-endpoint">
          {{ protocol.label }} · {{ protocol.endpoint }}
        </small>
      </div>
      <em v-else>当前设备没有可用连接协议</em>
    </div>
    <div v-if="activeSection === 'devices'" class="empty-workspace-actions" aria-label="选择连接方式">
      <button
        v-for="protocol in availableDeviceProtocols"
        :key="protocol.kind"
        class="primary-button empty-workspace-protocol"
        type="button"
        :disabled="Boolean(workspace.openingKind)"
        :title="`使用 ${protocol.label} 打开 ${workspace.selectedDevice?.name || '设备'}`"
        @click="openDeviceProtocolSession(protocol.kind)"
      >
        <KeyRound v-if="protocol.kind === 'ssh'" :size="15" />
        <Cable v-else-if="protocol.kind === 'telnet'" :size="15" />
        <Plug v-else :size="15" />
        <span>{{ workspace.openingKind === protocol.kind ? '正在连接…' : `打开 ${protocol.label}` }}</span>
      </button>
      <span v-if="workspace.selectedDevice && !availableDeviceProtocols.length" class="empty-workspace-unavailable">暂无可用连接</span>
    </div>
    <button
      v-else
      class="primary-button"
      type="button"
      :disabled="!selectedProfile || !profileCanConnect(selectedProfile)"
      @click="selectedProfile && workspace.openProfileSession(selectedProfile)"
    >
      <Plus :size="16" />连接
    </button>
  </section>
  </div>
  <QuickActionsBar
    ref="quickActionsBarRef"
    @run-workflow="openWorkflowRunDialog(workspace.selectedDeviceId, $event.workflowId, undefined, $event.autoRun)"
  />
  <CommandWorkspace />
</main>
</template>
