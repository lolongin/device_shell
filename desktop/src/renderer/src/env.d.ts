/// <reference types="vite/client" />

interface BackendRuntime {
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
  payload: import('./types').ConnectionProfilePayload
  secrets: import('./types').ConnectionProfileSecrets
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

interface DesktopApi {
  getRuntimeConfig(): Promise<BackendRuntime>
  request(request: BackendRequest): Promise<BackendResponse>
  listLocalTerminals(): Promise<LocalTerminalSummary[]>
  openLocalTerminal(request?: { shell?: string; cwd?: string }): Promise<LocalTerminalSummary>
  subscribeLocalTerminal(sessionId: string): Promise<{ session: LocalTerminalSummary; output: string }>
  writeLocalTerminal(sessionId: string, data: string): Promise<boolean>
  resizeLocalTerminal(sessionId: string, cols: number, rows: number): Promise<boolean>
  closeLocalTerminal(sessionId: string): Promise<boolean>
  disconnectLocalTerminal(sessionId: string): Promise<boolean>
  reconnectLocalTerminal(sessionId: string): Promise<LocalTerminalSummary>
  onLocalTerminalData(callback: (event: { sessionId: string; sequence: number; data: string }) => void): () => void
  onLocalTerminalStatus(callback: (event: { sessionId: string; sequence: number; status: string; error?: string }) => void): () => void
  openProfileSession(request: ProfileCredentialRequest): Promise<import('./types').SessionSummary | null>
  openDeviceSession(request: DeviceConnectionRequest): Promise<import('./types').SessionSummary | null>
  manageProfileCredential(request: ProfileCredentialRequest): Promise<boolean>
  saveTemporaryProfile(request: TemporaryProfileSaveRequest): Promise<BackendResponse>
  loginInternalService(request: InternalLoginPromptRequest): Promise<import('./types').InternalAuthStatus | null>
  chooseDeviceImport(): Promise<import('./types').DeviceImportPreview | null>
  chooseTransferRoot(): Promise<string>
  choosePackage(defaultPath?: string): Promise<string>
  chooseWorkflowFile(request: { defaultPath?: string; label?: string; extensions?: string[] }): Promise<string>
  saveTransferSettings(request: TransferSettingsSaveRequest): Promise<BackendResponse>
  copyTransferCommand(command: string): Promise<boolean>
  chooseSessionLogDirectory(): Promise<string>
  openSessionLogDirectory(): Promise<boolean>
  openCurrentSessionLog(sessionId: string): Promise<boolean>
  saveSessionLog(request: SessionLogExportRequest): Promise<boolean>
  readClipboardText(): Promise<string>
  writeClipboardText(value: string): Promise<boolean>
  setAlwaysOnTop(enabled: boolean): Promise<boolean>
  setNativeTheme(mode: 'dark' | 'light'): Promise<'dark' | 'light'>
  showApplicationMenu(key: 'file' | 'edit' | 'view' | 'window', x: number, y: number): Promise<void>
  onBackendExit(callback: (details: string) => void): () => void
  onBackendRecovered(callback: (details: string) => void): () => void
}

interface Window {
  desktopApi: DesktopApi
}
