import { shell } from 'electron'
import type { IpcMain, WebContents } from 'electron'

export function registerExternalLinkIpc(ipcMain: IpcMain, getRenderer: () => WebContents | null): void {
  ipcMain.handle('external:open-link', async (event, value: unknown): Promise<void> => {
    if (event.sender !== getRenderer()) throw new Error('Untrusted external link caller')
    if (typeof value !== 'string' || value.length > 2048) throw new Error('Invalid external link')
    let url: URL
    try { url = new URL(value) }
    catch { throw new Error('Invalid external link') }
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) {
      throw new Error('Unsupported external link')
    }
    await shell.openExternal(url.toString())
  })
}
