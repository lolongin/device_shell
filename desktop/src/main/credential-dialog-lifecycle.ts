import path from 'node:path'
import type { BrowserWindow, IpcMain } from 'electron'
import type { BackendRuntime } from './backend-client.js'
import { fetchBackend } from './backend-client.js'
import type {
  CredentialDialogResult,
  DeviceConnectionRequest,
  InternalLoginPromptRequest,
  ProfileCredentialRequest
} from './credential-types.js'
import { createCredentialWindow } from './credential-window.js'

type CredentialRequest = ProfileCredentialRequest | DeviceConnectionRequest | InternalLoginPromptRequest
type CredentialMode = 'connect' | 'manage' | 'custom' | 'internal'

interface CredentialDialogDependencies {
  mainWindow: BrowserWindow
  ipcMain: IpcMain
  backend: BackendRuntime
  credentialDialogPath: () => string
  preloadPath: string
}

export async function promptForCredential(
  dependencies: CredentialDialogDependencies,
  request: CredentialRequest,
  mode: CredentialMode,
  initialPassword = ''
): Promise<CredentialDialogResult> {
  let credentialTheme: 'dark' | 'light' = 'dark'
  let dialogPassword = initialPassword
  if (mode === 'internal' && 'remembered' in request && request.remembered) {
    try {
      const response = await fetchBackend(dependencies.backend, '/api/v1/internal-auth/password', 'GET')
      if (response.status >= 200 && response.status < 300) {
        const payload = JSON.parse(response.body) as { password?: unknown }
        dialogPassword = typeof payload.password === 'string' ? payload.password : ''
      }
    } catch {
      // The dialog still opens and can accept a newly entered password.
    }
  }
  try {
    const rendererTheme = await dependencies.mainWindow.webContents.executeJavaScript(
      'document.documentElement.dataset.theme', true
    ) as unknown
    if (rendererTheme === 'light') credentialTheme = 'light'
  } catch {
    // Use the secure dark default if the renderer is unavailable during recovery.
  }
  const credentialWindow = createCredentialWindow(
    dependencies.mainWindow,
    mode,
    credentialTheme,
    dependencies.preloadPath,
  )

  return await new Promise<CredentialDialogResult>((resolve) => {
    let settled = false
    const finish = (result: CredentialDialogResult): void => {
      if (settled) return
      settled = true
      dependencies.ipcMain.removeListener('credential-dialog:submit', onSubmit)
      dependencies.ipcMain.removeListener('credential-dialog:remove', onRemove)
      dependencies.ipcMain.removeListener('credential-dialog:cancel', onCancel)
      if (!credentialWindow.isDestroyed()) credentialWindow.close()
      resolve(result)
    }
    const trusted = (event: Electron.IpcMainEvent): boolean => event.sender === credentialWindow.webContents
    const onSubmit = (event: Electron.IpcMainEvent, value: unknown): void => {
      if (!trusted(event) || !value || typeof value !== 'object') return
      const submission = value as {
        password?: unknown; save?: unknown; host?: unknown; port?: unknown
        username?: unknown; cid?: unknown; autoLogin?: unknown
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
        action: 'submit', password, save: submission.save === true,
        ...(mode === 'custom' ? { host, port, username } : {}),
        ...(mode === 'internal' ? { username, cid, autoLogin: submission.autoLogin === true } : {})
      })
    }
    const onRemove = (event: Electron.IpcMainEvent): void => {
      if (trusted(event)) finish({ action: 'remove', password: '', save: false })
    }
    const onCancel = (event: Electron.IpcMainEvent): void => {
      if (trusted(event)) finish({ action: 'cancel', password: '', save: false })
    }
    dependencies.ipcMain.on('credential-dialog:submit', onSubmit)
    dependencies.ipcMain.on('credential-dialog:remove', onRemove)
    dependencies.ipcMain.on('credential-dialog:cancel', onCancel)
    credentialWindow.once('closed', () => finish({ action: 'cancel', password: '', save: false }))
    const profileName = mode === 'internal'
      ? ('sourceLabel' in request ? request.sourceLabel : '设备网站')
      : 'profileName' in request ? request.profileName
        : 'deviceName' in request ? request.deviceName : '连接配置'
    const endpoint = mode === 'internal' ? ''
      : 'endpoint' in request ? request.endpoint
        : 'host' in request && 'port' in request ? `${request.host}:${request.port}` : ''
    credentialWindow.loadFile(dependencies.credentialDialogPath(), {
      query: {
        mode, theme: credentialTheme, profile: profileName,
        protocol: 'protocol' in request ? request.protocol : 'web', endpoint,
        hasPassword: (('hasPassword' in request && request.hasPassword) || ('remembered' in request && request.remembered)) ? '1' : '0',
        host: 'host' in request ? request.host : '', port: 'port' in request ? String(request.port) : '',
        username: 'username' in request ? request.username : '', cid: 'cid' in request ? request.cid : '',
        autoLogin: 'autoLogin' in request && request.autoLogin ? '1' : '0'
      }
    }).then(() => {
      if (dialogPassword) credentialWindow.webContents.send('credential-dialog:init', { password: dialogPassword })
      credentialWindow.show()
    }).catch(() => finish({ action: 'cancel', password: '', save: false }))
  })
}
