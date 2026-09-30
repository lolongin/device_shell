import { BrowserWindow } from 'electron'

export function createCredentialWindow(
  parent: BrowserWindow,
  mode: 'connect' | 'manage' | 'custom' | 'internal',
  theme: 'dark' | 'light',
  preload: string,
): BrowserWindow {
  const window = new BrowserWindow({
    parent,
    modal: true,
    width: mode === 'custom' ? 520 : 480,
    height: mode === 'custom' || mode === 'internal' ? 590 : 390,
    resizable: false,
    minimizable: false,
    maximizable: false,
    show: false,
    backgroundColor: theme === 'light' ? '#ffffff' : '#08101d',
    webPreferences: {
      preload,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  window.setMenuBarVisibility(false)
  return window
}
