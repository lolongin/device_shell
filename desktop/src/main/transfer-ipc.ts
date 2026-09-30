import type { IpcMain, WebContents } from 'electron'
import { clipboard } from 'electron'
import type { BackendResponse, BackendRuntime } from './backend-client.js'
import { backendError, fetchBackend } from './backend-client.js'
import { quoteShellArgument } from './shell-escaping.js'

export interface TransferSettingsSaveRequest {
  password?: unknown
  [key: string]: unknown
}

export interface TransferIpcDependencies {
  ipcMain: IpcMain
  getRenderer: () => WebContents | null
  getRuntime: () => BackendRuntime
  validateSettings: (value: unknown) => asserts value is TransferSettingsSaveRequest
}

const PASSWORD_PLACEHOLDER = '{{file_transfer.password}}'
const PASSWORD_SHELL_PLACEHOLDER = '{{file_transfer.password.shell}}'

export function registerTransferIpc(dependencies: TransferIpcDependencies): void {
  dependencies.ipcMain.handle('file-transfer:save-settings', async (event, request: unknown): Promise<BackendResponse> => {
    if (event.sender !== dependencies.getRenderer()) throw new Error('Untrusted file-transfer caller')
    dependencies.validateSettings(request)
    let body = JSON.stringify(request)
    try {
      return await fetchBackend(dependencies.getRuntime(), '/api/v1/file-transfer/settings', 'PUT', body)
    } finally {
      body = ''
      if (request.password !== undefined) request.password = ''
    }
  })

  dependencies.ipcMain.handle('file-transfer:copy-command', async (event, value: unknown): Promise<boolean> => {
    if (event.sender !== dependencies.getRenderer()) throw new Error('Untrusted file-transfer caller')
    if (typeof value !== 'string' || !value || value.length > 100_000) throw new Error('Invalid FTP command')
    let command = value
    let password = ''
    try {
      if (command.includes(PASSWORD_PLACEHOLDER) || command.includes(PASSWORD_SHELL_PLACEHOLDER)) {
        const response = await fetchBackend(dependencies.getRuntime(), '/api/v1/file-transfer/password')
        if (response.status < 200 || response.status >= 300) throw backendError(response)
        const payload = JSON.parse(response.body) as { password?: unknown }
        if (typeof payload.password !== 'string' || !payload.password) {
          throw new Error('FTP 密码尚未设置，请在上方 FTP 配置中输入并保存。')
        }
        password = payload.password
        command = command
          .replaceAll(PASSWORD_SHELL_PLACEHOLDER, quoteShellArgument(password))
          .replaceAll(PASSWORD_PLACEHOLDER, password)
      }
      clipboard.writeText(command)
      return true
    } finally {
      command = ''
      password = ''
    }
  })
}
