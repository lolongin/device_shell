import type { BrowserWindow, IpcMain, Menu } from 'electron'
import type { ApplicationMenuKey, NativeThemeMode } from './application-menu.js'
import { titleBarOverlayForTheme } from './application-menu.js'

export interface WindowIpcDependencies {
  ipcMain: IpcMain
  getWindow: () => BrowserWindow | null
  setTheme: (mode: NativeThemeMode) => void
  applicationMenu: Menu
}

export function registerWindowIpc(dependencies: WindowIpcDependencies): void {
  dependencies.ipcMain.handle('window:set-native-theme', (event, mode: unknown): NativeThemeMode => {
    const window = dependencies.getWindow()
    if (event.sender !== window?.webContents) throw new Error('Untrusted theme request')
    if (mode !== 'dark' && mode !== 'light') throw new Error('Invalid native theme')
    dependencies.setTheme(mode)
    window.setTitleBarOverlay(titleBarOverlayForTheme(mode))
    return mode
  })
  dependencies.ipcMain.handle('window:show-application-menu', (event, key: unknown, x: unknown, y: unknown): void => {
    const window = dependencies.getWindow()
    if (event.sender !== window?.webContents || !window) throw new Error('Untrusted application-menu caller')
    if (key !== 'file' && key !== 'edit' && key !== 'view' && key !== 'window') throw new Error('Invalid application-menu key')
    if (typeof x !== 'number' || typeof y !== 'number' || !Number.isFinite(x) || !Number.isFinite(y)) throw new Error('Invalid application-menu coordinates')
    dependencies.applicationMenu.getMenuItemById(key as ApplicationMenuKey)?.submenu?.popup({ window, x: Math.round(x), y: Math.round(y) })
  })
  dependencies.ipcMain.handle('window:set-always-on-top', (event, enabled: unknown): boolean => {
    const window = dependencies.getWindow()
    if (event.sender !== window?.webContents || !window || typeof enabled !== 'boolean') throw new Error('Untrusted always-on-top caller')
    window.setAlwaysOnTop(enabled)
    return window.isAlwaysOnTop()
  })
}
