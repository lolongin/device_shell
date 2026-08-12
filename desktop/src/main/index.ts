import path from 'node:path'
import { mkdir, writeFile } from 'node:fs/promises'
import { randomBytes } from 'node:crypto'
import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import { PythonBackend } from './python-backend.js'

let mainWindow: BrowserWindow | null = null

const backend = new PythonBackend((details) => {
  mainWindow?.webContents.send('backend:exit', details)
}, (details) => {
  mainWindow?.webContents.send('backend:recovered', details)
})

interface BackendRequest {
  path: string
  method?: string
  body?: string
}

interface BackendResponse {
  status: number
  body: string
}

interface ProfileCredentialRequest {
  profileId: string
  profileName: string
  protocol: 'ssh' | 'telnet' | 'serial'
  endpoint: string
  hasPassword: boolean
}

interface CredentialDialogResult {
  action: 'submit' | 'remove' | 'cancel'
  password: string
  save: boolean
}

interface SessionLogExportRequest {
  suggestedName: string
  content: string
}

function hasSensitiveKey(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  return Object.entries(value).some(([key, child]) =>
    /password|secret|token/i.test(key) || hasSensitiveKey(child)
  )
}

function validateBackendRequest(request: BackendRequest): void {
  if (
    typeof request.path !== 'string' ||
    !request.path.startsWith('/api/v1/') ||
    request.path.includes('..') ||
    request.path.includes('://')
  ) {
    throw new Error('Invalid backend API path')
  }
  if (request.path.includes('/credentials/') || request.path === '/api/v1/sessions/with-credential') {
    throw new Error('Credential endpoints require the isolated credential bridge')
  }
  const method = String(request.method || 'GET').toUpperCase()
  if (!['GET', 'POST', 'DELETE', 'PATCH', 'PUT'].includes(method)) {
    throw new Error('Invalid backend API method')
  }
  if (typeof request.body === 'string' && request.body.length > 2_000_000) {
    throw new Error('Backend API request is too large')
  }
  if (request.body) {
    try {
      if (hasSensitiveKey(JSON.parse(request.body))) {
        throw new Error('Sensitive values are not allowed through the renderer API bridge')
      }
    } catch (error) {
      if (error instanceof SyntaxError) throw new Error('Backend API request body must be valid JSON')
      throw error
    }
  }
}

async function fetchBackend(
  runtime: { apiBaseUrl: string; token: string },
  pathName: string,
  method = 'GET',
  body?: string
): Promise<BackendResponse> {
  const response = await fetch(`${runtime.apiBaseUrl}${pathName}`, {
    method,
    headers: {
      Authorization: `Bearer ${runtime.token}`,
      'Content-Type': 'application/json'
    },
    body: method === 'GET' || method === 'DELETE' ? undefined : body
  })
  return { status: response.status, body: await response.text() }
}

function backendError(response: BackendResponse): Error {
  let message = response.body || `Backend request failed (${response.status})`
  try {
    const payload = JSON.parse(response.body) as { detail?: string; error?: { message?: string } }
    message = payload.error?.message || payload.detail || message
  } catch {
    // Keep the backend's non-JSON response.
  }
  return new Error(message)
}

async function promptForCredential(
  request: ProfileCredentialRequest,
  mode: 'connect' | 'manage'
): Promise<CredentialDialogResult> {
  if (!mainWindow) return { action: 'cancel', password: '', save: false }
  const credentialWindow = new BrowserWindow({
    parent: mainWindow,
    modal: true,
    width: 480,
    height: 390,
    resizable: false,
    minimizable: false,
    maximizable: false,
    show: false,
    backgroundColor: '#08101d',
    webPreferences: {
      preload: path.join(__dirname, '../preload/credential.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })
  credentialWindow.setMenuBarVisibility(false)

  return await new Promise<CredentialDialogResult>((resolve) => {
    let settled = false
    const finish = (result: CredentialDialogResult): void => {
      if (settled) return
      settled = true
      ipcMain.removeListener('credential-dialog:submit', onSubmit)
      ipcMain.removeListener('credential-dialog:remove', onRemove)
      ipcMain.removeListener('credential-dialog:cancel', onCancel)
      if (!credentialWindow.isDestroyed()) credentialWindow.close()
      resolve(result)
    }
    const trusted = (event: Electron.IpcMainEvent): boolean =>
      event.sender === credentialWindow.webContents
    const onSubmit = (event: Electron.IpcMainEvent, value: unknown): void => {
      if (!trusted(event) || !value || typeof value !== 'object') return
      const submission = value as { password?: unknown; save?: unknown }
      const password = typeof submission.password === 'string' ? submission.password : ''
      if (!password || password.length > 4_096) return
      finish({ action: 'submit', password, save: submission.save === true })
    }
    const onRemove = (event: Electron.IpcMainEvent): void => {
      if (trusted(event)) finish({ action: 'remove', password: '', save: false })
    }
    const onCancel = (event: Electron.IpcMainEvent): void => {
      if (trusted(event)) finish({ action: 'cancel', password: '', save: false })
    }
    ipcMain.on('credential-dialog:submit', onSubmit)
    ipcMain.on('credential-dialog:remove', onRemove)
    ipcMain.on('credential-dialog:cancel', onCancel)
    credentialWindow.once('closed', () => finish({ action: 'cancel', password: '', save: false }))
    credentialWindow.loadFile(
      path.join(__dirname, '../../resources/credential-dialog.html'),
      {
        query: {
          mode,
          profile: request.profileName,
          protocol: request.protocol,
          endpoint: request.endpoint,
          hasPassword: request.hasPassword ? '1' : '0'
        }
      }
    ).then(() => credentialWindow.show()).catch(() => {
      finish({ action: 'cancel', password: '', save: false })
    })
  })
}

async function createWindow(): Promise<void> {
  await backend.start()
  ipcMain.removeHandler('runtime:get')
  ipcMain.removeHandler('backend:request')
  ipcMain.removeHandler('credential:open-profile-session')
  ipcMain.removeHandler('credential:manage-profile')
  ipcMain.removeHandler('logs:choose-directory')
  ipcMain.removeHandler('logs:open-directory')
  ipcMain.removeHandler('logs:open-session')
  ipcMain.removeHandler('logs:save-copy')
  ipcMain.removeHandler('window:set-always-on-top')
  ipcMain.handle('runtime:get', () => {
    const runtime = backend.config
    return {
      apiBaseUrl: runtime.apiBaseUrl,
      apiVersion: runtime.apiVersion
    }
  })
  ipcMain.handle('backend:request', async (event, request: BackendRequest): Promise<BackendResponse> => {
    if (event.sender !== mainWindow?.webContents) throw new Error('Untrusted backend API caller')
    validateBackendRequest(request)
    const method = String(request.method || 'GET').toUpperCase()
    return await fetchBackend(backend.config, request.path, method, request.body)
  })

  mainWindow = new BrowserWindow({
    width: 1560,
    height: 960,
    minWidth: 1180,
    minHeight: 720,
    show: false,
    backgroundColor: '#020617',
    webPreferences: {
      preload: path.join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })

  mainWindow.once('ready-to-show', () => mainWindow?.show())
  mainWindow.webContents.on('preload-error', (_event, preloadPath, error) => {
    console.error(`Preload failed: ${preloadPath}`, error)
  })
  mainWindow.webContents.on('console-message', (_event, level, message) => {
    if (level >= 2) {
      console.error(`[renderer] ${message}`)
    }
  })
  mainWindow.on('closed', () => {
    mainWindow = null
  })

  ipcMain.handle('file-transfer:choose-root', async (event): Promise<string> => {
    if (event.sender !== mainWindow?.webContents || !mainWindow) {
      throw new Error('Untrusted file-transfer directory caller')
    }
    const selected = await dialog.showOpenDialog(mainWindow, {
      title: '选择文件传输共享目录',
      properties: ['openDirectory', 'createDirectory']
    })
    return selected.canceled ? '' : selected.filePaths[0] || ''
  })

  ipcMain.handle('logs:choose-directory', async (event): Promise<string> => {
    if (event.sender !== mainWindow?.webContents || !mainWindow) {
      throw new Error('Untrusted log-directory chooser caller')
    }
    const configuredSelection = process.env.DEVICE_TUI_LOG_DIRECTORY_SELECTION || ''
    if (configuredSelection) return path.resolve(configuredSelection)
    const selected = await dialog.showOpenDialog(mainWindow, {
      title: '选择会话日志保存位置',
      properties: ['openDirectory', 'createDirectory']
    })
    return selected.canceled ? '' : selected.filePaths[0] || ''
  })

  ipcMain.handle('logs:open-directory', async (event): Promise<boolean> => {
    if (event.sender !== mainWindow?.webContents) throw new Error('Untrusted log-directory caller')
    const response = await fetchBackend(backend.config, '/api/v1/settings/session-logs')
    if (response.status !== 200) throw backendError(response)
    const payload = JSON.parse(response.body) as { directory?: unknown }
    if (typeof payload.directory !== 'string' || !path.isAbsolute(payload.directory)) {
      throw new Error('Backend returned an invalid session-log directory')
    }
    const logDirectory = path.resolve(payload.directory)
    await mkdir(logDirectory, { recursive: true })
    if (process.env.DEVICE_TUI_DISABLE_EXTERNAL_OPEN === '1') return true
    const error = await shell.openPath(logDirectory)
    if (error) throw new Error(error)
    return true
  })

  ipcMain.handle('logs:open-session', async (event, sessionId: unknown): Promise<boolean> => {
    if (
      event.sender !== mainWindow?.webContents
      || typeof sessionId !== 'string'
      || !sessionId
      || sessionId.length > 160
    ) {
      throw new Error('Untrusted session-log caller')
    }
    const response = await fetchBackend(
      backend.config,
      `/api/v1/sessions/${encodeURIComponent(sessionId)}/log-path`
    )
    if (response.status !== 200) throw backendError(response)
    const payload = JSON.parse(response.body) as { path?: unknown }
    if (typeof payload.path !== 'string' || !path.isAbsolute(payload.path)) {
      throw new Error('Backend returned an invalid session-log path')
    }
    const logPath = path.resolve(payload.path)
    if (process.env.DEVICE_TUI_DISABLE_EXTERNAL_OPEN === '1') return true
    const error = await shell.openPath(logPath)
    if (error) throw new Error(error)
    return true
  })

  ipcMain.handle(
    'logs:save-copy',
    async (event, request: SessionLogExportRequest): Promise<boolean> => {
      if (event.sender !== mainWindow?.webContents || !mainWindow) {
        throw new Error('Untrusted session-log export caller')
      }
      if (!request || typeof request.content !== 'string' || request.content.length > 2_000_000) {
        throw new Error('Invalid session-log export payload')
      }
      const safeName = String(request.suggestedName || 'session.log')
        .replace(/[^A-Za-z0-9._-]+/g, '_')
        .replace(/^\.+/, '')
        .slice(0, 160) || 'session.log'
      let destination = process.env.DEVICE_TUI_LOG_EXPORT_PATH || ''
      if (!destination) {
        const selected = await dialog.showSaveDialog(mainWindow, {
          title: '保存会话日志副本',
          defaultPath: safeName,
          filters: [{ name: '日志文件', extensions: ['log', 'txt'] }]
        })
        if (selected.canceled || !selected.filePath) return false
        destination = selected.filePath
      }
      const resolved = path.resolve(destination)
      await mkdir(path.dirname(resolved), { recursive: true })
      await writeFile(resolved, request.content, 'utf8')
      return true
    }
  )

  ipcMain.handle('window:set-always-on-top', (event, enabled: unknown): boolean => {
    if (event.sender !== mainWindow?.webContents || !mainWindow || typeof enabled !== 'boolean') {
      throw new Error('Untrusted always-on-top caller')
    }
    mainWindow.setAlwaysOnTop(enabled)
    return mainWindow.isAlwaysOnTop()
  })

  ipcMain.handle(
    'credential:open-profile-session',
    async (event, request: ProfileCredentialRequest): Promise<unknown | null> => {
      if (event.sender !== mainWindow?.webContents) throw new Error('Untrusted credential caller')
      if (!['ssh', 'telnet', 'serial'].includes(request.protocol)) {
        throw new Error('Invalid connection-profile protocol')
      }
      const profileId = encodeURIComponent(request.profileId)
      let result: CredentialDialogResult = request.hasPassword
        ? { action: 'submit', password: '', save: true }
        : await promptForCredential(request, 'connect')
      if (result.action !== 'submit') return null
      let response: BackendResponse
      try {
        if (request.hasPassword) {
          response = await fetchBackend(backend.config, '/api/v1/sessions', 'POST', JSON.stringify({
            device_id: request.profileId,
            kind: request.protocol,
            title: request.profileName
          }))
        } else if (result.save) {
          const saved = await fetchBackend(
            backend.config,
            `/api/v1/connection-profiles/${profileId}/credentials/${request.protocol}`,
            'PUT',
            JSON.stringify({ password: result.password })
          )
          if (saved.status < 200 || saved.status >= 300) throw backendError(saved)
          response = await fetchBackend(backend.config, '/api/v1/sessions', 'POST', JSON.stringify({
            device_id: request.profileId,
            kind: request.protocol,
            title: request.profileName
          }))
        } else {
          response = await fetchBackend(
            backend.config,
            '/api/v1/sessions/with-credential',
            'POST',
            JSON.stringify({
              profile_id: request.profileId,
              kind: request.protocol,
              password: result.password,
              title: request.profileName
            })
          )
        }
      } finally {
        result = { action: 'cancel', password: '', save: false }
      }
      if (response.status < 200 || response.status >= 300) throw backendError(response)
      return JSON.parse(response.body) as unknown
    }
  )

  ipcMain.handle(
    'credential:manage-profile',
    async (event, request: ProfileCredentialRequest): Promise<boolean> => {
      if (event.sender !== mainWindow?.webContents) throw new Error('Untrusted credential caller')
      if (!['ssh', 'telnet', 'serial'].includes(request.protocol)) {
        throw new Error('Invalid connection-profile protocol')
      }
      let result = await promptForCredential(request, 'manage')
      if (result.action === 'cancel') return false
      const profileId = encodeURIComponent(request.profileId)
      const method = result.action === 'remove' ? 'DELETE' : 'PUT'
      const body = result.action === 'submit' ? JSON.stringify({ password: result.password }) : undefined
      let response: BackendResponse
      try {
        response = await fetchBackend(
          backend.config,
          `/api/v1/connection-profiles/${profileId}/credentials/${request.protocol}`,
          method,
          body
        )
      } finally {
        result = { action: 'cancel', password: '', save: false }
      }
      if (response.status < 200 || response.status >= 300) throw backendError(response)
      return true
    }
  )

  if (process.env.ELECTRON_RENDERER_URL) {
    await mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    await mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'))
  }

  const capturePath = process.env.DEVICE_TUI_CAPTURE_PATH
  if (capturePath) {
    setTimeout(async () => {
      if (!mainWindow) return
      let primaryCaptureWritten = false
      const bridgeType = await mainWindow.webContents.executeJavaScript(
        'typeof window.desktopApi',
        true
      )
      console.log(`[renderer] desktopApi=${bridgeType}`)
      const tokenExposed = await mainWindow.webContents.executeJavaScript(
        "window.desktopApi.getRuntimeConfig().then((runtime) => 'token' in runtime)",
        true
      )
      console.log(`[renderer] tokenExposed=${tokenExposed}`)
      const captureSection = process.env.DEVICE_TUI_CAPTURE_SECTION
      if (captureSection) {
        await mainWindow.webContents.executeJavaScript(
          `document.querySelector('button[title="${captureSection}"]')?.click()`,
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 450))
      }
      const captureActionTitle = process.env.DEVICE_TUI_CAPTURE_ACTION_TITLE
      if (captureActionTitle) {
        await mainWindow.webContents.executeJavaScript(
          `document.querySelector('button[title="${captureActionTitle}"]')?.click()`,
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 300))
      }
      if (process.env.DEVICE_TUI_CAPTURE_SUBMIT_ONE_TIME === '1') {
        const promptWindow = BrowserWindow.getFocusedWindow()
        if (promptWindow && promptWindow !== mainWindow) {
          const smokePassword = randomBytes(18).toString('base64url')
          await promptWindow.webContents.executeJavaScript(
            `document.querySelector('#password').value = ${JSON.stringify(smokePassword)}; document.querySelector('#credential-form').requestSubmit()`,
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 1_000))
        }
      }
      const profileRows = await mainWindow.webContents.executeJavaScript(
        "document.querySelectorAll('.profile-list .device-row').length",
        true
      )
      console.log(`[renderer] profileRows=${profileRows}`)
      const sessionTabs = await mainWindow.webContents.executeJavaScript(
        "document.querySelectorAll('.session-tab').length",
        true
      )
      console.log(`[renderer] sessionTabs=${sessionTabs}`)
      if (process.env.DEVICE_TUI_CAPTURE_TERMINAL === '1') {
        await mainWindow.webContents.executeJavaScript(
          "document.querySelector('.empty-workspace .primary-button')?.click()",
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 1_800))
      }
      if (process.env.DEVICE_TUI_CAPTURE_UI_PARITY === '1') {
        const manualUpgradeRoot = path.join(app.getPath('userData'), 'manual-upgrade-share')
        const manualUpgradePackageName = 'manual-fallback-smoke.cc'
        await mkdir(manualUpgradeRoot, { recursive: true })
        await writeFile(
          path.join(manualUpgradeRoot, manualUpgradePackageName),
          Buffer.from('device-tui-manual-upgrade-smoke', 'utf8')
        )
        const uiParity = await mainWindow.webContents.executeJavaScript(
          `(async () => {
            const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
            const checks = {}
            const details = {}
            const setCheck = (name, value, detail = '') => {
              checks[name] = Boolean(value)
              details[name] = detail
            }
            const text = (selector) => document.querySelector(selector)?.textContent?.trim() || ''
            const labels = (selector) => [...document.querySelectorAll(selector)].map((item) => item.textContent?.trim() || '').filter(Boolean)
            const deviceRows = () => [...(document.querySelector('.device-list.device-table-list')?.querySelectorAll(':scope > .device-table-row') || [])]
              .filter((row) => row.isConnected && row.getClientRects().length > 0 && getComputedStyle(row).visibility !== 'hidden')
            const selectedDeviceRow = () => deviceRows().find((row) => row.classList.contains('selected')) || null
            const click = (selector) => {
              const element = document.querySelector(selector)
              if (!element) return false
              element.click()
              return true
            }
            const clickButtonByTitle = (title) => {
              const button = [...document.querySelectorAll('button')].find((item) => item.getAttribute('title') === title)
              if (!button) return false
              button.click()
              return true
            }
            const setValue = (selector, value) => {
              const element = document.querySelector(selector)
              if (!element) return false
              element.value = value
              element.dispatchEvent(new Event('input', { bubbles: true }))
              element.dispatchEvent(new Event('change', { bubbles: true }))
              return true
            }
            const selectFirstOption = (selector) => {
              const element = document.querySelector(selector)
              const option = [...(element?.querySelectorAll('option') || [])].find((item) => item.value)
              if (!element || !option) return ''
              element.value = option.value
              element.dispatchEvent(new Event('input', { bubbles: true }))
              element.dispatchEvent(new Event('change', { bubbles: true }))
              return option.value
            }
            const resetDeviceFilters = async () => {
              setValue('.search-field input[type="search"]', '')
              setValue('.device-filter-panel input[aria-label="CPU"]', '')
              for (const selector of ['.device-filter-panel select[aria-label="领域"]', '.device-filter-panel select[aria-label="状态"]']) {
                const element = document.querySelector(selector)
                if (element) {
                  element.value = ''
                  element.dispatchEvent(new Event('input', { bubbles: true }))
                  element.dispatchEvent(new Event('change', { bubbles: true }))
                }
              }
              const mineButton = document.querySelector('.filter-toggle[aria-pressed="true"]')
              mineButton?.click()
              await sleep(80)
            }
            const openContextMenu = (selector) => {
              const element = document.querySelector(selector)
              if (!element) return false
              const rect = element.getBoundingClientRect()
              element.dispatchEvent(new MouseEvent('contextmenu', {
                bubbles: true,
                cancelable: true,
                clientX: Math.max(8, rect.left + Math.min(24, Math.max(1, rect.width / 2))),
                clientY: Math.max(8, rect.top + Math.min(24, Math.max(1, rect.height / 2)))
              }))
              return true
            }
            const menuHasLabels = (selector, expected) => {
              const body = text(selector)
              return expected.every((label) => body.includes(label))
            }
            const columns = labels('.device-table-header [role="columnheader"]')
            setCheck(
              'legacyDeviceColumns',
              ['序号', '设备', '板类型', 'CPU', 'Slot', '状态'].every((label) => columns.includes(label)),
              columns.join('|')
            )
            const deviceTable = document.querySelector('.device-list.device-table-list')
            setCheck(
              'legacyDeviceColumnsFitWithoutHorizontalScroll',
              Boolean(deviceTable) && deviceTable.scrollWidth <= deviceTable.clientWidth + 1,
              'client=' + (deviceTable?.clientWidth || 0) + ' scroll=' + (deviceTable?.scrollWidth || 0)
            )
            setCheck('deviceRowsVisible', deviceRows().length > 0, String(deviceRows().length))
            const simulatedRows = deviceRows().filter((row) => row.getAttribute('data-device-row-id') === 'SIM-TERMINAL::0000')
            setCheck(
              'legacyInventoryHasTwentyOneRows',
              deviceRows().length === 21,
              String(deviceRows().length)
            )
            setCheck(
              'simulatedTerminalAppearsExactlyOnce',
              simulatedRows.length === 1
                && (simulatedRows[0].textContent || '').includes('模拟终端')
                && (simulatedRows[0].textContent || '').includes('SIM-TERMINAL'),
              simulatedRows.map((row) => row.textContent?.trim() || '').join('|')
            )
            setCheck('deviceSelectionVisible', Boolean(selectedDeviceRow()), selectedDeviceRow()?.querySelector('strong')?.textContent?.trim() || '')
            const navigatorDetail = document.querySelector('.navigator > .navigator-detail')
            setCheck(
              'deviceInspectorVisible',
              Boolean(navigatorDetail)
                && text('.navigator-detail').includes('设备详情')
                && navigatorDetail.querySelectorAll('.property-copy-button').length >= 8,
              String(navigatorDetail?.querySelectorAll('.property-copy-button').length || 0)
            )
            setCheck(
              'deviceDetailSharesLeftNavigator',
              Boolean(navigatorDetail)
                && navigatorDetail.parentElement?.classList.contains('navigator')
                && !navigatorDetail.hasAttribute('hidden'),
              navigatorDetail?.parentElement?.className || ''
            )
            document.querySelector('.navigator-detail-header .icon-button')?.click()
            await sleep(40)
            const detailCollapsedByControl = document.querySelector('.navigator-detail')?.getAttribute('data-collapsed') === 'true'
              && localStorage.getItem('device-tui.desktop-v2.navigator-detail-collapsed') === '1'
            document.querySelector('.navigator-detail-header .icon-button')?.click()
            await sleep(40)
            setCheck(
              'navigatorDetailCollapsePersists',
              detailCollapsedByControl
                && document.querySelector('.navigator-detail')?.getAttribute('data-collapsed') === 'false'
                && localStorage.getItem('device-tui.desktop-v2.navigator-detail-collapsed') === '0',
              'collapsed=' + detailCollapsedByControl
                + ' restored=' + (document.querySelector('.navigator-detail')?.getAttribute('data-collapsed') || '')
            )
            const emptySessionWorkspace = document.querySelector('.session-workspace')
            const collapsedCommandWorkspace = document.querySelector('.command-workspace:not(.open)')
            const workspaceStage = document.querySelector('.workspace-stage')
            const emptySessionRect = emptySessionWorkspace?.getBoundingClientRect()
            const collapsedCommandRect = collapsedCommandWorkspace?.getBoundingClientRect()
            const workspaceStageRect = workspaceStage?.getBoundingClientRect()
            setCheck(
              'emptyWorkspaceCommandBarHasNoDeadClickRegion',
              Boolean(emptySessionRect)
                && Boolean(collapsedCommandRect)
                && Boolean(workspaceStageRect)
                && collapsedCommandRect.height <= 37
                && Math.abs(emptySessionRect.bottom - collapsedCommandRect.top) <= 1
                && Math.abs(collapsedCommandRect.bottom - workspaceStageRect.bottom) <= 1,
              'sessionBottom=' + (emptySessionRect?.bottom || 0)
                + ' command=' + (collapsedCommandRect?.top || 0) + '-' + (collapsedCommandRect?.bottom || 0)
                + ' height=' + (collapsedCommandRect?.height || 0)
                + ' stageBottom=' + (workspaceStageRect?.bottom || 0)
            )
            setCheck(
              'deviceSummaryMatchesVisibleRows',
              Number(document.querySelector('.summary-row b')?.textContent || -1) === deviceRows().length,
              (document.querySelector('.summary-row')?.textContent?.trim() || '') + ' rows=' + deviceRows().length
            )
            setCheck(
              'legacyStatusBucketsClassifyPipelineBeforeOccupied',
              Number(document.querySelector('.summary-row .idle b')?.textContent || -1) === 10
                && Number(document.querySelector('.summary-row .occupied b')?.textContent || -1) === 3
                && Number(document.querySelector('.summary-row .pipeline b')?.textContent || -1) === 2
                && Number(document.querySelector('.summary-row .other b')?.textContent || -1) === 6,
              document.querySelector('.summary-row')?.textContent?.trim() || ''
            )

            const initialRowCount = deviceRows().length
            const selectedDeviceId = selectedDeviceRow()?.getAttribute('data-device-row-id') || deviceRows()[0]?.getAttribute('data-device-row-id') || ''
            const mineToggle = document.querySelector('.filter-toggle')
            mineToggle?.click()
            await sleep(80)
            setCheck(
              'ownedDeviceCountUsesUniqueIdsWhileFilterKeepsBoardRows',
              (mineToggle?.textContent?.trim() || '') === '我的 4'
                && deviceRows().length === 7,
              (mineToggle?.textContent?.trim() || '') + ' rows=' + deviceRows().length
            )
            mineToggle?.click()
            await sleep(80)
            deviceRows().find((row) => row.getAttribute('data-device-row-id') === selectedDeviceId)?.click()
            setValue('.search-field input[type="search"]', selectedDeviceId)
            await sleep(120)
            setCheck(
              'deviceKeywordSearchFiltersAndKeepsSelection',
              Boolean(selectedDeviceId) &&
                deviceRows().length > 0 &&
                deviceRows().length <= initialRowCount &&
                Boolean(selectedDeviceRow()),
              selectedDeviceId + ' rows=' + deviceRows().length
            )
            await resetDeviceFilters()
            const domainValue = selectFirstOption('.device-filter-panel select[aria-label="领域"]')
            await sleep(120)
            setCheck(
              'deviceDomainFilterUpdatesRowsAndClearAction',
              !domainValue || (deviceRows().length > 0 && Boolean(document.querySelector('.summary-clear'))),
              domainValue + ' rows=' + deviceRows().length
            )
            await resetDeviceFilters()
            const statusValue = selectFirstOption('.device-filter-panel select[aria-label="状态"]')
            await sleep(120)
            setCheck(
              'deviceStatusFilterUpdatesRowsAndClearAction',
              !statusValue || (deviceRows().length > 0 && Boolean(document.querySelector('.summary-clear'))),
              statusValue + ' rows=' + deviceRows().length
            )
            await resetDeviceFilters()
            const cpuValue = deviceRows().flatMap((row) => [...row.querySelectorAll('.mono')])
              .map((item) => item.textContent?.trim() || '')
              .find((value) => value && value !== '—') || ''
            setValue('.device-filter-panel input[aria-label="CPU"]', cpuValue)
            await sleep(120)
            setCheck(
              'deviceCpuFilterUpdatesRowsAndClearAction',
              !cpuValue || (deviceRows().length > 0 && Boolean(document.querySelector('.summary-clear'))),
              cpuValue + ' rows=' + deviceRows().length
            )
            document.querySelector('.summary-clear')?.click()
            for (let attempt = 0; attempt < 30; attempt += 1) {
              const rowCount = deviceRows().length
              const summaryTotal = Number(document.querySelector('.summary-row b')?.textContent || -1)
              if (rowCount > 0 && summaryTotal === rowCount && !document.querySelector('.summary-clear')) break
              await sleep(100)
            }
            setCheck(
              'deviceClearFiltersRestoresAllRows',
              deviceRows().length === initialRowCount &&
                Number(document.querySelector('.summary-row b')?.textContent || -1) === deviceRows().length &&
                !document.querySelector('.summary-clear'),
              (document.querySelector('.summary-row')?.textContent?.trim() || '') + ' rows=' + deviceRows().length + ' initial=' + initialRowCount
            )
            const simulatedRow = deviceRows().find((row) => row.getAttribute('data-device-row-id') === 'SIM-TERMINAL::0000')
            simulatedRow?.click()
            await sleep(60)
            const simulatedProtocolButtons = [...document.querySelectorAll('.connection-actions button')]
            const simulatedOnlyButton = simulatedProtocolButtons.find((button) => (button.textContent || '').includes('模拟'))
            const unavailableSimulatedProtocols = simulatedProtocolButtons.filter((button) =>
              ['SSH', 'Telnet', '串口'].some((label) => (button.textContent || '').includes(label))
            )
            setCheck(
              'simulatedTerminalOnlyOffersSimulatedSession',
              Boolean(simulatedRow)
                && simulatedProtocolButtons.length === 4
                && Boolean(simulatedOnlyButton)
                && !simulatedOnlyButton?.disabled
                && unavailableSimulatedProtocols.length === 3
                && unavailableSimulatedProtocols.every((button) => button.disabled && (button.getAttribute('title') || '').includes('模拟终端不支持')),
              simulatedProtocolButtons.map((button) => (button.textContent?.trim() || '') + ':' + button.disabled + ':' + (button.getAttribute('title') || '')).join('|')
            )
            if (simulatedRow) {
              openContextMenu('[data-device-row-id="SIM-TERMINAL::0000"]')
              await sleep(40)
            }
            const simulatedMenuButtons = [...document.querySelectorAll('.device-context-menu button')]
            const simulatedDeviceActions = simulatedMenuButtons.filter((button) => ['占用', '掉电'].includes(button.textContent?.trim() || ''))
            setCheck(
              'simulatedTerminalDeviceActionsAreDisabledWithReason',
              simulatedDeviceActions.length === 2
                && simulatedDeviceActions.every((button) => button.disabled && (button.getAttribute('title') || '').includes('模拟终端不支持')),
              simulatedDeviceActions.map((button) => (button.textContent?.trim() || '') + ':' + button.disabled + ':' + (button.getAttribute('title') || '')).join('|')
            )
            document.body.click()
            deviceRows().find((row) => row.getAttribute('data-device-row-id') === selectedDeviceId)?.click()
            await sleep(40)
            const disabledConnectionButtons = [...document.querySelectorAll('.connection-actions button:disabled')]
              .filter((button) => ['SSH', 'Telnet', '串口'].some((label) => (button.textContent || '').includes(label)))
            setCheck(
              'disabledConnectionActionsExplainReason',
              disabledConnectionButtons.length === 0 || disabledConnectionButtons.every((button) => Boolean(button.getAttribute('title'))),
              disabledConnectionButtons.map((button) => (button.textContent?.trim() || '') + ':' + (button.getAttribute('title') || '')).join('|')
            )

            const beforeTheme = document.documentElement.dataset.theme || 'dark'
            click('.theme-toggle')
            await sleep(80)
            const afterTheme = document.documentElement.dataset.theme || 'dark'
            setCheck('themeToggleChangesRendererTheme', beforeTheme !== afterTheme && ['dark', 'light'].includes(afterTheme), beforeTheme + '->' + afterTheme)
            click('.theme-toggle')
            await sleep(40)
            clickButtonByTitle('窗口置顶')
            await sleep(80)
            const alwaysOnTopButton = document.querySelector('.always-on-top-toggle')
            setCheck(
              'alwaysOnTopTogglePersistsState',
              alwaysOnTopButton?.getAttribute('aria-pressed') === 'true'
                && localStorage.getItem('device-tui.desktop-v2.always-on-top') === '1',
              (alwaysOnTopButton?.getAttribute('title') || '') + ':' + (alwaysOnTopButton?.getAttribute('aria-pressed') || '')
            )

            clickButtonByTitle('设置')
            for (let attempt = 0; attempt < 30 && !document.querySelector('.settings-panel'); attempt += 1) {
              await sleep(50)
            }
            setCheck(
              'settingsPanelExposesLegacyControls',
              Boolean(document.querySelector('.settings-panel[role="dialog"]'))
                && ['工作台设置', '会话页签布局', '右侧会话栏默认折叠', '终端字体大小', '会话日志', '保存目录', '单个日志分卷大小']
                  .every((label) => text('.settings-panel').includes(label)),
              text('.settings-panel')
            )
            const sideLayoutButton = [...document.querySelectorAll('.settings-panel button')]
              .find((button) => button.textContent?.trim() === '右侧')
            sideLayoutButton?.click()
            await sleep(60)
            setCheck(
              'sessionTabSideLayoutAppliesAndPersists',
              document.querySelector('.session-workspace')?.getAttribute('data-tab-layout') === 'side'
                && localStorage.getItem('device-tui.desktop-v2.session-tab-layout') === 'side',
              document.querySelector('.session-workspace')?.getAttribute('data-tab-layout') || ''
            )
            const collapseSetting = [...document.querySelectorAll('.settings-panel label')]
              .find((label) => (label.textContent || '').includes('右侧会话栏默认折叠'))
              ?.querySelector('input[type="checkbox"]')
            if (collapseSetting && !collapseSetting.checked) collapseSetting.click()
            await sleep(60)
            setCheck(
              'sessionTabCollapsedPreferenceAppliesAndPersists',
              document.querySelector('.session-workspace')?.getAttribute('data-tab-collapsed') === 'true'
                && localStorage.getItem('device-tui.desktop-v2.session-tab-rail-collapsed') === '1',
              document.querySelector('.session-workspace')?.getAttribute('data-tab-collapsed') || ''
            )
            if (document.querySelector('.settings-panel input[type="range"]')) {
              setValue('.settings-panel input[type="range"]', '15')
            }
            await sleep(80)
            setCheck(
              'settingsTerminalFontAppliesImmediately',
              localStorage.getItem('device-tui.desktop-v2.terminal-font-size') === '15',
              localStorage.getItem('device-tui.desktop-v2.terminal-font-size') || ''
            )
            const chooseLogDirectory = [...document.querySelectorAll('.directory-control button')]
              .find((button) => button.textContent?.trim() === '选择')
            chooseLogDirectory?.click()
            await sleep(120)
            setValue('.settings-panel input[type="number"]', '7')
            const saveLogSettings = [...document.querySelectorAll('.settings-panel button')]
              .find((button) => (button.textContent || '').includes('保存日志设置'))
            saveLogSettings?.click()
            for (let attempt = 0; attempt < 40; attempt += 1) {
              if (text('.settings-panel').includes('日志设置已保存')) break
              await sleep(100)
            }
            const logSettingsResponse = await window.desktopApi.request({ path: '/api/v1/settings/session-logs' })
            let savedLogSettings = { rotate_size_mb: undefined, directory: undefined }
            try {
              savedLogSettings = JSON.parse(logSettingsResponse.body)
            } catch {
              savedLogSettings = {}
            }
            setCheck(
              'settingsLogDirectoryAndRotationPersist',
              logSettingsResponse.status === 200
                && savedLogSettings.rotate_size_mb === 7
                && String(savedLogSettings.directory || '').includes('configured-session-logs'),
              logSettingsResponse.body
            )
            clickButtonByTitle('关闭设置')
            await sleep(60)
            clickButtonByTitle('帮助')
            await sleep(60)
            setCheck(
              'helpPanelIsFunctional',
              Boolean(document.querySelector('.help-panel[role="dialog"]'))
                && text('.help-panel').includes('操作帮助')
                && text('.help-panel').includes('安全边界'),
              text('.help-panel')
            )
            clickButtonByTitle('关闭帮助')
            await sleep(40)

            setCheck(
              'deviceContextMenu',
              openContextMenu('.device-list.device-table-list > .device-table-row') && await sleep(40).then(() => menuHasLabels('.device-context-menu', ['复制设备行', '复制 SSH IP', '复制 Telnet IP', '复制串口 IP', '复制连接信息', '占用', '掉电', '打开设备管理口', '打开 Linux 后台', '打开串口'])),
              text('.device-context-menu')
            )
            document.querySelector('.workspace-stage')?.click()
            await sleep(40)

            if (!document.querySelector('.session-tab')) {
              const simulatedButton = [...document.querySelectorAll('button')].find((button) => {
                const body = button.textContent?.trim() || ''
                return body.includes('创建首个终端') || body === '模拟' || body.endsWith('模拟')
              })
              simulatedButton?.click()
              for (let attempt = 0; attempt < 60 && !document.querySelector('.session-tab'); attempt += 1) {
                await sleep(100)
              }
            }
            setCheck('simulatedSessionTabVisible', document.querySelectorAll('.session-tab').length > 0, String(document.querySelectorAll('.session-tab').length))
            const simulatedSessionResponse = await window.desktopApi.request({ path: '/api/v1/sessions' })
            let simulatedSessions = []
            try {
              simulatedSessions = JSON.parse(simulatedSessionResponse.body).sessions || []
            } catch {
              simulatedSessions = []
            }
            setCheck(
              'simulatedSessionUsesCanonicalDevice',
              simulatedSessionResponse.status === 200
                && simulatedSessions.some((session) => session.kind === 'simulated' && session.device_id === 'SIM-TERMINAL')
                && !simulatedSessions.some((session) => session.kind === 'simulated' && session.device_id !== 'SIM-TERMINAL'),
              simulatedSessionResponse.body
            )
            const collapsedTabs = [...document.querySelectorAll('.session-tab')]
            const collapsedRail = document.querySelector('.session-tabs')
            const collapsedWidth = collapsedRail?.getBoundingClientRect().width || 0
            const collapsedSidebarRect = document.querySelector('.session-sidebar')?.getBoundingClientRect()
            const collapsedWorkspaceRect = document.querySelector('.workspace-stage')?.getBoundingClientRect()
            const expandRailButton = document.querySelector('.session-rail-toggle[title="展开右侧会话栏"]')
            expandRailButton?.click()
            await sleep(60)
            const expandedByControl = document.querySelector('.session-workspace')?.getAttribute('data-tab-collapsed') === 'false'
            const managerGroups = [...document.querySelectorAll('.session-device-group')]
            const managerGroupHeaders = [...document.querySelectorAll('.session-device-group-header')]
            const managerSearchRect = document.querySelector('.session-manager-search-row')?.getBoundingClientRect()
            const firstManagerGroupRect = managerGroups[0]?.getBoundingClientRect()
            setCheck(
              'sessionManagerTreeStartsBelowSearch',
              Boolean(managerSearchRect)
                && Boolean(firstManagerGroupRect)
                && firstManagerGroupRect.top >= managerSearchRect.bottom - 1
                && firstManagerGroupRect.top <= managerSearchRect.bottom + 12,
              'searchBottom=' + (managerSearchRect?.bottom || 0)
                + ' firstGroupTop=' + (firstManagerGroupRect?.top || 0)
            )
            const rightSessionSidebar = document.querySelector('.app-shell > .session-sidebar')
            const rightSessionManager = rightSessionSidebar?.querySelector(':scope > .session-manager')
            const rightSessionRect = rightSessionSidebar?.getBoundingClientRect()
            const appShellRect = document.querySelector('.app-shell')?.getBoundingClientRect()
            setCheck(
              'sessionManagerLivesInRightSidebar',
              Boolean(rightSessionManager)
                && !document.querySelector('.session-workspace .session-manager')
                && Math.abs((rightSessionRect?.right || 0) - (appShellRect?.right || 0)) <= 1,
              'parent=' + (rightSessionManager?.parentElement?.className || '')
                + ' right=' + (rightSessionRect?.right || 0) + '/' + (appShellRect?.right || 0)
            )
            setCheck(
              'hierarchicalSessionManagerGroupsSessionsByDevice',
              Boolean(document.querySelector('.session-manager-header'))
                && managerGroups.length === 1
                && managerGroupHeaders[0]?.getAttribute('data-device-group-id') === 'SIM-TERMINAL'
                && managerGroups[0]?.querySelectorAll('.session-manager-session').length === 1,
              'groups=' + managerGroups.length + ' sessions=' + document.querySelectorAll('.session-manager-session').length
            )
            const managerWidthBefore = Number(document.querySelector('.session-manager')?.getAttribute('data-manager-width') || 0)
            document.querySelector('.session-manager-resize-handle')?.dispatchEvent(new KeyboardEvent('keydown', {
              key: 'ArrowLeft',
              bubbles: true,
              cancelable: true
            }))
            await sleep(50)
            const managerWidthAfter = Number(document.querySelector('.session-manager')?.getAttribute('data-manager-width') || 0)
            setCheck(
              'sessionManagerWidthResizePersists',
              managerWidthAfter === managerWidthBefore + 10
                && localStorage.getItem('device-tui.desktop-v2.session-manager-width') === String(managerWidthAfter),
              managerWidthBefore + '->' + managerWidthAfter
            )
            setValue('.session-manager-search-row input', 'SIM-TERMINAL')
            await sleep(60)
            const matchingManagerGroups = document.querySelectorAll('.session-device-group').length
            setValue('.session-manager-search-row input', 'no-such-session')
            await sleep(60)
            const managerEmptyForMissingQuery = text('.session-manager-tree').includes('没有匹配的设备或会话')
            setValue('.session-manager-search-row input', '')
            await sleep(60)
            setCheck(
              'sessionManagerSearchFiltersDevicesAndSessions',
              matchingManagerGroups === 1 && managerEmptyForMissingQuery,
              'matching=' + matchingManagerGroups + ' empty=' + managerEmptyForMissingQuery
            )
            setCheck(
              'sessionManagerDeviceContextActions',
              openContextMenu('.session-device-group-header') && await sleep(40).then(() => menuHasLabels('.session-device-context-menu', [
                '关闭当前设备会话',
                '关闭左侧设备会话',
                '关闭右侧设备会话',
                '关闭其他设备会话',
                '关闭所有设备会话',
                '定位到设备列表',
                '打开设备管理口',
                '打开 Linux 后台',
                '打开串口'
              ])),
              text('.session-device-context-menu')
            )
            document.querySelector('.workspace-stage')?.click()
            await sleep(40)
            document.querySelector('.session-manager-expand-all[title="全部收起"]')?.click()
            await sleep(60)
            let collapsedManagerGroups = []
            try {
              collapsedManagerGroups = JSON.parse(localStorage.getItem('device-tui.desktop-v2.session-manager-collapsed-groups') || '[]')
            } catch {
              collapsedManagerGroups = []
            }
            setCheck(
              'sessionManagerGroupCollapseStatePersists',
              collapsedManagerGroups.includes('SIM-TERMINAL')
                && document.querySelectorAll('.session-manager-session').length === 0,
              JSON.stringify(collapsedManagerGroups)
            )
            document.querySelector('.session-rail-toggle[title="折叠右侧会话栏"]')?.click()
            await sleep(60)
            setCheck(
              'collapsedSessionRailRemainsAccessibleAndRestorable',
              collapsedWidth <= 44
                && collapsedTabs.length > 0
                && collapsedTabs.every((tab) => Boolean(tab.getAttribute('title')) && Boolean(tab.querySelector('[role="tab"]')?.getAttribute('aria-label')))
                && (collapsedSidebarRect?.left || 0) >= (collapsedWorkspaceRect?.right || 0) - 1
                && expandedByControl
                && document.querySelector('.session-workspace')?.getAttribute('data-tab-collapsed') === 'true',
              'width=' + collapsedWidth + ' tabs=' + collapsedTabs.length + ' expanded=' + expandedByControl
                + ' edge=' + (collapsedWorkspaceRect?.right || 0) + '/' + (collapsedSidebarRect?.left || 0)
            )
            setCheck(
              'sessionContextMenu',
              openContextMenu('.session-tab') && await sleep(40).then(() => menuHasLabels('.session-context-menu', ['关闭当前页签', '关闭左侧页签', '关闭右侧页签', '关闭其他页签', '关闭所有页签'])),
              text('.session-context-menu')
            )
            document.querySelector('.workspace-stage')?.click()
            await sleep(40)
            setCheck(
              'terminalContextMenu',
              openContextMenu('.terminal-host') && await sleep(40).then(() => menuHasLabels('.terminal-context-menu', ['复制选中文本', '复制全部', '粘贴', '清屏', '搜索终端', '自动响应', '查看会话日志', '断开连接', '重新连接'])),
              text('.terminal-context-menu')
            )
            document.querySelector('.workspace-stage')?.click()
            await sleep(40)

            clickButtonByTitle('打开当前会话自动响应')
            for (let attempt = 0; attempt < 30 && !document.querySelector('.automation-workspace'); attempt += 1) {
              await sleep(50)
            }
            setCheck(
              'terminalAutomationQuickAccessTargetsCurrentSession',
              Boolean(document.querySelector('.automation-workspace[role="dialog"]'))
                && text('.automation-workspace').includes('终端自动化')
                && Boolean(document.querySelector('.automation-session-status')),
              text('.automation-header')
            )

            document.querySelector('.automation-new-button')?.click()
            await sleep(60)
            setValue('[data-testid="automation-name"]', '分步烟测')
            setValue('[data-testid="automation-trigger"]', 'manual')
            document.querySelector('[data-testid="automation-mode-steps"]')?.click()
            await sleep(60)
            setValue('.automation-step-response-text', 'display version')
            const stepAppendEnter = document.querySelector('.automation-step-response-append')
            if (stepAppendEnter && !stepAppendEnter.checked) stepAppendEnter.click()
            const versionCountBeforeStepRun = [...document.querySelectorAll('.xterm-rows')]
              .map((rows) => rows.textContent || '').join('').split('SimOS V1.0').length - 1
            document.querySelector('[data-testid="automation-save"]')?.click()
            for (let attempt = 0; attempt < 40; attempt += 1) {
              if ([...document.querySelectorAll('.automation-rule-row strong')].some((node) => node.textContent?.trim() === '分步烟测')) break
              await sleep(100)
            }
            const stepWorkspaceResponse = await window.desktopApi.request({ path: '/api/v1/automation/workspace' })
            let stepSmokeRule = null
            try {
              stepSmokeRule = JSON.parse(stepWorkspaceResponse.body).rules
                ?.find((record) => record.rule?.name === '分步烟测') || null
            } catch {
              stepSmokeRule = null
            }
            document.querySelector('[data-testid="automation-run"]')?.click()
            let versionCountAfterStepRun = versionCountBeforeStepRun
            for (let attempt = 0; attempt < 50; attempt += 1) {
              versionCountAfterStepRun = [...document.querySelectorAll('.xterm-rows')]
                .map((rows) => rows.textContent || '').join('').split('SimOS V1.0').length - 1
              if (versionCountAfterStepRun > versionCountBeforeStepRun) break
              await sleep(100)
            }
            setCheck(
              'advancedAutomationStepEditorPersistsAndRuns',
              stepWorkspaceResponse.status === 200
                && stepSmokeRule?.rule?.steps?.[0]?.response_texts?.[0] === 'display version'
                && stepSmokeRule?.rule?.steps?.[0]?.response_append_enters?.[0] === true
                && versionCountAfterStepRun > versionCountBeforeStepRun,
              stepWorkspaceResponse.body + ' versions=' + versionCountBeforeStepRun + '->' + versionCountAfterStepRun
            )

            document.querySelector('.automation-new-button')?.click()
            await sleep(60)
            setValue('[data-testid="automation-name"]', '动作流烟测')
            setValue('[data-testid="automation-trigger"]', 'manual')
            document.querySelector('[data-testid="automation-mode-actions"]')?.click()
            await sleep(60)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-send .automation-action-send-text', 'display version')
            await sleep(30)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-send .automation-action-send-target', 'next')
            await sleep(30)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-send .automation-action-send-delay', '25')
            await sleep(30)
            const rootSendAppend = document.querySelector('.automation-action-list[data-depth="0"] > .automation-action-card.kind-send .automation-action-send-append')
            if (rootSendAppend && !rootSendAppend.checked) rootSendAppend.click()
            await sleep(50)
            document.querySelector('.automation-action-list[data-depth="0"] > .automation-action-add button[data-action-kind="loop"]')?.click()
            await sleep(40)
            document.querySelector('.automation-action-list[data-depth="0"] > .automation-action-add button[data-action-kind="condition"]')?.click()
            await sleep(40)
            document.querySelector('.automation-action-list[data-depth="0"] > .automation-action-add button[data-action-kind="exit"]')?.click()
            await sleep(60)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-loop .automation-action-loop-repeat', '2')
            await sleep(30)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-loop .automation-action-loop-interval', '15')
            await sleep(30)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-loop .automation-action-send-text', 'display version')
            await sleep(30)
            const loopSendAppend = document.querySelector('.automation-action-list[data-depth="0"] > .automation-action-card.kind-loop .automation-action-send-append')
            if (loopSendAppend && !loopSendAppend.checked) loopSendAppend.click()
            await sleep(50)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-condition .automation-action-condition-pattern', 'SimOS')
            await sleep(30)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-condition .automation-action-condition-match', 'contains')
            await sleep(30)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-condition .automation-action-send-text', 'display version')
            await sleep(30)
            const conditionSendAppend = document.querySelector('.automation-action-list[data-depth="0"] > .automation-action-card.kind-condition .automation-action-send-append')
            if (conditionSendAppend && !conditionSendAppend.checked) conditionSendAppend.click()
            await sleep(50)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-exit .automation-action-exit-pattern', 'never-match')
            await sleep(30)
            setValue('.automation-action-list[data-depth="0"] > .automation-action-card.kind-exit .automation-action-exit-scope', 'rule')
            await sleep(50)
            document.querySelector('[data-testid="automation-save"]')?.click()
            for (let attempt = 0; attempt < 40; attempt += 1) {
              if ([...document.querySelectorAll('.automation-rule-row strong')].some((node) => node.textContent?.trim() === '动作流烟测')) break
              await sleep(100)
            }
            const actionWorkspaceResponse = await window.desktopApi.request({ path: '/api/v1/automation/workspace' })
            let actionSmokeRule = null
            try {
              actionSmokeRule = JSON.parse(actionWorkspaceResponse.body).rules
                ?.find((record) => record.rule?.name === '动作流烟测') || null
            } catch {
              actionSmokeRule = null
            }
            const actionVersionCountBefore = [...document.querySelectorAll('.xterm-rows')]
              .map((rows) => rows.textContent || '').join('').split('SimOS V1.0').length - 1
            document.querySelector('[data-testid="automation-run"]')?.click()
            let actionVersionCountAfter = actionVersionCountBefore
            for (let attempt = 0; attempt < 50; attempt += 1) {
              actionVersionCountAfter = [...document.querySelectorAll('.xterm-rows')]
                .map((rows) => rows.textContent || '').join('').split('SimOS V1.0').length - 1
              if (actionVersionCountAfter > actionVersionCountBefore) break
              await sleep(100)
            }
            const smokeActions = actionSmokeRule?.rule?.actions || []
            const actionSmokeAssertions = {
              status: actionWorkspaceResponse.status === 200,
              rootSend: smokeActions[0]?.kind === 'send',
              target: smokeActions[0]?.target === 'next',
              delay: smokeActions[0]?.delay_ms === 25,
              appendEnter: smokeActions[0]?.append_enter === true,
              loop: smokeActions[1]?.kind === 'loop',
              loopCount: smokeActions[1]?.repeat_count === 2,
              loopInterval: smokeActions[1]?.interval_ms === 15,
              loopChild: smokeActions[1]?.actions?.[0]?.text === 'display version',
              condition: smokeActions[2]?.kind === 'condition',
              conditionPattern: smokeActions[2]?.condition_pattern === 'SimOS',
              conditionChild: smokeActions[2]?.actions?.[0]?.text === 'display version',
              exit: smokeActions[3]?.kind === 'exit',
              exitPattern: smokeActions[3]?.exit_pattern === 'never-match',
              exitScope: smokeActions[3]?.exit_scope === 'rule',
              executed: actionVersionCountAfter > actionVersionCountBefore
            }
            setCheck(
              'advancedAutomationActionEditorPersistsNestedFlow',
              Object.values(actionSmokeAssertions).every(Boolean),
              JSON.stringify(actionSmokeAssertions)
                + ' versions=' + actionVersionCountBefore + '->' + actionVersionCountAfter
            )
            document.querySelector('button[aria-label="关闭自动化面板"]')?.click()
            await sleep(60)

            const quickSendName = '快捷烟测'
            const editedQuickSendName = '快捷烟测-已编辑'
            click('[data-testid="quick-send-add"]')
            for (let attempt = 0; attempt < 30 && !document.querySelector('.quick-send-dialog'); attempt += 1) {
              await sleep(50)
            }
            setValue('[data-testid="quick-send-name"]', quickSendName)
            setValue('[data-testid="quick-send-response"]', 'display version')
            const appendEnterOption = [...document.querySelectorAll('.quick-send-option')]
              .find((label) => (label.textContent || '').includes('发送后追加 Enter'))
              ?.querySelector('input[type="checkbox"]')
            if (appendEnterOption && !appendEnterOption.checked) appendEnterOption.click()
            document.querySelector('[data-testid="quick-send-save"]')?.click()
            for (let attempt = 0; attempt < 40; attempt += 1) {
              if ([...document.querySelectorAll('.quick-send-button')].some((button) => button.textContent?.trim() === quickSendName)) break
              await sleep(100)
            }
            const createdQuickSendButton = [...document.querySelectorAll('.quick-send-button')]
              .find((button) => button.textContent?.trim() === quickSendName)
            const createdQuickSendId = createdQuickSendButton?.getAttribute('data-quick-send-id') || ''
            const terminalTextBeforeQuickSend = [...document.querySelectorAll('.xterm-rows')]
              .map((rows) => rows.textContent || '').join('\\n')
            createdQuickSendButton?.click()
            let terminalTextAfterQuickSend = terminalTextBeforeQuickSend
            for (let attempt = 0; attempt < 50; attempt += 1) {
              terminalTextAfterQuickSend = [...document.querySelectorAll('.xterm-rows')]
                .map((rows) => rows.textContent || '').join('\\n')
              if (terminalTextAfterQuickSend.includes('SimOS V1.0') && terminalTextAfterQuickSend.length > terminalTextBeforeQuickSend.length) break
              await sleep(100)
            }
            setCheck(
              'quickSendCreateAndDispatchUsesActiveSession',
              Boolean(createdQuickSendId)
                && terminalTextAfterQuickSend.includes('SimOS V1.0')
                && terminalTextAfterQuickSend.length > terminalTextBeforeQuickSend.length,
              'id=' + createdQuickSendId + ' terminal=' + terminalTextAfterQuickSend.slice(-180)
            )

            const quickSendEditButton = [...document.querySelectorAll('.quick-send-edit')]
              .find((button) => button.getAttribute('aria-label') === '编辑 ' + quickSendName)
            quickSendEditButton?.click()
            for (let attempt = 0; attempt < 30 && !document.querySelector('.quick-send-dialog'); attempt += 1) {
              await sleep(50)
            }
            setValue('[data-testid="quick-send-name"]', editedQuickSendName)
            document.querySelector('[data-testid="quick-send-save"]')?.click()
            for (let attempt = 0; attempt < 40; attempt += 1) {
              if ([...document.querySelectorAll('.quick-send-button')].some((button) => button.textContent?.trim() === editedQuickSendName)) break
              await sleep(100)
            }
            const editedWorkspaceResponse = await window.desktopApi.request({ path: '/api/v1/automation/workspace' })
            let editedQuickSendButtons = []
            try {
              editedQuickSendButtons = JSON.parse(editedWorkspaceResponse.body).quick_send_buttons || []
            } catch {
              editedQuickSendButtons = []
            }
            setCheck(
              'quickSendEditPersistsThroughPythonWorkspace',
              editedWorkspaceResponse.status === 200
                && editedQuickSendButtons.some((button) => button.id === createdQuickSendId && button.name === editedQuickSendName),
              editedWorkspaceResponse.body
            )

            clickButtonByTitle('收起终端快捷工具栏')
            await sleep(60)
            const quickToolbarCollapsed = localStorage.getItem('device-tui.desktop-v2.quick-toolbar-collapsed') === '1'
              && Boolean(document.querySelector('.quick-toolbar-restore'))
              && !document.querySelector('[data-testid="terminal-quick-toolbar"]')
            clickButtonByTitle('展开终端快捷工具栏')
            await sleep(60)
            setCheck(
              'quickToolbarCollapseAndRestorePersist',
              quickToolbarCollapsed
                && localStorage.getItem('device-tui.desktop-v2.quick-toolbar-collapsed') === '0'
                && Boolean(document.querySelector('[data-testid="terminal-quick-toolbar"]')),
              'collapsed=' + quickToolbarCollapsed + ' state=' + localStorage.getItem('device-tui.desktop-v2.quick-toolbar-collapsed')
            )

            const editedQuickSendButton = [...document.querySelectorAll('.quick-send-edit')]
              .find((button) => button.getAttribute('aria-label') === '编辑 ' + editedQuickSendName)
            editedQuickSendButton?.click()
            await sleep(60)
            const originalConfirm = window.confirm
            window.confirm = () => true
            const quickSendDeleteButton = [...document.querySelectorAll('.quick-send-dialog button')]
              .find((button) => button.textContent?.trim() === '删除')
            quickSendDeleteButton?.click()
            window.confirm = originalConfirm
            for (let attempt = 0; attempt < 40; attempt += 1) {
              if (![...document.querySelectorAll('.quick-send-button')].some((button) => button.getAttribute('data-quick-send-id') === createdQuickSendId)) break
              await sleep(100)
            }
            const deletedWorkspaceResponse = await window.desktopApi.request({ path: '/api/v1/automation/workspace' })
            let remainingQuickSendButtons = []
            try {
              remainingQuickSendButtons = JSON.parse(deletedWorkspaceResponse.body).quick_send_buttons || []
            } catch {
              remainingQuickSendButtons = []
            }
            setCheck(
              'quickSendDeleteLeavesPersistentDefault',
              deletedWorkspaceResponse.status === 200
                && !remainingQuickSendButtons.some((button) => button.id === createdQuickSendId)
                && remainingQuickSendButtons.some((button) => button.response_text === 'Ctrl+B'),
              deletedWorkspaceResponse.body
            )

            clickButtonByTitle('文件传输')
            for (let attempt = 0; attempt < 30 && !document.querySelector('.transfer-workspace'); attempt += 1) {
              await sleep(50)
            }
            setValue('[data-testid="transfer-root"]', ${JSON.stringify(manualUpgradeRoot)})
            document.querySelector('[data-testid="transfer-settings"]')?.requestSubmit()
            await sleep(700)
            const initialClientCommand = text('[data-testid="transfer-client-command"]')
            const startFileServiceButton = [...document.querySelectorAll('.transfer-settings-card button')]
              .find((button) => button.textContent?.trim() === '启动服务')
            startFileServiceButton?.click()
            for (let attempt = 0; attempt < 50; attempt += 1) {
              if (document.querySelector('.service-state[data-running="true"]')) break
              await sleep(100)
            }
            for (let attempt = 0; attempt < 30; attempt += 1) {
              if (document.querySelector('[data-testid="transfer-service-log"] pre')?.textContent?.includes('服务已启动')) break
              await sleep(100)
            }
            const runningClientCommand = text('[data-testid="transfer-client-command"]')
            setCheck(
              'fileServiceLogAndClientCommandAreVisibleAndSafe',
              Boolean(startFileServiceButton)
                && Boolean(document.querySelector('.service-state[data-running="true"]'))
                && text('[data-testid="transfer-service-log"] pre').includes('服务已启动')
                && runningClientCommand.includes('ftp ')
                && runningClientCommand.includes('<本机IP>')
                && !runningClientCommand.toLocaleLowerCase().includes('password')
                && Boolean(document.querySelector('button[title="复制客户端命令"]'))
                && Boolean(document.querySelector('button[title="复制服务日志"]')),
              'initial=' + initialClientCommand + ' running=' + runningClientCommand + ' log=' + text('[data-testid="transfer-service-log"] pre')
            )
            document.querySelector('button[title="清空服务日志"]')?.click()
            await sleep(100)
            const clearedTransferLogResponse = await window.desktopApi.request({ path: '/api/v1/file-transfer/service/log' })
            let clearedTransferLogEntries = ['unread']
            try {
              clearedTransferLogEntries = JSON.parse(clearedTransferLogResponse.body).entries || []
            } catch {
              clearedTransferLogEntries = ['invalid']
            }
            setCheck(
              'fileServiceLogClearPersistsThroughPythonService',
              clearedTransferLogResponse.status === 200
                && clearedTransferLogEntries.length === 0
                && text('[data-testid="transfer-service-log"] pre').includes('服务启动、登录、上传和下载事件'),
              clearedTransferLogResponse.body
            )
            const stopFileServiceButton = [...document.querySelectorAll('.transfer-settings-card button')]
              .find((button) => button.textContent?.trim() === '停止服务')
            stopFileServiceButton?.click()
            await sleep(120)
            document.querySelector('button[aria-label="关闭文件传输"]')?.click()
            await sleep(60)

            clickButtonByTitle('升级任务')
            for (let attempt = 0; attempt < 30 && !document.querySelector('.upgrade-workspace'); attempt += 1) {
              await sleep(50)
            }
            const manualPackageRow = [...document.querySelectorAll('[data-testid="upgrade-package"]')]
              .find((row) => row.querySelector('strong')?.textContent?.trim() === ${JSON.stringify(manualUpgradePackageName)})
            manualPackageRow?.click()
            document.querySelector('[data-testid="upgrade-manual-fallback"] .upgrade-manual-toggle')?.click()
            await sleep(80)
            document.querySelector('[data-testid="upgrade-manual-read"]')?.click()
            for (let attempt = 0; attempt < 30; attempt += 1) {
              if (document.querySelector('[data-testid="upgrade-manual-terminal"]')?.value) break
              await sleep(100)
            }
            const terminalSnapshotRead = Boolean(document.querySelector('[data-testid="upgrade-manual-terminal"]')?.value)
            document.querySelector('[data-testid="upgrade-manual-generate"]')?.click()
            let generatedManualScript = ''
            for (let attempt = 0; attempt < 50; attempt += 1) {
              generatedManualScript = document.querySelector('[data-testid="upgrade-manual-script"]')?.value || ''
              if (generatedManualScript.includes('{{file_transfer.password}}')) break
              await sleep(100)
            }
            document.querySelector('[data-testid="upgrade-manual-copy"]')?.click()
            await sleep(100)
            const manualCopyNotice = text('.upgrade-manual-notice')
            let copiedManualScript = ''
            try {
              copiedManualScript = await navigator.clipboard.readText()
            } catch {
              copiedManualScript = ''
            }
            const activeManualSessionId = document.querySelector('.session-tab.active')?.getAttribute('data-session-tab-id') || ''
            const readVersionCount = async () => {
              if (!activeManualSessionId) return -1
              const response = await window.desktopApi.request({ path: '/api/v1/sessions/' + encodeURIComponent(activeManualSessionId) + '/log' })
              try {
                return (JSON.parse(response.body).content.match(/SimOS V1\.0/g) || []).length
              } catch {
                return -1
              }
            }
            const versionCountBeforeManualSend = await readVersionCount()
            setValue('[data-testid="upgrade-manual-script"]', 'display version')
            await sleep(80)
            document.querySelector('[data-testid="upgrade-manual-confirm"]')?.click()
            await sleep(40)
            document.querySelector('[data-testid="upgrade-manual-send"]')?.click()
            let versionCountAfterManualSend = versionCountBeforeManualSend
            for (let attempt = 0; attempt < 40; attempt += 1) {
              versionCountAfterManualSend = await readVersionCount()
              if (versionCountAfterManualSend > versionCountBeforeManualSend) break
              await sleep(100)
            }
            setCheck(
              'packageUpgradeManualFallbackReadsGeneratesEditsCopiesAndSends',
              Boolean(manualPackageRow)
                && terminalSnapshotRead
                && generatedManualScript.includes('{{file_transfer.password}}')
                && generatedManualScript.includes(${JSON.stringify(manualUpgradePackageName)})
                && (copiedManualScript === generatedManualScript || manualCopyNotice.includes('已复制脚本'))
                && !document.querySelector('.upgrade-workspace input[type="password"]')
                && versionCountAfterManualSend > versionCountBeforeManualSend,
              'package=' + Boolean(manualPackageRow)
                + ' terminal=' + terminalSnapshotRead
                + ' placeholder=' + generatedManualScript.includes('{{file_transfer.password}}')
                + ' copied=' + (copiedManualScript === generatedManualScript)
                + ' copyNotice=' + manualCopyNotice
                + ' notice=' + text('.upgrade-manual-notice')
                + ' error=' + text('.upgrade-error')
                + ' versions=' + versionCountBeforeManualSend + '->' + versionCountAfterManualSend
            )
            document.querySelector('button[aria-label="关闭升级任务"]')?.click()
            await sleep(60)

            clickButtonByTitle('断开连接')
            for (let attempt = 0; attempt < 40; attempt += 1) {
              if (document.querySelector('.connection-state[data-state="disconnected"]')) break
              await sleep(100)
            }
            setCheck(
              'terminalDisconnectShowsInlineFeedback',
              Boolean(document.querySelector('.connection-state[data-state="disconnected"]'))
                && (document.querySelector('.xterm-rows')?.textContent || '').includes('会话已断开'),
              text('.connection-state') + ' ' + (document.querySelector('.xterm-rows')?.textContent || '').slice(-120)
            )
            clickButtonByTitle('重新连接 (Ctrl+Shift+R)')
            for (let attempt = 0; attempt < 50; attempt += 1) {
              if (document.querySelector('.connection-state[data-state="connected"]')) break
              await sleep(100)
            }
            setCheck(
              'terminalReconnectRestoresConnectedState',
              Boolean(document.querySelector('.connection-state[data-state="connected"]')),
              text('.connection-state')
            )
            await sleep(1300)

            click('.command-collapsed-bar')
            await sleep(120)
            const commandPanel = document.querySelector('.command-workspace.open')
            const commandResizeHandle = document.querySelector('[data-testid="command-resize-handle"]')
            const commandInitialHeight = commandPanel?.getBoundingClientRect().height || 0
            if (commandResizeHandle) {
              const rect = commandResizeHandle.getBoundingClientRect()
              commandResizeHandle.dispatchEvent(new PointerEvent('pointerdown', {
                bubbles: true,
                button: 0,
                clientX: rect.left + rect.width / 2,
                clientY: rect.top + rect.height / 2
              }))
              document.dispatchEvent(new PointerEvent('pointermove', {
                bubbles: true,
                clientX: rect.left + rect.width / 2,
                clientY: rect.top + rect.height / 2 - 70
              }))
              document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }))
            }
            await sleep(80)
            const commandDraggedHeight = commandPanel?.getBoundingClientRect().height || 0
            commandResizeHandle?.dispatchEvent(new KeyboardEvent('keydown', {
              key: 'End',
              bubbles: true,
              cancelable: true
            }))
            await sleep(60)
            const commandPreferredHeight = commandPanel?.getBoundingClientRect().height || 0
            window.resizeTo(1280, 720)
            await sleep(220)
            const commandHeightInSmallWindow = commandPanel?.getBoundingClientRect().height || 0
            const commandStageHeightInSmallWindow = document.querySelector('.workspace-stage')?.getBoundingClientRect().height || 0
            window.resizeTo(1560, 960)
            await sleep(220)
            const commandHeightAfterWindowRestore = commandPanel?.getBoundingClientRect().height || 0
            commandResizeHandle?.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
            await sleep(40)
            commandResizeHandle?.dispatchEvent(new KeyboardEvent('keydown', {
              key: 'ArrowUp',
              shiftKey: true,
              bubbles: true,
              cancelable: true
            }))
            await sleep(60)
            const commandFinalHeight = commandPanel?.getBoundingClientRect().height || 0
            document.querySelector('button[title="收起常用命令"]')?.click()
            await sleep(50)
            document.querySelector('.command-collapsed-bar')?.click()
            await sleep(80)
            const commandHeightAfterCollapseRestore = document.querySelector('.command-workspace.open')?.getBoundingClientRect().height || 0
            const persistedCommandHeight = Number(localStorage.getItem('device-tui.desktop-v2.command-panel-height') || 0)
            setCheck(
              'commandPanelDragResizePersistsAndClampsToWindow',
              Boolean(commandResizeHandle)
                && commandDraggedHeight >= commandInitialHeight + 60
                && commandPreferredHeight > commandDraggedHeight
                && commandHeightInSmallWindow <= commandStageHeightInSmallWindow - 178
                && commandHeightInSmallWindow < commandPreferredHeight
                && commandHeightAfterWindowRestore === commandPreferredHeight
                && commandFinalHeight === 340
                && commandHeightAfterCollapseRestore === commandFinalHeight
                && persistedCommandHeight === commandFinalHeight,
              'initial=' + commandInitialHeight + ' dragged=' + commandDraggedHeight
                + ' preferred=' + commandPreferredHeight + ' small=' + commandHeightInSmallWindow
                + '/' + commandStageHeightInSmallWindow + ' restored=' + commandHeightAfterWindowRestore
                + ' final=' + commandFinalHeight + ' collapseRestore=' + commandHeightAfterCollapseRestore
                + ' stored=' + persistedCommandHeight
            )
            const shortcutCommandEditor = document.querySelector('.command-editor-row textarea')
            shortcutCommandEditor?.focus()
            shortcutCommandEditor?.dispatchEvent(new KeyboardEvent('keydown', {
              key: 'f',
              ctrlKey: true,
              bubbles: true,
              cancelable: true
            }))
            await sleep(80)
            setCheck(
              'commandFindShortcutOpensWithoutTerminalConflict',
              Boolean(document.querySelector('.command-find-row input[aria-label="查找命令"]')) && !document.querySelector('.terminal-search'),
              'command=' + Boolean(document.querySelector('.command-find-row')) + ' terminal=' + Boolean(document.querySelector('.terminal-search'))
            )
            document.querySelector('.command-find-row input[aria-label="查找命令"]')?.dispatchEvent(new KeyboardEvent('keydown', {
              key: 'Escape',
              bubbles: true,
              cancelable: true
            }))
            await sleep(80)
            setCheck(
              'commandFindEscapeCloses',
              !document.querySelector('.command-find-row'),
              String(Boolean(document.querySelector('.command-find-row')))
            )
            setCheck(
              'commandGroupContextMenu',
              openContextMenu('.command-tab button') && await sleep(40).then(() => menuHasLabels('.command-context-menu', ['重命名', '新增命令页签', '删除页签'])),
              text('.command-context-menu')
            )
            document.querySelector('.command-header')?.click()
            await sleep(40)
            setCheck(
              'commandEditorContextMenu',
              openContextMenu('.command-editor-row textarea') && await sleep(40).then(() => menuHasLabels('.command-context-menu', ['复制选中/当前命令', '粘贴', '选择当前行', '发送到终端', '广播发送', '查找和替换', '清空当前页签'])),
              text('.command-context-menu')
            )
            document.querySelector('.command-header')?.click()
            await sleep(40)
            for (let attempt = 0; attempt < 60; attempt += 1) {
              if ((document.querySelector('.xterm-rows')?.textContent || '').includes('System ready.')) break
              await sleep(100)
            }
            const smokeCommand = 'display startup'
            const smokeCommandOutput = 'Current startup system software'
            const commandWorkspaceBeforeResponse = await window.desktopApi.request({ path: '/api/v1/commands/workspace' })
            let smokeCommandCountBefore = 0
            try {
              const parsed = JSON.parse(commandWorkspaceBeforeResponse.body)
              smokeCommandCountBefore = parsed.history
                ?.find((item) => item.command === smokeCommand)?.count || 0
            } catch {
              smokeCommandCountBefore = 0
            }
            setValue('.command-editor-row textarea', smokeCommand)
            const commandEditor = document.querySelector('.command-editor-row textarea')
            commandEditor?.focus()
            commandEditor?.setSelectionRange(0, smokeCommand.length)
            const terminalTextBeforeCommand = document.querySelector('.xterm-rows')?.textContent || ''
            const outputCountBeforeCommand = terminalTextBeforeCommand.split(smokeCommandOutput).length - 1
            document.querySelector('.command-dispatch-actions .primary-button')?.click()
            let terminalTextAfterCommand = terminalTextBeforeCommand
            for (let attempt = 0; attempt < 50; attempt += 1) {
              terminalTextAfterCommand = document.querySelector('.xterm-rows')?.textContent || ''
              const currentOutputCount = terminalTextAfterCommand.split(smokeCommandOutput).length - 1
              if (currentOutputCount > outputCountBeforeCommand) break
              await sleep(100)
            }
            const commandWorkspaceResponse = await window.desktopApi.request({ path: '/api/v1/commands/workspace' })
            let recordedSmokeCommand = null
            try {
              const parsed = JSON.parse(commandWorkspaceResponse.body)
              recordedSmokeCommand = parsed.history?.find((item) => item.command === smokeCommand) || null
            } catch {
              recordedSmokeCommand = null
            }
            setCheck(
              'commandHistoryRecordsUiDispatch',
              commandWorkspaceResponse.status === 200
                && Boolean(recordedSmokeCommand)
                && Number(recordedSmokeCommand.count || 0) > smokeCommandCountBefore,
              commandWorkspaceResponse.status + ':' + JSON.stringify(recordedSmokeCommand)
            )
            clickButtonByTitle('查看会话日志')
            for (let attempt = 0; attempt < 40; attempt += 1) {
              const logText = document.querySelector('.terminal-log-panel pre')?.textContent || ''
              if (logText.includes(smokeCommand) || logText.includes(smokeCommandOutput)) break
              await sleep(100)
            }
            const logPanelText = document.querySelector('.terminal-log-panel pre')?.textContent || ''
            setCheck(
              'commandDispatchWritesTerminalOutput',
              terminalTextAfterCommand.split(smokeCommandOutput).length - 1 > outputCountBeforeCommand
                || logPanelText.includes(smokeCommandOutput),
              'terminal=' + terminalTextAfterCommand.slice(-160) + ' log=' + logPanelText.slice(-160)
            )
            setCheck(
              'terminalLogPanelShowsSessionLog',
              Boolean(document.querySelector('.terminal-log-panel')) &&
                (logPanelText.includes(smokeCommand) || logPanelText.includes(smokeCommandOutput)),
              logPanelText.slice(-240)
            )
            setCheck(
              'terminalLogCopyControlAvailable',
              Boolean(document.querySelector('.terminal-log-panel button[title="复制日志"]:not(:disabled)')),
              text('.terminal-log-panel header')
            )
            clickButtonByTitle('保存日志副本')
            for (let attempt = 0; attempt < 30; attempt += 1) {
              if (text('.terminal-log-panel header').includes('日志副本已保存')) break
              await sleep(100)
            }
            setCheck(
              'terminalLogExportCreatesSafeCopy',
              text('.terminal-log-panel header').includes('日志副本已保存'),
              text('.terminal-log-panel header')
            )
            clickButtonByTitle('打开日志目录')
            for (let attempt = 0; attempt < 20; attempt += 1) {
              if (text('.terminal-log-panel header').includes('已打开日志目录')) break
              await sleep(50)
            }
            setCheck(
              'terminalLogDirectoryActionWorks',
              text('.terminal-log-panel header').includes('已打开日志目录'),
              text('.terminal-log-panel header')
            )
            clickButtonByTitle('打开当前会话日志')
            for (let attempt = 0; attempt < 20; attempt += 1) {
              if (text('.terminal-log-panel header').includes('已打开当前会话日志')) break
              await sleep(50)
            }
            setCheck(
              'terminalCurrentLogNativeOpenWorks',
              text('.terminal-log-panel header').includes('已打开当前会话日志'),
              text('.terminal-log-panel header')
            )
            clickButtonByTitle('新建日志')
            for (let attempt = 0; attempt < 30; attempt += 1) {
              if (text('.terminal-log-panel header').includes('已新建当前会话日志')) break
              await sleep(100)
            }
            setCheck(
              'terminalManualNewLogWorks',
              text('.terminal-log-panel header').includes('已新建当前会话日志')
                && text('.terminal-log-panel pre').includes('New log created'),
              text('.terminal-log-panel header') + ' ' + text('.terminal-log-panel pre').slice(-160)
            )
            clickButtonByTitle('关闭日志')
            const sshButton = [...document.querySelectorAll('.connection-actions button')]
              .find((button) => button.textContent?.trim() === 'SSH')
            sshButton?.click()
            for (let attempt = 0; attempt < 80; attempt += 1) {
              const terminalText = document.querySelector('.xterm-rows')?.textContent || ''
              if (document.querySelector('.connection-state[data-state="failed"]') && terminalText.includes('Connection failed')) break
              await sleep(100)
            }
            const failedSshText = document.querySelector('.xterm-rows')?.textContent || ''
            setCheck(
              'sshFailureShowsInlineReasonAndRetry',
              Boolean(sshButton)
                && Boolean(document.querySelector('.connection-state[data-state="failed"]'))
                && text('.connection-state') === '连接失败'
                && failedSshText.includes('Connection failed')
                && Boolean(document.querySelector('button[title="重新连接 (Ctrl+Shift+R)"]:not(:disabled)')),
              text('.terminal-endpoint') + ' ' + text('.connection-state') + ' ' + failedSshText.slice(-180)
            )
            const activeSshSessionId = document.querySelector('.session-tab.active')?.getAttribute('data-session-tab-id') || ''
            const readSessionSnapshot = async (sessionId) => {
              const response = await window.desktopApi.request({ path: '/api/v1/sessions' })
              if (response.status !== 200) return {}
              try {
                return JSON.parse(response.body).sessions?.find((session) => session.id === sessionId) || {}
              } catch {
                return {}
              }
            }
            const beforeSshRetry = await readSessionSnapshot(activeSshSessionId)
            clickButtonByTitle('重新连接 (Ctrl+Shift+R)')
            let afterSshRetry = beforeSshRetry
            for (let attempt = 0; attempt < 80; attempt += 1) {
              afterSshRetry = await readSessionSnapshot(activeSshSessionId)
              if (
                document.querySelector('.connection-state[data-state="failed"]')
                && Number(afterSshRetry.generation || 0) > Number(beforeSshRetry.generation || 0)
                && afterSshRetry.status === 'failed'
                && document.querySelector('button[title="重新连接 (Ctrl+Shift+R)"]:not(:disabled)')
              ) break
              await sleep(100)
            }
            const failedSshRetryText = document.querySelector('.xterm-rows')?.textContent || ''
            setCheck(
              'sshFailureRetryStaysInline',
              Boolean(document.querySelector('.connection-state[data-state="failed"]'))
                && Number(afterSshRetry.generation || 0) > Number(beforeSshRetry.generation || 0)
                && afterSshRetry.status === 'failed'
                && failedSshRetryText.includes('Connection failed')
                && Boolean(document.querySelector('button[title="重新连接 (Ctrl+Shift+R)"]:not(:disabled)')),
              'generation=' + beforeSshRetry.generation + '->' + afterSshRetry.generation + ' '
                + text('.connection-state') + ' ' + failedSshRetryText.slice(-220)
            )
            const telnetButton = [...document.querySelectorAll('.connection-actions button')]
              .find((button) => button.textContent?.trim() === 'Telnet')
            telnetButton?.click()
            for (let attempt = 0; attempt < 80; attempt += 1) {
              if (
                text('.terminal-endpoint').includes('telnet')
                && document.querySelector('.connection-state[data-state="failed"]')
              ) break
              await sleep(100)
            }
            const failedTelnetText = document.querySelector('.xterm-rows')?.textContent || ''
            setCheck(
              'telnetFailureShowsInlineReasonAndRetry',
              Boolean(telnetButton)
                && text('.terminal-endpoint').includes('telnet')
                && text('.connection-state') === '连接失败'
                && failedTelnetText.includes('Connection failed')
                && Boolean(document.querySelector('button[title="重新连接 (Ctrl+Shift+R)"]:not(:disabled)')),
              text('.terminal-endpoint') + ' ' + text('.connection-state') + ' ' + failedTelnetText.slice(-180)
            )

            clickButtonByTitle('占用设备')
            for (let attempt = 0; attempt < 40; attempt += 1) {
              const serialAction = [...document.querySelectorAll('.connection-actions button')]
                .find((button) => button.textContent?.trim() === '串口')
              if (document.querySelector('button[title="释放设备"]') && serialAction && !serialAction.disabled) break
              await sleep(100)
            }
            const serialButton = [...document.querySelectorAll('.connection-actions button')]
              .find((button) => button.textContent?.trim() === '串口')
            const serialEnabledAfterClaim = Boolean(serialButton && !serialButton.disabled)
            serialButton?.click()
            for (let attempt = 0; attempt < 80; attempt += 1) {
              if (
                text('.terminal-endpoint').includes('serial')
                && document.querySelector('.connection-state[data-state="failed"]')
              ) break
              await sleep(100)
            }
            const failedSerialText = document.querySelector('.xterm-rows')?.textContent || ''
            setCheck(
              'serialClaimAndFailureFlowStaysInline',
              serialEnabledAfterClaim
                && text('.terminal-endpoint').includes('serial')
                && text('.connection-state') === '连接失败'
                && failedSerialText.includes('Connection failed')
                && Boolean(document.querySelector('button[title="重新连接 (Ctrl+Shift+R)"]:not(:disabled)')),
              'enabledAfterClaim=' + serialEnabledAfterClaim + ' ' + text('.terminal-endpoint') + ' ' + text('.connection-state') + ' ' + failedSerialText.slice(-180)
            )

            const smokeServerGroup = '折叠烟测组'
            const smokeServerName = '折叠烟测服务器'
            clickButtonByTitle('服务器')
            await sleep(120)
            clickButtonByTitle('新建分组')
            await sleep(60)
            setValue('.group-dialog input', smokeServerGroup)
            document.querySelector('.group-dialog')?.requestSubmit()
            for (let attempt = 0; attempt < 30; attempt += 1) {
              if ([...document.querySelectorAll('.profile-group')].some((group) => group.getAttribute('data-profile-group-name') === smokeServerGroup)) break
              await sleep(100)
            }
            clickButtonByTitle('新增连接')
            for (let attempt = 0; attempt < 30 && !document.querySelector('.server-dialog'); attempt += 1) {
              await sleep(50)
            }
            setValue('.server-dialog .profile-form-body > .form-field:nth-of-type(1) input', smokeServerName)
            setValue('.server-dialog .profile-form-body > .form-field:nth-of-type(2) input', smokeServerGroup)
            setValue('.server-dialog .protocol-form input[placeholder="主机地址"]', '192.0.2.44')
            await sleep(100)
            const saveOnlyServer = [...document.querySelectorAll('.server-dialog footer button')]
              .find((button) => button.textContent?.trim() === '仅保存')
            saveOnlyServer?.click()
            for (let attempt = 0; attempt < 40; attempt += 1) {
              if ([...document.querySelectorAll('.profile-list .device-row strong')].some((node) => node.textContent?.trim() === smokeServerName)) break
              await sleep(100)
            }
            let smokeServerRow = [...document.querySelectorAll('.profile-list .device-row')]
              .find((row) => row.querySelector('strong')?.textContent?.trim() === smokeServerName)
            let smokeServerGroupElement = [...document.querySelectorAll('.profile-group')]
              .find((group) => group.getAttribute('data-profile-group-name') === smokeServerGroup)
            smokeServerGroupElement?.querySelector('.profile-group-toggle')?.click()
            await sleep(60)
            let collapsedProfileGroups = []
            try {
              collapsedProfileGroups = JSON.parse(localStorage.getItem('device-tui.desktop-v2.profile-collapsed-groups') || '[]')
            } catch {
              collapsedProfileGroups = []
            }
            const rowHiddenWhenCollapsed = Boolean(smokeServerRow) && smokeServerRow.getClientRects().length === 0
            setValue('.search-field input[type="search"]', smokeServerName)
            await sleep(100)
            smokeServerRow = [...document.querySelectorAll('.profile-list .device-row')]
              .find((row) => row.querySelector('strong')?.textContent?.trim() === smokeServerName)
            const rowVisibleDuringSearch = Boolean(smokeServerRow) && smokeServerRow.getClientRects().length > 0
            setCheck(
              'serverGroupCollapsePersistsAndSearchTemporarilyExpands',
              collapsedProfileGroups.includes(smokeServerGroup)
                && rowHiddenWhenCollapsed
                && rowVisibleDuringSearch,
              'stored=' + JSON.stringify(collapsedProfileGroups)
                + ' hidden=' + rowHiddenWhenCollapsed + ' searchVisible=' + rowVisibleDuringSearch
            )
            if (smokeServerRow) {
              const rect = smokeServerRow.getBoundingClientRect()
              smokeServerRow.dispatchEvent(new MouseEvent('contextmenu', {
                bubbles: true,
                cancelable: true,
                clientX: rect.left + 20,
                clientY: rect.top + 16
              }))
            }
            await sleep(40)
            const moveToUngrouped = [...document.querySelectorAll('.profile-context-menu button')]
              .find((button) => button.textContent?.trim() === '移动到未分组')
            moveToUngrouped?.click()
            await sleep(160)
            smokeServerRow = [...document.querySelectorAll('.profile-list .device-row')]
              .find((row) => row.querySelector('strong')?.textContent?.trim() === smokeServerName)
            if (smokeServerRow) {
              const rect = smokeServerRow.getBoundingClientRect()
              smokeServerRow.dispatchEvent(new MouseEvent('contextmenu', {
                bubbles: true,
                cancelable: true,
                clientX: rect.left + 20,
                clientY: rect.top + 16
              }))
            }
            await sleep(40)
            const moveBackToGroup = [...document.querySelectorAll('.profile-context-menu button')]
              .find((button) => button.textContent?.trim() === '移动到 ' + smokeServerGroup)
            moveBackToGroup?.click()
            await sleep(180)
            setValue('.search-field input[type="search"]', '')
            await sleep(80)
            smokeServerGroupElement = [...document.querySelectorAll('.profile-group')]
              .find((group) => group.getAttribute('data-profile-group-name') === smokeServerGroup)
            smokeServerRow = [...document.querySelectorAll('.profile-list .device-row')]
              .find((row) => row.querySelector('strong')?.textContent?.trim() === smokeServerName)
            const moveExpandedDestination = Boolean(moveToUngrouped)
              && Boolean(moveBackToGroup)
              && smokeServerGroupElement?.querySelector('.profile-group-toggle')?.getAttribute('aria-expanded') === 'true'
              && Boolean(smokeServerRow)
              && smokeServerRow.getClientRects().length > 0
            setCheck(
              'serverGroupMoveExpandsDestinationWithoutLosingProfile',
              moveExpandedDestination,
              'out=' + Boolean(moveToUngrouped) + ' back=' + Boolean(moveBackToGroup)
                + ' expanded=' + smokeServerGroupElement?.querySelector('.profile-group-toggle')?.getAttribute('aria-expanded')
            )
            smokeServerGroupElement?.querySelector('.profile-group-toggle')?.click()
            await sleep(60)

            let profileRows = 0
            let profileMenuText = ''
            for (const title of ['临时连接', '服务器']) {
              clickButtonByTitle(title)
              await sleep(160)
              profileRows = document.querySelectorAll('.profile-list .device-row').length
              if (profileRows > 0) {
                openContextMenu('.profile-list .device-row')
                await sleep(40)
                profileMenuText = text('.profile-context-menu')
                break
              }
            }
            setCheck(
              'profileContextMenuWhenProfilesExist',
              profileRows === 0 || ['打开', '复制连接信息', '编辑', '删除'].every((label) => profileMenuText.includes(label)),
              profileRows === 0 ? 'skipped:no profile rows in this user data dir' : profileMenuText
            )
            clickButtonByTitle('设备与终端')
            await sleep(80)

            const sessionsBeforeSplitResponse = await window.desktopApi.request({ path: '/api/v1/sessions' })
            let sessionsBeforeSplit = []
            try {
              sessionsBeforeSplit = JSON.parse(sessionsBeforeSplitResponse.body).sessions || []
            } catch {
              sessionsBeforeSplit = []
            }
            openContextMenu('.session-tab')
            await sleep(50)
            const splitLabels = [...document.querySelectorAll('.session-context-menu button')]
              .map((button) => button.textContent?.trim() || '')
            setCheck(
              'terminalSplitContextActionsExposeAllDirections',
              ['分屏到左侧', '分屏到右侧', '分屏到上方', '分屏到下方']
                .every((label) => splitLabels.includes(label)),
              splitLabels.join('|')
            )
            const splitRightButton = [...document.querySelectorAll('.session-context-menu button')]
              .find((button) => button.textContent?.trim() === '分屏到右侧')
            splitRightButton?.click()
            await sleep(180)
            const sessionsAfterSplitResponse = await window.desktopApi.request({ path: '/api/v1/sessions' })
            let sessionsAfterSplit = []
            try {
              sessionsAfterSplit = JSON.parse(sessionsAfterSplitResponse.body).sessions || []
            } catch {
              sessionsAfterSplit = []
            }
            setCheck(
              'terminalSplitCreatesTwoPanesWithoutDuplicatingBackendSessions',
              Boolean(splitRightButton)
                && document.querySelector('.terminal-split-layout')?.getAttribute('data-split-direction') === 'right'
                && document.querySelectorAll('.terminal-split-pane').length === 2
                && document.querySelectorAll('.terminal-split-pane .terminal-pane').length === 2
                && sessionsAfterSplit.length === sessionsBeforeSplit.length,
              'direction=' + (document.querySelector('.terminal-split-layout')?.getAttribute('data-split-direction') || '')
                + ' panes=' + document.querySelectorAll('.terminal-split-pane').length
                + ' backend=' + sessionsBeforeSplit.length + '->' + sessionsAfterSplit.length
            )
            const draggableTabs = [...document.querySelectorAll('.session-tab')]
            const secondaryPane = document.querySelector('.terminal-split-pane[data-pane-id="secondary"]')
            const secondarySessionIds = [...document.querySelectorAll('.terminal-split-pane[data-pane-id="secondary"] .split-session-tab')]
              .map((tab) => tab.getAttribute('data-session-id') || '')
            const primaryCandidate = draggableTabs.find((tab) => {
              const id = tab.getAttribute('data-session-tab-id') || ''
              return Boolean(id) && !secondarySessionIds.includes(id)
            }) || draggableTabs[1]
            let dragDropWorked = false
            if (primaryCandidate && secondaryPane) {
              const transfer = new DataTransfer()
              primaryCandidate.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: transfer }))
              const rect = secondaryPane.getBoundingClientRect()
              secondaryPane.dispatchEvent(new DragEvent('dragover', {
                bubbles: true,
                cancelable: true,
                clientX: rect.right - 4,
                clientY: rect.top + rect.height / 2,
                dataTransfer: transfer
              }))
              secondaryPane.dispatchEvent(new DragEvent('drop', {
                bubbles: true,
                cancelable: true,
                clientX: rect.right - 4,
                clientY: rect.top + rect.height / 2,
                dataTransfer: transfer
              }))
              await sleep(160)
              dragDropWorked = document.querySelectorAll('.terminal-split-pane[data-pane-id="secondary"] .split-session-tab').length >= 2
            }
            const sessionsAfterDragResponse = await window.desktopApi.request({ path: '/api/v1/sessions' })
            let sessionsAfterDrag = []
            try {
              sessionsAfterDrag = JSON.parse(sessionsAfterDragResponse.body).sessions || []
            } catch {
              sessionsAfterDrag = []
            }
            setCheck(
              'terminalTabDragDropMovesExistingSessionOnly',
              dragDropWorked && sessionsAfterDrag.length === sessionsBeforeSplit.length,
              'secondaryTabs=' + document.querySelectorAll('.terminal-split-pane[data-pane-id="secondary"] .split-session-tab').length
                + ' backend=' + sessionsBeforeSplit.length + '->' + sessionsAfterDrag.length
            )

            const failed = Object.entries(checks).filter(([, value]) => !value).map(([name]) => name)
            return {
              passed: failed.length === 0,
              failed,
              checks,
              details
            }
          })()`,
          true
        )
        console.log(`[renderer] uiParity=${JSON.stringify(uiParity)}`)
        console.log(`[renderer] uiParityPassed=${Boolean(uiParity?.passed)}`)
        console.log(`[renderer] uiParityFailed=${(uiParity?.failed || []).join('|')}`)
        const captureAdvancedAutomationPath = process.env.DEVICE_TUI_CAPTURE_ADVANCED_AUTOMATION_PATH
        if (captureAdvancedAutomationPath) {
          await mainWindow.webContents.executeJavaScript(
            "[...document.querySelectorAll('button')].find((button) => button.getAttribute('title') === '终端自动化')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 180))
          await mainWindow.webContents.executeJavaScript(
            "[...document.querySelectorAll('.automation-rule-row')].find((button) => (button.textContent || '').includes('动作流烟测'))?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 160))
          const advancedAutomationImage = await mainWindow.webContents.capturePage()
          await writeFile(captureAdvancedAutomationPath, advancedAutomationImage.toPNG())
          const captureAdvancedAutomationLightPath = process.env.DEVICE_TUI_CAPTURE_ADVANCED_AUTOMATION_LIGHT_PATH
          if (captureAdvancedAutomationLightPath) {
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 180))
            const advancedAutomationLightImage = await mainWindow.webContents.capturePage()
            await writeFile(captureAdvancedAutomationLightPath, advancedAutomationLightImage.toPNG())
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 100))
          }
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('button[aria-label=\"关闭自动化面板\"]')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 80))
        }
        const captureTransferServicePath = process.env.DEVICE_TUI_CAPTURE_TRANSFER_SERVICE_PATH
        if (captureTransferServicePath) {
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('button[title=\"文件传输\"]')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 180))
          const transferServiceImage = await mainWindow.webContents.capturePage()
          await writeFile(captureTransferServicePath, transferServiceImage.toPNG())
          const captureTransferServiceLightPath = process.env.DEVICE_TUI_CAPTURE_TRANSFER_SERVICE_LIGHT_PATH
          if (captureTransferServiceLightPath) {
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 180))
            const transferServiceLightImage = await mainWindow.webContents.capturePage()
            await writeFile(captureTransferServiceLightPath, transferServiceLightImage.toPNG())
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 100))
          }
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('button[aria-label=\"关闭文件传输\"]')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 80))
        }
        const captureManualUpgradePath = process.env.DEVICE_TUI_CAPTURE_MANUAL_UPGRADE_PATH
        if (captureManualUpgradePath) {
          await mainWindow.webContents.executeJavaScript(
            `(() => {
              document.querySelector('button[title="升级任务"]')?.click()
              const row = [...document.querySelectorAll('[data-testid="upgrade-package"]')]
                .find((item) => item.querySelector('strong')?.textContent?.trim() === ${JSON.stringify(manualUpgradePackageName)})
              row?.click()
            })()`,
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 180))
          await mainWindow.webContents.executeJavaScript(
            `(() => {
              if (!document.querySelector('#upgrade-manual-content')) {
                document.querySelector('[data-testid="upgrade-manual-fallback"] .upgrade-manual-toggle')?.click()
              }
              document.querySelector('[data-testid="upgrade-manual-generate"]')?.click()
            })()`,
            true
          )
          for (let attempt = 0; attempt < 50; attempt += 1) {
            const ready = await mainWindow.webContents.executeJavaScript(
              "document.querySelector('[data-testid=\"upgrade-manual-script\"]')?.value?.includes('{{file_transfer.password}}') || false",
              true
            )
            if (ready) break
            await new Promise((resolve) => setTimeout(resolve, 100))
          }
          const manualUpgradeImage = await mainWindow.webContents.capturePage()
          await writeFile(captureManualUpgradePath, manualUpgradeImage.toPNG())
          const captureManualUpgradeLightPath = process.env.DEVICE_TUI_CAPTURE_MANUAL_UPGRADE_LIGHT_PATH
          if (captureManualUpgradeLightPath) {
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 180))
            const manualUpgradeLightImage = await mainWindow.webContents.capturePage()
            await writeFile(captureManualUpgradeLightPath, manualUpgradeLightImage.toPNG())
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 100))
          }
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('button[aria-label=\"关闭升级任务\"]')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 80))
        }
        const captureServerGroupsPath = process.env.DEVICE_TUI_CAPTURE_SERVER_GROUPS_PATH
        if (captureServerGroupsPath) {
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('button[title=\"服务器\"]')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 180))
          const serverGroupsImage = await mainWindow.webContents.capturePage()
          await writeFile(captureServerGroupsPath, serverGroupsImage.toPNG())
          const captureServerGroupsLightPath = process.env.DEVICE_TUI_CAPTURE_SERVER_GROUPS_LIGHT_PATH
          if (captureServerGroupsLightPath) {
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 180))
            const serverGroupsLightImage = await mainWindow.webContents.capturePage()
            await writeFile(captureServerGroupsLightPath, serverGroupsLightImage.toPNG())
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 100))
          }
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('button[title=\"设备与终端\"]')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 80))
        }
        const captureCommandPanelPath = process.env.DEVICE_TUI_CAPTURE_COMMAND_PANEL_PATH
        if (captureCommandPanelPath) {
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('.command-collapsed-bar')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 120))
          const commandPanelImage = await mainWindow.webContents.capturePage()
          await writeFile(captureCommandPanelPath, commandPanelImage.toPNG())
          const captureCommandPanelLightPath = process.env.DEVICE_TUI_CAPTURE_COMMAND_PANEL_LIGHT_PATH
          if (captureCommandPanelLightPath) {
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 180))
            const commandPanelLightImage = await mainWindow.webContents.capturePage()
            await writeFile(captureCommandPanelLightPath, commandPanelLightImage.toPNG())
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 100))
          }
        }
        const captureSessionManagerPath = process.env.DEVICE_TUI_CAPTURE_SESSION_MANAGER_PATH
        if (captureSessionManagerPath) {
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('.command-header')?.click(); document.querySelector('.workspace-header')?.click(); document.querySelector('.session-rail-toggle[title=\"展开右侧会话栏\"]')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 180))
          const sessionManagerImage = await mainWindow.webContents.capturePage()
          await writeFile(captureSessionManagerPath, sessionManagerImage.toPNG())
          const captureSessionManagerLightPath = process.env.DEVICE_TUI_CAPTURE_SESSION_MANAGER_LIGHT_PATH
          if (captureSessionManagerLightPath) {
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 180))
            const sessionManagerLightImage = await mainWindow.webContents.capturePage()
            await writeFile(captureSessionManagerLightPath, sessionManagerLightImage.toPNG())
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 100))
          }
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('.session-rail-toggle[title=\"折叠右侧会话栏\"]')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 80))
        }
        const captureSettingsPath = process.env.DEVICE_TUI_CAPTURE_SETTINGS_PATH
        if (captureSettingsPath) {
          await mainWindow.webContents.executeJavaScript(
            "[...document.querySelectorAll('button')].find((button) => button.getAttribute('title') === '设置')?.click()",
            true
          )
          await new Promise((resolve) => setTimeout(resolve, 180))
          const settingsImage = await mainWindow.webContents.capturePage()
          await writeFile(captureSettingsPath, settingsImage.toPNG())
          await mainWindow.webContents.executeJavaScript(
            "[...document.querySelectorAll('button')].find((button) => button.getAttribute('title') === '关闭设置')?.click()",
            true
          )
        }
        const restoreBaseline = await mainWindow.webContents.executeJavaScript(
          `({
            sessionCount: document.querySelectorAll('.session-tab').length,
            activeSessionId: document.querySelector('.session-tab.active')?.getAttribute('data-session-tab-id') || '',
            selectedDeviceRowId: document.querySelector('.device-table-row.selected')?.getAttribute('data-device-row-id') || '',
            theme: document.documentElement.dataset.theme || '',
            alwaysOnTop: document.querySelector('.always-on-top-toggle')?.getAttribute('aria-pressed') === 'true',
            sessionTabLayout: document.querySelector('.session-workspace')?.getAttribute('data-tab-layout') || '',
            sessionTabRailCollapsed: document.querySelector('.session-workspace')?.getAttribute('data-tab-collapsed') === 'true',
            sessionManagerWidth: localStorage.getItem('device-tui.desktop-v2.session-manager-width') || '',
            sessionManagerCollapsedGroups: localStorage.getItem('device-tui.desktop-v2.session-manager-collapsed-groups') || '',
            profileCollapsedGroups: localStorage.getItem('device-tui.desktop-v2.profile-collapsed-groups') || '',
            navigatorDetailCollapsed: localStorage.getItem('device-tui.desktop-v2.navigator-detail-collapsed') === '1',
            commandPanelHeight: localStorage.getItem('device-tui.desktop-v2.command-panel-height') || '',
            terminalSplitDirection: document.querySelector('.terminal-split-layout')?.getAttribute('data-split-direction') || '',
            terminalSplitPaneCount: document.querySelectorAll('.terminal-split-pane').length
          })`,
          true
        )
        const rendererReloaded = new Promise<void>((resolve) => {
          mainWindow?.webContents.once('did-finish-load', () => resolve())
        })
        mainWindow.reload()
        await rendererReloaded
        for (let attempt = 0; attempt < 50; attempt += 1) {
          const ready = await mainWindow.webContents.executeJavaScript(
            `document.querySelectorAll('.device-table-row').length > 0
              && document.querySelectorAll('.session-tab').length >= ${Number(restoreBaseline.sessionCount || 0)}`,
            true
          )
          if (ready) break
          await new Promise((resolve) => setTimeout(resolve, 100))
        }
        const uiRestore = await mainWindow.webContents.executeJavaScript(
          `(async () => {
            const baseline = ${JSON.stringify(restoreBaseline)}
            const runtime = await window.desktopApi.getRuntimeConfig()
            const restored = {
              sessionCount: document.querySelectorAll('.session-tab').length,
              activeSessionId: document.querySelector('.session-tab.active')?.getAttribute('data-session-tab-id') || '',
              selectedDeviceRowId: document.querySelector('.device-table-row.selected')?.getAttribute('data-device-row-id') || '',
              theme: document.documentElement.dataset.theme || '',
              alwaysOnTop: document.querySelector('.always-on-top-toggle')?.getAttribute('aria-pressed') === 'true',
              sessionTabLayout: document.querySelector('.session-workspace')?.getAttribute('data-tab-layout') || '',
              sessionTabRailCollapsed: document.querySelector('.session-workspace')?.getAttribute('data-tab-collapsed') === 'true',
              sessionManagerWidth: localStorage.getItem('device-tui.desktop-v2.session-manager-width') || '',
              sessionManagerCollapsedGroups: localStorage.getItem('device-tui.desktop-v2.session-manager-collapsed-groups') || '',
              profileCollapsedGroups: localStorage.getItem('device-tui.desktop-v2.profile-collapsed-groups') || '',
              navigatorDetailCollapsed: localStorage.getItem('device-tui.desktop-v2.navigator-detail-collapsed') === '1',
              navigatorDetailCollapsedDom: document.querySelector('.navigator-detail')?.getAttribute('data-collapsed') === 'true',
              rightSessionSidebarPresent: Boolean(document.querySelector('.app-shell > .session-sidebar > .session-manager')),
              commandPanelHeight: localStorage.getItem('device-tui.desktop-v2.command-panel-height') || '',
              commandPanelDomHeight: document.querySelector('.command-workspace.open')?.getAttribute('data-panel-height') || '',
              terminalSplitDirection: document.querySelector('.terminal-split-layout')?.getAttribute('data-split-direction') || '',
              terminalSplitPaneCount: document.querySelectorAll('.terminal-split-pane').length,
              tokenExposed: 'token' in runtime
            }
            const serverSectionButton = [...document.querySelectorAll('button')]
              .find((button) => button.getAttribute('title') === '服务器')
            serverSectionButton?.click()
            await new Promise((resolve) => setTimeout(resolve, 120))
            restored.serverGroupCollapsedDom = [...document.querySelectorAll('.profile-group')]
              .some((group) => group.getAttribute('data-profile-group-name') === '折叠烟测组'
                && group.querySelector('.profile-group-toggle')?.getAttribute('aria-expanded') === 'false')
            const deviceSectionButton = [...document.querySelectorAll('button')]
              .find((button) => button.getAttribute('title') === '设备与终端')
            deviceSectionButton?.click()
            await new Promise((resolve) => setTimeout(resolve, 80))
            const checks = {
              multiSessionCountRestored: baseline.sessionCount >= 2 && restored.sessionCount === baseline.sessionCount,
              activeSessionRestored: Boolean(baseline.activeSessionId) && restored.activeSessionId === baseline.activeSessionId,
              selectedDeviceRowRestored: Boolean(baseline.selectedDeviceRowId) && restored.selectedDeviceRowId === baseline.selectedDeviceRowId,
              themeRestored: Boolean(baseline.theme) && restored.theme === baseline.theme,
              alwaysOnTopRestored: baseline.alwaysOnTop === true && restored.alwaysOnTop === true,
              sessionTabLayoutRestored: baseline.sessionTabLayout === 'side' && restored.sessionTabLayout === 'side',
              sessionTabRailCollapsedRestored: baseline.sessionTabRailCollapsed === true && restored.sessionTabRailCollapsed === true,
              rightSessionSidebarRestored: restored.rightSessionSidebarPresent === true,
              sessionManagerWidthRestored: Boolean(baseline.sessionManagerWidth)
                && restored.sessionManagerWidth === baseline.sessionManagerWidth,
              sessionManagerGroupStateRestored: baseline.sessionManagerCollapsedGroups.includes('SIM-TERMINAL')
                && restored.sessionManagerCollapsedGroups === baseline.sessionManagerCollapsedGroups,
              serverGroupCollapsedStateRestored: baseline.profileCollapsedGroups.includes('折叠烟测组')
                && restored.profileCollapsedGroups === baseline.profileCollapsedGroups
                && restored.serverGroupCollapsedDom === true,
              navigatorDetailStateRestored: restored.navigatorDetailCollapsed === baseline.navigatorDetailCollapsed
                && restored.navigatorDetailCollapsedDom === baseline.navigatorDetailCollapsed,
              commandPanelHeightRestored: Boolean(baseline.commandPanelHeight)
                && restored.commandPanelHeight === baseline.commandPanelHeight
                && restored.commandPanelDomHeight === baseline.commandPanelHeight,
              terminalSplitLayoutRestored: baseline.terminalSplitDirection === 'right'
                && restored.terminalSplitDirection === baseline.terminalSplitDirection
                && restored.terminalSplitPaneCount === baseline.terminalSplitPaneCount
                && restored.terminalSplitPaneCount === 2,
              tokenStillHiddenAfterReload: restored.tokenExposed === false
            }
            const failed = Object.entries(checks).filter(([, value]) => !value).map(([name]) => name)
            return { passed: failed.length === 0, failed, checks, baseline, restored }
          })()`,
          true
        )
        uiRestore.checks.nativeAlwaysOnTopRestored = mainWindow.isAlwaysOnTop()
        if (!uiRestore.checks.nativeAlwaysOnTopRestored) uiRestore.failed.push('nativeAlwaysOnTopRestored')
        uiRestore.passed = uiRestore.failed.length === 0
        console.log(`[renderer] uiRestore=${JSON.stringify(uiRestore)}`)
        console.log(`[renderer] uiRestorePassed=${Boolean(uiRestore?.passed)}`)
        const captureLightPath = process.env.DEVICE_TUI_CAPTURE_LIGHT_PATH
        if (captureLightPath) {
          const previousTheme = await mainWindow.webContents.executeJavaScript(
            "document.documentElement.dataset.theme || 'dark'",
            true
          )
          if (previousTheme !== 'light') {
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 180))
          }
          const lightImage = await mainWindow.webContents.capturePage()
          await writeFile(captureLightPath, lightImage.toPNG())
          if (previousTheme !== 'light') {
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.theme-toggle')?.click()",
              true
            )
            await new Promise((resolve) => setTimeout(resolve, 120))
          }
          console.log(`[renderer] lightThemeCapture=${captureLightPath}`)
        }
        const primaryImage = await mainWindow.webContents.capturePage()
        await writeFile(capturePath, primaryImage.toPNG())
        primaryCaptureWritten = true
      }
      const captureAutomationCommand = process.env.DEVICE_TUI_CAPTURE_AUTOMATION_COMMAND
      if (captureAutomationCommand) {
        await mainWindow.webContents.executeJavaScript(
          "document.querySelector('button[title=\"终端自动化\"]')?.click()",
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 350))
        const automationFormReady = await mainWindow.webContents.executeJavaScript(
          "Boolean(document.querySelector('[data-testid=\"automation-save\"]'))",
          true
        )
        console.log(`[renderer] automationFormReady=${automationFormReady}`)
        await mainWindow.webContents.executeJavaScript(
          `(() => {
            const setValue = (selector, value) => {
              const element = document.querySelector(selector)
              if (!element) return false
              element.value = value
              element.dispatchEvent(new Event('input', { bubbles: true }))
              element.dispatchEvent(new Event('change', { bubbles: true }))
              return true
            }
            setValue('[data-testid="automation-name"]', 'Electron 自动化烟测')
            setValue('[data-testid="automation-trigger"]', 'manual')
            setValue('[data-testid="automation-response"]', ${JSON.stringify(captureAutomationCommand)})
            document.querySelector('[data-testid="automation-save"]')?.click()
            return true
          })()`,
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 700))
        await mainWindow.webContents.executeJavaScript(
          "document.querySelector('[data-testid=\"automation-run\"]')?.click()",
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 1_000))
        const automationRows = await mainWindow.webContents.executeJavaScript(
          "document.querySelectorAll('.automation-rule-row').length",
          true
        )
        const automationTerminalOutput = await mainWindow.webContents.executeJavaScript(
          "document.querySelector('.xterm-rows')?.textContent?.includes('SimOS V1.0') || false",
          true
        )
        const automationError = await mainWindow.webContents.executeJavaScript(
          "document.querySelector('.automation-error')?.textContent?.trim() || ''",
          true
        )
        console.log(`[renderer] automationRows=${automationRows}`)
        console.log(`[renderer] automationTerminalOutput=${automationTerminalOutput}`)
        console.log(`[renderer] automationError=${automationError}`)
      }
      const captureTransferSource = process.env.DEVICE_TUI_CAPTURE_TRANSFER_SOURCE
      if (captureTransferSource) {
        const transferRoot = path.dirname(captureTransferSource)
        const transferName = path.basename(captureTransferSource)
        await mainWindow.webContents.executeJavaScript(
          "document.querySelector('button[title=\"文件传输\"]')?.click()",
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 400))
        const transferPanelReady = await mainWindow.webContents.executeJavaScript(
          "Boolean(document.querySelector('[data-testid=\"transfer-settings\"]'))",
          true
        )
        console.log(`[renderer] transferPanelReady=${transferPanelReady}`)
        await mainWindow.webContents.executeJavaScript(
          `(() => {
            const root = document.querySelector('[data-testid="transfer-root"]')
            if (!root) return false
            root.value = ${JSON.stringify(transferRoot)}
            root.dispatchEvent(new Event('input', { bubbles: true }))
            root.dispatchEvent(new Event('change', { bubbles: true }))
            document.querySelector('[data-testid="transfer-settings"]')?.requestSubmit()
            return true
          })()`,
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 700))
        const transferFileSelected = await mainWindow.webContents.executeJavaScript(
          `(() => {
            const rows = [...document.querySelectorAll('[data-testid="transfer-file"]')]
            const row = rows.find((item) => item.querySelector('strong')?.textContent?.trim() === ${JSON.stringify(transferName)})
            row?.click()
            return Boolean(row)
          })()`,
          true
        )
        console.log(`[renderer] transferFileSelected=${transferFileSelected}`)
        await mainWindow.webContents.executeJavaScript(
          "document.querySelector('[data-testid=\"transfer-run\"]')?.requestSubmit()",
          true
        )
        for (let attempt = 0; attempt < 80; attempt += 1) {
          const terminalStatus = await mainWindow.webContents.executeJavaScript(
            "document.querySelector('[data-testid=\"transfer-operation\"]')?.getAttribute('data-status') || ''",
            true
          )
          if (terminalStatus && terminalStatus !== 'running') break
          await new Promise((resolve) => setTimeout(resolve, 100))
        }
        const transferRows = await mainWindow.webContents.executeJavaScript(
          "document.querySelectorAll('[data-testid=\"transfer-operation\"]').length",
          true
        )
        const transferStatus = await mainWindow.webContents.executeJavaScript(
          "document.querySelector('[data-testid=\"transfer-operation\"]')?.getAttribute('data-status') || ''",
          true
        )
        const transferVerified = await mainWindow.webContents.executeJavaScript(
          "document.querySelector('[data-testid=\"transfer-operation\"]')?.textContent?.includes('完全匹配') || false",
          true
        )
        const transferSecretField = await mainWindow.webContents.executeJavaScript(
          "Boolean(document.querySelector('.transfer-workspace input[type=\"password\"]'))",
          true
        )
        const transferError = await mainWindow.webContents.executeJavaScript(
          "document.querySelector('.transfer-error')?.textContent?.trim() || ''",
          true
        )
        console.log(`[renderer] transferRows=${transferRows}`)
        console.log(`[renderer] transferStatus=${transferStatus}`)
        console.log(`[renderer] transferVerified=${transferVerified}`)
        console.log(`[renderer] transferSecretField=${transferSecretField}`)
        console.log(`[renderer] transferError=${transferError}`)
      }
      const captureUpgradeSource = process.env.DEVICE_TUI_CAPTURE_UPGRADE_SOURCE
      if (captureUpgradeSource) {
        const upgradeRoot = path.dirname(captureUpgradeSource)
        const upgradeName = path.basename(captureUpgradeSource)
        await mainWindow.webContents.executeJavaScript(
          "document.querySelector('button[title=\"文件传输\"]')?.click()",
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 350))
        await mainWindow.webContents.executeJavaScript(
          `(() => {
            const root = document.querySelector('[data-testid="transfer-root"]')
            if (!root) return false
            root.value = ${JSON.stringify(upgradeRoot)}
            root.dispatchEvent(new Event('input', { bubbles: true }))
            root.dispatchEvent(new Event('change', { bubbles: true }))
            document.querySelector('[data-testid="transfer-settings"]')?.requestSubmit()
            return true
          })()`,
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 650))
        await mainWindow.webContents.executeJavaScript(
          "document.querySelector('button[title=\"升级任务\"]')?.click()",
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 450))
        const upgradePanelReady = await mainWindow.webContents.executeJavaScript(
          "Boolean(document.querySelector('[data-testid=\"upgrade-form\"]'))",
          true
        )
        const upgradePackageSelected = await mainWindow.webContents.executeJavaScript(
          `(() => {
            const rows = [...document.querySelectorAll('[data-testid="upgrade-package"]')]
            const row = rows.find((item) => item.querySelector('strong')?.textContent?.trim() === ${JSON.stringify(upgradeName)})
            row?.click()
            return Boolean(row)
          })()`,
          true
        )
        if (process.env.DEVICE_TUI_CAPTURE_UPGRADE_REBOOT === '1') {
          await mainWindow.webContents.executeJavaScript(
            "document.querySelector('[data-testid=\"upgrade-reboot\"]')?.click()",
            true
          )
        }
        console.log(`[renderer] upgradePanelReady=${upgradePanelReady}`)
        console.log(`[renderer] upgradePackageSelected=${upgradePackageSelected}`)
        await mainWindow.webContents.executeJavaScript(
          "document.querySelector('[data-testid=\"upgrade-form\"]')?.requestSubmit()",
          true
        )
        let upgradeRebootApproved = false
        for (let attempt = 0; attempt < 180; attempt += 1) {
          const upgradeStatus = await mainWindow.webContents.executeJavaScript(
            "document.querySelector('[data-testid=\"upgrade-operation\"]')?.getAttribute('data-status') || ''",
            true
          )
          if (upgradeStatus === 'waiting_approval' && process.env.DEVICE_TUI_CAPTURE_UPGRADE_REBOOT === '1') {
            await mainWindow.webContents.executeJavaScript(
              "document.querySelector('[data-testid=\"upgrade-approve\"]')?.click()",
              true
            )
            upgradeRebootApproved = true
          }
          if (['completed', 'failed', 'cancelled'].includes(upgradeStatus)) break
          await new Promise((resolve) => setTimeout(resolve, 100))
        }
        const upgradeStatus = await mainWindow.webContents.executeJavaScript(
          "document.querySelector('[data-testid=\"upgrade-operation\"]')?.getAttribute('data-status') || ''",
          true
        )
        const upgradeVerified = await mainWindow.webContents.executeJavaScript(
          "document.querySelector('[data-testid=\"upgrade-operation\"]')?.textContent?.includes('升级完成') || document.querySelector('[data-testid=\"upgrade-operation\"]')?.textContent?.includes('人工重启') || false",
          true
        )
        const upgradeError = await mainWindow.webContents.executeJavaScript(
          "document.querySelector('.upgrade-error')?.textContent?.trim() || ''",
          true
        )
        const upgradePanelVisible = await mainWindow.webContents.executeJavaScript(
          "Boolean(document.querySelector('.upgrade-workspace'))",
          true
        )
        console.log(`[renderer] upgradeStatus=${upgradeStatus}`)
        console.log(`[renderer] upgradeVerified=${upgradeVerified}`)
        console.log(`[renderer] upgradeRebootApproved=${upgradeRebootApproved}`)
        console.log(`[renderer] upgradeError=${upgradeError}`)
        console.log(`[renderer] upgradePanelVisible=${upgradePanelVisible}`)
      }
      const captureCommand = process.env.DEVICE_TUI_CAPTURE_COMMAND
      if (captureCommand) {
        await mainWindow.webContents.executeJavaScript(
          `(() => { const editor = document.querySelector('.command-editor-row textarea'); if (!editor) return false; editor.value = ${JSON.stringify(captureCommand)}; editor.dispatchEvent(new Event('input', { bubbles: true })); editor.setSelectionRange(0, editor.value.length); document.querySelector('.command-dispatch-actions .primary-button')?.click(); return true })()`,
          true
        )
        await new Promise((resolve) => setTimeout(resolve, 900))
      }
      if (process.env.DEVICE_TUI_CAPTURE_BACKEND_RECOVERY === '1') {
        const beforeRuntime = backend.config
        console.log(`[renderer] recoveryBefore=${beforeRuntime.apiBaseUrl}`)
        const crashed = backend.crashForRecoveryProbe()
        console.log(`[renderer] recoveryCrashed=${crashed}`)
        let recoveredRuntime = beforeRuntime
        let failureBannerSeen = false
        for (let attempt = 0; attempt < 80; attempt += 1) {
          try {
            const failure = await mainWindow.webContents.executeJavaScript(
              "document.querySelector('.system-banner')?.textContent?.trim() || ''",
              true
            )
            if (failure) failureBannerSeen = true
            const nextRuntime = backend.config
            if (nextRuntime.apiBaseUrl && nextRuntime.apiBaseUrl !== beforeRuntime.apiBaseUrl) {
              recoveredRuntime = nextRuntime
              break
            }
          } catch {
            // The backend is expected to be briefly unavailable while Main restarts it.
          }
          await new Promise((resolve) => setTimeout(resolve, 100))
        }
        console.log(`[renderer] recoveryAfter=${recoveredRuntime.apiBaseUrl}`)
        console.log(`[renderer] recoveryChanged=${recoveredRuntime.apiBaseUrl !== beforeRuntime.apiBaseUrl}`)
        const recoveryResponse = await mainWindow.webContents.executeJavaScript(
          "window.desktopApi.request({ path: '/api/v1/devices' }).then((response) => response.status)",
          true
        )
        console.log(`[renderer] recoveryRequestStatus=${recoveryResponse}`)
        const recoveredLogSettingsResponse = await fetchBackend(
          recoveredRuntime,
          '/api/v1/settings/session-logs'
        )
        let recoveredLogSettings: { directory?: string; rotate_size_mb?: number } = {}
        try {
          recoveredLogSettings = JSON.parse(recoveredLogSettingsResponse.body)
        } catch {
          recoveredLogSettings = {}
        }
        const logSettingsRestored = !process.env.DEVICE_TUI_LOG_DIRECTORY_SELECTION || (
          recoveredLogSettingsResponse.status === 200
          && path.resolve(recoveredLogSettings.directory || '') === path.resolve(process.env.DEVICE_TUI_LOG_DIRECTORY_SELECTION)
          && recoveredLogSettings.rotate_size_mb === 7
        )
        let recoveryDom = { failure: '', notice: '', deviceRows: 0 }
        for (let attempt = 0; attempt < 80; attempt += 1) {
          recoveryDom = await mainWindow.webContents.executeJavaScript(
            `({
              failure: document.querySelector('.system-banner')?.textContent?.trim() || '',
              notice: document.querySelector('.notice-banner')?.textContent?.trim() || '',
              deviceRows: document.querySelectorAll('.device-table-row').length
            })`,
            true
          )
          if (!recoveryDom.failure && recoveryDom.notice.includes('后端已自动恢复') && recoveryDom.deviceRows > 0) break
          await new Promise((resolve) => setTimeout(resolve, 100))
        }
        await new Promise((resolve) => setTimeout(resolve, 500))
        const stableRecoveryDom = await mainWindow.webContents.executeJavaScript(
          `({
            failure: document.querySelector('.system-banner')?.textContent?.trim() || '',
            notice: document.querySelector('.notice-banner')?.textContent?.trim() || '',
            deviceRows: document.querySelectorAll('.device-table-row').length,
            loading: Boolean(document.querySelector('.navigator-state:not(.error)'))
          })`,
          true
        )
        const backendRecovery = {
          ...stableRecoveryDom,
          firstRecoveredDom: recoveryDom,
          crashStarted: crashed,
          failureBannerSeen,
          requestStatus: recoveryResponse,
          logSettingsRestored,
          runtimeChanged: recoveredRuntime.apiBaseUrl !== beforeRuntime.apiBaseUrl,
          passed: Boolean(
            crashed
              && failureBannerSeen
              && recoveredRuntime.apiBaseUrl !== beforeRuntime.apiBaseUrl
              && recoveryResponse === 200
              && logSettingsRestored
              && !stableRecoveryDom.failure
              && stableRecoveryDom.notice.includes('后端已自动恢复')
              && stableRecoveryDom.deviceRows > 0
              && stableRecoveryDom.loading === false
          )
        }
        console.log(`[renderer] backendRecovery=${JSON.stringify(backendRecovery)}`)
        console.log(`[renderer] backendRecoveryPassed=${backendRecovery.passed}`)
      }
      if (!primaryCaptureWritten) {
        const captureWindow = process.env.DEVICE_TUI_CAPTURE_ACTIVE_WINDOW === '1'
          ? BrowserWindow.getFocusedWindow() || mainWindow
          : mainWindow
        const image = await captureWindow.webContents.capturePage()
        await writeFile(capturePath, image.toPNG())
      }
      app.quit()
      // A renderer with polling timers can keep Electron alive after quit has
      // closed its window. Capture mode is disposable test infrastructure, so
      // keep a bounded exit fallback without affecting normal production runs.
      setTimeout(() => {
        backend.stop()
        app.exit(0)
      }, 1_500).unref()
    }, 2_500)
  }
}

const instanceLock = app.requestSingleInstanceLock()
if (!instanceLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app.whenReady().then(createWindow).catch((error: unknown) => {
    console.error(error)
    app.quit()
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })

  app.on('before-quit', () => backend.stop())
}
