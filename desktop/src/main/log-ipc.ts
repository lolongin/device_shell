import path from 'node:path'
import { mkdir, writeFile } from 'node:fs/promises'
import type { BrowserWindow, IpcMain, WebContents } from 'electron'
import { dialog, shell } from 'electron'
import type { BackendRuntime } from './backend-client.js'
import { backendError, fetchBackend } from './backend-client.js'

export interface SessionLogExportRequest {
  suggestedName: string
  content: string
}

export interface LogIpcDependencies {
  ipcMain: IpcMain
  getRenderer: () => WebContents | null
  getWindow: () => BrowserWindow | null
  getRuntime: () => BackendRuntime
}

export function registerLogIpc(dependencies: LogIpcDependencies): void {
  dependencies.ipcMain.handle('logs:choose-directory', async (event): Promise<string> => {
    const window = dependencies.getWindow()
    if (event.sender !== dependencies.getRenderer() || !window) throw new Error('Untrusted log-directory chooser caller')
    const configuredSelection = process.env.DEVICE_TUI_LOG_DIRECTORY_SELECTION || ''
    if (configuredSelection) return path.resolve(configuredSelection)
    const selected = await dialog.showOpenDialog(window, { title: '选择会话日志保存位置', properties: ['openDirectory', 'createDirectory'] })
    return selected.canceled ? '' : selected.filePaths[0] || ''
  })

  dependencies.ipcMain.handle('logs:open-directory', async (event): Promise<boolean> => {
    if (event.sender !== dependencies.getRenderer()) throw new Error('Untrusted log-directory caller')
    const response = await fetchBackend(dependencies.getRuntime(), '/api/v1/settings/session-logs')
    if (response.status !== 200) throw backendError(response)
    const payload = JSON.parse(response.body) as { directory?: unknown }
    if (typeof payload.directory !== 'string' || !path.isAbsolute(payload.directory)) throw new Error('Backend returned an invalid session-log directory')
    const logDirectory = path.resolve(payload.directory)
    await mkdir(logDirectory, { recursive: true })
    if (process.env.DEVICE_TUI_DISABLE_EXTERNAL_OPEN === '1') return true
    const error = await shell.openPath(logDirectory)
    if (error) throw new Error(error)
    return true
  })

  dependencies.ipcMain.handle('logs:open-session', async (event, sessionId: unknown): Promise<boolean> => {
    if (event.sender !== dependencies.getRenderer() || typeof sessionId !== 'string' || !sessionId || sessionId.length > 160) throw new Error('Untrusted session-log caller')
    const response = await fetchBackend(dependencies.getRuntime(), `/api/v1/sessions/${encodeURIComponent(sessionId)}/log-path`)
    if (response.status !== 200) throw backendError(response)
    const payload = JSON.parse(response.body) as { path?: unknown }
    if (typeof payload.path !== 'string' || !path.isAbsolute(payload.path)) throw new Error('Backend returned an invalid session-log path')
    if (process.env.DEVICE_TUI_DISABLE_EXTERNAL_OPEN === '1') return true
    const error = await shell.openPath(path.resolve(payload.path))
    if (error) throw new Error(error)
    return true
  })

  dependencies.ipcMain.handle('logs:save-copy', async (event, request: SessionLogExportRequest): Promise<boolean> => {
    const window = dependencies.getWindow()
    if (event.sender !== dependencies.getRenderer() || !window) throw new Error('Untrusted session-log export caller')
    if (!request || typeof request.content !== 'string' || request.content.length > 2_000_000) throw new Error('Invalid session-log export payload')
    const safeName = String(request.suggestedName || 'session.log').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^\.+/, '').slice(0, 160) || 'session.log'
    let destination = process.env.DEVICE_TUI_LOG_EXPORT_PATH || ''
    if (!destination) {
      const selected = await dialog.showSaveDialog(window, { title: '保存会话日志副本', defaultPath: safeName, filters: [{ name: '日志文件', extensions: ['log', 'txt'] }] })
      if (selected.canceled || !selected.filePath) return false
      destination = selected.filePath
    }
    const resolved = path.resolve(destination)
    await mkdir(path.dirname(resolved), { recursive: true })
    await writeFile(resolved, request.content, 'utf8')
    return true
  })
}
