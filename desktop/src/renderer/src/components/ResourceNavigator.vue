<script setup lang="ts">
import {
  Cable, ChevronDown, ChevronRight, CircleAlert, Database, FileUp, FileSpreadsheet,
  FolderPlus, Globe2, KeyRound, LogIn, LogOut, MonitorDot, PanelLeftClose, Pencil, Plug,
  Play, Plus, RefreshCw, Search, SearchX, ServerCog, SquareTerminal, Trash2, UserRound
} from 'lucide-vue-next'
import CompactSelect from './CompactSelect.vue'

type ResourceNavigatorContext = Record<string, any>
const props = defineProps<{ context: ResourceNavigatorContext }>()
const workspace = props.context.workspace as { profileGroups: string[] } & Record<string, any>
const {
  activeSection, activeDeviceSource, importDeviceSource, defaultDeviceSource,
  deviceDomainFilterOptions, deviceStatusFilterOptions, navigatorVisible, operationPanelOpen,
  showSessionSidebar, navigatorDetailCollapsed, selectedProfile, selectedProfileId,
  visibleProfiles, visibleProfileGroupCount, visibleProfileCredentialCount,
  groupedServerProfiles, statusCounts, deviceListElement, virtualDeviceTopHeight,
  virtualDeviceBottomHeight, renderedDevices, virtualDeviceStart, profileGroupCollapsed,
  availableDeviceProtocols, navigatorMaxWidth, effectiveNavigatorWidth, navigatorResizing,
  NAVIGATOR_MIN_WIDTH, profileCanConnect, deviceSourceLabel, statusKind, sessionKindLabel,
  recommendedSessionKind, endpointHost, copyableSerialText, deviceRowCopyText,
  deviceConnectionCopyText, visibleDeviceFieldValue, dynamicDeviceFieldValue,
  setNavigatorVisible, openLocalTerminal, setSection, showGroupDialog, showProfileDialog,
  switchDeviceSource, chooseDeviceImport, restoreDefaultDeviceSource, showInternalLogin,
  logoutInternalService, toggleNavigatorDetail, selectDevice, handleDeviceListScroll,
  handleDeviceTableKeydown, openDeviceContextMenu, openProfileContextMenu,
  handleProfileKeydown, openProfileIfReady, toggleProfileGroup, openDeviceInspectorContextMenu,
  handleDeviceInspectorKeydown, copyDeviceInspectorField, connectionDisabledReason,
  openWorkflowRunDialog, openDeviceProtocolSession, workspaceRecoveryBusy,
  openDeviceContextSimulatedSession, openDeviceContextRecommendedSession,
  openDeviceContextSession, canSplitDevice, splitDeviceById, closeDeviceContextMenu,
  copyDeviceText, runDeviceContextAction, profileContextMenu, profileContextMenuElement,
  handleContextMenuKeydown, closeProfileContextMenuAndRestoreFocus,
  profileDefaultOpenLabel, openProfileFromContext, manageProfileCredentialFromContext,
  moveProfileToGroupFromContext, editProfileFromContext, deleteProfileFromContext,
  deleteSelectedProfile, copyProfileText, profileConnectionCopyText,
  deviceContextMenu, deviceContextMenuElement, closeDeviceContextMenuAndRestoreFocus,
  navigatorDetailCollapsed: detailCollapsed, startNavigatorResize,
  handleNavigatorResizeKeydown, resetNavigatorWidth
} = props.context
</script>

<template>
<aside v-show="navigatorVisible && !operationPanelOpen" class="navigator">
  <header class="navigator-header">
    <div>
      <h1>资源</h1>
    </div>
    <div class="navigator-actions">
      <button class="icon-button" type="button" title="打开本地终端" aria-label="打开本地终端" :disabled="Boolean(workspace.openingKind)" @click="openLocalTerminal"><SquareTerminal :size="16" /></button>
      <button v-if="activeSection === 'devices'" class="icon-button" type="button" title="刷新" :disabled="workspace.loading" @click="workspace.initialize">
        <RefreshCw :size="15" /><span class="sr-only">刷新设备</span>
      </button>
      <template v-else-if="activeSection === 'temporary' || activeSection === 'server'">
        <button v-if="activeSection === 'server'" class="icon-button" type="button" title="新建分组" @click="showGroupDialog($event)">
          <FolderPlus :size="16" /><span class="sr-only">新建服务器分组</span>
        </button>
        <button class="icon-button" type="button" title="新增连接" @click="showProfileDialog(activeSection, null, $event)">
          <Plus :size="16" /><span class="sr-only">新增连接</span>
        </button>
      </template>
      <button class="icon-button" type="button" title="隐藏设备工作台" aria-label="隐藏设备工作台" @click="setNavigatorVisible(false)">
        <PanelLeftClose :size="16" aria-hidden="true" />
      </button>
    </div>
  </header>

  <nav class="resource-tabs" aria-label="资源类型">
    <button type="button" :class="{ active: activeSection === 'devices' }" :aria-pressed="activeSection === 'devices'" @click="setSection('devices')">
      <MonitorDot :size="14" />设备
    </button>
    <button type="button" :class="{ active: activeSection === 'temporary' }" :aria-pressed="activeSection === 'temporary'" @click="setSection('temporary')">
      <Cable :size="14" />临时连接
    </button>
    <button type="button" :class="{ active: activeSection === 'server' }" :aria-pressed="activeSection === 'server'" @click="setSection('server')">
      <ServerCog :size="14" />服务器
    </button>
  </nav>

  <section
    v-if="activeSection === 'devices' && workspace.deviceSourceStatus.allow_source_switch"
    class="device-source-bar"
    aria-label="设备数据源"
  >
    <div
      class="device-source-current"
      :title="`${activeDeviceSource?.description || ''} 当前只显示这一来源的设备。`"
    >
      <span class="sr-only">当前设备来源</span>
      <span class="device-source-icon" aria-hidden="true">
        <Globe2 v-if="activeDeviceSource?.icon === 'globe'" :size="16" />
        <FileSpreadsheet v-else-if="activeDeviceSource?.icon === 'spreadsheet'" :size="16" />
        <Plug v-else-if="activeDeviceSource?.icon === 'plug'" :size="16" />
        <Database v-else :size="16" />
      </span>
      <strong>{{ activeDeviceSource?.label || '正在识别…' }}</strong>
      <b v-if="workspace.deviceSourceStatus.active_source === workspace.deviceSourceStatus.default_source">默认</b>
      <b v-else data-variant="changed">已切换</b>
    </div>
    <label class="device-source-switch">
      <span class="sr-only">切换来源</span>
      <select
        :value="workspace.deviceSourceStatus.active_source"
        :disabled="workspace.deviceSourceBusy || workspace.sessions.length > 0"
        aria-label="切换设备来源"
        @change="switchDeviceSource"
      >
        <option
          v-for="source in workspace.deviceSourceStatus.sources"
          :key="source.id"
          :value="source.id"
          :disabled="!source.available"
          :title="source.unavailable_reason"
        >{{ source.label }}{{ source.id === workspace.deviceSourceStatus.default_source ? '（默认）' : '' }}</option>
      </select>
    </label>
    <button
      v-if="importDeviceSource"
      class="secondary-button device-import-button"
      type="button"
      :disabled="workspace.deviceImportBusy || workspace.sessions.length > 0"
      @click="chooseDeviceImport($event)"
    ><FileUp :size="13" />{{ workspace.deviceSourceStatus.imported_count ? '重新导入' : '导入 Excel' }}</button>
    <div class="device-source-context">
      <small v-if="workspace.sessions.length">关闭终端后可切换来源</small>
      <small v-else-if="activeDeviceSource?.supports_import && workspace.deviceSourceStatus.imported_count">
        {{ workspace.deviceSourceStatus.imported_count }} 台设备 · {{ workspace.deviceSourceStatus.imported_file }}
      </small>
      <button
        v-if="workspace.deviceSourceStatus.active_source !== workspace.deviceSourceStatus.default_source"
        type="button"
        :disabled="workspace.deviceSourceBusy || workspace.sessions.length > 0"
        @click="restoreDefaultDeviceSource"
      >恢复默认“{{ defaultDeviceSource?.label }}”</button>
    </div>
    <p
      v-if="workspace.deviceSourceStatus.plugin_warnings.length"
      class="device-source-plugin-warning"
      role="status"
      :title="workspace.deviceSourceStatus.plugin_warnings.join('\n')"
    ><CircleAlert :size="12" />{{ workspace.deviceSourceStatus.plugin_warnings[0] }}</p>
  </section>

  <section
    v-if="activeSection === 'devices' && !workspace.deviceSourceStatus.allow_source_switch && workspace.deviceSourceStatus.allow_import"
    class="device-import-bar"
    aria-label="设备表格"
  >
    <span class="device-import-summary">
      <span class="device-source-icon" aria-hidden="true"><FileSpreadsheet :size="16" /></span>
      <span>
        <strong>{{ workspace.deviceSourceStatus.imported_count ? '设备表格' : '导入设备表格' }}</strong>
        <small v-if="workspace.deviceSourceStatus.imported_count">
          {{ workspace.deviceSourceStatus.imported_file }} · {{ workspace.deviceSourceStatus.imported_count }} 台设备
        </small>
        <small v-else>选择 Excel、CSV 或 TSV 文件开始使用</small>
      </span>
    </span>
    <button
      class="secondary-button device-import-button"
      type="button"
      :disabled="workspace.deviceImportBusy || workspace.sessions.length > 0"
      @click="chooseDeviceImport($event)"
    ><FileUp :size="13" />{{ workspace.deviceSourceStatus.imported_count ? '更新设备表' : '选择文件' }}</button>
    <small v-if="workspace.sessions.length" class="device-import-hint">关闭全部终端后才能更新设备表。</small>
  </section>

  <section v-if="activeSection === 'devices' && activeDeviceSource?.requires_login" class="internal-account-bar" :data-authenticated="workspace.internalAuthStatus.authenticated">
    <button
      class="internal-account-main"
      type="button"
      :disabled="workspace.internalAuthBusy"
      @click="showInternalLogin"
    >
      <span class="internal-account-icon" aria-hidden="true">
        <UserRound :size="16" />
      </span>
      <span class="internal-account-copy">
        <strong>{{ workspace.internalAuthStatus.authenticated ? workspace.internalAuthStatus.username : `登录${activeDeviceSource?.label || '设备网站'}` }}</strong>
        <small
          v-if="workspace.internalAuthStatus.authenticated"
          :title="`Cookie 已连接${workspace.internalAuthStatus.auto_login ? ' · 自动登录已开启' : ''}`"
        >已连接 · CID {{ workspace.internalAuthStatus.cid }}</small>
        <small
          v-else
          :title="workspace.internalAuthStatus.configured
            ? (workspace.internalAuthStatus.remembered ? '密码已安全保存 · 点击登录' : '输入账号、密码和 CID 后加载设备')
            : '当前为本地数据 · 点击查看配置要求'"
        >点击登录加载设备</small>
      </span>
      <LogIn v-if="!workspace.internalAuthStatus.authenticated" :size="15" aria-hidden="true" />
      <span v-else class="internal-account-switch">切换</span>
    </button>
    <button
      v-if="workspace.internalAuthStatus.authenticated"
      class="icon-button internal-account-logout"
      type="button"
      :title="`退出${activeDeviceSource?.label || '设备网站'}`"
      :aria-label="`退出${activeDeviceSource?.label || '设备网站'}`"
      :disabled="workspace.internalAuthBusy"
      @click="logoutInternalService"
    >
      <LogOut :size="15" />
    </button>
  </section>

  <label class="search-field">
    <Search :size="15" aria-hidden="true" />
    <input
      v-if="activeSection === 'devices'"
      v-model="workspace.query"
      type="search" aria-label="搜索设备" placeholder="搜索设备名、IP、ID、站点、机架位或型号"
    />
    <input
      v-else
      v-model="workspace.profileQuery"
      type="search"
      placeholder="搜索名称、地址、分组或备注"
    />
  </label>

  <div v-if="activeSection === 'temporary' || activeSection === 'server'" class="profile-summary-row" aria-label="连接配置统计">
    <span><b>{{ visibleProfiles.length }}</b> 个配置</span>
    <span v-if="activeSection === 'server'"><b>{{ visibleProfileGroupCount }}</b> 个分组</span>
    <span :class="visibleProfileCredentialCount ? 'ready' : 'attention'"><b>{{ visibleProfileCredentialCount }}</b> 凭据就绪</span>
  </div>

  <div v-if="activeSection === 'devices'" class="device-filter-panel" aria-label="设备筛选">
    <CompactSelect v-model="workspace.domainFilter" label="领域" :options="deviceDomainFilterOptions" />
    <CompactSelect v-model="workspace.statusFilter" label="状态" :options="deviceStatusFilterOptions" />
    <input v-model="workspace.cpuFilter" aria-label="CPU" placeholder="CPU" />
    <button
      class="filter-toggle"
      :class="{ active: workspace.mineOnly }"
      type="button"
      :aria-pressed="workspace.mineOnly"
      @click="workspace.mineOnly = !workspace.mineOnly"
    >我的 {{ workspace.myOccupancyCount }}</button>
  </div>

  <div v-if="activeSection === 'devices'" class="summary-row compact-summary" aria-label="设备统计">
    <span><b>{{ statusCounts.total }}</b> 台</span>
    <span class="idle"><b>{{ statusCounts.idle }}</b> 空闲</span>
    <span class="occupied"><b>{{ statusCounts.occupied }}</b> 占用</span>
    <span class="pipeline"><b>{{ statusCounts.pipeline }}</b> 流水线</span>
    <span class="other"><b>{{ statusCounts.other }}</b> 其他</span>
    <button
      v-if="workspace.hasActiveDeviceFilters"
      class="summary-clear"
      type="button"
      @click="workspace.clearDeviceFilters"
    >清空</button>
  </div>

  <div
    v-if="workspace.loading"
    class="navigator-loading"
    role="status"
    aria-live="polite"
    aria-label="正在载入设备"
  >
    <span class="sr-only">正在载入设备…</span>
    <div class="device-table-header" aria-hidden="true">
      <span>序号</span>
      <span>设备</span>
      <span>板类型</span>
      <span>CPU</span>
      <span>Slot</span>
      <span>状态</span>
    </div>
    <div class="device-loading-rows" aria-hidden="true">
      <div v-for="index in 7" :key="index" class="device-loading-row">
        <span><i></i></span>
        <span><i></i><i></i></span>
        <span><i></i></span>
        <span><i></i></span>
        <span><i></i></span>
        <span><i></i></span>
      </div>
    </div>
  </div>
  <div v-else-if="workspace.error && !workspace.devices.length" class="navigator-state error">
    <CircleAlert :size="18" aria-hidden="true" />
    <strong>设备列表加载失败</strong>
    <span>{{ workspace.error }}</span>
    <button class="secondary-button" type="button" :disabled="workspace.loading" @click="workspace.initialize">
      <RefreshCw :size="13" />重新加载
    </button>
  </div>
  <div
    v-else-if="activeSection === 'devices'"
    ref="deviceListElement"
    class="device-list device-table-list"
    :role="workspace.filteredDevices.length ? 'table' : 'region'"
    aria-label="设备列表"
    tabindex="0"
    @scroll="handleDeviceListScroll"
    @keydown="handleDeviceTableKeydown"
  >
    <div class="device-table-header" role="row">
      <span role="columnheader">序号</span>
      <span role="columnheader">设备</span>
      <span role="columnheader">板类型</span>
      <span role="columnheader">CPU</span>
      <span role="columnheader">Slot</span>
      <span role="columnheader">状态</span>
    </div>
    <div
      v-if="virtualDeviceTopHeight"
      class="device-virtual-spacer"
      :style="{ height: `${virtualDeviceTopHeight}px` }"
      aria-hidden="true"
    ></div>
    <div
      v-for="(device, index) in renderedDevices"
      :key="device.row_id"
      class="device-row device-table-row"
      :class="{ selected: device.row_id === workspace.selectedDeviceRowId }"
      tabindex="-1"
      role="row"
      :aria-selected="device.row_id === workspace.selectedDeviceRowId"
      :data-device-row-id="device.row_id"
      :title="device.tooltip"
      @click="selectDevice(device.row_id)"
      @contextmenu.prevent="openDeviceContextMenu($event, device)"
    >
      <span class="device-index" role="cell">{{ device.board_id || virtualDeviceStart + index + 1 }}</span>
      <span class="device-copy device-name-cell" role="cell">
        <strong>{{ device.name }}</strong>
        <small>{{ device.id }} · {{ device.site || device.domain }}</small>
      </span>
      <span class="device-cell" role="cell" :title="device.tooltip || device.board_type">{{ device.board_type || device.device_type || '—' }}</span>
      <span class="device-cell mono" role="cell" :title="device.cpu">{{ device.cpu || '—' }}</span>
      <span class="device-cell" role="cell" :title="device.tooltip || device.slot">{{ device.slot || device.rack || '—' }}</span>
      <span class="device-status-cell" role="cell">
        <i class="status-dot" :data-status="statusKind(device.status)" aria-hidden="true"></i>
        <span :title="device.tooltip || device.status_text">{{ device.status_text || device.status }}</span>
      </span>
    </div>
    <div
      v-if="virtualDeviceBottomHeight"
      class="device-virtual-spacer"
      :style="{ height: `${virtualDeviceBottomHeight}px` }"
      aria-hidden="true"
    ></div>
    <div v-if="!workspace.filteredDevices.length" class="navigator-empty-state device-table-empty" role="status">
      <SearchX :size="22" aria-hidden="true" />
      <strong>{{ workspace.hasActiveDeviceFilters ? '没有匹配的设备' : '暂无设备数据' }}</strong>
      <span>{{ workspace.hasActiveDeviceFilters ? '尝试名称、ID、站点、CPU 或调整筛选条件。' : '刷新设备列表以重新从后端加载数据。' }}</span>
      <button v-if="workspace.hasActiveDeviceFilters" class="secondary-button" type="button" @click="workspace.clearDeviceFilters">清除全部筛选</button>
      <button v-else class="secondary-button" type="button" @click="workspace.initialize"><RefreshCw :size="13" />刷新设备</button>
    </div>
  </div>
  <div v-else class="device-list profile-list" role="listbox" aria-label="连接配置列表">
    <template v-if="activeSection === 'temporary'">
      <button
        v-for="profile in visibleProfiles"
        :key="profile.id"
        class="device-row"
        :class="{ selected: profile.id === selectedProfileId }"
        type="button"
        role="option"
        :aria-selected="profile.id === selectedProfileId"
        :data-profile-row-id="profile.id"
        @click="selectedProfileId = profile.id"
        @dblclick="openProfileIfReady(profile)"
        @contextmenu.prevent="openProfileContextMenu($event, profile)"
        @keydown="handleProfileKeydown($event, profile)"
      >
        <i class="status-dot" :data-status="profile[profile.preferred_protocol].has_password ? 'idle' : 'other'" aria-hidden="true"></i>
        <span class="device-copy">
          <strong>{{ profile.name }}</strong>
          <small>{{ profile.preferred_protocol.toUpperCase() }} · {{ profile[profile.preferred_protocol].host }}</small>
        </span>
        <ChevronRight :size="15" aria-hidden="true" />
      </button>
    </template>
    <section
      v-else
      v-for="group in groupedServerProfiles"
      :key="group.name"
      class="profile-group"
      role="group"
      :aria-label="group.name"
      :data-profile-group-name="group.name"
      :data-collapsed="profileGroupCollapsed(group.name)"
    >
      <header>
        <button
          class="profile-group-toggle"
          type="button"
          :aria-expanded="!profileGroupCollapsed(group.name)"
          :aria-label="`${profileGroupCollapsed(group.name) ? '展开' : '折叠'}分组 ${group.name}`"
          @click="toggleProfileGroup(group.name)"
        >
          <span>
            <ChevronRight v-if="profileGroupCollapsed(group.name)" :size="13" aria-hidden="true" />
            <ChevronDown v-else :size="13" aria-hidden="true" />
            {{ group.name }}
          </span>
          <b>{{ group.profiles.length }}</b>
        </button>
      </header>
      <div v-show="!profileGroupCollapsed(group.name)" class="profile-group-items">
        <button
          v-for="profile in group.profiles"
          :key="profile.id"
          class="device-row"
          :class="{ selected: profile.id === selectedProfileId }"
          type="button"
          role="option"
          :aria-selected="profile.id === selectedProfileId"
          :data-profile-row-id="profile.id"
          @click="selectedProfileId = profile.id"
          @dblclick="openProfileIfReady(profile)"
          @contextmenu.prevent="openProfileContextMenu($event, profile)"
          @keydown="handleProfileKeydown($event, profile)"
        >
          <i class="status-dot" :data-status="profile.ssh.has_password ? 'idle' : 'other'" aria-hidden="true"></i>
          <span class="device-copy">
            <strong>{{ profile.name }}</strong>
            <small>SSH · {{ profile.ssh.host }}:{{ profile.ssh.port }}</small>
          </span>
          <ChevronRight :size="15" aria-hidden="true" />
        </button>
        <p v-if="!group.profiles.length" class="empty-group">空分组</p>
      </div>
    </section>
    <div v-if="!visibleProfiles.length && (activeSection === 'temporary' || !groupedServerProfiles.length)" class="navigator-empty-state" role="status">
      <SearchX v-if="workspace.profileQuery" :size="22" aria-hidden="true" />
      <ServerCog v-else :size="22" aria-hidden="true" />
      <strong>{{ workspace.profileQuery ? '没有匹配的连接配置' : '还没有连接配置' }}</strong>
      <span>{{ workspace.profileQuery ? '尝试名称、地址、分组或备注中的关键词。' : '创建配置后，可直接打开 SSH、Telnet 或串口会话。' }}</span>
      <button v-if="workspace.profileQuery" class="secondary-button" type="button" @click="workspace.profileQuery = ''">清除搜索</button>
      <button v-else class="primary-button" type="button" @click="showProfileDialog(activeSection, null, $event)"><Plus :size="13" />新增连接</button>
    </div>
  </div>
  <section
    class="navigator-detail"
    :class="{ collapsed: navigatorDetailCollapsed }"
    :data-collapsed="navigatorDetailCollapsed ? 'true' : 'false'"
    aria-label="设备与连接详情"
  >
    <header class="navigator-detail-header">
      <div>
        <p class="eyebrow">{{ activeSection === 'devices' ? 'DEVICE DETAIL' : 'CONNECTION DETAIL' }}</p>
        <strong>{{ activeSection === 'devices' ? '设备详情' : '连接详情' }}</strong>
      </div>
      <button
        class="icon-button"
        type="button"
        :title="navigatorDetailCollapsed ? '展开详情' : '折叠详情'"
        :aria-label="navigatorDetailCollapsed ? '展开详情' : '折叠详情'"
        :aria-expanded="!navigatorDetailCollapsed"
        @click="toggleNavigatorDetail"
      >
        <ChevronRight v-if="navigatorDetailCollapsed" :size="15" />
        <ChevronDown v-else :size="15" />
      </button>
    </header>
    <div v-if="!navigatorDetailCollapsed" class="navigator-detail-content">
      <template v-if="activeSection === 'devices' && workspace.selectedDevice">
        <section
          class="device-identity"
          tabindex="0"
          title="右键打开设备快捷操作"
          @contextmenu.prevent="openDeviceInspectorContextMenu($event, workspace.selectedDevice)"
          @keydown="handleDeviceInspectorKeydown($event, workspace.selectedDevice)"
        >
          <div class="device-avatar"><ServerCog :size="21" /></div>
          <div>
            <strong>{{ workspace.selectedDevice.name }}</strong>
            <span>{{ workspace.selectedDevice.vendor }} {{ workspace.selectedDevice.model }} · {{ deviceSourceLabel(workspace.selectedDevice) }}</span>
          </div>
          <button
            v-if="!workspace.selectedDevice.can_release"
            class="primary-button device-lease-button"
            type="button"
            :disabled="!workspace.selectedDevice.can_claim || Boolean(workspace.deviceAction)"
            :title="workspace.selectedDevice.can_claim ? '占用设备' : '当前设备不可占用或已被占用'"
            @click="workspace.runDeviceAction('claim')"
          >占用</button>
          <button
            v-else
            class="secondary-button device-lease-button"
            type="button"
            :disabled="!workspace.selectedDevice.can_release || Boolean(workspace.deviceAction)"
            :title="workspace.selectedDevice.can_release ? '释放设备' : '只有我的占用设备可释放'"
            @click="workspace.runDeviceAction('release')"
          >释放</button>
          <button
            class="secondary-button device-workflow-action"
            type="button"
            title="运行已发布 Workflow"
            @click="openWorkflowRunDialog(workspace.selectedDeviceId)"
          ><Play :size="13" />运行 Workflow</button>
        </section>
        <section class="device-connection-panel" aria-label="当前设备连接">
          <header>
            <div>
              <span>管理地址</span>
              <strong class="mono">{{ workspace.selectedDevice.telnet_endpoint || workspace.selectedDevice.ssh_endpoint || workspace.selectedDevice.serial_endpoint || '连接时输入 IP 和端口' }}</strong>
            </div>
            <small>IP、端口、账号、密码均可修改</small>
          </header>
          <div v-if="!workspace.selectedDevice.is_simulated" class="device-protocol-list">
            <div class="device-protocol-action" data-protocol="ssh">
              <button class="device-protocol-connect" type="button" :disabled="Boolean(connectionDisabledReason(workspace.selectedDevice, 'ssh')) || Boolean(workspace.openingKind)" :title="connectionDisabledReason(workspace.selectedDevice, 'ssh') || '一键连接 SSH'" @click="workspace.openSession('ssh')">
                <span><b>SSH</b><small class="mono">{{ workspace.selectedDevice.ssh_endpoint || '未配置' }}</small></span><ChevronRight :size="15" aria-hidden="true" />
              </button>
              <button class="device-protocol-edit" type="button" :disabled="Boolean(workspace.openingKind)" title="编辑 SSH 的 IP、端口、账号和密码" aria-label="编辑 SSH 连接" @click="workspace.openCustomDeviceSession(workspace.selectedDevice, 'ssh')"><Pencil :size="13" /></button>
            </div>
            <div class="device-protocol-action" data-protocol="telnet">
              <button class="device-protocol-connect" type="button" :disabled="Boolean(connectionDisabledReason(workspace.selectedDevice, 'telnet')) || Boolean(workspace.openingKind)" :title="connectionDisabledReason(workspace.selectedDevice, 'telnet') || '一键连接 Telnet'" @click="workspace.openSession('telnet')">
                <span><b>Telnet</b><small class="mono">{{ workspace.selectedDevice.telnet_endpoint || '未配置' }}</small></span><ChevronRight :size="15" aria-hidden="true" />
              </button>
              <button class="device-protocol-edit" type="button" :disabled="Boolean(workspace.openingKind)" title="编辑 Telnet 的 IP、端口、账号和密码" aria-label="编辑 Telnet 连接" @click="workspace.openCustomDeviceSession(workspace.selectedDevice, 'telnet')"><Pencil :size="13" /></button>
            </div>
            <div class="device-protocol-action" data-protocol="serial">
              <button class="device-protocol-connect" type="button" :disabled="Boolean(connectionDisabledReason(workspace.selectedDevice, 'serial')) || Boolean(workspace.openingKind)" :title="connectionDisabledReason(workspace.selectedDevice, 'serial') || '一键连接串口'" @click="workspace.openSession('serial')">
                <span><b>串口</b><small class="mono">{{ workspace.selectedDevice.serial_endpoint || '未配置' }}</small></span><ChevronRight :size="15" aria-hidden="true" />
              </button>
              <button class="device-protocol-edit" type="button" :disabled="Boolean(workspace.openingKind)" title="编辑串口的 IP、端口、账号和密码" aria-label="编辑串口连接" @click="workspace.openCustomDeviceSession(workspace.selectedDevice, 'serial')"><Pencil :size="13" /></button>
            </div>
          </div>
          <button v-else class="primary-button simulated-connect-button" type="button" :disabled="Boolean(workspace.openingKind)" @click="workspace.openSimulatedSession"><MonitorDot :size="14" />打开模拟终端</button>
        </section>
        <dl
          class="property-list copyable-property-list"
          tabindex="0"
          title="右键打开设备快捷操作"
          @contextmenu.prevent="openDeviceInspectorContextMenu($event, workspace.selectedDevice)"
          @keydown="handleDeviceInspectorKeydown($event, workspace.selectedDevice)"
        >
          <div>
            <dt>状态</dt>
            <dd>
              <span class="status-pill" :data-status="statusKind(workspace.selectedDevice.status)" :title="workspace.selectedDevice.tooltip">{{ workspace.selectedDevice.status_text || workspace.selectedDevice.status }}</span>
              <button class="property-copy-button" type="button" title="复制状态" @click="copyDeviceInspectorField('状态', workspace.selectedDevice.status_text || workspace.selectedDevice.status)">复制</button>
            </dd>
          </div>
          <div>
            <dt>占用人</dt>
            <dd>
              <span>{{ workspace.selectedDevice.owner || '未占用' }}</span>
              <button class="property-copy-button" type="button" title="复制占用人" @click="copyDeviceInspectorField('占用人', workspace.selectedDevice.owner || '未占用')">复制</button>
            </dd>
          </div>
          <div>
            <dt>设备ID</dt>
            <dd>
              <span>{{ workspace.selectedDevice.id }}</span>
              <button class="property-copy-button" type="button" title="复制设备ID" @click="copyDeviceInspectorField('设备ID', workspace.selectedDevice.id)">复制</button>
            </dd>
          </div>
          <div>
            <dt>位置</dt>
            <dd>
              <span>{{ workspace.selectedDevice.site }} / {{ workspace.selectedDevice.slot || workspace.selectedDevice.rack }}</span>
              <button class="property-copy-button" type="button" title="复制位置" @click="copyDeviceInspectorField('位置', `${visibleDeviceFieldValue(workspace.selectedDevice.site)} / ${visibleDeviceFieldValue(workspace.selectedDevice.slot || workspace.selectedDevice.rack)}`)">复制</button>
            </dd>
          </div>
        </dl>
        <details :key="workspace.selectedDevice.row_id" class="device-more-details">
          <summary><span>更多设备信息</span><ChevronDown :size="14" aria-hidden="true" /></summary>
          <dl
            class="property-list copyable-property-list extended-property-list"
            tabindex="0"
            title="右键打开设备快捷操作"
            @contextmenu.prevent="openDeviceInspectorContextMenu($event, workspace.selectedDevice)"
            @keydown="handleDeviceInspectorKeydown($event, workspace.selectedDevice)"
          >
            <div>
              <dt>板类型</dt>
              <dd><span>{{ workspace.selectedDevice.board_type || workspace.selectedDevice.device_type || '—' }}</span><button class="property-copy-button" type="button" title="复制板类型" @click="copyDeviceInspectorField('板类型', workspace.selectedDevice.board_type || workspace.selectedDevice.device_type || '—')">复制</button></dd>
            </div>
            <div>
              <dt>区域</dt>
              <dd><span>{{ workspace.selectedDevice.domain || '—' }}</span><button class="property-copy-button" type="button" title="复制区域" @click="copyDeviceInspectorField('区域', visibleDeviceFieldValue(workspace.selectedDevice.domain))">复制</button></dd>
            </div>
            <div>
              <dt>CPU</dt>
              <dd><span>{{ workspace.selectedDevice.cpu || '—' }}</span><button class="property-copy-button" type="button" title="复制CPU" @click="copyDeviceInspectorField('CPU', visibleDeviceFieldValue(workspace.selectedDevice.cpu))">复制</button></dd>
            </div>
            <div>
              <dt>版本</dt>
              <dd><span>{{ workspace.selectedDevice.version || '—' }}</span><button class="property-copy-button" type="button" title="复制版本" @click="copyDeviceInspectorField('版本', visibleDeviceFieldValue(workspace.selectedDevice.version))">复制</button></dd>
            </div>
            <div>
              <dt>SSH</dt>
              <dd class="mono"><span>{{ workspace.selectedDevice.ssh_endpoint || '—' }}</span><button class="property-copy-button" type="button" title="复制 SSH" @click="copyDeviceInspectorField('SSH', visibleDeviceFieldValue(workspace.selectedDevice.ssh_endpoint))">复制</button></dd>
            </div>
            <div>
              <dt>Telnet</dt>
              <dd class="mono"><span>{{ workspace.selectedDevice.telnet_endpoint || '—' }}</span><button class="property-copy-button" type="button" title="复制 Telnet" @click="copyDeviceInspectorField('Telnet', visibleDeviceFieldValue(workspace.selectedDevice.telnet_endpoint))">复制</button></dd>
            </div>
            <div>
              <dt>串口</dt>
              <dd class="mono"><span>{{ workspace.selectedDevice.serial_display || workspace.selectedDevice.serial_endpoint || '—' }}</span><button class="property-copy-button" type="button" title="复制串口" @click="copyDeviceInspectorField('串口', visibleDeviceFieldValue(workspace.selectedDevice.serial_display || workspace.selectedDevice.serial_endpoint))">复制</button></dd>
            </div>
          </dl>
          <dl v-if="workspace.deviceFieldSchema.length" class="property-list copyable-property-list extended-property-list dynamic-property-list">
            <div v-for="field in workspace.deviceFieldSchema" :key="field.key">
              <dt>{{ field.label }}</dt>
              <dd>
                <span>{{ dynamicDeviceFieldValue(workspace.selectedDevice, field.key) }}</span>
                <button class="property-copy-button" type="button" :title="`复制${field.label}`" @click="copyDeviceInspectorField(field.label, dynamicDeviceFieldValue(workspace.selectedDevice, field.key))">复制</button>
              </dd>
            </div>
          </dl>
          <button
            class="secondary-button danger-button device-power-button"
            type="button"
            :disabled="!workspace.selectedDevice.can_power_off || Boolean(workspace.deviceAction)"
            :title="workspace.selectedDevice.can_power_off ? '设备下电' : '仅我的占用且支持下电的资产设备可操作'"
            @click="workspace.runDeviceAction('power_off')"
          >设备下电</button>
        </details>
      </template>
      <template v-else-if="(activeSection === 'temporary' || activeSection === 'server') && selectedProfile">
        <section class="device-identity">
          <div class="device-avatar"><ServerCog :size="21" /></div>
          <div>
            <strong>{{ selectedProfile.name }}</strong>
            <span>{{ selectedProfile.profile_type === 'server' ? selectedProfile.group || '未分组' : '临时连接' }} · 手动添加</span>
          </div>
        </section>
        <dl class="property-list">
          <div><dt>默认协议</dt><dd>{{ selectedProfile.preferred_protocol.toUpperCase() }}</dd></div>
          <div v-if="selectedProfile.ssh.host"><dt>SSH</dt><dd class="mono">{{ selectedProfile.ssh.host }}:{{ selectedProfile.ssh.port }}</dd></div>
          <div v-if="selectedProfile.telnet.host"><dt>Telnet</dt><dd class="mono">{{ selectedProfile.telnet.host }}:{{ selectedProfile.telnet.port }}</dd></div>
          <div v-if="selectedProfile.serial.host"><dt>串口</dt><dd class="mono">{{ selectedProfile.serial.host }}:{{ selectedProfile.serial.port }}</dd></div>
          <div><dt>凭据</dt><dd>{{ selectedProfile[selectedProfile.preferred_protocol].has_password ? '系统凭据库' : '未保存' }}</dd></div>
        </dl>
        <div v-if="selectedProfile.profile_type === 'server'" class="credential-actions" aria-label="管理连接凭据">
          <button v-if="selectedProfile.ssh.host" class="secondary-button" type="button" @click="workspace.manageProfileCredential(selectedProfile, 'ssh')">
            <KeyRound :size="13" />SSH 凭据
          </button>
          <button v-if="selectedProfile.telnet.host" class="secondary-button" type="button" @click="workspace.manageProfileCredential(selectedProfile, 'telnet')">
            <KeyRound :size="13" />Telnet 凭据
          </button>
          <button v-if="selectedProfile.serial.host" class="secondary-button" type="button" @click="workspace.manageProfileCredential(selectedProfile, 'serial')">
            <KeyRound :size="13" />串口凭据
          </button>
        </div>
        <div class="device-actions">
          <button class="secondary-button" type="button" @click="showProfileDialog(selectedProfile.profile_type, selectedProfile, $event)">
            <Pencil :size="14" />编辑
          </button>
          <button class="secondary-button danger-button" type="button" @click="deleteSelectedProfile">
            <Trash2 :size="14" />删除
          </button>
        </div>
        <div class="inspector-note">
          {{ selectedProfile.notes || '配置元数据存放于 SQLite，密码存放于操作系统凭据库。' }}
        </div>
      </template>
      <div v-else class="navigator-state">尚未选择项目</div>
    </div>
  </section>
  <div
    v-if="profileContextMenu"
    ref="profileContextMenuElement"
    class="profile-context-menu"
    role="menu"
    :style="{ left: `${profileContextMenu.x}px`, top: `${profileContextMenu.y}px` }"
    @click.stop
    @keydown="handleContextMenuKeydown($event, profileContextMenuElement, closeProfileContextMenuAndRestoreFocus)"
  >
    <p>{{ profileContextMenu.profile.name }}<small>{{ profileContextMenu.profile.profile_type === 'server' ? '服务器配置' : '临时连接' }}</small></p>
    <button
      v-if="profileCanConnect(profileContextMenu.profile)"
      type="button"
      role="menuitem"
      :disabled="Boolean(workspace.openingKind)"
      @click="openProfileFromContext()"
    >{{ profileDefaultOpenLabel(profileContextMenu.profile) }}</button>
    <button
      v-if="profileContextMenu.profile.ssh.host && profileContextMenu.profile.preferred_protocol !== 'ssh'"
      type="button"
      role="menuitem"
      :disabled="!profileCanConnect(profileContextMenu.profile, 'ssh') || Boolean(workspace.openingKind)"
      @click="openProfileFromContext('ssh')"
    >打开 SSH</button>
    <button
      v-if="profileContextMenu.profile.profile_type === 'temporary' && profileContextMenu.profile.telnet.host && profileContextMenu.profile.preferred_protocol !== 'telnet'"
      type="button"
      role="menuitem"
      :disabled="!profileCanConnect(profileContextMenu.profile, 'telnet') || Boolean(workspace.openingKind)"
      @click="openProfileFromContext('telnet')"
    >打开设备管理口</button>
    <button
      v-if="profileContextMenu.profile.profile_type === 'temporary' && profileContextMenu.profile.serial.host && profileContextMenu.profile.preferred_protocol !== 'serial'"
      type="button"
      role="menuitem"
      :disabled="!profileCanConnect(profileContextMenu.profile, 'serial') || Boolean(workspace.openingKind)"
      @click="openProfileFromContext('serial')"
    >打开串口</button>
    <button
      type="button"
      role="menuitem"
      @click="copyProfileText(profileConnectionCopyText(profileContextMenu.profile), `已复制连接信息: ${profileContextMenu.profile.name}`)"
    >复制连接信息</button>
    <hr v-if="profileContextMenu.profile.profile_type === 'server'" />
    <button
      v-if="profileContextMenu.profile.profile_type === 'server' && profileContextMenu.profile.ssh.host"
      type="button"
      role="menuitem"
      @click="manageProfileCredentialFromContext('ssh')"
    >管理 SSH 凭据</button>
    <button
      v-if="profileContextMenu.profile.profile_type === 'server' && profileContextMenu.profile.telnet.host"
      type="button"
      role="menuitem"
      @click="manageProfileCredentialFromContext('telnet')"
    >管理 Telnet 凭据</button>
    <button
      v-if="profileContextMenu.profile.profile_type === 'server' && profileContextMenu.profile.serial.host"
      type="button"
      role="menuitem"
      @click="manageProfileCredentialFromContext('serial')"
    >管理串口凭据</button>
    <template v-if="profileContextMenu.profile.profile_type === 'server' && (profileContextMenu.profile.group || workspace.profileGroups.some((group) => group !== profileContextMenu?.profile.group))">
      <hr />
      <button
        type="button"
        role="menuitem"
        v-if="profileContextMenu.profile.group"
        @click="moveProfileToGroupFromContext('')"
      >移动到未分组</button>
      <template v-for="group in workspace.profileGroups" :key="group">
        <button
          v-if="group !== profileContextMenu.profile.group"
          type="button"
          role="menuitem"
          @click="moveProfileToGroupFromContext(group)"
        >移动到 {{ group }}</button>
      </template>
    </template>
    <hr />
    <button type="button" role="menuitem" @click="editProfileFromContext">编辑</button>
    <button type="button" role="menuitem" class="danger-menu-item" @click="deleteProfileFromContext">删除</button>
  </div>
  <div
    v-if="deviceContextMenu"
    ref="deviceContextMenuElement"
    class="device-context-menu"
    role="menu"
    :style="{ left: `${deviceContextMenu.x}px`, top: `${deviceContextMenu.y}px` }"
    @click.stop
    @keydown="handleContextMenuKeydown($event, deviceContextMenuElement, closeDeviceContextMenuAndRestoreFocus)"
  >
    <p>{{ deviceContextMenu.device.name }}<small>{{ deviceContextMenu.device.id }}</small></p>
    <button
      v-if="deviceContextMenu.device.is_simulated"
      type="button"
      role="menuitem"
      :disabled="Boolean(workspace.openingKind)"
      @click="openDeviceContextSimulatedSession"
    >打开模拟终端</button>
    <button
      v-if="!deviceContextMenu.device.is_simulated && recommendedSessionKind(deviceContextMenu.device)"
      type="button"
      role="menuitem"
      :disabled="Boolean(workspace.openingKind)"
      title="按 SSH、Telnet、串口的优先级打开第一个可用终端"
      @click="openDeviceContextRecommendedSession"
    >快速打开推荐终端 · {{ sessionKindLabel(recommendedSessionKind(deviceContextMenu.device)) }}</button>
    <button
      v-if="deviceContextMenu.device.can_connect_telnet"
      type="button"
      role="menuitem"
      :disabled="Boolean(workspace.openingKind)"
      title="打开设备管理口"
      @click="openDeviceContextSession('telnet')"
    >打开设备管理口</button>
    <button
      v-if="deviceContextMenu.device.can_connect_ssh"
      type="button"
      role="menuitem"
      :disabled="Boolean(workspace.openingKind)"
      title="打开 Linux 后台"
      @click="openDeviceContextSession('ssh')"
    >打开 Linux 后台</button>
    <button
      v-if="deviceContextMenu.device.can_connect_serial"
      type="button"
      role="menuitem"
      :disabled="Boolean(workspace.openingKind)"
      title="打开串口"
      @click="openDeviceContextSession('serial')"
    >打开串口</button>
    <button
      type="button"
      role="menuitem"
      title="运行已发布 Workflow"
      @click="openWorkflowRunDialog(deviceContextMenu.device.id)"
    >运行 Workflow</button>
    <template v-if="canSplitDevice(deviceContextMenu.device.id)">
      <hr />
      <button type="button" role="menuitem" @click="splitDeviceById(deviceContextMenu.device.id, 'left'); closeDeviceContextMenu()">分屏到左侧</button>
      <button type="button" role="menuitem" @click="splitDeviceById(deviceContextMenu.device.id, 'right'); closeDeviceContextMenu()">分屏到右侧</button>
      <button type="button" role="menuitem" @click="splitDeviceById(deviceContextMenu.device.id, 'top'); closeDeviceContextMenu()">分屏到上方</button>
      <button type="button" role="menuitem" @click="splitDeviceById(deviceContextMenu.device.id, 'bottom'); closeDeviceContextMenu()">分屏到下方</button>
    </template>
    <hr />
    <button
      type="button"
      role="menuitem"
      @click="copyDeviceText(deviceRowCopyText(deviceContextMenu.device), `已复制设备行: ${deviceContextMenu.device.name}`)"
    >复制设备行</button>
    <button
      v-if="endpointHost(deviceContextMenu.device.ssh_endpoint) && !deviceContextMenu.device.is_simulated"
      type="button"
      role="menuitem"
      @click="copyDeviceText(endpointHost(deviceContextMenu.device.ssh_endpoint), `已复制 SSH IP: ${deviceContextMenu.device.name}`)"
    >复制 SSH IP</button>
    <button
      v-if="endpointHost(deviceContextMenu.device.telnet_endpoint) && !deviceContextMenu.device.is_simulated"
      type="button"
      role="menuitem"
      @click="copyDeviceText(endpointHost(deviceContextMenu.device.telnet_endpoint), `已复制 Telnet IP: ${deviceContextMenu.device.name}`)"
    >复制 Telnet IP</button>
    <button
      v-if="copyableSerialText(deviceContextMenu.device)"
      type="button"
      role="menuitem"
      @click="copyDeviceText(copyableSerialText(deviceContextMenu.device), `已复制串口地址: ${deviceContextMenu.device.name}`)"
    >复制串口地址</button>
    <button
      v-if="!deviceContextMenu.device.is_simulated"
      type="button"
      role="menuitem"
      @click="copyDeviceText(deviceConnectionCopyText(deviceContextMenu.device), `已复制连接信息: ${deviceContextMenu.device.name}`)"
    >复制连接信息</button>
    <hr v-if="deviceContextMenu.device.can_claim || deviceContextMenu.device.can_release || deviceContextMenu.device.can_power_off" />
    <button
      v-if="deviceContextMenu.device.can_claim"
      type="button"
      role="menuitem"
      :disabled="Boolean(workspace.deviceAction)"
      title="占用设备"
      @click="runDeviceContextAction('claim')"
    >占用设备</button>
    <button
      v-if="deviceContextMenu.device.can_release"
      type="button"
      role="menuitem"
      :disabled="Boolean(workspace.deviceAction)"
      title="释放设备"
      @click="runDeviceContextAction('release')"
    >释放设备</button>
    <button
      v-if="deviceContextMenu.device.can_power_off"
      type="button"
      role="menuitem"
      class="danger-menu-item"
      :disabled="Boolean(workspace.deviceAction)"
      title="设备掉电"
      @click="runDeviceContextAction('power_off')"
    >设备掉电…</button>
  </div>
  <div
    class="navigator-resize-handle"
    data-testid="navigator-resize-handle"
    role="separator"
    aria-label="调整设备工作台宽度"
    aria-orientation="vertical"
    :aria-valuemin="NAVIGATOR_MIN_WIDTH"
    :aria-valuemax="navigatorMaxWidth"
    :aria-valuenow="effectiveNavigatorWidth"
    tabindex="0"
    title="拖动调整设备工作台宽度；双击恢复默认"
    @pointerdown="startNavigatorResize"
    @keydown="handleNavigatorResizeKeydown"
    @dblclick="resetNavigatorWidth"
  ><span aria-hidden="true"></span></div>
</aside>
</template>
