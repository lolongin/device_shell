import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { appendFileSync, existsSync, mkdirSync, renameSync, statSync, unlinkSync } from 'node:fs'
import path from 'node:path'
import { app } from 'electron'

export interface BackendRuntime {
  apiBaseUrl: string
  token: string
  apiVersion: number
}

interface ReadyMessage {
  type: 'ready'
  host: string
  port: number
  apiVersion: number
}

export class PythonBackend {
  private child: ChildProcessWithoutNullStreams | null = null
  private stopping = false
  private runtime: BackendRuntime | null = null
  private externalRuntime = false
  private restartAttempts = 0
  private restartTimer: NodeJS.Timeout | null = null

  constructor(
    private readonly onUnexpectedExit: (details: string) => void,
    private readonly onRecovered: (details: string) => void = () => undefined
  ) {}

  get config(): BackendRuntime {
    if (!this.runtime) throw new Error('Python backend is not ready')
    return this.runtime
  }

  async start(): Promise<BackendRuntime> {
    if (this.runtime) return this.runtime
    this.stopping = false
    const configuredUrl = process.env.DEVICE_TUI_BACKEND_URL
    const configuredToken = process.env.DEVICE_TUI_DESKTOP_TOKEN
    if (configuredUrl && configuredToken) {
      this.externalRuntime = true
      this.runtime = {
        apiBaseUrl: configuredUrl.replace(/\/$/, ''),
        token: configuredToken,
        apiVersion: 1
      }
      this.writeDiagnostic(`Using externally configured backend at ${this.runtime.apiBaseUrl}`)
      return this.runtime
    }

    const token = randomBytes(32).toString('hex')
    const bundledBackend = this.bundledBackendPath()
    const python = process.env.DEVICE_TUI_PYTHON || 'python'
    const command = bundledBackend || python
    const args = bundledBackend
      ? ['--port', '0']
      : ['-m', 'src.desktop_backend.main', '--port', '0']
    const projectRoot = process.env.DEVICE_TUI_PROJECT_ROOT || path.resolve(app.getAppPath(), '..')
    if (bundledBackend && !existsSync(bundledBackend)) {
      throw new Error(`Bundled Python backend was not found: ${bundledBackend}`)
    }
    this.externalRuntime = false
    this.writeDiagnostic(`Starting Python backend: ${command} ${args.join(' ')}`)
    const backendProcess = spawn(command, args, {
      cwd: projectRoot,
      windowsHide: true,
      env: {
        ...process.env,
        DEVICE_TUI_DESKTOP_TOKEN: token,
        DEVICE_TUI_DATA_DIR: app.getPath('userData'),
        DEVICE_TUI_PACKAGED: bundledBackend ? '1' : '0',
        PYTHONUNBUFFERED: '1'
      }
    })
    this.child = backendProcess

    backendProcess.stderr.on('data', (chunk: Buffer) => {
      const text = chunk.toString()
      process.stderr.write(`[python-backend] ${text}`)
      this.writeDiagnostic(text.trimEnd())
    })
    backendProcess.once('exit', (code, signal) => {
      const expected = this.stopping
      const wasReady = this.runtime !== null
      const reason = code ?? signal ?? 'unknown'
      this.child = null
      this.runtime = null
      this.writeDiagnostic(`Python backend exited (${reason})`)
      if (!expected) {
        const details = `Python backend exited (${reason})`
        this.onUnexpectedExit(details)
        if (wasReady) this.scheduleRestart(details)
      }
    })

    return await new Promise<BackendRuntime>((resolve, reject) => {
      let buffer = ''
      const timer = setTimeout(() => {
        reject(new Error('Timed out waiting for Python backend startup'))
        this.stop()
      }, 15_000)

      const handleLine = (line: string): void => {
        if (!line.trim()) return
        try {
          const message = JSON.parse(line) as Partial<ReadyMessage>
          if (
            message.type === 'ready' &&
            typeof message.host === 'string' &&
            typeof message.port === 'number'
          ) {
            clearTimeout(timer)
            this.runtime = {
              apiBaseUrl: `http://${message.host}:${message.port}`,
              token,
              apiVersion: Number(message.apiVersion || 1)
            }
            this.writeDiagnostic(`Python backend ready at ${this.runtime.apiBaseUrl}`)
            resolve(this.runtime)
          }
        } catch {
          process.stdout.write(`[python-backend] ${line}\n`)
          this.writeDiagnostic(line)
        }
      }

      backendProcess.stdout.on('data', (chunk: Buffer) => {
        buffer += chunk.toString()
        const lines = buffer.split(/\r?\n/)
        buffer = lines.pop() || ''
        lines.forEach(handleLine)
      })
      backendProcess.once('error', (error) => {
        clearTimeout(timer)
        this.writeDiagnostic(`Python backend failed to start: ${error.message}`)
        reject(error)
      })
      backendProcess.once('exit', (code, signal) => {
        clearTimeout(timer)
        const reason = code ?? signal ?? 'unknown'
        reject(new Error(`Python backend exited before startup (${reason})`))
      })
    })
  }

  stop(): void {
    this.stopping = true
    if (this.restartTimer) {
      clearTimeout(this.restartTimer)
      this.restartTimer = null
    }
    this.child?.kill()
    this.child = null
    this.runtime = null
  }

  crashForRecoveryProbe(): boolean {
    if (this.externalRuntime || !this.child) return false
    this.writeDiagnostic('Crashing Python backend for packaged recovery probe')
    return this.child.kill()
  }

  private bundledBackendPath(): string | null {
    const override = process.env.DEVICE_TUI_BACKEND_EXECUTABLE
    if (override) return path.resolve(override)
    if (!app.isPackaged) return null
    const executable = process.platform === 'win32' ? 'device-tui-backend.exe' : 'device-tui-backend'
    return path.join(process.resourcesPath, 'backend', 'device-tui-backend', executable)
  }

  private scheduleRestart(details: string): void {
    if (this.externalRuntime || this.restartTimer || this.restartAttempts >= 2) return
    this.restartAttempts += 1
    const delayMs = 500 * this.restartAttempts
    this.writeDiagnostic(`${details}; restarting backend in ${delayMs}ms`)
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null
      void this.start()
        .then((runtime) => {
          this.onRecovered(`Python backend recovered at ${runtime.apiBaseUrl}`)
        })
        .catch((error: Error) => {
          this.writeDiagnostic(`Python backend restart failed: ${error.message}`)
          this.onUnexpectedExit(`Python backend restart failed: ${error.message}`)
        })
    }, delayMs)
  }

  private writeDiagnostic(message: string): void {
    if (!message) return
    try {
      const logDir = path.join(app.getPath('userData'), 'logs')
      mkdirSync(logDir, { recursive: true })
      const line = `[${new Date().toISOString()}] ${message}\n`
      const logPath = path.join(logDir, 'backend.log')
      this.rotateDiagnosticIfNeeded(logPath, Buffer.byteLength(line, 'utf8'))
      appendFileSync(logPath, line, 'utf8')
    } catch {
      // Diagnostics must never prevent backend startup or shutdown.
    }
  }

  private rotateDiagnosticIfNeeded(logPath: string, incomingBytes: number): void {
    const maxBytes = Number(process.env.DEVICE_TUI_BACKEND_LOG_MAX_BYTES || 5 * 1024 * 1024)
    const backupCount = Math.max(1, Number(process.env.DEVICE_TUI_BACKEND_LOG_BACKUPS || 3))
    if (!existsSync(logPath)) return
    let size = 0
    try {
      size = statSync(logPath).size
    } catch {
      return
    }
    if (size + incomingBytes <= maxBytes) return
    for (let index = backupCount; index >= 1; index -= 1) {
      const source = `${logPath}.${index}`
      const target = `${logPath}.${index + 1}`
      try {
        if (index === backupCount) {
          if (existsSync(source)) unlinkSync(source)
        } else if (existsSync(source)) {
          renameSync(source, target)
        }
      } catch {
        return
      }
    }
    try {
      renameSync(logPath, `${logPath}.1`)
    } catch {
      // Keep writing the current file if rotation loses a benign race.
    }
  }
}
