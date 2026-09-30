import { Menu } from 'electron'
import type { TitleBarOverlayOptions } from 'electron'

export type NativeThemeMode = 'dark' | 'light'
export type ApplicationMenuKey = 'file' | 'edit' | 'view' | 'window'

const WINDOW_TITLE_BAR_HEIGHT = 32

export function titleBarOverlayForTheme(mode: NativeThemeMode): TitleBarOverlayOptions {
  return mode === 'light'
    ? { color: '#f8fafc', symbolColor: '#334155', height: WINDOW_TITLE_BAR_HEIGHT }
    : { color: '#0f172a', symbolColor: '#cbd5e1', height: WINDOW_TITLE_BAR_HEIGHT }
}

export function buildApplicationMenu(): Menu {
  return Menu.buildFromTemplate([
    { id: 'file', label: '文件', submenu: [{ role: 'close', label: '关闭窗口' }, { type: 'separator' }, { role: 'quit', label: '退出' }] },
    { id: 'edit', label: '编辑', submenu: [{ role: 'undo', label: '撤销' }, { role: 'redo', label: '重做' }, { type: 'separator' }, { role: 'cut', label: '剪切' }, { role: 'copy', label: '复制' }, { role: 'paste', label: '粘贴' }, { role: 'selectAll', label: '全选' }] },
    { id: 'view', label: '视图', submenu: [{ role: 'reload', label: '重新加载' }, { role: 'forceReload', label: '强制重新加载' }, { type: 'separator' }, { role: 'resetZoom', label: '重置缩放' }, { role: 'zoomIn', label: '放大' }, { role: 'zoomOut', label: '缩小' }, { type: 'separator' }, { role: 'toggleDevTools', label: '切换开发者工具' }] },
    { id: 'window', label: '窗口', submenu: [{ role: 'minimize', label: '最小化' }, { role: 'zoom', label: '最大化/还原' }, { type: 'separator' }, { role: 'close', label: '关闭窗口' }] },
  ])
}
