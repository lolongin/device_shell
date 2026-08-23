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

const desktopApi = {
  getRuntimeConfig: (): Promise<RendererRuntime> => ipcRenderer.invoke('runtime:get'),
  request: (request: BackendRequest): Promise<BackendResponse> =>
    ipcRenderer.invoke('backend:request', request),
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
