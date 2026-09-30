import path from 'node:path'
import { existsSync, statSync } from 'node:fs'

export function validDialogDefaultPath(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.trim()) return undefined
  try {
    const candidate = path.resolve(value.trim())
    if (!existsSync(candidate)) return undefined
    return statSync(candidate).isDirectory() ? candidate : path.dirname(candidate)
  } catch {
    return undefined
  }
}
