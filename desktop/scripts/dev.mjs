import { spawn } from 'node:child_process'
import path from 'node:path'
import process from 'node:process'

const projectRoot = process.cwd()
const electronViteCli = path.resolve(projectRoot, 'node_modules/electron-vite/bin/electron-vite.js')
const userDataDir = process.env.ODYTERM_DEV_USER_DATA_DIR?.trim()
  || path.resolve(projectRoot, '..', '.odyterm-dev-user-data')
const extraArgs = process.argv.slice(2)

const child = spawn(
  process.execPath,
  [electronViteCli, 'dev', '--noSandbox', ...extraArgs, '--', `--user-data-dir=${userDataDir}`],
  {
    cwd: projectRoot,
    env: { ...process.env },
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
