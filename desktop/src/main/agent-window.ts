import path from 'node:path'
import { BrowserWindow } from 'electron'
import type { IpcMain, WebContents } from 'electron'

export function registerAgentWindowIpc(ipcMain: IpcMain, getRenderer: () => WebContents | null, agentWindow: AgentWindow): void {
  ipcMain.removeHandler('agent:open-window')
  ipcMain.handle('agent:open-window', async (event, conversationId: unknown) => {
    if (event.sender !== getRenderer()) throw new Error('Untrusted Agent window caller')
    if (conversationId !== undefined && (typeof conversationId !== 'string' || !/^[a-zA-Z0-9_-]{1,160}$/.test(conversationId))) throw new Error('Invalid conversation ID')
    await agentWindow.open(conversationId as string | undefined)
  })
}

/** Owns only the view. Backend requests and tasks outlive this window. */
export class AgentWindow {
  private window: BrowserWindow | null = null
  private loading: Promise<void> | null = null

  get webContents(): WebContents | null {
    return this.window?.webContents || null
  }

  async open(conversationId?: string): Promise<void> {
    if (this.window) {
      const window = this.window
      await this.loading
      if (window.isDestroyed()) return
      if (conversationId) window.webContents.send('agent:conversation', conversationId)
      if (window.isMinimized()) window.restore()
      window.show()
      window.focus()
      return
    }
    const window = new BrowserWindow({
      title: 'OdyTerm · Agent 工作区',
      width: 1280, height: 900, minWidth: 860, minHeight: 620,
      show: false, backgroundColor: '#020617',
      webPreferences: {
        preload: path.join(__dirname, '../preload/index.js'),
        sandbox: true, contextIsolation: true, nodeIntegration: false
      }
    })
    this.window = window
    window.setMenuBarVisibility(false)
    window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    window.webContents.on('will-navigate', event => event.preventDefault())
    window.on('closed', () => {
      if (this.window === window) this.window = null
    })
    const query = { workspace: 'agent', ...(conversationId ? { conversation: conversationId } : {}) }
    const loading = (async () => {
      if (process.env.ELECTRON_RENDERER_URL) {
        const url = new URL(process.env.ELECTRON_RENDERER_URL)
        Object.entries(query).forEach(([key, value]) => url.searchParams.set(key, value))
        await window.loadURL(url.toString())
      } else {
        await window.loadFile(path.join(__dirname, '../renderer/index.html'), { query })
      }
    })()
    this.loading = loading
    try {
      await loading
      if (!window.isDestroyed()) { window.show(); window.focus() }
    } catch (error) {
      if (!window.isDestroyed()) window.destroy()
      throw error
    } finally { if (this.loading === loading) this.loading = null }
  }
}
