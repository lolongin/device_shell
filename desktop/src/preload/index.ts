import { contextBridge, ipcRenderer } from 'electron'
interface RendererRuntime {
  apiBaseUrl: string
  apiVersion: number
}

interface BackendRequest {
  path: string
  method?: string
  body?: string
}

interface BackendResponse {
  status: number
  body: string
}

interface ProfileCredentialRequest {
  profileId: string
  profileName: string
  protocol: 'ssh' | 'telnet' | 'serial'
  endpoint: string
  hasPassword: boolean
}

interface DeviceConnectionRequest {
  deviceId: string
  deviceName: string
  protocol: 'ssh' | 'telnet' | 'serial'
  host: string
  port: number
  username: string
}

interface TemporaryProfileSaveRequest {
  profileId?: string
  payload: Record<string, unknown>
  secrets: Partial<Record<'telnet' | 'ssh' | 'serial', string>>
}

interface InternalLoginPromptRequest {
  sourceLabel: string
  username: string
  cid: string
  remembered: boolean
  autoLogin: boolean
}

interface SessionLogExportRequest {
  suggestedName: string
  content: string
}

interface TransferSettingsSaveRequest {
  protocol: 'ftp'
  host: string
  advertised_host: string
  port: number
  root: string
  username: string
  password?: string
  writable: boolean
}

interface LocalTerminalSummary {
  id: string
  device_id: string
  kind: 'local'
  title: string
  status: string
  sequence: number
  generation: number
  shell: string
  cwd: string
}

const desktopApi = {
  getRuntimeConfig: (): Promise<RendererRuntime> => ipcRenderer.invoke('runtime:get'),
  request: (request: BackendRequest): Promise<BackendResponse> =>
    ipcRenderer.invoke('backend:request', request),
  listLocalTerminals: (): Promise<LocalTerminalSummary[]> => ipcRenderer.invoke('local-terminal:list'),
  openLocalTerminal: (request?: { shell?: string; cwd?: string }): Promise<LocalTerminalSummary> =>
    ipcRenderer.invoke('local-terminal:open', request),
  subscribeLocalTerminal: (sessionId: string): Promise<{ session: LocalTerminalSummary; output: string }> =>
    ipcRenderer.invoke('local-terminal:subscribe', sessionId),
  writeLocalTerminal: (sessionId: string, data: string): Promise<boolean> =>
    ipcRenderer.invoke('local-terminal:write', sessionId, data),
  resizeLocalTerminal: (sessionId: string, cols: number, rows: number): Promise<boolean> =>
    ipcRenderer.invoke('local-terminal:resize', sessionId, cols, rows),
  closeLocalTerminal: (sessionId: string): Promise<boolean> => ipcRenderer.invoke('local-terminal:close', sessionId),
  disconnectLocalTerminal: (sessionId: string): Promise<boolean> => ipcRenderer.invoke('local-terminal:disconnect', sessionId),
  reconnectLocalTerminal: (sessionId: string): Promise<LocalTerminalSummary> =>
    ipcRenderer.invoke('local-terminal:reconnect', sessionId),
  onLocalTerminalData: (callback: (event: { sessionId: string; sequence: number; data: string }) => void): (() => void) => {
    const listener = (_event: Electron.IpcRendererEvent, value: unknown): void => {
      if (!value || typeof value !== 'object') return
      const payload = value as { sessionId?: unknown; sequence?: unknown; data?: unknown }
      if (typeof payload.sessionId !== 'string' || typeof payload.sequence !== 'number' || typeof payload.data !== 'string') return
      callback({ sessionId: payload.sessionId, sequence: payload.sequence, data: payload.data })
    }
    ipcRenderer.on('local-terminal:data', listener)
    return () => ipcRenderer.removeListener('local-terminal:data', listener)
  },
  onLocalTerminalStatus: (callback: (event: { sessionId: string; sequence: number; status: string; error?: string }) => void): (() => void) => {
    const listener = (_event: Electron.IpcRendererEvent, value: unknown): void => {
      if (!value || typeof value !== 'object') return
      const payload = value as { sessionId?: unknown; sequence?: unknown; status?: unknown; error?: unknown }
      if (typeof payload.sessionId !== 'string' || typeof payload.sequence !== 'number' || typeof payload.status !== 'string') return
      callback({ sessionId: payload.sessionId, sequence: payload.sequence, status: payload.status, ...(typeof payload.error === 'string' ? { error: payload.error } : {}) })
    }
    ipcRenderer.on('local-terminal:status', listener)
    return () => ipcRenderer.removeListener('local-terminal:status', listener)
  },
  openProfileSession: (request: ProfileCredentialRequest): Promise<unknown | null> =>
    ipcRenderer.invoke('credential:open-profile-session', request),
  openDeviceSession: (request: DeviceConnectionRequest): Promise<unknown | null> =>
    ipcRenderer.invoke('credential:open-device-session', request),
  manageProfileCredential: (request: ProfileCredentialRequest): Promise<boolean> =>
    ipcRenderer.invoke('credential:manage-profile', request),
  saveTemporaryProfile: (request: TemporaryProfileSaveRequest): Promise<BackendResponse> =>
    ipcRenderer.invoke('credential:create-temporary-profile', request),
  loginInternalService: (request: InternalLoginPromptRequest): Promise<unknown | null> =>
    ipcRenderer.invoke('internal-auth:login', request),
  chooseDeviceImport: (): Promise<unknown | null> =>
    ipcRenderer.invoke('device-source:choose-import'),
  chooseTransferRoot: (): Promise<string> =>
    ipcRenderer.invoke('file-transfer:choose-root'),
  choosePackage: (defaultPath?: string): Promise<string> =>
    ipcRenderer.invoke('file-transfer:choose-package', defaultPath),
  chooseWorkflowFile: (request: { defaultPath?: string; label?: string; extensions?: string[] }): Promise<string> =>
    ipcRenderer.invoke('workflow:choose-file', request),
  saveTransferSettings: (request: TransferSettingsSaveRequest): Promise<BackendResponse> =>
    ipcRenderer.invoke('file-transfer:save-settings', request),
  copyTransferCommand: (command: string): Promise<boolean> =>
    ipcRenderer.invoke('file-transfer:copy-command', command),
  chooseSessionLogDirectory: (): Promise<string> =>
    ipcRenderer.invoke('logs:choose-directory'),
  openSessionLogDirectory: (): Promise<boolean> =>
    ipcRenderer.invoke('logs:open-directory'),
  openCurrentSessionLog: (sessionId: string): Promise<boolean> =>
    ipcRenderer.invoke('logs:open-session', sessionId),
  saveSessionLog: (request: SessionLogExportRequest): Promise<boolean> =>
    ipcRenderer.invoke('logs:save-copy', request),
  readClipboardText: (): Promise<string> =>
    ipcRenderer.invoke('clipboard:read-text'),
  writeClipboardText: (value: string): Promise<boolean> =>
    ipcRenderer.invoke('clipboard:write-text', value),
  setAlwaysOnTop: (enabled: boolean): Promise<boolean> =>
    ipcRenderer.invoke('window:set-always-on-top', enabled),
  setNativeTheme: (mode: 'dark' | 'light'): Promise<'dark' | 'light'> =>
    ipcRenderer.invoke('window:set-native-theme', mode),
  showApplicationMenu: (key: 'file' | 'edit' | 'view' | 'window', x: number, y: number): Promise<void> =>
    ipcRenderer.invoke('window:show-application-menu', key, x, y),
  onBackendExit: (callback: (details: string) => void): (() => void) => {
    const listener = (_event: Electron.IpcRendererEvent, details: string): void => callback(details)
    ipcRenderer.on('backend:exit', listener)
    return () => ipcRenderer.removeListener('backend:exit', listener)
  },
  onBackendRecovered: (callback: (details: string) => void): (() => void) => {
    const listener = (_event: Electron.IpcRendererEvent, details: string): void => callback(details)
    ipcRenderer.on('backend:recovered', listener)
    return () => ipcRenderer.removeListener('backend:recovered', listener)
  }
}

contextBridge.exposeInMainWorld('desktopApi', desktopApi)
