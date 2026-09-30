// Registration of local terminal IPC handlers.

import path from 'node:path'
import { existsSync, statSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import type { IpcMain, WebContents } from 'electron'

import type { LocalTerminalProcess, LocalTerminalSummary } from './local-terminal.js'

interface LocalTerminalIpcOptions {
  ipcMain: IpcMain
  getWebContents: () => WebContents | null
  terminals: Map<string, LocalTerminalProcess>
  start: (session: LocalTerminalProcess) => void
  toSummary: (session: LocalTerminalProcess) => LocalTerminalSummary
}

export function registerLocalTerminalIpc(options: LocalTerminalIpcOptions): void {
  const { ipcMain, getWebContents, terminals, start, toSummary } = options
  for (const channel of ['local-terminal:list', 'local-terminal:open', 'local-terminal:subscribe', 'local-terminal:write', 'local-terminal:resize', 'local-terminal:close', 'local-terminal:disconnect', 'local-terminal:reconnect']) ipcMain.removeHandler(channel)
ipcMain.handle('local-terminal:list', (event): LocalTerminalSummary[] => {
  if (event.sender !== getWebContents()) throw new Error('Untrusted local-terminal caller')
  return [...terminals.values()].map(toSummary)
})
ipcMain.handle('local-terminal:open', (event, request?: unknown): LocalTerminalSummary => {
  if (event.sender !== getWebContents()) throw new Error('Untrusted local-terminal caller')
  const payload = request && typeof request === 'object' ? request as Record<string, unknown> : {}
  const shellName = typeof payload.shell === 'string' ? payload.shell.trim() : ''
  if (shellName && !['powershell', 'powershell.exe', 'pwsh', 'pwsh.exe', 'cmd', 'cmd.exe', 'bash', 'zsh'].includes(shellName.toLowerCase())) {
    throw new Error('Unsupported local shell')
  }
  const requestedCwd = typeof payload.cwd === 'string' ? payload.cwd.trim() : ''
  const cwd = requestedCwd ? path.resolve(requestedCwd) : process.cwd()
  if (!existsSync(cwd) || !statSync(cwd).isDirectory()) throw new Error('Invalid local terminal directory')
  const id = `local-${randomBytes(8).toString('hex')}`
  const shell = shellName || (process.platform === 'win32' ? 'powershell' : (process.env.SHELL || 'sh'))
  const session: LocalTerminalProcess = {
    id,
    device_id: `local:${id}`,
    kind: 'local',
    title: '本地终端',
    status: 'connecting',
    sequence: 0,
    generation: 0,
    shell,
    cwd,
    process: null,
    output: ''
  }
  terminals.set(id, session)
  try {
    start(session)
  } catch (error) {
    terminals.delete(id)
    throw error
  }
  return toSummary(session)
})
ipcMain.handle('local-terminal:subscribe', (event, sessionId: unknown): { session: LocalTerminalSummary; output: string } => {
  if (event.sender !== getWebContents() || typeof sessionId !== 'string' || !sessionId) {
    throw new Error('Invalid local terminal session')
  }
  const session = terminals.get(sessionId)
  if (!session) throw new Error('Unknown local terminal session')
  return { session: toSummary(session), output: session.output }
})
ipcMain.handle('local-terminal:write', (event, sessionId: unknown, data: unknown): boolean => {
  if (event.sender !== getWebContents() || typeof sessionId !== 'string' || typeof data !== 'string' || data.length > 1_000_000) {
    throw new Error('Invalid local terminal input')
  }
  const session = terminals.get(sessionId)
  if (!session?.process) return false
  session.process.write(data)
  return true
})
ipcMain.handle('local-terminal:resize', (event, sessionId: unknown, cols: unknown, rows: unknown): boolean => {
  if (event.sender !== getWebContents() || typeof sessionId !== 'string' || !sessionId) {
    throw new Error('Invalid local terminal session')
  }
  if (typeof cols !== 'number' || typeof rows !== 'number' || !Number.isFinite(cols) || !Number.isFinite(rows)) {
    throw new Error('Invalid local terminal size')
  }
  const session = terminals.get(sessionId)
  if (!session?.process) return false
  session.process.resize(Math.max(2, Math.floor(cols)), Math.max(2, Math.floor(rows)))
  return true
})
ipcMain.handle('local-terminal:close', (event, sessionId: unknown): boolean => {
  if (event.sender !== getWebContents() || typeof sessionId !== 'string' || !sessionId) {
    throw new Error('Invalid local terminal session')
  }
  const session = terminals.get(sessionId)
  if (!session) return false
  session.status = 'closed'
  const process = session.process
  session.process = null
  session.generation += 1
  process?.kill()
  terminals.delete(sessionId)
  return true
})
ipcMain.handle('local-terminal:disconnect', (event, sessionId: unknown): boolean => {
  if (event.sender !== getWebContents() || typeof sessionId !== 'string' || !sessionId) {
    throw new Error('Invalid local terminal session')
  }
  const session = terminals.get(sessionId)
  if (!session) return false
  session.status = 'disconnected'
  session.process?.kill()
  session.process = null
  session.sequence += 1
  getWebContents()?.send('local-terminal:status', {
    sessionId,
    sequence: session.sequence,
    status: session.status
  })
  return true
})
ipcMain.handle('local-terminal:reconnect', (event, sessionId: unknown): LocalTerminalSummary => {
  if (event.sender !== getWebContents() || typeof sessionId !== 'string' || !sessionId) {
    throw new Error('Invalid local terminal session')
  }
  const session = terminals.get(sessionId)
  if (!session) throw new Error('Unknown local terminal session')
  const previous = session.process
  session.process = null
  previous?.kill()
  session.output = ''
  session.generation += 1
  start(session)
  return toSummary(session)
})

}
