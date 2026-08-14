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
  payload: import('./types').ConnectionProfilePayload
  secrets: import('./types').ConnectionProfileSecrets
}

interface SessionLogExportRequest {
  suggestedName: string
  content: string
}

interface DesktopApi {
  getRuntimeConfig(): Promise<BackendRuntime>
  request(request: BackendRequest): Promise<BackendResponse>
  openProfileSession(request: ProfileCredentialRequest): Promise<import('./types').SessionSummary | null>
  openDeviceSession(request: DeviceConnectionRequest): Promise<import('./types').SessionSummary | null>
  manageProfileCredential(request: ProfileCredentialRequest): Promise<boolean>
  saveTemporaryProfile(request: TemporaryProfileSaveRequest): Promise<BackendResponse>
  chooseTransferRoot(): Promise<string>
  chooseSessionLogDirectory(): Promise<string>
  openSessionLogDirectory(): Promise<boolean>
  openCurrentSessionLog(sessionId: string): Promise<boolean>
  saveSessionLog(request: SessionLogExportRequest): Promise<boolean>
  readClipboardText(): Promise<string>
  writeClipboardText(value: string): Promise<boolean>
  setAlwaysOnTop(enabled: boolean): Promise<boolean>
  onBackendExit(callback: (details: string) => void): () => void
  onBackendRecovered(callback: (details: string) => void): () => void
}

interface Window {
  desktopApi: DesktopApi
}
