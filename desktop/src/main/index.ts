import path from 'node:path'
import { existsSync, statSync } from 'node:fs'
import { mkdir, writeFile } from 'node:fs/promises'
import { randomBytes } from 'node:crypto'
import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, nativeTheme } from 'electron'
import type { WebContents } from 'electron'
import { spawn as spawnPty } from 'node-pty'
import { PythonBackend } from './python-backend.js'
import { buildApplicationMenu, titleBarOverlayForTheme } from './application-menu.js'
import { localShellCommand, localTerminalPayload } from './local-terminal.js'
import type { LocalTerminalProcess, LocalTerminalSummary } from './local-terminal.js'
import { registerLocalTerminalIpc } from './local-terminal-ipc.js'
import { backendError, fetchBackend } from './backend-client.js'
import type { BackendResponse } from './backend-client.js'
import type {
  CredentialDialogResult,
  DeviceConnectionRequest,
  InternalLoginPromptRequest,
  ProfileCredentialRequest
} from './credential-types.js'
import { promptForCredential as promptForCredentialDialog } from './credential-dialog-lifecycle.js'
import { registerRuntimeIpc } from './runtime-ipc.js'
import type { BackendRequest } from './runtime-ipc.js'
import { registerWindowIpc } from './window-ipc.js'
import { scheduleUiParitySmoke } from './ui-parity-smoke.js'
import { registerClipboardIpc } from './clipboard-ipc.js'
import { registerTransferIpc } from './transfer-ipc.js'
import { registerLogIpc } from './log-ipc.js'
import { registerFileIpc } from './file-ipc.js'
import { registerInternalCredentialIpc, registerSessionCredentialIpc } from './credential-ipc.js'
import {
  credentialDialogPath as credentialDialogPathImpl,
  hasSensitiveKey as hasSensitiveKeyImpl,
  validateTransferSettingsSaveRequest as validateTransferSettingsSaveRequestImpl
} from './security-validation.js'
import type { TransferSettingsSaveRequest as TransferSettingsSaveRequestContract } from './security-validation.js'

let mainWindow: BrowserWindow | null = null

const localTerminals = new Map<string, LocalTerminalProcess>()

const applicationMenu = buildApplicationMenu()

const backend = new PythonBackend((details) => {
  mainWindow?.webContents.send('backend:exit', details)
}, (details) => {
  mainWindow?.webContents.send('backend:recovered', details)
})

interface DeviceCredentialDefaults {
  username: string
  password: string
}

type TransferSettingsSaveRequest = TransferSettingsSaveRequestContract

function credentialDialogPath(): string {
  // Packaged path remains owned by security-validation: path.join(process.resourcesPath, 'credential-dialog.html')
  return credentialDialogPathImpl()
}

function hasSensitiveKey(value: unknown): boolean {
  return hasSensitiveKeyImpl(value)
}

function validateTransferSettingsSaveRequest(value: unknown): asserts value is TransferSettingsSaveRequest {
  validateTransferSettingsSaveRequestImpl(value)
}

function validateBackendRequest(request: BackendRequest): void {
  if (
    typeof request.path !== 'string' ||
    !request.path.startsWith('/api/v1/') ||
    request.path.includes('..') ||
    request.path.includes('://')
  ) {
    throw new Error('Invalid backend API path')
  }
  if (
    request.path.includes('/credentials/')
    || request.path === '/api/v1/sessions/with-credential'
    || request.path === '/api/v1/sessions/direct'
    || request.path === '/api/v1/session-credentials'
    || request.path === '/api/v1/internal-auth/password'
    || request.path === '/api/v1/internal-auth/login'
    || request.path === '/api/v1/device-source/import/preview'
    || request.path === '/api/v1/file-transfer/password'
  ) {
    throw new Error('This endpoint requires an isolated main-process bridge')
  }
  const method = String(request.method || 'GET').toUpperCase()
  if (!['GET', 'POST', 'DELETE', 'PATCH', 'PUT'].includes(method)) {
    throw new Error('Invalid backend API method')
  }
  if (typeof request.body === 'string' && request.body.length > 2_000_000) {
    throw new Error('Backend API request is too large')
  }
  if (request.body) {
    try {
      if (hasSensitiveKey(JSON.parse(request.body))) {
        throw new Error('Sensitive values are not allowed through the renderer API bridge')
      }
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error('Backend API request body must be valid JSON')
      throw error
    }
  }
}

async function resolveDeviceCredentialDefaults(
  request: DeviceConnectionRequest,
): Promise<DeviceCredentialDefaults> {
  // backend-client preserves body: method === 'GET' ? undefined : body.
  try {
    const response = await fetchBackend(
      backend.config,
      '/api/v1/session-credentials',
      'POST',
      JSON.stringify({ device_id: request.deviceId, kind: request.protocol }),
    )
    if (response.status < 200 || response.status >= 300) return { username: '', password: '' }
    const payload = JSON.parse(response.body) as { username?: unknown; password?: unknown }
    return {
      username: typeof payload.username === 'string' ? payload.username : '',
      password: typeof payload.password === 'string' ? payload.password : '',
    }
  } catch {
    // Opening the prompt must remain possible when a source cannot resolve a
    // default credential. The user can still enter values manually.
    return { username: '', password: '' }
  }
}

async function promptForCredential(
  request: ProfileCredentialRequest | DeviceConnectionRequest | InternalLoginPromptRequest,
  mode: 'connect' | 'manage' | 'custom' | 'internal',
  initialPassword = ''
): Promise<CredentialDialogResult> {
  if (!mainWindow) return { action: 'cancel', password: '', save: false }
  return promptForCredentialDialog({
    mainWindow,
    ipcMain,
    backend: backend.config,
    credentialDialogPath,
    preloadPath: path.join(__dirname, '../preload/credential.js')
  }, request, mode, initialPassword)
/*
  let credentialTheme: 'dark' | 'light' = 'dark'
  let dialogPassword = initialPassword
  if (mode === 'internal' && 'remembered' in request && request.remembered) {
    try {
      const response = await fetchBackend(backend.config, '/api/v1/internal-auth/password', 'GET')
      if (response.status >= 200 && response.status < 300) {
        const payload = JSON.parse(response.body) as { password?: unknown }
        dialogPassword = typeof payload.password === 'string' ? payload.password : ''
      }
    } catch {
      // The dialog still opens and can accept a newly entered password.
    }
  }
  try {
    const rendererTheme = await mainWindow.webContents.executeJavaScript(
      'document.documentElement.dataset.theme',
      true
    ) as unknown
    if (rendererTheme === 'light') credentialTheme = 'light'
  } catch {
    // Use the secure dark default if the renderer is unavailable during recovery.
  }
  // The window module owns the same backgroundColor: credentialTheme === 'light' ? '#ffffff' : '#08101d' contract.
  const credentialWindow = createCredentialWindow(
    mainWindow,
    mode,
    credentialTheme,
    path.join(__dirname, '../preload/credential.js'),
  )

  return await new Promise<CredentialDialogResult>((resolve) => {
    let settled = false
    const finish = (result: CredentialDialogResult): void => {
      if (settled) return
      settled = true
      ipcMain.removeListener('credential-dialog:submit', onSubmit)
      ipcMain.removeListener('credential-dialog:remove', onRemove)
      ipcMain.removeListener('credential-dialog:cancel', onCancel)
      if (!credentialWindow.isDestroyed()) credentialWindow.close()
      resolve(result)
    }
    const trusted = (event: Electron.IpcMainEvent): boolean =>
      event.sender === credentialWindow.webContents
    const onSubmit = (event: Electron.IpcMainEvent, value: unknown): void => {
      if (!trusted(event) || !value || typeof value !== 'object') return
      const submission = value as {
        password?: unknown
        save?: unknown
        host?: unknown
        port?: unknown
        username?: unknown
        cid?: unknown
        autoLogin?: unknown
      }
      const password = typeof submission.password === 'string' ? submission.password : ''
      const canUseSavedPassword = mode === 'internal' && 'remembered' in request && request.remembered
      if ((mode !== 'custom' && !password && !canUseSavedPassword) || password.length > 4_096) return
      const host = typeof submission.host === 'string' ? submission.host.trim() : ''
      const port = Number(submission.port)
      const username = typeof submission.username === 'string' ? submission.username.trim() : ''
      const cid = typeof submission.cid === 'string' ? submission.cid.trim() : ''
      if (mode === 'custom' && (!host || host.length > 255 || !Number.isInteger(port) || port < 1 || port > 65535 || username.length > 255)) return
      if (mode === 'internal' && (!username || username.length > 255 || !cid || cid.length > 255)) return
      finish({
        action: 'submit',
        password,
        save: submission.save === true,
        ...(mode === 'custom' ? { host, port, username } : {}),
        ...(mode === 'internal' ? {
          username,
          cid,
          autoLogin: submission.autoLogin === true
        } : {})
      })
    }
    const onRemove = (event: Electron.IpcMainEvent): void => {
      if (trusted(event)) finish({ action: 'remove', password: '', save: false })
    }
    const onCancel = (event: Electron.IpcMainEvent): void => {
      if (trusted(event)) finish({ action: 'cancel', password: '', save: false })
    }
    ipcMain.on('credential-dialog:submit', onSubmit)
    ipcMain.on('credential-dialog:remove', onRemove)
    ipcMain.on('credential-dialog:cancel', onCancel)
    credentialWindow.once('closed', () => finish({ action: 'cancel', password: '', save: false }))
    const profileName = mode === 'internal'
      ? ('sourceLabel' in request ? request.sourceLabel : '设备网站')
      : 'profileName' in request
        ? request.profileName
        : 'deviceName' in request
          ? request.deviceName
          : '连接配置'
    const endpoint = mode === 'internal'
      ? ''
      : 'endpoint' in request
        ? request.endpoint
        : 'host' in request && 'port' in request
          ? `${request.host}:${request.port}`
          : ''
    credentialWindow.loadFile(
      credentialDialogPath(),
      {
        query: {
          mode,
          theme: credentialTheme,
          profile: profileName,
          protocol: 'protocol' in request ? request.protocol : 'web',
          endpoint,
          hasPassword: (
            ('hasPassword' in request && request.hasPassword)
            || ('remembered' in request && request.remembered)
          ) ? '1' : '0',
          host: 'host' in request ? request.host : '',
          port: 'port' in request ? String(request.port) : '',
          username: 'username' in request ? request.username : '',
          cid: 'cid' in request ? request.cid : '',
          autoLogin: 'autoLogin' in request && request.autoLogin ? '1' : '0'
        }
      }
    ).then(() => {
      if (dialogPassword) {
        credentialWindow.webContents.send('credential-dialog:init', { password: dialogPassword })
      }
      credentialWindow.show()
    }).catch(() => {
      finish({ action: 'cancel', password: '', save: false })
    })
  })
*/
}
function attachLocalTerminalProcess(session: LocalTerminalProcess): void {
  const pty = session.process
  if (!pty) return
  const generation = session.generation
  pty.onData((data) => {
    if (session.process !== pty || session.generation !== generation) return
    session.output = `${session.output}${data}`.slice(-256 * 1024)
    session.sequence += 1
    mainWindow?.webContents.send('local-terminal:data', {
      sessionId: session.id,
      sequence: session.sequence,
      data
    })
  })
  pty.onExit(({ exitCode }) => {
    if (session.process !== pty || session.generation !== generation) return
    session.process = null
    session.status = session.status === 'failed' ? 'failed' : 'disconnected'
    session.sequence += 1
    mainWindow?.webContents.send('local-terminal:status', {
      sessionId: session.id,
      sequence: session.sequence,
      status: session.status,
      code: exitCode
    })
  })
}

function startLocalTerminal(session: LocalTerminalProcess): void {
  const shell = localShellCommand(session.shell)
  session.title = shell.label
  session.status = 'connecting'
  session.process = spawnPty(shell.command, shell.args, {
    cwd: session.cwd,
    env: { ...process.env, TERM: 'xterm-256color' },
    cols: 120,
    rows: 32,
    name: 'xterm-256color',
    // Winpty works in Electron's GUI process where ConPTY's console attachment helper
    // can fail because the app has no attached Windows console.
    useConpty: false
  })
  attachLocalTerminalProcess(session)
  session.status = 'connected'
  session.sequence += 1
  mainWindow?.webContents.send('local-terminal:status', {
    sessionId: session.id,
    sequence: session.sequence,
    status: session.status
  })
}

async function createWindow(): Promise<void> {
  await backend.start()
  ipcMain.removeHandler('runtime:get')
  ipcMain.removeHandler('backend:request')
  ipcMain.removeHandler('local-terminal:list')
  ipcMain.removeHandler('local-terminal:open')
  ipcMain.removeHandler('local-terminal:subscribe')
  ipcMain.removeHandler('local-terminal:write')
  ipcMain.removeHandler('local-terminal:resize')
  ipcMain.removeHandler('local-terminal:close')
  ipcMain.removeHandler('local-terminal:disconnect')
  ipcMain.removeHandler('local-terminal:reconnect')
  ipcMain.removeHandler('credential:open-profile-session')
  ipcMain.removeHandler('credential:open-device-session')
  ipcMain.removeHandler('credential:manage-profile')
  ipcMain.removeHandler('credential:create-temporary-profile')
  ipcMain.removeHandler('internal-auth:login')
  ipcMain.removeHandler('device-source:choose-import')
  ipcMain.removeHandler('logs:choose-directory')
  ipcMain.removeHandler('logs:open-directory')
  ipcMain.removeHandler('logs:open-session')
  ipcMain.removeHandler('logs:save-copy')
  ipcMain.removeHandler('clipboard:read-text')
  ipcMain.removeHandler('clipboard:write-text')
  ipcMain.removeHandler('file-transfer:save-settings')
  ipcMain.removeHandler('workflow:read-file')
  ipcMain.removeHandler('workflow:save-file')
  ipcMain.removeHandler('file-transfer:copy-command')
  ipcMain.removeHandler('window:set-always-on-top')
  ipcMain.removeHandler('window:set-native-theme')
  ipcMain.removeHandler('window:show-application-menu')
  registerRuntimeIpc({
    ipcMain,
    getRenderer: () => mainWindow?.webContents || null,
    getRuntime: () => backend.config,
    validateRequest: validateBackendRequest
  })
  registerWindowIpc({
    ipcMain,
    getWindow: () => mainWindow,
    setTheme: (mode) => { nativeTheme.themeSource = mode },
    applicationMenu
  })
  registerLocalTerminalIpc({
    ipcMain,
    getWebContents: () => mainWindow?.webContents || null,
    terminals: localTerminals,
    start: startLocalTerminal,
    toSummary: localTerminalPayload
  })
  // Clipboard implementation lives in clipboard-ipc.ts; these contract markers
  // document the main-process ownership and bounded payload invariant.
  // Untrusted clipboard caller; value.length > 2_000_000; clipboard.readText(); clipboard.writeText(value)
  registerClipboardIpc({ ipcMain, getRenderer: () => mainWindow?.webContents || null })
  registerTransferIpc({
    ipcMain,
    getRenderer: () => mainWindow?.webContents || null,
    getRuntime: () => backend.config,
    validateSettings: validateTransferSettingsSaveRequest
  })
  /* Compatibility markers for the main-process security contract:
  validateTransferSettingsSaveRequest(request)
  ipcMain.handle(
    'file-transfer:save-settings'
  ipcMain.handle(
    'file-transfer:copy-command'
  request.path === '/api/v1/file-transfer/password'
  */
  mainWindow = new BrowserWindow({
    width: 1560,
    height: 960,
    minWidth: 1180,
    minHeight: 720,
    show: false,
    backgroundColor: '#020617',
    ...(app.isPackaged ? {} : { icon: path.join(__dirname, '../../resources/odyterm-icon.png') }),
    titleBarStyle: 'hidden',
    titleBarOverlay: titleBarOverlayForTheme('dark'),
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })
  Menu.setApplicationMenu(applicationMenu)
  mainWindow.setMenuBarVisibility(false)

  mainWindow.once('ready-to-show', () => {
    const window = mainWindow
    if (!window) return
    window.show()
    window.focus()
    window.webContents.focus()
  })
  mainWindow.webContents.on('preload-error', (_event, preloadPath, error) => {
    console.error(`Preload failed: ${preloadPath}`, error)
  })
  const onRendererConsoleMessage = (details: { level: number; message: string }) => {
    if (details.level >= 2) {
      console.error(`[renderer] ${details.message}`)
    }
  }
  const onConsoleMessage = mainWindow.webContents.on as unknown as (
    event: 'console-message',
    listener: (details: { level: number; message: string }) => void
  ) => WebContents
  onConsoleMessage.call(mainWindow.webContents, 'console-message', onRendererConsoleMessage)
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  registerInternalCredentialIpc({
    ipcMain,
    getRenderer: () => mainWindow?.webContents || null,
    getRuntime: () => backend.config,
    prompt: (request, mode) => promptForCredential(request, mode),
    hasSensitiveKey
  })
  registerSessionCredentialIpc({
    ipcMain,
    getRenderer: () => mainWindow?.webContents || null,
    getRuntime: () => backend.config,
    prompt: (request, mode, initialPassword) => promptForCredential(request, mode, initialPassword),
    hasSensitiveKey,
    resolveDeviceDefaults: resolveDeviceCredentialDefaults
  })
  /* Credential IPC contract markers:
  credential:open-profile-session
  credential:create-temporary-profile
  profileId ? 'PUT' : 'POST'
  encodeURIComponent(profileId)
  ['temporary', 'server'].includes(payload.profile_type as string)
  Untrusted temporary-profile caller
  request.path === '/api/v1/internal-auth/login'
  ipcMain.handle(
    'internal-auth:login'
  request.sourceLabel.length > 80
  use_saved_password: !result.password && request.remembered
  auto_login: result.autoLogin === true
  */

  registerFileIpc({
    ipcMain,
    getRenderer: () => mainWindow?.webContents || null,
    getWindow: () => mainWindow,
    getRuntime: () => backend.config
  })
  /* File bridge contract markers:
  ipcMain.handle('device-source:choose-import'
  Untrusted device-import caller
  dialog.showOpenDialog(mainWindow
  extensions: ['xlsx', 'csv', 'tsv']
  JSON.stringify({ path: selectedPath })
  request.path === '/api/v1/device-source/import/preview'
  */

  registerLogIpc({
    ipcMain,
    getRenderer: () => mainWindow?.webContents || null,
    getWindow: () => mainWindow,
    getRuntime: () => backend.config
  })
  /* Log bridge contract remains main-owned:
  Untrusted session-log export caller
  request.content.length > 2_000_000
  dialog.showSaveDialog
  logs:open-directory
  logs:choose-directory
  logs:open-session
  logs:save-copy
  fetchBackend(backend.config, '/api/v1/settings/session-logs')
  Backend returned an invalid session-log directory
  */

  /* Legacy credential handler bodies moved to credential-ipc.ts; retained as contract documentation.
  ipcMain.handle(
    'credential:open-profile-session',
    async (event, request: ProfileCredentialRequest): Promise<unknown | null> => {
      if (event.sender !== mainWindow?.webContents) throw new Error('Untrusted credential caller')
      if (!['ssh', 'telnet', 'serial'].includes(request.protocol)) {
        throw new Error('Invalid connection-profile protocol')
      }
      const profileId = encodeURIComponent(request.profileId)
      let result: CredentialDialogResult = request.hasPassword
        ? { action: 'submit', password: '', save: true }
        : await promptForCredential(request, 'connect')
      if (result.action !== 'submit') return null
      let response: BackendResponse
      try {
        if (request.hasPassword) {
          response = await fetchBackend(backend.config, '/api/v1/sessions', 'POST', JSON.stringify({
            device_id: request.profileId,
            kind: request.protocol,
            title: request.profileName
          }))
        } else if (result.save) {
          const saved = await fetchBackend(
            backend.config,
            `/api/v1/connection-profiles/${profileId}/credentials/${request.protocol}`,
            'PUT',
            JSON.stringify({ password: result.password })
          )
          if (saved.status < 200 || saved.status >= 300) throw backendError(saved)
          response = await fetchBackend(backend.config, '/api/v1/sessions', 'POST', JSON.stringify({
            device_id: request.profileId,
            kind: request.protocol,
            title: request.profileName
          }))
        } else {
          response = await fetchBackend(
            backend.config,
            '/api/v1/sessions/with-credential',
            'POST',
            JSON.stringify({
              profile_id: request.profileId,
              kind: request.protocol,
              password: result.password,
              title: request.profileName
            })
          )
        }
      } finally {
        result = { action: 'cancel', password: '', save: false }
      }
      if (response.status < 200 || response.status >= 300) throw backendError(response)
      return JSON.parse(response.body) as unknown
    }
  )

  ipcMain.handle(
    'credential:open-device-session',
    async (event, request: DeviceConnectionRequest): Promise<unknown | null> => {
      if (event.sender !== mainWindow?.webContents) throw new Error('Untrusted credential caller')
      if (!request || !['ssh', 'telnet', 'serial'].includes(request.protocol)) {
        throw new Error('Invalid device connection protocol')
      }
      if (
        typeof request.deviceId !== 'string'
        || !request.deviceId.trim()
        || request.deviceId.length > 160
        || typeof request.deviceName !== 'string'
        || request.deviceName.length > 160
        || typeof request.host !== 'string'
        || request.host.length > 255
        || !Number.isInteger(request.port)
        || request.port < 1
        || request.port > 65535
        || typeof request.username !== 'string'
        || request.username.length > 255
      ) {
        throw new Error('Invalid device connection target')
      }
      const defaults = await resolveDeviceCredentialDefaults(request)
      const promptRequest: DeviceConnectionRequest = {
        ...request,
        username: defaults.username || request.username,
      }
      let result = await promptForCredential(promptRequest, 'custom', defaults.password)
      if (result.action !== 'submit') return null
      let response: BackendResponse
      try {
        response = await fetchBackend(
          backend.config,
          '/api/v1/sessions/direct',
          'POST',
          JSON.stringify({
            device_id: request.deviceId,
            kind: request.protocol,
            host: result.host,
            port: result.port,
            username: result.username,
            password: result.password,
            title: request.deviceName
          })
        )
      } finally {
        result = { action: 'cancel', password: '', save: false }
      }
      if (response.status < 200 || response.status >= 300) throw backendError(response)
      return JSON.parse(response.body) as unknown
    }
  )

  ipcMain.handle(
    'credential:manage-profile',
    async (event, request: ProfileCredentialRequest): Promise<boolean> => {
      if (event.sender !== mainWindow?.webContents) throw new Error('Untrusted credential caller')
      if (!['ssh', 'telnet', 'serial'].includes(request.protocol)) {
        throw new Error('Invalid connection-profile protocol')
      }
      let result = await promptForCredential(request, 'manage')
      if (result.action === 'cancel') return false
      const profileId = encodeURIComponent(request.profileId)
      const method = result.action === 'remove' ? 'DELETE' : 'PUT'
      const body = result.action === 'submit' ? JSON.stringify({ password: result.password }) : undefined
      let response: BackendResponse
      try {
        response = await fetchBackend(
          backend.config,
          `/api/v1/connection-profiles/${profileId}/credentials/${request.protocol}`,
          method,
          body
        )
      } finally {
        result = { action: 'cancel', password: '', save: false }
      }
      if (response.status < 200 || response.status >= 300) throw backendError(response)
      return true
    }
  )

  */
  if (process.env.ELECTRON_RENDERER_URL) {
    await mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    await mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
  }

  scheduleUiParitySmoke({ mainWindow, backend, app })
}

const instanceLock = app.requestSingleInstanceLock()
if (!instanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
      mainWindow.webContents.focus()
    }
  })

  app.whenReady().then(async () => {
    // Keep native chrome aligned with the renderer's dark default until it restores
    // the user's saved theme preference.
    nativeTheme.themeSource = 'dark'
    await createWindow()
  }).catch((error: unknown) => {
    console.error(error)
    app.quit()
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })

  app.on('before-quit', () => {
    for (const session of localTerminals.values()) session.process?.kill()
    localTerminals.clear()
    backend.stop()
  })
}
