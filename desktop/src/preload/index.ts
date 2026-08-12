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

interface SessionLogExportRequest {
  suggestedName: string
  content: string
}

const desktopApi = {
  getRuntimeConfig: (): Promise<RendererRuntime> => ipcRenderer.invoke('runtime:get'),
  request: (request: BackendRequest): Promise<BackendResponse> =>
    ipcRenderer.invoke('backend:request', request),
  openProfileSession: (request: ProfileCredentialRequest): Promise<unknown | null> =>
    ipcRenderer.invoke('credential:open-profile-session', request),
  manageProfileCredential: (request: ProfileCredentialRequest): Promise<boolean> =>
    ipcRenderer.invoke('credential:manage-profile', request),
  chooseTransferRoot: (): Promise<string> =>
    ipcRenderer.invoke('file-transfer:choose-root'),
  chooseSessionLogDirectory: (): Promise<string> =>
    ipcRenderer.invoke('logs:choose-directory'),
  openSessionLogDirectory: (): Promise<boolean> =>
    ipcRenderer.invoke('logs:open-directory'),
  openCurrentSessionLog: (sessionId: string): Promise<boolean> =>
    ipcRenderer.invoke('logs:open-session', sessionId),
  saveSessionLog: (request: SessionLogExportRequest): Promise<boolean> =>
    ipcRenderer.invoke('logs:save-copy', request),
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
