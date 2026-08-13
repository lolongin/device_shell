import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { BackendApiError, applicationEventSocketUrl, desktopApi } from '../transport/api'
import type {
  ConnectionProfilePayload,
  ConnectionProfileSummary,
  CommandGroup,
  CommandHistoryItem,
  CommandWorkspaceResponse,
  AutoResponseRulePayload,
  AutomationRuleRecord,
  AutomationSessionStatus,
  AutomationWorkspaceResponse,
  QuickSendButtonPayload,
  QuickSendButtonRecord,
  OperationRecord,
  SharedTransferFile,
  TransferSettings,
  DeviceSummary,
  SessionKind,
  SessionSummary,
  AiPlanResponse,
  ApplicationEvent
} from '../types'

const VIEW_STATE_KEY = 'device-tui.desktop-v2.workspace'

function storedViewState(): {
  selectedDeviceRowId?: string
  selectedDeviceId?: string
  activeSessionId?: string
} {
  try {
    return JSON.parse(localStorage.getItem(VIEW_STATE_KEY) || '{}') as {
      selectedDeviceRowId?: string
      selectedDeviceId?: string
      activeSessionId?: string
    }
  } catch {
    return {}
  }
}

export const useWorkspaceStore = defineStore('workspace', () => {
  const restored = storedViewState()
  const devices = ref<DeviceSummary[]>([])
  const sessions = ref<SessionSummary[]>([])
  const profiles = ref<ConnectionProfileSummary[]>([])
  const profileGroups = ref<string[]>([])
  const commandGroups = ref<CommandGroup[]>([])
  const commandHistory = ref<CommandHistoryItem[]>([])
  const currentCommandGroupId = ref('')
  const commandEnterSends = ref(false)
  const commandPanelOpen = ref(localStorage.getItem('device-tui.desktop-v2.commands-open') === '1')
  const commandSuggestions = ref<string[]>([])
  const commandBusy = ref(false)
  const automationRules = ref<AutomationRuleRecord[]>([])
  const quickSendButtons = ref<QuickSendButtonRecord[]>([])
  const automationSessions = ref<AutomationSessionStatus[]>([])
  const automationPanelOpen = ref(
    localStorage.getItem('device-tui.desktop-v2.automation-open') === '1'
  )
  const automationBusy = ref(false)
  const transferSettings = ref<TransferSettings | null>(null)
  const transferServiceLog = ref<string[]>([])
  const transferClientCommand = ref('')
  const transferFiles = ref<SharedTransferFile[]>([])
  const operations = ref<OperationRecord[]>([])
  const transferPanelOpen = ref(
    localStorage.getItem('device-tui.desktop-v2.transfer-open') === '1'
  )
  const transferBusy = ref(false)
  const upgradeOperations = ref<OperationRecord[]>([])
  const upgradePanelOpen = ref(
    localStorage.getItem('device-tui.desktop-v2.upgrade-open') === '1'
  )
  const upgradeBusy = ref(false)
  const aiPanelOpen = ref(localStorage.getItem('device-tui.desktop-v2.ai-open') === '1')
  const aiBusy = ref(false)
  const aiObjective = ref('')
  const aiPlan = ref<AiPlanResponse | null>(null)
  const selectedDeviceRowId = ref(restored.selectedDeviceRowId || restored.selectedDeviceId || '')
  const activeSessionId = ref(restored.activeSessionId || '')
  const query = ref('')
  const domainFilter = ref('')
  const statusFilter = ref('')
  const cpuFilter = ref('')
  const mineOnly = ref(false)
  const profileQuery = ref('')
  const currentUser = ref('')
  const ownedDeviceIds = ref<string[]>([])
  const loading = ref(false)
  const error = ref('')
  const errorCode = ref('')
  const openingKind = ref<SessionKind | ''>('')
  const deviceAction = ref('')
  const notice = ref('')
  let eventSocket: WebSocket | null = null
  let eventReconnectTimer: ReturnType<typeof setTimeout> | null = null
  let lastEventSequence = 0
  let eventStreamWanted = false

  const selectedDevice = computed(
    () => devices.value.find((device) => device.row_id === selectedDeviceRowId.value)
      || devices.value.find((device) => device.id === selectedDeviceRowId.value)
      || null
  )
  const selectedDeviceId = computed(() => selectedDevice.value?.id || '')
  const activeSession = computed(
    () => sessions.value.find((session) => session.id === activeSessionId.value) || null
  )
  const currentCommandGroup = computed(
    () => commandGroups.value.find((group) => group.id === currentCommandGroupId.value) || null
  )
  const connectedSessions = computed(() =>
    sessions.value.filter((session) => session.status === 'connected')
  )
  const activeAutomationStatus = computed(() =>
    automationSessions.value.find((status) => status.session_id === activeSessionId.value) || null
  )
  const filteredDevices = computed(() => {
    const needle = query.value.trim().toLocaleLowerCase()
    const cpuNeedle = cpuFilter.value.trim().toLocaleLowerCase()
    return devices.value.filter((device) => {
      if (
        needle &&
        ![
          device.name,
          device.id,
          device.row_id,
          device.board_id,
          device.domain,
          device.model,
          device.site,
          device.cpu,
          device.board_type,
          device.slot,
          device.status_text,
          device.tooltip
        ]
          .join(' ')
          .toLocaleLowerCase()
          .includes(needle)
      ) return false
      if (domainFilter.value && device.domain !== domainFilter.value) return false
      if (statusFilter.value && device.status !== statusFilter.value) return false
      if (cpuNeedle && !device.cpu.toLocaleLowerCase().includes(cpuNeedle)) return false
      if (mineOnly.value && !ownedDeviceIds.value.includes(device.id)) return false
      return true
    })
  })
  const deviceDomains = computed(() =>
    [...new Set(devices.value.map((device) => device.domain).filter(Boolean))].sort()
  )
  const deviceStatuses = computed(() =>
    [...new Set(devices.value.map((device) => device.status).filter(Boolean))].sort()
  )
  const myOccupancyCount = computed(() => ownedDeviceIds.value.length)
  const hasActiveDeviceFilters = computed(() => Boolean(
    query.value.trim() || domainFilter.value || statusFilter.value ||
    cpuFilter.value.trim() || mineOnly.value
  ))

  function clearDeviceFilters(): void {
    query.value = ''
    domainFilter.value = ''
    statusFilter.value = ''
    cpuFilter.value = ''
    mineOnly.value = false
  }

  function applyCommandWorkspace(response: CommandWorkspaceResponse): void {
    commandGroups.value = response.groups
    commandHistory.value = response.history
    currentCommandGroupId.value = response.current_group_id
    commandEnterSends.value = response.enter_sends
  }

  function upsertSession(session: SessionSummary): void {
    const index = sessions.value.findIndex((item) => item.id === session.id)
    if (index < 0) {
      sessions.value.push(session)
      return
    }
    const current = sessions.value[index]
    if (Number(session.sequence || 0) < Number(current.sequence || 0)) return
    sessions.value[index] = { ...current, ...session }
  }

  function applyAutomationWorkspace(response: AutomationWorkspaceResponse): void {
    automationRules.value = response.rules
    automationSessions.value = response.sessions
    quickSendButtons.value = response.quick_send_buttons
  }

  async function initialize(): Promise<void> {
    loading.value = true
    error.value = ''
    errorCode.value = ''
    try {
      const [
        deviceResponse,
        sessionResponse,
        profileResponse,
        commandResponse,
        automationResponse,
        transferSettingsResponse,
        transferLogResponse,
        operationResponse,
        upgradeOperationResponse
      ] = await Promise.all([
        desktopApi.devices(),
        desktopApi.sessions(),
        desktopApi.connectionProfiles(),
        desktopApi.commandWorkspace(),
        desktopApi.automationWorkspace(),
        desktopApi.transferSettings(),
        desktopApi.transferServiceLog(),
        desktopApi.operations('managed_file_transfer'),
        desktopApi.operations('package_upgrade')
      ])
      devices.value = deviceResponse.devices
      currentUser.value = deviceResponse.current_user
      ownedDeviceIds.value = deviceResponse.owned_device_ids
      sessions.value = []
      for (const session of sessionResponse) upsertSession(session)
      profiles.value = profileResponse.profiles
      profileGroups.value = profileResponse.groups
      applyCommandWorkspace(commandResponse)
      applyAutomationWorkspace(automationResponse)
      transferSettings.value = transferSettingsResponse
      transferServiceLog.value = transferLogResponse.entries
      transferClientCommand.value = transferLogResponse.client_command
      operations.value = operationResponse.operations
      upgradeOperations.value = upgradeOperationResponse.operations
      const restoredDevice = devices.value.find(
        (device) => device.row_id === selectedDeviceRowId.value
      ) || devices.value.find((device) => device.id === selectedDeviceRowId.value)
      selectedDeviceRowId.value = restoredDevice?.row_id || devices.value[0]?.row_id || ''
      if (!sessions.value.some((session) => session.id === activeSessionId.value)) {
        activeSessionId.value = sessions.value[0]?.id || ''
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      loading.value = false
    }
  }

  function applyApplicationEvent(event: ApplicationEvent): void {
    lastEventSequence = Math.max(lastEventSequence, Number(event.sequence || 0))
    const data = event.data || {}
    if (event.type.startsWith('session.') && typeof data.id === 'string') {
      const session = data as unknown as SessionSummary
      if (event.type === 'session.closed') {
        sessions.value = sessions.value.filter((item) => item.id !== event.resourceId)
      } else {
        upsertSession(session)
      }
      return
    }
    if (event.type.startsWith('operation.') && typeof data.id === 'string') {
      const operation = data as unknown as OperationRecord
      const target = operation.kind === 'package_upgrade' ? upgradeOperations : operations
      const index = target.value.findIndex((item) => item.id === operation.id)
      if (index >= 0) target.value[index] = operation
      else target.value.unshift(operation)
      if (operation.status !== 'running') notice.value = operation.message
      return
    }
    if (event.type === 'transfer.service.log' && typeof data.message === 'string') {
      transferServiceLog.value = [...transferServiceLog.value, data.message].slice(-300)
      return
    }
    if (event.type === 'ai.result.created') {
      notice.value = 'AI operation completed'
      return
    }
    if (event.type.startsWith('automation.')) {
      const name = typeof data.name === 'string' ? data.name : '自动化规则'
      if (event.type === 'automation.rule.started') notice.value = `自动化已启动: ${name}`
      else if (event.type === 'automation.rule.completed') notice.value = `自动化已完成: ${name}`
      else if (event.type === 'automation.rule.failed') notice.value = `自动化执行失败: ${name}`
      else if (event.type === 'automation.rule.cancelled') notice.value = `自动化已取消: ${name}`
      void refreshAutomation()
    }
  }

  async function connectApplicationEvents(): Promise<void> {
    if (eventSocket || !eventStreamWanted) return
    try {
      eventSocket = new WebSocket(await applicationEventSocketUrl(lastEventSequence))
      eventSocket.onmessage = (message) => {
        try {
          applyApplicationEvent(JSON.parse(String(message.data)) as ApplicationEvent)
        } catch {
          // Ignore one malformed event and retain the active connection.
        }
      }
      eventSocket.onclose = () => {
        eventSocket = null
        if (eventStreamWanted) {
          eventReconnectTimer = setTimeout(() => { void connectApplicationEvents() }, 800)
        }
      }
      eventSocket.onerror = () => eventSocket?.close()
    } catch {
      eventSocket = null
      if (eventStreamWanted) eventReconnectTimer = setTimeout(() => { void connectApplicationEvents() }, 1_500)
    }
  }

  function startApplicationEvents(): () => void {
    eventStreamWanted = true
    void connectApplicationEvents()
    return () => {
      eventStreamWanted = false
      if (eventReconnectTimer) clearTimeout(eventReconnectTimer)
      eventReconnectTimer = null
      eventSocket?.close()
      eventSocket = null
    }
  }

  async function buildAiPlan(): Promise<AiPlanResponse | null> {
    if (!aiObjective.value.trim()) return null
    aiBusy.value = true
    try {
      aiPlan.value = await desktopApi.aiPlan(aiObjective.value, selectedDeviceId.value)
      return aiPlan.value
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return null
    } finally {
      aiBusy.value = false
    }
  }

  async function openSession(kind: SessionKind): Promise<void> {
    const device = kind === 'simulated'
      ? devices.value.find((candidate) => candidate.is_simulated) || null
      : selectedDevice.value
    if (!device) {
      error.value = kind === 'simulated'
        ? '模拟终端不可用，请刷新设备列表后重试。'
        : '请先选择设备。'
      return
    }
    if (kind === 'ssh' && !device?.can_connect_ssh) {
      error.value = device?.is_simulated ? '模拟终端不支持 SSH。' : '设备 SSH 地址不可用。'
      return
    }
    if (kind === 'telnet' && !device?.can_connect_telnet) {
      error.value = device?.is_simulated
        ? '模拟终端不支持 Telnet。'
        : device?.is_saved_server
          ? '保存服务器请使用 SSH。'
          : '设备 Telnet 地址不可用。'
      return
    }
    if (kind === 'serial' && !device?.can_connect_serial) {
      error.value = device?.serial_display || '请先占用设备后再连接串口。'
      return
    }
    openingKind.value = kind
    error.value = ''
    try {
      const session = await desktopApi.createSession(device.id, kind)
      upsertSession(session)
      activeSessionId.value = session.id
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      openingKind.value = ''
    }
  }

  const openSimulatedSession = (): Promise<void> => openSession('simulated')

  function splitEndpoint(endpoint: string | null, defaultPort: number): { host: string; port: number } {
    const value = String(endpoint || '').trim()
    if (!value) return { host: '', port: defaultPort }
    if (value.startsWith('[')) {
      const end = value.indexOf(']')
      const host = end > 0 ? value.slice(1, end) : value
      const port = end > 0 && value[end + 1] === ':' ? Number(value.slice(end + 2)) : defaultPort
      return { host, port: Number.isInteger(port) && port > 0 ? port : defaultPort }
    }
    const separator = value.lastIndexOf(':')
    const parsedPort = separator > 0 ? Number(value.slice(separator + 1)) : defaultPort
    return {
      host: separator > 0 ? value.slice(0, separator) : value,
      port: Number.isInteger(parsedPort) && parsedPort > 0 ? parsedPort : defaultPort
    }
  }

  async function openCustomDeviceSession(
    device: DeviceSummary,
    kind: Exclude<SessionKind, 'simulated'>
  ): Promise<void> {
    const endpoint = splitEndpoint(
      kind === 'ssh'
        ? device.ssh_endpoint
        : kind === 'telnet'
          ? device.telnet_endpoint
          : device.serial_endpoint,
      kind === 'ssh' ? 22 : 23
    )
    openingKind.value = kind
    error.value = ''
    try {
      const session = await window.desktopApi.openDeviceSession({
        deviceId: device.id,
        deviceName: device.name,
        protocol: kind,
        host: endpoint.host,
        port: endpoint.port,
        username: kind === 'ssh' ? 'root' : ''
      })
      if (!session) return
      upsertSession(session)
      activeSessionId.value = session.id
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      openingKind.value = ''
    }
  }

  async function openProfileSession(
    profile: ConnectionProfileSummary,
    kind: Exclude<SessionKind, 'simulated'> = profile.preferred_protocol
  ): Promise<void> {
    openingKind.value = kind
    error.value = ''
    try {
      const endpoint = profile[kind]
      const session = await window.desktopApi.openProfileSession({
        profileId: profile.id,
        profileName: profile.name,
        protocol: kind,
        endpoint: `${endpoint.host}:${endpoint.port}`,
        hasPassword: endpoint.has_password
      })
      if (!session) return
      upsertSession(session)
      activeSessionId.value = session.id
      if (!endpoint.has_password) {
        const refreshed = await desktopApi.connectionProfiles()
        profiles.value = refreshed.profiles
        profileGroups.value = refreshed.groups
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      openingKind.value = ''
    }
  }

  async function manageProfileCredential(
    profile: ConnectionProfileSummary,
    kind: Exclude<SessionKind, 'simulated'> = profile.preferred_protocol
  ): Promise<boolean> {
    error.value = ''
    try {
      const endpoint = profile[kind]
      const changed = await window.desktopApi.manageProfileCredential({
        profileId: profile.id,
        profileName: profile.name,
        protocol: kind,
        endpoint: `${endpoint.host}:${endpoint.port}`,
        hasPassword: endpoint.has_password
      })
      if (changed) {
        const refreshed = await desktopApi.connectionProfiles()
        profiles.value = refreshed.profiles
        profileGroups.value = refreshed.groups
      }
      return changed
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    }
  }

  async function saveProfile(
    payload: ConnectionProfilePayload,
    profileId = ''
  ): Promise<ConnectionProfileSummary | null> {
    error.value = ''
    errorCode.value = ''
    try {
      const saved = profileId
        ? await desktopApi.updateConnectionProfile(profileId, payload)
        : await desktopApi.createConnectionProfile(payload)
      const index = profiles.value.findIndex((profile) => profile.id === saved.id)
      if (index >= 0) profiles.value[index] = saved
      else profiles.value.push(saved)
      const refreshed = await desktopApi.connectionProfiles()
      profiles.value = refreshed.profiles
      profileGroups.value = refreshed.groups
      return saved
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      errorCode.value = cause instanceof BackendApiError ? cause.code : ''
      return null
    }
  }

  async function createProfileGroup(name: string): Promise<boolean> {
    error.value = ''
    errorCode.value = ''
    try {
      const response = await desktopApi.createConnectionProfileGroup(name)
      profileGroups.value = response.groups
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    }
  }

  async function createCommandGroup(): Promise<void> {
    commandBusy.value = true
    error.value = ''
    try {
      applyCommandWorkspace(await desktopApi.createCommandGroup())
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      commandBusy.value = false
    }
  }

  async function updateCommandGroup(
    groupId: string,
    update: { name?: string; content?: string }
  ): Promise<boolean> {
    error.value = ''
    try {
      applyCommandWorkspace(await desktopApi.updateCommandGroup(groupId, update))
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    }
  }

  async function deleteCommandGroup(groupId: string): Promise<void> {
    commandBusy.value = true
    error.value = ''
    try {
      applyCommandWorkspace(await desktopApi.deleteCommandGroup(groupId))
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      commandBusy.value = false
    }
  }

  async function selectCommandGroup(groupId: string): Promise<void> {
    if (groupId === currentCommandGroupId.value) return
    try {
      applyCommandWorkspace(await desktopApi.updateCommandPreferences({ current_group_id: groupId }))
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function setCommandEnterSends(enabled: boolean): Promise<void> {
    try {
      applyCommandWorkspace(await desktopApi.updateCommandPreferences({ enter_sends: enabled }))
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function fetchCommandSuggestions(query: string): Promise<void> {
    const normalized = query.trim()
    if (!normalized) {
      commandSuggestions.value = []
      return
    }
    try {
      const response = await desktopApi.commandSuggestions(normalized, activeSessionId.value)
      commandSuggestions.value = response.suggestions
    } catch {
      commandSuggestions.value = []
    }
  }

  async function dispatchCommand(command: string, broadcast = false): Promise<boolean> {
    if (!command.trim()) {
      notice.value = '请先选中要发送的命令，或将光标放到要发送的命令行。'
      return false
    }
    if (!broadcast && !activeSessionId.value) {
      notice.value = '命令已记录，当前没有打开的终端会话。'
      return false
    }
    if (broadcast && !connectedSessions.value.length) {
      notice.value = '命令已记录，当前没有已连接的终端会话。'
      return false
    }
    commandBusy.value = true
    error.value = ''
    notice.value = ''
    try {
      const response = broadcast
        ? await desktopApi.broadcastCommand(command)
        : await desktopApi.sendCommand(activeSessionId.value, command)
      notice.value = broadcast
        ? `已广播到 ${response.session_ids.length} 个会话`
        : '命令已发送'
      const refreshed = await desktopApi.commandWorkspace()
      applyCommandWorkspace(refreshed)
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      commandBusy.value = false
    }
  }

  async function refreshAutomation(): Promise<void> {
    try {
      applyAutomationWorkspace(await desktopApi.automationWorkspace())
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function saveAutomationRule(
    rule: AutoResponseRulePayload,
    ruleId = ''
  ): Promise<AutomationRuleRecord | null> {
    automationBusy.value = true
    error.value = ''
    try {
      const response = ruleId
        ? await desktopApi.updateAutomationRule(ruleId, rule)
        : await desktopApi.createAutomationRule(rule)
      applyAutomationWorkspace(response)
      return ruleId
        ? automationRules.value.find((record) => record.id === ruleId) || null
        : automationRules.value.at(-1) || null
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return null
    } finally {
      automationBusy.value = false
    }
  }

  async function setAutomationRuleEnabled(ruleId: string, enabled: boolean): Promise<void> {
    automationBusy.value = true
    error.value = ''
    try {
      applyAutomationWorkspace(await desktopApi.setAutomationRuleEnabled(ruleId, enabled))
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      automationBusy.value = false
    }
  }

  async function deleteAutomationRule(ruleId: string): Promise<boolean> {
    automationBusy.value = true
    error.value = ''
    try {
      await desktopApi.deleteAutomationRule(ruleId)
      automationRules.value = automationRules.value.filter((record) => record.id !== ruleId)
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      automationBusy.value = false
    }
  }

  async function triggerAutomationRule(ruleId: string): Promise<boolean> {
    if (!activeSessionId.value) return false
    automationBusy.value = true
    error.value = ''
    notice.value = ''
    try {
      await desktopApi.triggerAutomationRule(ruleId, activeSessionId.value)
      notice.value = '自动化流程已启动'
      await refreshAutomation()
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      automationBusy.value = false
    }
  }

  async function cancelActiveAutomation(): Promise<void> {
    if (!activeSessionId.value) return
    automationBusy.value = true
    error.value = ''
    try {
      await desktopApi.cancelSessionAutomation(activeSessionId.value)
      notice.value = '当前会话的自动化已停止'
      await refreshAutomation()
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      automationBusy.value = false
    }
  }

  async function saveQuickSendButton(
    payload: QuickSendButtonPayload,
    buttonId = ''
  ): Promise<boolean> {
    automationBusy.value = true
    error.value = ''
    try {
      const response = buttonId
        ? await desktopApi.updateQuickSendButton(buttonId, payload)
        : await desktopApi.createQuickSendButton(payload)
      applyAutomationWorkspace(response)
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      automationBusy.value = false
    }
  }

  async function deleteQuickSendButton(buttonId: string): Promise<boolean> {
    automationBusy.value = true
    error.value = ''
    try {
      await desktopApi.deleteQuickSendButton(buttonId)
      quickSendButtons.value = quickSendButtons.value.filter((button) => button.id !== buttonId)
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      automationBusy.value = false
    }
  }

  async function sendQuickSendButton(buttonId: string): Promise<boolean> {
    if (!activeSessionId.value) return false
    automationBusy.value = true
    error.value = ''
    try {
      await desktopApi.sendQuickSendButton(buttonId, activeSessionId.value)
      notice.value = '快捷内容已发送'
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      automationBusy.value = false
    }
  }

  async function loadTransferFiles(): Promise<void> {
    error.value = ''
    try {
      const response = await desktopApi.sharedTransferFiles()
      transferFiles.value = response.files
    } catch (cause) {
      transferFiles.value = []
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function loadTransferServiceLog(): Promise<void> {
    try {
      const response = await desktopApi.transferServiceLog()
      transferServiceLog.value = response.entries
      transferClientCommand.value = response.client_command
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function clearTransferServiceLog(): Promise<void> {
    try {
      const response = await desktopApi.clearTransferServiceLog()
      transferServiceLog.value = response.entries
      transferClientCommand.value = response.client_command
      notice.value = '文件服务日志已清空'
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function refreshOperations(): Promise<void> {
    try {
      const [operationResponse, settingsResponse] = await Promise.all([
        desktopApi.operations('managed_file_transfer'),
        desktopApi.transferSettings()
      ])
      operations.value = operationResponse.operations
      transferSettings.value = settingsResponse
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function saveTransferSettings(
    settings: Pick<TransferSettings, 'protocol' | 'host' | 'port' | 'root' | 'username' | 'writable'>
  ): Promise<boolean> {
    transferBusy.value = true
    error.value = ''
    try {
      transferSettings.value = await desktopApi.updateTransferSettings(settings)
      await loadTransferFiles()
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      transferBusy.value = false
    }
  }

  async function toggleTransferService(): Promise<void> {
    if (!transferSettings.value) return
    transferBusy.value = true
    error.value = ''
    try {
      transferSettings.value = transferSettings.value.service_running
        ? await desktopApi.stopTransferService()
        : await desktopApi.startTransferService()
      await loadTransferServiceLog()
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      transferBusy.value = false
    }
  }

  async function startManagedTransfer(payload: {
    direction: 'upload' | 'download'
    source_path: string
    destination_path: string
    overwrite: boolean
  }): Promise<boolean> {
    if (!activeSessionId.value) return false
    transferBusy.value = true
    error.value = ''
    notice.value = ''
    try {
      const response = await desktopApi.startManagedTransfer({
        ...payload,
        session_id: activeSessionId.value
      })
      operations.value = [
        response.operation,
        ...operations.value.filter((record) => record.id !== response.operation.id)
      ]
      notice.value = '文件传输已启动'
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      transferBusy.value = false
    }
  }

  async function cancelOperation(operationId: string): Promise<void> {
    transferBusy.value = true
    error.value = ''
    try {
      const response = await desktopApi.cancelOperation(operationId)
      const index = operations.value.findIndex((record) => record.id === operationId)
      if (index >= 0) operations.value[index] = response.operation
      const upgradeIndex = upgradeOperations.value.findIndex((record) => record.id === operationId)
      if (upgradeIndex >= 0) upgradeOperations.value[upgradeIndex] = response.operation
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      transferBusy.value = false
    }
  }

  async function refreshUpgradeOperations(): Promise<void> {
    try {
      const [operationResponse, settingsResponse, filesResponse] = await Promise.all([
        desktopApi.operations('package_upgrade'),
        desktopApi.transferSettings(),
        desktopApi.sharedTransferFiles()
      ])
      upgradeOperations.value = operationResponse.operations
      transferSettings.value = settingsResponse
      transferFiles.value = filesResponse.files
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function startPackageUpgrade(payload: {
    package_path: string
    include_slave: boolean
    auto_delete_old_packages: boolean
    reboot_after_setting: boolean
  }): Promise<boolean> {
    if (!activeSessionId.value) return false
    upgradeBusy.value = true
    error.value = ''
    notice.value = ''
    try {
      const response = await desktopApi.startPackageUpgrade({
        ...payload,
        session_id: activeSessionId.value,
        master_storage: 'flash:/',
        slave_storage: 'slave#flash:/'
      })
      upgradeOperations.value = [
        response.operation,
        ...upgradeOperations.value.filter((record) => record.id !== response.operation.id)
      ]
      notice.value = '系统包升级已启动'
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      upgradeBusy.value = false
    }
  }

  async function approvePackageUpgrade(operationId: string): Promise<void> {
    upgradeBusy.value = true
    error.value = ''
    try {
      const response = await desktopApi.approvePackageUpgradeReboot(operationId)
      const index = upgradeOperations.value.findIndex((record) => record.id === operationId)
      if (index >= 0) upgradeOperations.value[index] = response.operation
      notice.value = '设备重启已批准'
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      upgradeBusy.value = false
    }
  }

  async function deleteProfile(profileId: string): Promise<boolean> {
    error.value = ''
    try {
      await desktopApi.deleteConnectionProfile(profileId)
      profiles.value = profiles.value.filter((profile) => profile.id !== profileId)
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    }
  }

  async function closeSession(sessionId: string): Promise<void> {
    const closingDeviceId = sessions.value.find((session) => session.id === sessionId)?.device_id || ''
    await desktopApi.closeSession(sessionId)
    sessions.value = sessions.value.filter((session) => session.id !== sessionId)
    if (activeSessionId.value === sessionId) {
      activeSessionId.value = sessions.value.find(
        (session) => session.device_id === closingDeviceId
      )?.id || sessions.value[0]?.id || ''
    }
  }

  async function closeSessionsRelative(
    referenceSessionId: string,
    mode: 'current' | 'left' | 'right' | 'others' | 'all',
    deviceId = ''
  ): Promise<void> {
    const snapshot = [...sessions.value]
    const scoped = deviceId
      ? snapshot.filter((session) => session.device_id === deviceId)
      : snapshot
    const referenceIndex = scoped.findIndex((session) => session.id === referenceSessionId)
    if (referenceIndex < 0 && mode !== 'all') {
      notice.value = '没有符合条件的会话可关闭。'
      return
    }
    const targets =
      mode === 'current'
        ? scoped.filter((session) => session.id === referenceSessionId)
        : mode === 'left'
          ? scoped.slice(0, referenceIndex)
          : mode === 'right'
            ? scoped.slice(referenceIndex + 1)
            : mode === 'others'
              ? scoped.filter((session) => session.id !== referenceSessionId)
              : scoped
    if (!targets.length) {
      notice.value = '没有符合条件的会话可关闭。'
      return
    }
    if (mode === 'left' || mode === 'right' || mode === 'others') {
      activeSessionId.value = referenceSessionId
    }
    const closingIds = targets.map((session) => session.id)
    await Promise.all(closingIds.map((sessionId) => desktopApi.closeSession(sessionId)))
    sessions.value = sessions.value.filter((session) => !closingIds.includes(session.id))
    if (!sessions.value.some((session) => session.id === activeSessionId.value)) {
      activeSessionId.value =
        sessions.value.find((session) => session.id === referenceSessionId)?.id
        || sessions.value.find((session) => session.device_id === deviceId)?.id
        || sessions.value[0]?.id
        || ''
    }
  }

  async function closeDeviceSessionGroups(
    referenceDeviceId: string,
    mode: 'current' | 'left' | 'right' | 'others' | 'all'
  ): Promise<void> {
    const snapshot = [...sessions.value]
    const deviceIds = [...new Set(snapshot.map((session) => session.device_id))]
    const referenceIndex = deviceIds.indexOf(referenceDeviceId)
    if (referenceIndex < 0 && mode !== 'all') {
      notice.value = '没有符合条件的设备会话可关闭。'
      return
    }
    const targetDeviceIds = mode === 'current'
      ? [referenceDeviceId]
      : mode === 'left'
        ? deviceIds.slice(0, referenceIndex)
        : mode === 'right'
          ? deviceIds.slice(referenceIndex + 1)
          : mode === 'others'
            ? deviceIds.filter((deviceId) => deviceId !== referenceDeviceId)
            : deviceIds
    const closingIds = snapshot
      .filter((session) => targetDeviceIds.includes(session.device_id))
      .map((session) => session.id)
    if (!closingIds.length) {
      notice.value = '没有符合条件的设备会话可关闭。'
      return
    }
    if (mode === 'left' || mode === 'right' || mode === 'others') {
      activeSessionId.value = snapshot.find(
        (session) => session.device_id === referenceDeviceId
      )?.id || activeSessionId.value
    }
    await Promise.all(closingIds.map((sessionId) => desktopApi.closeSession(sessionId)))
    sessions.value = sessions.value.filter((session) => !closingIds.includes(session.id))
    if (!sessions.value.some((session) => session.id === activeSessionId.value)) {
      activeSessionId.value = sessions.value[0]?.id || ''
    }
  }

  async function closeActiveSession(): Promise<void> {
    if (!activeSessionId.value) return
    await closeSessionsRelative(activeSessionId.value, 'current')
  }

  async function closeOtherSessions(): Promise<void> {
    if (!activeSessionId.value) return
    await closeSessionsRelative(activeSessionId.value, 'others')
  }

  async function closeAllSessions(): Promise<void> {
    await closeSessionsRelative(activeSessionId.value, 'all')
  }

  async function runDeviceAction(action: 'claim' | 'release' | 'power_off'): Promise<void> {
    if (!selectedDeviceId.value) return
    deviceAction.value = action
    error.value = ''
    notice.value = ''
    try {
      const response =
        action === 'claim'
          ? await desktopApi.claimDevice(selectedDeviceId.value)
          : action === 'release'
            ? await desktopApi.releaseDevice(selectedDeviceId.value)
            : await desktopApi.powerOffDevice(selectedDeviceId.value)
      devices.value = devices.value.map((device) => device.id === response.device_id
        ? {
            ...device,
            status: response.device.status,
            owner: response.device.owner,
            status_text: response.device.status_text,
            tooltip: response.device.tooltip,
            can_claim: response.device.can_claim,
            can_release: response.device.can_release,
            can_power_off: response.device.can_power_off,
            can_connect_serial: response.device.can_connect_serial,
            serial_display: response.device.serial_display
          }
        : device)
      if (action === 'claim' && !ownedDeviceIds.value.includes(response.device_id)) {
        ownedDeviceIds.value = [...ownedDeviceIds.value, response.device_id]
      } else if (action === 'release') {
        ownedDeviceIds.value = ownedDeviceIds.value.filter(
          (deviceId) => deviceId !== response.device_id
        )
      }
      notice.value = response.message
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      deviceAction.value = ''
    }
  }

  function updateSessionStatus(sessionId: string, status: string, sequence: number): void {
    const session = sessions.value.find((candidate) => candidate.id === sessionId)
    if (!session) return
    session.status = status
    session.sequence = Math.max(session.sequence, sequence)
  }

  watch([selectedDeviceRowId, activeSessionId], () => {
    localStorage.setItem(
      VIEW_STATE_KEY,
      JSON.stringify({
        selectedDeviceRowId: selectedDeviceRowId.value,
        selectedDeviceId: selectedDeviceId.value,
        activeSessionId: activeSessionId.value
      })
    )
  })
  watch(filteredDevices, (visibleDevices) => {
    if (!visibleDevices.length) {
      selectedDeviceRowId.value = ''
      return
    }
    if (!visibleDevices.some((device) => device.row_id === selectedDeviceRowId.value)) {
      selectedDeviceRowId.value = visibleDevices[0].row_id
    }
  })
  watch(commandPanelOpen, (open) => {
    localStorage.setItem('device-tui.desktop-v2.commands-open', open ? '1' : '0')
  })
  watch(automationPanelOpen, (open) => {
    localStorage.setItem('device-tui.desktop-v2.automation-open', open ? '1' : '0')
  })
  watch(transferPanelOpen, (open) => {
    localStorage.setItem('device-tui.desktop-v2.transfer-open', open ? '1' : '0')
  })
  watch(upgradePanelOpen, (open) => {
    localStorage.setItem('device-tui.desktop-v2.upgrade-open', open ? '1' : '0')
  })
  watch(aiPanelOpen, (open) => {
    localStorage.setItem('device-tui.desktop-v2.ai-open', open ? '1' : '0')
  })

  return {
    devices,
    sessions,
    profiles,
    profileGroups,
    commandGroups,
    commandHistory,
    currentCommandGroupId,
    commandEnterSends,
    commandPanelOpen,
    commandSuggestions,
    commandBusy,
    automationRules,
    quickSendButtons,
    automationSessions,
    automationPanelOpen,
    automationBusy,
    transferSettings,
    transferServiceLog,
    transferClientCommand,
    transferFiles,
    operations,
    transferPanelOpen,
    transferBusy,
    upgradeOperations,
    upgradePanelOpen,
    upgradeBusy,
    aiPanelOpen, aiBusy, aiObjective, aiPlan,
    buildAiPlan,
    selectedDeviceId,
    activeSessionId,
    query,
    domainFilter,
    statusFilter,
    cpuFilter,
    mineOnly,
    profileQuery,
    currentUser,
    loading,
    error,
    errorCode,
    openingKind,
    deviceAction,
    notice,
    selectedDevice,
    selectedDeviceRowId,
    activeSession,
    currentCommandGroup,
    connectedSessions,
    activeAutomationStatus,
    filteredDevices,
    deviceDomains,
    deviceStatuses,
    myOccupancyCount,
    hasActiveDeviceFilters,
    clearDeviceFilters,
    initialize,
    startApplicationEvents,
    openSimulatedSession,
    openCustomDeviceSession,
    openSession,
    openProfileSession,
    manageProfileCredential,
    saveProfile,
    createProfileGroup,
    createCommandGroup,
    updateCommandGroup,
    deleteCommandGroup,
    selectCommandGroup,
    setCommandEnterSends,
    fetchCommandSuggestions,
    dispatchCommand,
    refreshAutomation,
    saveAutomationRule,
    setAutomationRuleEnabled,
    deleteAutomationRule,
    triggerAutomationRule,
    cancelActiveAutomation,
    saveQuickSendButton,
    deleteQuickSendButton,
    sendQuickSendButton,
    loadTransferFiles,
    loadTransferServiceLog,
    clearTransferServiceLog,
    refreshOperations,
    saveTransferSettings,
    toggleTransferService,
    startManagedTransfer,
    cancelOperation,
    refreshUpgradeOperations,
    startPackageUpgrade,
    approvePackageUpgrade,
    deleteProfile,
    closeSession,
    closeSessionsRelative,
    closeDeviceSessionGroups,
    closeActiveSession,
    closeOtherSessions,
    closeAllSessions,
    runDeviceAction,
    updateSessionStatus
  }
})
