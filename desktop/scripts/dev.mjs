import { copyFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { spawn } from 'node:child_process'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'

const projectRoot = process.cwd()
const electronViteCli = path.resolve(projectRoot, 'node_modules/electron-vite/bin/electron-vite.js')
const userDataDir = process.env.ODYTERM_DEV_USER_DATA_DIR?.trim()
  || path.resolve(projectRoot, '..', '.odyterm-dev-user-data')
const configuredBackendDataDir = process.env.DEVICE_TUI_DATA_DIR?.trim()
const legacyBackendDataDir = path.join(
  process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming'),
  'odyterm-desktop'
)
const backendDataDir = configuredBackendDataDir || userDataDir
const extraArgs = process.argv.slice(2)

function seedDevelopmentData(sourceDirectory, targetDirectory) {
  if (configuredBackendDataDir) return
  mkdirSync(targetDirectory, { recursive: true })
  const sourceDatabase = path.join(sourceDirectory, 'odyterm.sqlite3')
  const targetDatabase = path.join(targetDirectory, 'odyterm.sqlite3')
  const marker = path.join(targetDirectory, '.legacy-data-seeded')
  if (path.resolve(sourceDirectory) === path.resolve(targetDirectory)
    || existsSync(marker)
    || !existsSync(sourceDatabase)) return
  if (existsSync(targetDatabase)) {
    copyFileSync(targetDatabase, `${targetDatabase}.before-legacy-seed.bak`)
  }
  copyFileSync(sourceDatabase, targetDatabase)
  for (const suffix of ['-wal', '-shm']) {
    const sourceSidecar = `${sourceDatabase}${suffix}`
    if (existsSync(sourceSidecar)) copyFileSync(sourceSidecar, `${targetDatabase}${suffix}`)
  }
  writeFileSync(marker, `${new Date().toISOString()}\n`, 'utf8')
}

seedDevelopmentData(legacyBackendDataDir, backendDataDir)

const child = spawn(
  process.execPath,
  [electronViteCli, 'dev', '--noSandbox', ...extraArgs, '--', `--user-data-dir=${userDataDir}`],
  {
    cwd: projectRoot,
    env: { ...process.env, DEVICE_TUI_DATA_DIR: backendDataDir },
    stdio: 'inherit'
  }
)

child.once('error', (error) => {
  console.error(`Failed to start electron-vite: ${error.message}`)
  process.exitCode = 1
})

child.once('exit', (code, signal) => {
  if (signal) {
    process.exitCode = 1
    return
  }
  process.exitCode = code ?? 1
})
