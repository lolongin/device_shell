import type { IpcMain, WebContents } from 'electron'
import { clipboard } from 'electron'

export interface ClipboardIpcDependencies {
  ipcMain: IpcMain
  getRenderer: () => WebContents | null
}

export function registerClipboardIpc(dependencies: ClipboardIpcDependencies): void {
  dependencies.ipcMain.handle('clipboard:read-text', (event): string => {
    if (event.sender !== dependencies.getRenderer()) throw new Error('Untrusted clipboard caller')
    return clipboard.readText()
  })
  dependencies.ipcMain.handle('clipboard:write-text', (event, value: unknown): boolean => {
    if (event.sender !== dependencies.getRenderer()) throw new Error('Untrusted clipboard caller')
    if (typeof value !== 'string' || value.length > 2_000_000) throw new Error('Invalid clipboard text')
    clipboard.writeText(value)
    return true
  })
}
