import path from 'node:path'
import { app } from 'electron'

export interface TransferSettingsSaveRequest {
  protocol: 'ftp'
  host: string
  advertised_host: string
  port: number
  root: string
  username: string
  password?: string
  writable: boolean
}

export function credentialDialogPath(): string {
  return app.isPackaged
    ? path.join(process.resourcesPath, 'credential-dialog.html')
    : path.join(__dirname, '../../resources/credential-dialog.html')
}

export function hasSensitiveKey(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  return Object.entries(value).some(([key, child]) => /password|secret|token/i.test(key) || hasSensitiveKey(child))
}

export function validateTransferSettingsSaveRequest(value: unknown): asserts value is TransferSettingsSaveRequest {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid file-transfer settings')
  const payload = value as Record<string, unknown>
  const allowed = new Set(['protocol', 'host', 'advertised_host', 'port', 'root', 'username', 'password', 'writable'])
  if (Object.keys(payload).some((key) => !allowed.has(key))) throw new Error('Invalid file-transfer settings field')
  if (payload.protocol !== 'ftp' || typeof payload.host !== 'string' || payload.host.length > 255
    || typeof payload.advertised_host !== 'string' || payload.advertised_host.length > 255
    || typeof payload.port !== 'number' || !Number.isInteger(payload.port) || payload.port < 0 || payload.port > 65535
    || typeof payload.root !== 'string' || !payload.root || payload.root.length > 4_096
    || typeof payload.username !== 'string' || !payload.username || payload.username.length > 255
    || (payload.password !== undefined && (typeof payload.password !== 'string' || payload.password.length > 1_024))
    || typeof payload.writable !== 'boolean') throw new Error('Invalid file-transfer settings')
}
