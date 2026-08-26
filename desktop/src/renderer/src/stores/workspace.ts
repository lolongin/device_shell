import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import { BackendApiError, applicationEventSocketUrl, desktopApi } from '../transport/api'
import type {
  ConnectionProfilePayload,
  ConnectionProfileSecrets,
  ConnectionProfileSummary,
  CommandGroup,
  CommandHistoryItem,
  CommandWorkspaceResponse,
  AutoResponseRulePayload,
  AutomationActivityRecord,
  AutomationPreviewResponse,
  AutomationRuleRecord,
  AutomationSessionStatus,
  AutomationWorkspaceResponse,
  QuickSendButtonPayload,
  QuickSendButtonRecord,
  OperationRecord,
  SharedTransferFile,
  TransferSettings,
  DeviceListResponse,
  DeviceFieldDescriptor,
  DeviceSummary,
  DeviceSourceId,
  DeviceSourceStatus,
  DeviceImportPreview,
  SessionKind,
  SessionSummary,
  InternalAuthStatus,
  AiPlanResponse,
  ApplicationEvent,
  TaskRecord,
  TaskDecisionContext,
  TaskDecisionActionPayload,
  WorkflowDescriptor
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
  const deviceFieldSchema = ref<DeviceFieldDescriptor[]>([])
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
  const automationActivity = ref<AutomationActivityRecord[]>([])
  const automationPanelOpen = ref(
    localStorage.getItem('device-tui.desktop-v2.automation-open') === '1'
  )
  const automationBusy = ref(false)
  let automationCloseGuard: (() => boolean) | null = null
  const transferSettings = ref<TransferSettings | null>(null)
  const transferServiceLog = ref<string[]>([])
  const transferClientCommand = ref('')
  const transferFiles = ref<SharedTransferFile[]>([])
  const transferFilesLoading = ref(false)
  const transferFileTotal = ref(0)
  const transferFileNextOffset = ref<number | null>(null)
  const operations = ref<OperationRecord[]>([])
  const transferPanelOpen = ref(
    localStorage.getItem('device-tui.desktop-v2.transfer-open') === '1'
  )
  const transferBusy = ref(false)
  const transferError = ref('')
  const upgradePanelOpen = ref(
    localStorage.getItem('device-tui.desktop-v2.upgrade-open') === '1'
  )
  const tasks = ref<TaskRecord[]>([])
  const workflows = ref<WorkflowDescriptor[]>([])
  const activeTaskId = ref('')
  const taskBusy = ref(false)
  const taskDecision = ref<TaskDecisionContext | null>(null)
  const taskError = ref('')
  let taskRefreshTimer: ReturnType<typeof setInterval> | null = null
  const aiPanelOpen = ref(localStorage.getItem('device-tui.desktop-v2.ai-open') === '1')
  const aiBusy = ref(false)
  const aiObjective = ref('')
  const aiPlan = ref<AiPlanResponse | null>(null)
  const selectedDeviceRowId = ref(restored.selectedDeviceRowId || restored.selectedDeviceId || '')
  const activeSessionId = ref(restored.activeSessionId || '')
  const query = ref('')
  const effectiveQuery = ref('')
  const domainFilter = ref('')
  const statusFilter = ref('')
  const cpuFilter = ref('')
  const mineOnly = ref(false)
  const profileQuery = ref('')
  const currentUser = ref('')
  const internalAuthStatus = ref<InternalAuthStatus>({
    api_version: 1,
    available: false,
    configured: false,
    authenticated: false,
    username: '',
    cid: '',
    remembered: false,
    auto_login: false,
    auto_login_error: '',
    credential_warning: ''
  })
  const internalAuthBusy = ref(false)
  const deviceSourceStatus = ref<DeviceSourceStatus>({
    api_version: 1,
    product_mode: 'universal',
    allow_source_switch: false,
    allow_plugin_management: false,
    allow_import: false,
    active_source: 'sample',
    default_source: 'sample',
    sources: [],
    plugin_warnings: [],
    imported_count: 0,
    imported_file: '',
    imported_sheet: '',
    imported_at: ''
  })
  const deviceSourceBusy = ref(false)
  const deviceImportPreview = ref<DeviceImportPreview | null>(null)
  const deviceImportBusy = ref(false)
  const ownedDeviceIds = ref<string[]>([])
  const loading = ref(false)
  const error = ref('')
  const errorCode = ref('')
  const openingKind = ref<SessionKind | ''>('')
  const sessionActionId = ref('')
  const deviceAction = ref('')
  const notice = ref('')
  let eventSocket: WebSocket | null = null
  let eventReconnectTimer: ReturnType<typeof setTimeout> | null = null
  let automationRefreshTimer: ReturnType<typeof setTimeout> | null = null
  let automationRefreshPromise: Promise<void> | null = null
  let automationRefreshQueued = false
  let lastEventSequence = 0
  let eventStreamWanted = false
  let eventConnectedOnce = false
  let deviceQueryTimer: ReturnType<typeof setTimeout> | null = null

  const selectedDevice = computed(
    () => devices.value.find((device) => device.row_id === selectedDeviceRowId.value)
      || devices.value.find((device) => device.id === selectedDeviceRowId.value)
      || null
  )
  const selectedDeviceId = computed(() => selectedDevice.value?.id || '')
  const activeSession = computed(
    () => sessions.value.find((session) => session.id === activeSessionId.value) || null
  )

  function selectDevice(deviceId: string): void {
    // Prefer the stable row identity. Device IDs can appear on multiple
    // controller rows, while row_id identifies the exact selectable entry.
    const device = devices.value.find((item) => item.row_id === deviceId)
      || devices.value.find((item) => item.id === deviceId)
    if (device) selectedDeviceRowId.value = device.row_id
  }
  const currentCommandGroup = computed(
    () => commandGroups.value.find((group) => group.id === currentCommandGroupId.value) || null
  )
  const connectedSessions = computed(() =>
    sessions.value.filter((session) => session.status === 'connected')
  )
  const activeAutomationStatus = computed(() =>
    automationSessions.value.find((status) => status.session_id === activeSessionId.value) || null
  )
  const ownedDeviceIdSet = computed(() => new Set(ownedDeviceIds.value))
  const deviceFilterIndex = computed(() => new Map(
    devices.value.map((device) => [device.row_id, {
      searchText: [
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
      ].join(' ').toLocaleLowerCase(),
      cpu: device.cpu.toLocaleLowerCase()
    }])
  ))
  const filteredDevices = computed(() => {
    const needle = effectiveQuery.value
    const cpuNeedle = cpuFilter.value.trim().toLocaleLowerCase()
    return devices.value.filter((device) => {
      const index = deviceFilterIndex.value.get(device.row_id)
      if (needle && !index?.searchText.includes(needle)) return false
      if (domainFilter.value && device.domain !== domainFilter.value) return false
      if (statusFilter.value && device.status !== statusFilter.value) return false
      if (cpuNeedle && !index?.cpu.includes(cpuNeedle)) return false
      if (mineOnly.value && !ownedDeviceIdSet.value.has(device.id)) return false
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
    if (deviceQueryTimer) clearTimeout(deviceQueryTimer)
    deviceQueryTimer = null
    query.value = ''
    effectiveQuery.value = ''
    domainFilter.value = ''
    statusFilter.value = ''
    cpuFilter.value = ''
    mineOnly.value = false
  }

  watch(query, (value) => {
    if (deviceQueryTimer) clearTimeout(deviceQueryTimer)
    deviceQueryTimer = null
    const normalized = value.trim().toLocaleLowerCase()
    if (!normalized || devices.value.length < 200) {
      effectiveQuery.value = normalized
      return
    }
    deviceQueryTimer = setTimeout(() => {
      effectiveQuery.value = normalized
      deviceQueryTimer = null
    }, 120)
  })

  function applyCommandWorkspace(response: CommandWorkspaceResponse): void {
    commandGroups.value = response.groups
    commandHistory.value = response.history
    currentCommandGroupId.value = response.current_group_id
    commandEnterSends.value = response.enter_sends
  }

  function applyDeviceInventory(response: DeviceListResponse): void {
    devices.value = response.devices
    deviceFieldSchema.value = response.field_schema || []
    currentUser.value = response.current_user
    ownedDeviceIds.value = response.owned_device_ids
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
    automationActivity.value = response.activity || []
  }

  async function initialize(): Promise<void> {
    loading.value = true
    error.value = ''
    errorCode.value = ''
    try {
      deviceSourceStatus.value = await desktopApi.deviceSource()
      internalAuthStatus.value = await desktopApi.internalAuthStatus()
      if (
        internalAuthStatus.value.auto_login_error
        && !internalAuthStatus.value.authenticated
      ) {
        notice.value = `自动登录失败：${internalAuthStatus.value.auto_login_error}`
      }
      const [
        deviceResponse,
        sessionResponse,
        profileResponse,
        commandResponse,
        automationResponse,
        transferSettingsResponse,
        transferLogResponse,
        operationResponse,
        taskResponse,
        workflowResponse
      ] = await Promise.all([
        desktopApi.devices(),
        desktopApi.sessions(),
        desktopApi.connectionProfiles(),
        desktopApi.commandWorkspace(),
        desktopApi.automationWorkspace(),
        desktopApi.transferSettings(),
        desktopApi.transferServiceLog(),
        desktopApi.operations('managed_file_transfer'),
        desktopApi.listTasks().catch((cause) => {
          taskError.value = cause instanceof Error ? cause.message : String(cause)
          return { api_version: 1, tasks: [] }
        }),
        desktopApi.workflows().catch(() => ({ workflows: [] }))
      ])
      applyDeviceInventory(deviceResponse)
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
      tasks.value = taskResponse.tasks
      workflows.value = workflowResponse.workflows
      const restoredDevice = devices.value.find(
        (device) => device.row_id === selectedDeviceRowId.value
      ) || devices.value.find((device) => device.id === selectedDeviceRowId.value)
      // A refresh must not silently move the user's selection to the first
      // device (usually the simulator). Only choose a default on first load.
      if (restoredDevice) {
        selectedDeviceRowId.value = restoredDevice.row_id
      } else if (!selectedDeviceRowId.value) {
        selectedDeviceRowId.value = devices.value[0]?.row_id || ''
      }
      if (!sessions.value.some((session) => session.id === activeSessionId.value)) {
        activeSessionId.value = sessions.value[0]?.id || ''
      }
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      loading.value = false
    }
  }

  async function switchDeviceSource(source: DeviceSourceId): Promise<boolean> {
    if (deviceSourceBusy.value || source === deviceSourceStatus.value.active_source) return false
    deviceSourceBusy.value = true
    error.value = ''
    errorCode.value = ''
    try {
      deviceSourceStatus.value = await desktopApi.switchDeviceSource(source)
      clearDeviceFilters()
      devices.value = []
      ownedDeviceIds.value = []
      currentUser.value = ''
      selectedDeviceRowId.value = ''
      await initialize()
      if (!error.value) {
        const label = deviceSourceStatus.value.sources.find((item) => item.id === source)?.label || source
        const defaultLabel = deviceSourceStatus.value.sources.find(
          (item) => item.id === deviceSourceStatus.value.default_source
        )?.label || deviceSourceStatus.value.default_source
        notice.value = source === deviceSourceStatus.value.default_source
          ? `已恢复默认来源“${label}”，当前只显示这一来源的设备。`
          : `已切换到“${label}”；默认来源仍是“${defaultLabel}”，设备不会混合。`
      }
      return !error.value
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      errorCode.value = cause instanceof BackendApiError ? cause.code : ''
      return false
    } finally {
      deviceSourceBusy.value = false
    }
  }

  async function chooseDeviceImport(): Promise<boolean> {
    if (deviceImportBusy.value) return false
    deviceImportBusy.value = true
    error.value = ''
    try {
      const preview = await window.desktopApi.chooseDeviceImport()
      if (!preview) return false
      deviceImportPreview.value = preview
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      deviceImportBusy.value = false
    }
  }

  function cancelDeviceImport(): void {
    deviceImportPreview.value = null
  }

  async function commitDeviceImport(): Promise<boolean> {
    const preview = deviceImportPreview.value
    if (!preview || deviceImportBusy.value) return false
    deviceImportBusy.value = true
    error.value = ''
    errorCode.value = ''
    try {
      const response = await desktopApi.commitDeviceImport(preview.token)
      deviceSourceStatus.value = response.source
      deviceImportPreview.value = null
      clearDeviceFilters()
      devices.value = []
      ownedDeviceIds.value = []
      currentUser.value = ''
      selectedDeviceRowId.value = ''
      await initialize()
      if (!error.value) {
        notice.value = `已用 ${preview.file_name} 覆盖导入 ${response.imported_count} 台设备。`
      }
      return !error.value
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      errorCode.value = cause instanceof BackendApiError ? cause.code : ''
      return false
    } finally {
      deviceImportBusy.value = false
    }
  }

  async function loginInternalService(): Promise<boolean> {
    if (internalAuthBusy.value) return false
    internalAuthBusy.value = true
    error.value = ''
    try {
      const status = await window.desktopApi.loginInternalService({
        sourceLabel: deviceSourceStatus.value.sources.find(
          (source) => source.id === deviceSourceStatus.value.active_source
        )?.label || '设备网站',
        username: internalAuthStatus.value.username,
        cid: internalAuthStatus.value.cid,
        remembered: internalAuthStatus.value.remembered,
        autoLogin: internalAuthStatus.value.auto_login
      })
      if (!status) return false
      internalAuthStatus.value = status
      const credentialWarning = status.credential_warning
      await initialize()
      if (!error.value) {
        const sourceLabel = deviceSourceStatus.value.sources.find(
          (source) => source.id === deviceSourceStatus.value.active_source
        )?.label || '设备网站'
        notice.value = credentialWarning
          ? `已登录，但未能记住密码：${credentialWarning}`
          : `已登录${sourceLabel}：${status.username}`
      }
      return !error.value
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      internalAuthBusy.value = false
    }
  }

  async function logoutInternalService(): Promise<boolean> {
    if (internalAuthBusy.value) return false
    internalAuthBusy.value = true
    error.value = ''
    try {
      internalAuthStatus.value = await desktopApi.logoutInternalService()
      devices.value = []
      ownedDeviceIds.value = []
      currentUser.value = ''
      selectedDeviceRowId.value = ''
      notice.value = '已退出设备网站，登录 Cookie 已清除。'
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      internalAuthBusy.value = false
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
      const index = operations.value.findIndex((item) => item.id === operation.id)
      if (index >= 0 && operations.value[index].revision >= operation.revision) return
      if (index >= 0) operations.value[index] = operation
      else operations.value.unshift(operation)
      if (['completed', 'failed', 'cancelled', 'interrupted'].includes(operation.status)) {
        notice.value = operation.message
      }
      return
    }
    if (event.type.startsWith('transfer.service.') && event.type !== 'transfer.service.log') {
      transferSettings.value = {
        ...(transferSettings.value || {} as TransferSettings),
        ...(data as unknown as Partial<TransferSettings>)
      }
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
      else if (event.type === 'automation.rule.waiting') notice.value = `自动化等待下一步输出: ${name}`
      else if (event.type === 'automation.rule.failed') {
        const message = typeof data.message === 'string' ? data.message.trim() : ''
        error.value = `自动化执行失败: ${name}${message ? ` · ${message}` : ''}`
      }
      else if (event.type === 'automation.rule.cancelled') notice.value = `自动化已取消: ${name}`
      scheduleAutomationRefresh()
    }
  }

  async function connectApplicationEvents(): Promise<void> {
    if (eventSocket || !eventStreamWanted) return
    try {
      eventSocket = new WebSocket(await applicationEventSocketUrl(lastEventSequence))
      eventSocket.onopen = () => {
        if (eventConnectedOnce) {
          void refreshOperations()
          void loadTransferServiceLog()
        }
        eventConnectedOnce = true
      }
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
      if (automationRefreshTimer) clearTimeout(automationRefreshTimer)
      automationRefreshTimer = null
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
    profileId = '',
    secrets: ConnectionProfileSecrets = {}
  ): Promise<ConnectionProfileSummary | null> {
    error.value = ''
    errorCode.value = ''
    try {
      const saved = payload.profile_type === 'temporary'
        ? await desktopApi.saveTemporaryProfileWithSecrets(profileId, payload, secrets)
        : profileId
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

  async function reorderCommandGroups(groupIds: string[]): Promise<boolean> {
    const previous = [...commandGroups.value]
    const byId = new Map(previous.map((group) => [group.id, group]))
    if (groupIds.length !== previous.length || groupIds.some((groupId) => !byId.has(groupId))) {
      return false
    }
    commandGroups.value = groupIds.map((groupId, sortOrder) => ({
      ...byId.get(groupId)!,
      sort_order: sortOrder
    }))
    try {
      applyCommandWorkspace(await desktopApi.reorderCommandGroups(groupIds))
      return true
    } catch (cause) {
      commandGroups.value = previous
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
      if (broadcast) await desktopApi.broadcastCommand(command)
      else await desktopApi.sendCommand(activeSessionId.value, command)
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

  function scheduleAutomationRefresh(): void {
    if (automationRefreshTimer) clearTimeout(automationRefreshTimer)
    automationRefreshTimer = setTimeout(() => {
      automationRefreshTimer = null
      void refreshAutomation()
    }, 40)
  }

  async function refreshAutomation(): Promise<void> {
    if (automationRefreshTimer) clearTimeout(automationRefreshTimer)
    automationRefreshTimer = null
    if (automationRefreshPromise) {
      automationRefreshQueued = true
      return automationRefreshPromise
    }
    automationRefreshPromise = (async () => {
      do {
        automationRefreshQueued = false
        try {
          applyAutomationWorkspace(await desktopApi.automationWorkspace())
        } catch (cause) {
          error.value = cause instanceof Error ? cause.message : String(cause)
        }
      } while (automationRefreshQueued)
    })()
    try {
      await automationRefreshPromise
    } finally {
      automationRefreshPromise = null
    }
  }

  function registerAutomationCloseGuard(guard: () => boolean): () => void {
    automationCloseGuard = guard
    return () => {
      if (automationCloseGuard === guard) automationCloseGuard = null
    }
  }

  function closeAutomationPanel(): boolean {
    if (!automationPanelOpen.value) return true
    if (automationCloseGuard && !automationCloseGuard()) return false
    automationPanelOpen.value = false
    return true
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

  async function previewAutomationRule(
    rule: AutoResponseRulePayload,
    sampleOutput = ''
  ): Promise<AutomationPreviewResponse | null> {
    automationBusy.value = true
    error.value = ''
    try {
      return await desktopApi.previewAutomationRule(
        rule,
        activeSessionId.value,
        sampleOutput
      )
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

  async function cloneAutomationRule(ruleId: string): Promise<AutomationRuleRecord | null> {
    automationBusy.value = true
    error.value = ''
    const previousIds = new Set(automationRules.value.map((record) => record.id))
    try {
      applyAutomationWorkspace(await desktopApi.cloneAutomationRule(ruleId))
      const cloned = automationRules.value.find((record) => !previousIds.has(record.id)) || null
      if (cloned) notice.value = `已创建停用副本: ${cloned.rule.name}`
      return cloned
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return null
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

  async function loadTransferFiles(options: {
    query?: string
    sort?: 'name' | 'size' | 'modified'
    order?: 'asc' | 'desc'
    offset?: number
    append?: boolean
  } = {}): Promise<void> {
    transferFilesLoading.value = true
    transferError.value = ''
    try {
      const response = await desktopApi.sharedTransferFiles({
        query: options.query,
        sort: options.sort,
        order: options.order,
        offset: options.offset,
        limit: 100
      })
      transferFiles.value = options.append
        ? [...transferFiles.value, ...response.files]
        : response.files
      transferFileTotal.value = response.total
      transferFileNextOffset.value = response.next_offset
    } catch (cause) {
      transferFiles.value = []
      transferFileTotal.value = 0
      transferFileNextOffset.value = null
      transferError.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      transferFilesLoading.value = false
    }
  }

  async function loadTransferServiceLog(): Promise<void> {
    try {
      const response = await desktopApi.transferServiceLog()
      transferServiceLog.value = response.entries
      transferClientCommand.value = response.client_command
    } catch (cause) {
      transferError.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function clearTransferServiceLog(): Promise<void> {
    try {
      const response = await desktopApi.clearTransferServiceLog()
      transferServiceLog.value = response.entries
      transferClientCommand.value = response.client_command
      notice.value = '文件服务日志已清空'
    } catch (cause) {
      transferError.value = cause instanceof Error ? cause.message : String(cause)
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
      transferError.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function saveTransferSettings(
    settings: Pick<TransferSettings, 'protocol' | 'host' | 'advertised_host' | 'port' | 'root' | 'username' | 'writable'> & {
      password?: string
    }
  ): Promise<boolean> {
    transferBusy.value = true
    transferError.value = ''
    try {
      transferSettings.value = await desktopApi.updateTransferSettings(settings)
      await loadTransferFiles()
      return true
    } catch (cause) {
      transferError.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      transferBusy.value = false
    }
  }

  async function toggleTransferService(): Promise<void> {
    if (!transferSettings.value) return
    transferBusy.value = true
    transferError.value = ''
    try {
      transferSettings.value = transferSettings.value.service_running
        ? await desktopApi.stopTransferService()
        : await desktopApi.startTransferService()
      await loadTransferServiceLog()
    } catch (cause) {
      transferError.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      transferBusy.value = false
    }
  }

  async function startManagedTransfer(payload: {
    direction: 'upload' | 'download'
    source_path: string
    destination_path: string
    overwrite: boolean
    terminal_environment: 'auto' | 'linux' | 'vrp'
    command_mode: 'vrp' | 'ftpget'
  }): Promise<boolean> {
    if (!activeSessionId.value) return false
    transferBusy.value = true
    transferError.value = ''
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
      transferError.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      transferBusy.value = false
    }
  }

  async function cancelOperation(operationId: string): Promise<void> {
    transferBusy.value = true
    transferError.value = ''
    try {
      const response = await desktopApi.cancelOperation(operationId)
      const index = operations.value.findIndex((record) => record.id === operationId)
      if (index >= 0) operations.value[index] = response.operation
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : String(cause)
      transferError.value = message
    } finally {
      transferBusy.value = false
    }
  }

  async function retryManagedTransfer(operationId: string): Promise<boolean> {
    transferBusy.value = true
    transferError.value = ''
    try {
      const response = await desktopApi.retryManagedTransfer(operationId)
      operations.value = [response.operation, ...operations.value]
      notice.value = '传输已重新加入队列'
      return true
    } catch (cause) {
      transferError.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      transferBusy.value = false
    }
  }

  async function resumeTransferQueue(sessionId: string): Promise<void> {
    transferBusy.value = true
    transferError.value = ''
    try {
      const response = await desktopApi.resumeTransferQueue(sessionId)
      notice.value = `已恢复 ${response.resumed_count} 个排队任务`
      await refreshOperations()
    } catch (cause) {
      transferError.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      transferBusy.value = false
    }
  }

  async function clearTransferHistory(): Promise<void> {
    transferBusy.value = true
    transferError.value = ''
    try {
      const response = await desktopApi.clearTransferHistory()
      operations.value = operations.value.filter((operation) => !['completed', 'failed', 'cancelled', 'interrupted'].includes(operation.status))
      notice.value = `已清理 ${response.deleted_count} 条传输历史`
    } catch (cause) {
      transferError.value = cause instanceof Error ? cause.message : String(cause)
    } finally {
      transferBusy.value = false
    }
  }

  async function refreshTasks(): Promise<void> {
    try {
      taskError.value = ''
      const response = await desktopApi.listTasks()
      tasks.value = response.tasks
      if (activeTaskId.value) {
        const active = tasks.value.find((item) => item.id === activeTaskId.value)
        const isTerminal = Boolean(active && ['completed', 'failed', 'cancelled'].includes(active.status))
        const isWaiting = Boolean(active && ['waiting_for_decision', 'waiting_for_user'].includes(active.status))
        // Keep task/session data fresh without taking the foreground away from
        // a device or session the user selected while the task is running.
        if (active) await syncTaskSession(active, false)
        if (isTerminal && taskRefreshTimer) {
          clearInterval(taskRefreshTimer)
          taskRefreshTimer = null
        }
        if (isWaiting && active) {
          const decision = await desktopApi.getTaskDecision(active.id)
          taskDecision.value = decision.decision
        } else {
          // A decision is actionable only while the task is waiting. Clear the
          // cached context after approval/resume and when a task reaches any
          // non-waiting state, otherwise a completed task can show stale
          // "需要人工 Action" controls from an earlier checkpoint.
          taskDecision.value = null
        }
      }
    } catch (cause) {
      taskError.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function refreshWorkflows(): Promise<void> {
    try {
      workflows.value = (await desktopApi.workflows()).workflows
    } catch (cause) {
      taskError.value = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async function createNamedWorkflowTask(workflowId: string, parameters: Record<string, unknown>): Promise<boolean> {
    const deviceId = selectedDeviceId.value
    if (!deviceId || !workflowId) return false
    taskBusy.value = true
    error.value = ''
    taskError.value = ''
    try {
      const response = await desktopApi.createTask({ workflow_id: workflowId, device_id: deviceId, parameters, source: 'desktop' })
      activeTaskId.value = response.task.id
      tasks.value = [response.task, ...tasks.value.filter((item) => item.id !== response.task.id)]
      await syncTaskSession(response.task)
      taskDecision.value = null
      notice.value = 'Workflow Task 已创建'
      startTaskPolling()
      return true
    } catch (cause) {
      taskError.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      taskBusy.value = false
    }
  }

  async function createDeviceUpgradeTask(packagePath: string, options: Record<string, unknown> = {}): Promise<boolean> {
    return createNamedWorkflowTask('device_upgrade', { package_path: packagePath, ...options })
  }

  async function createWorkflowPlanTask(objective: string, command: string): Promise<boolean> {
    const deviceId = selectedDeviceId.value
    if (!deviceId || !objective.trim() || !command.trim()) return false
    taskBusy.value = true
    taskError.value = ''
    try {
      const plan = {
        plan_id: 'ui-' + Date.now().toString(36),
        objective: objective.trim(),
        target: { device_id: deviceId },
        steps: [{
          id: 'command',
          capability: 'terminal.command',
          params: { command: command.trim() }
        }]
      }
      const validated = await desktopApi.workflowPlanValidate(plan)
      const result = validated.data
      if (!['validated', 'requires_confirmation'].includes(result.status)) {
        taskError.value = result.errors?.map((item) => item.message || item.code || '计划校验失败').join('；') || '计划校验失败'
        return false
      }
      if (result.status === 'requires_confirmation') {
        await desktopApi.workflowPlanApprove(result.plan_id, result.plan_hash, '桌面任务工作区确认执行')
      }
      const started = await desktopApi.workflowRunPlan(result.plan_id, result.plan_hash)
      activeTaskId.value = started.data.task.id
      tasks.value = [started.data.task, ...tasks.value.filter((item) => item.id !== started.data.task.id)]
      await syncTaskSession(started.data.task)
      taskDecision.value = null
      notice.value = '计划任务已创建'
      startTaskPolling()
      return true
    } catch (cause) {
      taskError.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      taskBusy.value = false
    }
  }

  async function getTask(taskId: string, focus = true): Promise<TaskRecord | null> {
    try {
      const response = await desktopApi.getTask(taskId)
      tasks.value = [response.task, ...tasks.value.filter((item) => item.id !== taskId)]
      if (taskId === activeTaskId.value) await syncTaskSession(response.task, focus)
      if (taskId === activeTaskId.value && ['waiting_for_decision', 'waiting_for_user'].includes(response.task.status)) {
        taskDecision.value = (await desktopApi.getTaskDecision(taskId)).decision
      } else if (taskId === activeTaskId.value) {
        // Do not retain the previous decision context once the task resumes or
        // reaches a terminal state.
        taskDecision.value = null
      }
      return response.task
    } catch (cause) {
      taskError.value = cause instanceof Error ? cause.message : String(cause)
      return null
    }
  }

  async function syncTaskSession(task: TaskRecord, focus = true): Promise<void> {
    if (focus && task.device_id) selectDevice(task.device_id)
    if (!task.session_id) return

    let session = sessions.value.find((item) => item.id === task.session_id)
    if (!session) {
      try {
        // An Agent may create the Backend session before the renderer knows
        // about it. Refresh the session inventory and attach the terminal to
        // the Task's existing session; do not open a second device session.
        const available = await desktopApi.sessions()
        for (const item of available) upsertSession(item)
        session = sessions.value.find((item) => item.id === task.session_id)
      } catch (cause) {
        taskError.value = cause instanceof Error ? cause.message : String(cause)
      }
    }
    if (focus && session) activeSessionId.value = session.id
  }

  async function pauseTask(taskId = activeTaskId.value): Promise<void> {
    if (!taskId) return
    taskBusy.value = true
    try {
      const response = await desktopApi.pauseTask(taskId)
      tasks.value = [response.task, ...tasks.value.filter((item) => item.id !== taskId)]
    } catch (cause) { taskError.value = cause instanceof Error ? cause.message : String(cause) } finally { taskBusy.value = false }
  }

  async function resumeTask(taskId = activeTaskId.value, stepId = ''): Promise<void> {
    if (!taskId) return
    taskBusy.value = true
    try {
      const response = await desktopApi.resumeTask(taskId, stepId)
      tasks.value = [response.task, ...tasks.value.filter((item) => item.id !== taskId)]
      startTaskPolling()
    } catch (cause) { taskError.value = cause instanceof Error ? cause.message : String(cause) } finally { taskBusy.value = false }
  }

  async function cancelTask(taskId = activeTaskId.value): Promise<void> {
    if (!taskId) return
    taskBusy.value = true
    try {
      const response = await desktopApi.cancelTask(taskId)
      tasks.value = [response.task, ...tasks.value.filter((item) => item.id !== taskId)]
      taskDecision.value = null
    } catch (cause) { taskError.value = cause instanceof Error ? cause.message : String(cause) } finally { taskBusy.value = false }
  }

  async function applyTaskDecision(action: TaskDecisionActionPayload, reason = ''): Promise<void> {
    const task = tasks.value.find((item) => item.id === activeTaskId.value)
    if (!task || !taskDecision.value) return
    taskBusy.value = true
    try {
      const response = await desktopApi.applyTaskDecision(activeTaskId.value, { action, expected_revision: taskDecision.value.checkpoint_revision, reason })
      tasks.value = [response.task, ...tasks.value.filter((item) => item.id !== response.task.id)]
      taskDecision.value = null
      startTaskPolling()
    } catch (cause) { taskError.value = cause instanceof Error ? cause.message : String(cause) } finally { taskBusy.value = false }
  }

  function startTaskPolling(): void {
    if (taskRefreshTimer) clearInterval(taskRefreshTimer)
    taskRefreshTimer = setInterval(() => { void refreshTasks() }, 900)
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

  async function reconnectSession(sessionId: string): Promise<boolean> {
    sessionActionId.value = sessionId
    error.value = ''
    try {
      upsertSession(await desktopApi.reconnectSession(sessionId))
      notice.value = '会话正在重新连接。'
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      sessionActionId.value = ''
    }
  }

  async function disconnectSession(sessionId: string): Promise<boolean> {
    sessionActionId.value = sessionId
    error.value = ''
    try {
      upsertSession(await desktopApi.disconnectSession(sessionId))
      notice.value = '会话已断开。'
      return true
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : String(cause)
      return false
    } finally {
      sessionActionId.value = ''
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
      // Frame-level occupancy can update several board rows at once. Apply the
      // authoritative post-action inventory returned with the same response.
      applyDeviceInventory(response)
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
    // Filtering changes the visible list, not the user's selected device.
    // Keep the selection stable so task controls cannot jump to the first row.
    if (!selectedDeviceRowId.value && visibleDevices.length) {
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
    if (open) transferError.value = ''
  })
  watch(upgradePanelOpen, (open) => {
    localStorage.setItem('device-tui.desktop-v2.upgrade-open', open ? '1' : '0')
  })
  watch(aiPanelOpen, (open) => {
    localStorage.setItem('device-tui.desktop-v2.ai-open', open ? '1' : '0')
  })

  return {
    devices,
    deviceFieldSchema,
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
    automationActivity,
    automationPanelOpen,
    automationBusy,
    transferSettings,
    transferServiceLog,
    transferClientCommand,
    transferFiles,
    transferFilesLoading,
    transferFileTotal,
    transferFileNextOffset,
    operations,
    transferPanelOpen,
    transferBusy,
    transferError,
    retryManagedTransfer,
    resumeTransferQueue,
    clearTransferHistory,
    upgradePanelOpen,
    tasks,
    workflows,
    activeTaskId,
    taskBusy,
    taskDecision,
    taskError,
    refreshTasks,
    refreshWorkflows,
    createNamedWorkflowTask,
    createDeviceUpgradeTask,
    createWorkflowPlanTask,
    getTask,
    pauseTask,
    resumeTask,
    cancelTask,
    applyTaskDecision,
    aiPanelOpen, aiBusy, aiObjective, aiPlan,
    buildAiPlan,
    selectedDeviceId,
    selectDevice,
    activeSessionId,
    query,
    domainFilter,
    statusFilter,
    cpuFilter,
    mineOnly,
    profileQuery,
    currentUser,
    internalAuthStatus,
    internalAuthBusy,
    deviceSourceStatus,
    deviceSourceBusy,
    deviceImportPreview,
    deviceImportBusy,
    loading,
    error,
    errorCode,
    openingKind,
    sessionActionId,
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
    switchDeviceSource,
    chooseDeviceImport,
    cancelDeviceImport,
    commitDeviceImport,
    loginInternalService,
    logoutInternalService,
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
    reorderCommandGroups,
    deleteCommandGroup,
    selectCommandGroup,
    setCommandEnterSends,
    fetchCommandSuggestions,
    dispatchCommand,
    refreshAutomation,
    registerAutomationCloseGuard,
    closeAutomationPanel,
    saveAutomationRule,
    previewAutomationRule,
    cloneAutomationRule,
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
    deleteProfile,
    closeSession,
    reconnectSession,
    disconnectSession,
    closeSessionsRelative,
    closeDeviceSessionGroups,
    closeActiveSession,
    closeOtherSessions,
    closeAllSessions,
    runDeviceAction,
    updateSessionStatus
  }
})
