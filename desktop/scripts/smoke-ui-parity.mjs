import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'
import electronPath from 'electron'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, '..')
const projectRoot = path.resolve(desktopRoot, '..')
const outMain = path.join(desktopRoot, 'out', 'main', 'index.js')
const captureDir = path.join(desktopRoot, 'out', 'smoke')
const capturePath = path.join(captureDir, 'ui-parity.png')
const captureLightPath = path.join(captureDir, 'ui-parity-light.png')
const captureSettingsPath = path.join(captureDir, 'ui-parity-settings.png')
const captureSessionManagerPath = path.join(captureDir, 'ui-parity-session-manager.png')
const captureSessionManagerLightPath = path.join(captureDir, 'ui-parity-session-manager-light.png')
const captureAdvancedAutomationPath = path.join(captureDir, 'ui-parity-advanced-automation.png')
const captureAdvancedAutomationLightPath = path.join(captureDir, 'ui-parity-advanced-automation-light.png')
const captureTransferServicePath = path.join(captureDir, 'ui-parity-transfer-service.png')
const captureTransferServiceLightPath = path.join(captureDir, 'ui-parity-transfer-service-light.png')
const captureManualUpgradePath = path.join(captureDir, 'ui-parity-manual-upgrade.png')
const captureManualUpgradeLightPath = path.join(captureDir, 'ui-parity-manual-upgrade-light.png')
const captureServerGroupsPath = path.join(captureDir, 'ui-parity-server-groups.png')
const captureServerGroupsLightPath = path.join(captureDir, 'ui-parity-server-groups-light.png')
const captureCommandPanelPath = path.join(captureDir, 'ui-parity-command-panel.png')
const captureCommandPanelLightPath = path.join(captureDir, 'ui-parity-command-panel-light.png')
const logExportPath = path.join(captureDir, 'session-log-export.log')
const configuredSessionLogDir = path.join(captureDir, 'configured-session-logs')
const userDataDir = mkdtempSync(path.join(tmpdir(), 'device-tui-ui-parity-'))

if (!existsSync(outMain)) {
  throw new Error('Electron output is missing. Run npm run build before smoke:ui-parity.')
}
mkdirSync(captureDir, { recursive: true })
rmSync(logExportPath, { force: true })
rmSync(configuredSessionLogDir, { recursive: true, force: true })

const env = {
  ...process.env,
  DEVICE_TUI_PROJECT_ROOT: projectRoot,
  DEVICE_TUI_CAPTURE_PATH: capturePath,
  DEVICE_TUI_CAPTURE_LIGHT_PATH: captureLightPath,
  DEVICE_TUI_CAPTURE_SETTINGS_PATH: captureSettingsPath,
  DEVICE_TUI_CAPTURE_SESSION_MANAGER_PATH: captureSessionManagerPath,
  DEVICE_TUI_CAPTURE_SESSION_MANAGER_LIGHT_PATH: captureSessionManagerLightPath,
  DEVICE_TUI_CAPTURE_ADVANCED_AUTOMATION_PATH: captureAdvancedAutomationPath,
  DEVICE_TUI_CAPTURE_ADVANCED_AUTOMATION_LIGHT_PATH: captureAdvancedAutomationLightPath,
  DEVICE_TUI_CAPTURE_TRANSFER_SERVICE_PATH: captureTransferServicePath,
  DEVICE_TUI_CAPTURE_TRANSFER_SERVICE_LIGHT_PATH: captureTransferServiceLightPath,
  DEVICE_TUI_CAPTURE_MANUAL_UPGRADE_PATH: captureManualUpgradePath,
  DEVICE_TUI_CAPTURE_MANUAL_UPGRADE_LIGHT_PATH: captureManualUpgradeLightPath,
  DEVICE_TUI_CAPTURE_SERVER_GROUPS_PATH: captureServerGroupsPath,
  DEVICE_TUI_CAPTURE_SERVER_GROUPS_LIGHT_PATH: captureServerGroupsLightPath,
  DEVICE_TUI_CAPTURE_COMMAND_PANEL_PATH: captureCommandPanelPath,
  DEVICE_TUI_CAPTURE_COMMAND_PANEL_LIGHT_PATH: captureCommandPanelLightPath,
  DEVICE_TUI_CAPTURE_TERMINAL: '1',
  DEVICE_TUI_CAPTURE_UI_PARITY: '1',
  DEVICE_TUI_CAPTURE_BACKEND_RECOVERY: '1',
  DEVICE_TUI_DISABLE_EXTERNAL_OPEN: '1',
  DEVICE_TUI_LOG_EXPORT_PATH: logExportPath,
  DEVICE_TUI_LOG_DIRECTORY_SELECTION: configuredSessionLogDir,
  DEVICE_TUI_MOCK_PROTOCOL_FAILURE: '1',
  ELECTRON_ENABLE_LOGGING: '1'
}

delete env.DEVICE_TUI_BACKEND_URL
delete env.DEVICE_TUI_DESKTOP_TOKEN
delete env.DEVICE_TUI_BACKEND_EXECUTABLE

const child = spawn(
  electronPath,
  ['.', `--user-data-dir=${userDataDir}`],
  {
    cwd: desktopRoot,
    env,
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe']
  }
)

let stdout = ''
let stderr = ''
child.stdout.on('data', (chunk) => {
  const text = chunk.toString()
  stdout += text
  process.stdout.write(text)
})
child.stderr.on('data', (chunk) => {
  const text = chunk.toString()
  stderr += text
  process.stderr.write(text)
})

const timeoutMs = Number(process.env.DEVICE_TUI_UI_PARITY_TIMEOUT_MS || 60_000)
let timedOut = false
const timer = setTimeout(() => {
  timedOut = true
  child.kill()
}, timeoutMs)

const exitCode = await new Promise((resolve, reject) => {
  child.once('error', reject)
  child.once('exit', (code) => resolve(code ?? 0))
})

clearTimeout(timer)

try {
  rmSync(userDataDir, { recursive: true, force: true })
} catch {
  // The smoke already uses a task-scoped temp directory. Cleanup failure should not
  // hide the UI parity result.
}

const parityMatch = stdout.match(/\[renderer\] uiParity=(.+)/)
const parityPassed = stdout.includes('[renderer] uiParityPassed=true')
const restoreMatch = stdout.match(/\[renderer\] uiRestore=(.+)/)
const restorePassed = stdout.includes('[renderer] uiRestorePassed=true')
const recoveryMatch = stdout.match(/\[renderer\] backendRecovery=(.+)/)
const recoveryPassed = stdout.includes('[renderer] backendRecoveryPassed=true')
const tokenHidden = stdout.includes('[renderer] tokenExposed=false')

if (timedOut) {
  throw new Error(`Electron UI parity smoke timed out after ${timeoutMs}ms.`)
}
if (exitCode !== 0) {
  throw new Error(`Electron UI parity smoke exited with code ${exitCode}.`)
}
if (!tokenHidden) {
  throw new Error('Renderer runtime exposed the backend token or did not report tokenExposed=false.')
}
if (!parityPassed) {
  const details = parityMatch?.[1] || stdout || stderr
  throw new Error(`Electron UI parity checks failed: ${details}`)
}
if (!restorePassed) {
  const details = restoreMatch?.[1] || stdout || stderr
  throw new Error(`Electron UI restore checks failed: ${details}`)
}
if (!recoveryPassed) {
  const details = recoveryMatch?.[1] || stdout || stderr
  throw new Error(`Electron backend recovery checks failed: ${details}`)
}
if (!existsSync(capturePath)) {
  throw new Error(`Electron UI parity capture was not written: ${capturePath}`)
}
if (!existsSync(captureLightPath)) {
  throw new Error(`Electron light-theme parity capture was not written: ${captureLightPath}`)
}
if (!existsSync(captureSettingsPath)) {
  throw new Error(`Electron settings parity capture was not written: ${captureSettingsPath}`)
}
if (!existsSync(captureSessionManagerPath)) {
  throw new Error(`Electron session-manager parity capture was not written: ${captureSessionManagerPath}`)
}
if (!existsSync(captureSessionManagerLightPath)) {
  throw new Error(`Electron light session-manager parity capture was not written: ${captureSessionManagerLightPath}`)
}
if (!existsSync(captureAdvancedAutomationPath)) {
  throw new Error(`Electron advanced-automation parity capture was not written: ${captureAdvancedAutomationPath}`)
}
if (!existsSync(captureAdvancedAutomationLightPath)) {
  throw new Error(`Electron light advanced-automation parity capture was not written: ${captureAdvancedAutomationLightPath}`)
}
if (!existsSync(captureTransferServicePath)) {
  throw new Error(`Electron transfer-service parity capture was not written: ${captureTransferServicePath}`)
}
if (!existsSync(captureTransferServiceLightPath)) {
  throw new Error(`Electron light transfer-service parity capture was not written: ${captureTransferServiceLightPath}`)
}
if (!existsSync(captureManualUpgradePath)) {
  throw new Error(`Electron manual-upgrade parity capture was not written: ${captureManualUpgradePath}`)
}
if (!existsSync(captureManualUpgradeLightPath)) {
  throw new Error(`Electron light manual-upgrade parity capture was not written: ${captureManualUpgradeLightPath}`)
}
if (!existsSync(captureServerGroupsPath)) {
  throw new Error(`Electron server-groups parity capture was not written: ${captureServerGroupsPath}`)
}
if (!existsSync(captureServerGroupsLightPath)) {
  throw new Error(`Electron light server-groups parity capture was not written: ${captureServerGroupsLightPath}`)
}
if (!existsSync(captureCommandPanelPath)) {
  throw new Error(`Electron command-panel parity capture was not written: ${captureCommandPanelPath}`)
}
if (!existsSync(captureCommandPanelLightPath)) {
  throw new Error(`Electron light command-panel parity capture was not written: ${captureCommandPanelLightPath}`)
}
if (!existsSync(logExportPath)) {
  throw new Error(`Electron session-log export was not written: ${logExportPath}`)
}
const exportedLog = readFileSync(logExportPath, 'utf8')
if (!exportedLog.includes('display version') && !exportedLog.includes('SimOS V1.0')) {
  throw new Error('Electron session-log export did not contain the live smoke output.')
}

console.log('Electron UI parity smoke passed')
console.log(`Capture=${capturePath}`)
console.log(`LightCapture=${captureLightPath}`)
console.log(`SettingsCapture=${captureSettingsPath}`)
console.log(`SessionManagerCapture=${captureSessionManagerPath}`)
console.log(`SessionManagerLightCapture=${captureSessionManagerLightPath}`)
console.log(`AdvancedAutomationCapture=${captureAdvancedAutomationPath}`)
console.log(`AdvancedAutomationLightCapture=${captureAdvancedAutomationLightPath}`)
console.log(`TransferServiceCapture=${captureTransferServicePath}`)
console.log(`TransferServiceLightCapture=${captureTransferServiceLightPath}`)
console.log(`ManualUpgradeCapture=${captureManualUpgradePath}`)
console.log(`ManualUpgradeLightCapture=${captureManualUpgradeLightPath}`)
console.log(`ServerGroupsCapture=${captureServerGroupsPath}`)
console.log(`ServerGroupsLightCapture=${captureServerGroupsLightPath}`)
console.log(`CommandPanelCapture=${captureCommandPanelPath}`)
console.log(`CommandPanelLightCapture=${captureCommandPanelLightPath}`)
console.log(`LogExport=${logExportPath}`)
