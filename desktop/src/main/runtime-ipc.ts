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
  getAgentRenderer?: () => WebContents | null
  getRuntime: () => BackendRuntime
  validateRequest: (request: BackendRequest) => void
}

export function registerRuntimeIpc(dependencies: RuntimeIpcDependencies): void {
  const trusted = (sender: WebContents): boolean => sender === dependencies.getRenderer() || sender === dependencies.getAgentRenderer?.()
  dependencies.ipcMain.handle('runtime:get', (event) => {
    if (!trusted(event.sender)) throw new Error('Untrusted runtime caller')
    const runtime = dependencies.getRuntime()
    return { apiBaseUrl: runtime.apiBaseUrl, apiVersion: runtime.apiVersion }
  })
  dependencies.ipcMain.handle('backend:request', async (event, request: BackendRequest): Promise<BackendResponse> => {
    if (!trusted(event.sender)) throw new Error('Untrusted backend API caller')
    dependencies.validateRequest(request)
    const method = String(request.method || 'GET').toUpperCase()
    if (event.sender !== dependencies.getRenderer()) {
      const agentRoute = (method === 'POST' && request.path === '/api/v1/ai/chat')
        || (method === 'GET' && request.path === '/api/v1/ai/agent/conversations')
        || (['GET', 'PUT', 'DELETE'].includes(method) && /^\/api\/v1\/ai\/agent\/conversations\/[a-zA-Z0-9_-]+(?:\?after=\d+)?$/.test(request.path))
        || (method === 'POST' && /^\/api\/v1\/ai\/agent\/conversations\/[a-zA-Z0-9_-]+\/approvals\/[a-zA-Z0-9_-]+\/(approve|reject)$/.test(request.path))
        || (method === 'GET' && /^\/api\/v1\/tasks\/[a-zA-Z0-9_-]+$/.test(request.path))
        || (method === 'POST' && /^\/api\/v1\/tasks\/[a-zA-Z0-9_-]+\/(pause|resume|cancel)$/.test(request.path))
      if (!agentRoute) throw new Error('Endpoint unavailable in Agent workspace')
    }
    return fetchBackend(dependencies.getRuntime(), request.path, method, request.body)
  })
}
