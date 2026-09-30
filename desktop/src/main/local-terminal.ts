import type { IPty } from 'node-pty'

export interface LocalTerminalSummary {
  id: string
  device_id: string
  kind: 'local'
  title: string
  status: 'connecting' | 'connected' | 'disconnected' | 'failed' | 'closed'
  sequence: number
  generation: number
  shell: string
  cwd: string
}

export interface LocalTerminalProcess extends LocalTerminalSummary {
  process: IPty | null
  output: string
}

export function localTerminalPayload(session: LocalTerminalProcess): LocalTerminalSummary {
  const { process: _process, output: _output, ...summary } = session
  return summary
}

export function localShellCommand(shellName: string): { command: string; args: string[]; label: string } {
  const requested = shellName.trim().toLowerCase()
  if (process.platform === 'win32') {
    if (requested === 'cmd' || requested === 'cmd.exe') return { command: process.env.ComSpec || 'cmd.exe', args: [], label: '命令提示符' }
    if (requested === 'pwsh' || requested === 'pwsh.exe') return { command: 'pwsh.exe', args: ['-NoLogo', '-NoProfile'], label: 'PowerShell 7' }
    return { command: 'powershell.exe', args: ['-NoLogo', '-NoProfile'], label: 'PowerShell' }
  }
  if (requested === 'bash') return { command: 'bash', args: [], label: 'Bash' }
  if (requested === 'zsh') return { command: 'zsh', args: [], label: 'Zsh' }
  return { command: process.env.SHELL || 'sh', args: [], label: 'Shell' }
}
