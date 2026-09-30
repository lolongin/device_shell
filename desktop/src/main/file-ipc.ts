import path from 'node:path'
import { readFile, writeFile } from 'node:fs/promises'
import type { BrowserWindow, IpcMain, WebContents } from 'electron'
import { dialog } from 'electron'
import type { BackendRuntime } from './backend-client.js'
import { backendError, fetchBackend } from './backend-client.js'
import { validDialogDefaultPath } from './file-dialogs.js'

export interface FileIpcDependencies {
  ipcMain: IpcMain
  getRenderer: () => WebContents | null
  getWindow: () => BrowserWindow | null
  getRuntime: () => BackendRuntime
}

const trusted = (event: Electron.IpcMainInvokeEvent, dependencies: FileIpcDependencies): BrowserWindow => {
  const window = dependencies.getWindow()
  if (event.sender !== dependencies.getRenderer() || !window) throw new Error('Untrusted file IPC caller')
  return window
}

export function registerFileIpc(dependencies: FileIpcDependencies): void {
  dependencies.ipcMain.handle('file-transfer:choose-root', async (event): Promise<string> => {
    const window = trusted(event, dependencies)
    const selected = await dialog.showOpenDialog(window, { title: '选择文件传输共享目录', properties: ['openDirectory', 'createDirectory'] })
    return selected.canceled ? '' : selected.filePaths[0] || ''
  })

  dependencies.ipcMain.handle('file-transfer:choose-package', async (event, defaultPath?: unknown): Promise<string> => {
    const window = trusted(event, dependencies)
    const initialPath = typeof defaultPath === 'string' && defaultPath.trim() ? path.resolve(defaultPath.trim()) : undefined
    const selected = await dialog.showOpenDialog(window, {
      title: '选择换包软件包', properties: ['openFile'], filters: [{ name: '设备软件包', extensions: ['cc'] }],
      ...(initialPath ? { defaultPath: initialPath } : {})
    })
    return selected.canceled ? '' : selected.filePaths[0] || ''
  })

  dependencies.ipcMain.handle('workflow:choose-file', async (event, request?: unknown): Promise<string> => {
    const window = trusted(event, dependencies)
    const payload = request && typeof request === 'object' ? request as Record<string, unknown> : {}
    const defaultPath = validDialogDefaultPath(payload.defaultPath)
    const label = typeof payload.label === 'string' && payload.label.trim() ? payload.label.trim().slice(0, 80) : 'Workflow 文件'
    const extensions = Array.isArray(payload.extensions)
      ? payload.extensions.map((item) => String(item).trim().replace(/^\./, '').toLowerCase()).filter((item) => /^[a-z0-9]{1,12}$/.test(item)).slice(0, 20)
      : []
    const selected = await dialog.showOpenDialog(window, {
      title: `选择${label}`, properties: ['openFile'],
      ...(extensions.length ? { filters: [{ name: label, extensions }] } : {}),
      ...(defaultPath ? { defaultPath } : {})
    })
    return selected.canceled ? '' : selected.filePaths[0] || ''
  })

  dependencies.ipcMain.handle('workflow:choose-directory', async (event, request?: unknown): Promise<string> => {
    const window = trusted(event, dependencies)
    const payload = request && typeof request === 'object' ? request as Record<string, unknown> : {}
    const defaultPath = validDialogDefaultPath(payload.defaultPath)
    const label = typeof payload.label === 'string' && payload.label.trim() ? payload.label.trim().slice(0, 80) : '选择文件夹'
    const selected = await dialog.showOpenDialog(window, { title: label, properties: ['openDirectory', 'createDirectory'], ...(defaultPath ? { defaultPath } : {}) })
    return selected.canceled ? '' : selected.filePaths[0] || ''
  })

  dependencies.ipcMain.handle('workflow:read-file', async (event, filePath: unknown): Promise<string> => {
    trusted(event, dependencies)
    if (typeof filePath !== 'string' || !filePath.trim()) throw new Error('Untrusted workflow file read caller')
    const content = await readFile(path.resolve(filePath), 'utf8')
    if (content.length > 2_000_000) throw new Error('Workflow 文件过大')
    return content
  })

  dependencies.ipcMain.handle('workflow:save-file', async (event, request: unknown): Promise<boolean> => {
    const window = trusted(event, dependencies)
    if (!request || typeof request !== 'object') throw new Error('Untrusted workflow file save caller')
    const payload = request as Record<string, unknown>
    if (typeof payload.content !== 'string' || payload.content.length > 2_000_000) throw new Error('Invalid workflow export payload')
    const safeName = String(payload.suggestedName || 'workflow.workflow.yaml').replace(/[^A-Za-z0-9._-]+/g, '_').replace(/^\.+/, '').slice(0, 160) || 'workflow.workflow.yaml'
    const selected = await dialog.showSaveDialog(window, { title: '导出 Workflow', defaultPath: safeName, filters: [{ name: 'Workflow 文件', extensions: ['yaml', 'yml', 'json'] }] })
    if (selected.canceled || !selected.filePath) return false
    await writeFile(path.resolve(selected.filePath), payload.content, 'utf8')
    return true
  })

  dependencies.ipcMain.handle('device-source:choose-import', async (event): Promise<unknown | null> => {
    const window = trusted(event, dependencies)
    const configuredSelection = process.env.DEVICE_TUI_DEVICE_IMPORT_SELECTION || ''
    let selectedPath = configuredSelection ? path.resolve(configuredSelection) : ''
    if (!selectedPath) {
      const selected = await dialog.showOpenDialog(window, {
        title: '导入设备清单', properties: ['openFile'],
        filters: [{ name: '设备清单', extensions: ['xlsx', 'csv', 'tsv'] }, { name: 'Excel 工作簿', extensions: ['xlsx'] }, { name: 'CSV / TSV', extensions: ['csv', 'tsv'] }]
      })
      if (selected.canceled) return null
      selectedPath = selected.filePaths[0] || ''
    }
    if (!['.xlsx', '.csv', '.tsv'].includes(path.extname(selectedPath).toLowerCase())) throw new Error('仅支持 .xlsx、.csv 和 .tsv 文件')
    const response = await fetchBackend(dependencies.getRuntime(), '/api/v1/device-source/import/preview', 'POST', JSON.stringify({ path: selectedPath }))
    if (response.status < 200 || response.status >= 300) throw backendError(response)
    return JSON.parse(response.body) as unknown
  })
}
