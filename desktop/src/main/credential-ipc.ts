import type { IpcMain, WebContents } from 'electron'
import type { BackendResponse, BackendRuntime } from './backend-client.js'
import { backendError, fetchBackend } from './backend-client.js'
import type { CredentialDialogResult, DeviceConnectionRequest, InternalLoginPromptRequest, ProfileCredentialRequest } from './credential-types.js'

export interface TemporaryProfileSaveRequest {
  profileId?: string
  payload: Record<string, unknown>
  secrets?: Partial<Record<'telnet' | 'ssh' | 'serial', unknown>>
}

export interface CredentialIpcDependencies {
  ipcMain: IpcMain
  getRenderer: () => WebContents | null
  getRuntime: () => BackendRuntime
  prompt: (request: InternalLoginPromptRequest | DeviceConnectionRequest | ProfileCredentialRequest, mode: 'internal' | 'connect' | 'custom' | 'manage', initialPassword?: string) => Promise<CredentialDialogResult>
  hasSensitiveKey: (value: unknown) => boolean
  resolveDeviceDefaults?: (request: DeviceConnectionRequest) => Promise<{ username: string; password: string }>
}

function assertRenderer(event: Electron.IpcMainInvokeEvent, dependencies: CredentialIpcDependencies): void {
  if (event.sender !== dependencies.getRenderer()) throw new Error('Untrusted credential caller')
}

export function registerSessionCredentialIpc(dependencies: CredentialIpcDependencies): void {
  dependencies.ipcMain.handle('credential:open-profile-session', async (event, request: ProfileCredentialRequest): Promise<unknown | null> => {
    assertRenderer(event, dependencies)
    if (!['ssh', 'telnet', 'serial'].includes(request.protocol)) throw new Error('Invalid connection-profile protocol')
    const profileId = encodeURIComponent(request.profileId)
    let result: CredentialDialogResult = request.hasPassword ? { action: 'submit', password: '', save: true } : await dependencies.prompt(request, 'connect')
    if (result.action !== 'submit') return null
    let response: BackendResponse
    try {
      if (request.hasPassword) {
        response = await fetchBackend(dependencies.getRuntime(), '/api/v1/sessions', 'POST', JSON.stringify({ device_id: request.profileId, kind: request.protocol, title: request.profileName }))
      } else if (result.save) {
        const saved = await fetchBackend(dependencies.getRuntime(), `/api/v1/connection-profiles/${profileId}/credentials/${request.protocol}`, 'PUT', JSON.stringify({ password: result.password }))
        if (saved.status < 200 || saved.status >= 300) throw backendError(saved)
        response = await fetchBackend(dependencies.getRuntime(), '/api/v1/sessions', 'POST', JSON.stringify({ device_id: request.profileId, kind: request.protocol, title: request.profileName }))
      } else {
        response = await fetchBackend(dependencies.getRuntime(), '/api/v1/sessions/with-credential', 'POST', JSON.stringify({ profile_id: request.profileId, kind: request.protocol, password: result.password, title: request.profileName }))
      }
    } finally { result = { action: 'cancel', password: '', save: false } }
    if (response.status < 200 || response.status >= 300) throw backendError(response)
    return JSON.parse(response.body) as unknown
  })

  dependencies.ipcMain.handle('credential:open-device-session', async (event, request: DeviceConnectionRequest): Promise<unknown | null> => {
    assertRenderer(event, dependencies)
    if (!request || !['ssh', 'telnet', 'serial'].includes(request.protocol)) throw new Error('Invalid device connection protocol')
    if (typeof request.deviceId !== 'string' || !request.deviceId.trim() || request.deviceId.length > 160 || typeof request.deviceName !== 'string' || request.deviceName.length > 160 || typeof request.host !== 'string' || request.host.length > 255 || !Number.isInteger(request.port) || request.port < 1 || request.port > 65535 || typeof request.username !== 'string' || request.username.length > 255) throw new Error('Invalid device connection target')
    if (!dependencies.resolveDeviceDefaults) throw new Error('Device credential defaults are unavailable')
    const defaults = await dependencies.resolveDeviceDefaults(request)
    const promptRequest = { ...request, username: defaults.username || request.username }
    let result = await dependencies.prompt(promptRequest, 'custom', defaults.password)
    if (result.action !== 'submit') return null
    let response: BackendResponse
    try {
      response = await fetchBackend(dependencies.getRuntime(), '/api/v1/sessions/direct', 'POST', JSON.stringify({ device_id: request.deviceId, kind: request.protocol, host: result.host, port: result.port, username: result.username, password: result.password, title: request.deviceName }))
    } finally { result = { action: 'cancel', password: '', save: false } }
    if (response.status < 200 || response.status >= 300) throw backendError(response)
    return JSON.parse(response.body) as unknown
  })

  dependencies.ipcMain.handle('credential:manage-profile', async (event, request: ProfileCredentialRequest): Promise<boolean> => {
    assertRenderer(event, dependencies)
    if (!['ssh', 'telnet', 'serial'].includes(request.protocol)) throw new Error('Invalid connection-profile protocol')
    let result = await dependencies.prompt(request, 'manage')
    if (result.action === 'cancel') return false
    const profileId = encodeURIComponent(request.profileId)
    const method = result.action === 'remove' ? 'DELETE' : 'PUT'
    const body = result.action === 'submit' ? JSON.stringify({ password: result.password }) : undefined
    let response: BackendResponse
    try { response = await fetchBackend(dependencies.getRuntime(), `/api/v1/connection-profiles/${profileId}/credentials/${request.protocol}`, method, body) }
    finally { result = { action: 'cancel', password: '', save: false } }
    if (response.status < 200 || response.status >= 300) throw backendError(response)
    return true
  })
}

export function registerInternalCredentialIpc(dependencies: CredentialIpcDependencies): void {
  dependencies.ipcMain.handle('internal-auth:login', async (event, request: InternalLoginPromptRequest): Promise<unknown | null> => {
    if (event.sender !== dependencies.getRenderer()) throw new Error('Untrusted internal-auth caller')
    if (!request || typeof request.sourceLabel !== 'string' || !request.sourceLabel.trim() || request.sourceLabel.length > 80
      || typeof request.username !== 'string' || request.username.length > 255
      || typeof request.cid !== 'string' || request.cid.length > 255
      || typeof request.remembered !== 'boolean' || typeof request.autoLogin !== 'boolean') {
      throw new Error('Invalid internal-auth prompt defaults')
    }
    let result = await dependencies.prompt(request, 'internal')
    if (result.action !== 'submit') return null
    let response: BackendResponse
    try {
      response = await fetchBackend(dependencies.getRuntime(), '/api/v1/internal-auth/login', 'POST', JSON.stringify({
        username: result.username, password: result.password, cid: result.cid,
        remember: result.save, auto_login: result.autoLogin === true,
        use_saved_password: !result.password && request.remembered
      }))
    } finally {
      result = { action: 'cancel', password: '', save: false }
    }
    if (response.status < 200 || response.status >= 300) throw backendError(response)
    return JSON.parse(response.body) as unknown
  })

  dependencies.ipcMain.handle('credential:create-temporary-profile', async (event, request: TemporaryProfileSaveRequest): Promise<BackendResponse> => {
    if (event.sender !== dependencies.getRenderer()) throw new Error('Untrusted temporary-profile caller')
    const payload = request?.payload
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('Invalid temporary-profile payload')
    if (!['temporary', 'server'].includes(payload.profile_type as string) || dependencies.hasSensitiveKey(payload)) throw new Error('Invalid temporary-profile payload')
    const profileId = request?.profileId
    if (profileId !== undefined && (typeof profileId !== 'string' || !profileId.trim() || profileId.length > 256)) throw new Error('Invalid temporary-profile id')
    const rawSecrets = request?.secrets || {}
    const allowedProtocols = new Set(['telnet', 'ssh', 'serial'])
    for (const [protocol, value] of Object.entries(rawSecrets)) {
      if (!allowedProtocols.has(protocol) || typeof value !== 'string' || value.length > 4_096) throw new Error('Invalid temporary-profile credential')
    }
    const backendPayload: Record<string, unknown> = { ...payload }
    for (const protocol of allowedProtocols) {
      const value = rawSecrets[protocol as 'telnet' | 'ssh' | 'serial']
      if (typeof value === 'string' && value) backendPayload[`${protocol}_password`] = value
    }
    let body = JSON.stringify(backendPayload)
    try {
      return await fetchBackend(dependencies.getRuntime(), profileId ? `/api/v1/connection-profiles/${encodeURIComponent(profileId)}` : '/api/v1/connection-profiles', profileId ? 'PUT' : 'POST', body)
    } finally {
      body = ''
      for (const protocol of allowedProtocols) backendPayload[`${protocol}_password`] = ''
    }
  })
}
