import type { IpcMain, WebContents } from 'electron'
import type { BackendResponse, BackendRuntime } from './backend-client.js'
import { fetchBackend } from './backend-client.js'

export interface BackendRequest {
  path: string
  method?: string
  body?: string
}

export interface RuntimeIpcDependencies {
  ipcMain: IpcMain
  getRenderer: () => WebContents | null
  getRuntime: () => BackendRuntime
  validateRequest: (request: BackendRequest) => void
}

export function registerRuntimeIpc(dependencies: RuntimeIpcDependencies): void {
  dependencies.ipcMain.handle('runtime:get', () => {
    const runtime = dependencies.getRuntime()
    return { apiBaseUrl: runtime.apiBaseUrl, apiVersion: runtime.apiVersion }
  })
  dependencies.ipcMain.handle('backend:request', async (event, request: BackendRequest): Promise<BackendResponse> => {
    if (event.sender !== dependencies.getRenderer()) throw new Error('Untrusted backend API caller')
    dependencies.validateRequest(request)
    const method = String(request.method || 'GET').toUpperCase()
    return fetchBackend(dependencies.getRuntime(), request.path, method, request.body)
  })
}
