// Exercise draft navigation with the real Studio and App panel handlers in Electron.
const { app, BrowserWindow } = require('electron')
const path = require('node:path')
const fs = require('node:fs')

app.whenReady().then(async () => {
  let server
  const timer = setTimeout(() => { console.error('Draft navigation check timed out'); app.exit(1) }, 40000)
  try {
    const { createServer } = await import('vite')
    const { default: vue } = await import('@vitejs/plugin-vue')
    const { transform } = await import('esbuild')
    const appSource = fs.readFileSync(path.resolve(__dirname, '../src/renderer/src/App.vue'), 'utf8')
    const handlerNames = ['setSection', 'openSessionTransfer', 'openSessionUpgrade', 'toggleTransferPanel', 'toggleWorkflowPanel', 'closeWorkflowPanel', 'toggleUpgradePanel', 'togglePackageBuildPanel']
    const handlerSource = handlerNames.map(name => {
      const start = appSource.indexOf('async function ' + name + '(')
      if (start < 0) throw new Error('Missing async App handler: ' + name)
      return appSource.slice(start, appSource.indexOf('\n}', start) + 2)
    }).join('\n')
    const { code: handlers } = await transform(handlerSource, { loader: 'ts' })
    server = await createServer({
      configFile: false, root: path.resolve(__dirname, '../src/renderer'),
      plugins: [vue(), { name: 'draft-fixture', configureServer(server) {
        server.middlewares.use('/__workflow-drafts', (_req, res) => {
          res.setHeader('Content-Type', 'text/html')
          res.end('<!doctype html><html><body><div id="test"></div></body></html>')
        })
      } }], server: { host: '127.0.0.1', port: 5199 },
    })
    await server.listen()
    const window = new BrowserWindow({ show: false, width: 1200, height: 800, webPreferences: { backgroundThrottling: false, offscreen: true } })
    window.webContents.on('console-message', event => {
      if (event.level === 'error') console.error(event.message)
    })
    await window.loadURL(`http://127.0.0.1:${server.httpServer.address().port}/__workflow-drafts`)
    const result = await window.webContents.executeJavaScript(`(async () => {
      const source = await (await fetch('/src/components/WorkflowLibrary.vue')).text()
      const storeSource = await (await fetch('/src/stores/workspace.ts')).text()
      const dependency = (source, name) => source.split('from "').map(part => part.split('"')[0]).find(url => url.includes('/' + name + '.js'))
      const { createApp, h, nextTick, ref, KeepAlive } = await import(dependency(source, 'vue'))
      const { createPinia } = await import(dependency(storeSource, 'pinia'))
      const { useWorkspaceStore } = await import('/src/stores/workspace.ts')
      const { default: Studio } = await import('/src/components/WorkflowLibrary.vue')
      const clone = value => JSON.parse(JSON.stringify(value))
      const workflows = ['a', 'b'].map(id => ({ id, name: 'Flow ' + id, version: 'draft', inputs: [], outputs: [], nodes: [{ id: 'target', action_id: 'device.select', config: {} }], edges: [] }))
      const scripts = ['a', 'b'].map(id => ({ id: 'script-' + id, name: 'Script ' + id, description: '', language: 'python', script: 'def main(): return 1', input_schema: [], entrypoint: '', input_schema_source: 'manual' }))
      const checks = [], errors = [], writes = []
      const check = (name, passed) => { checks.push({ name, passed: Boolean(passed) }); if (!passed) throw new Error(name) }
      const pause = () => new Promise(resolve => setTimeout(resolve, 20))
      const waitFor = async predicate => { for (let i = 0; i < 100; i++) { await nextTick(); if (predicate()) return; await pause() }; throw new Error('Waiting for editor timed out') }
      let fail = false, release, hold = false, confirmations = 0
      window.confirm = () => { confirmations++; return false }
      window.desktopApi = { request: async request => {
        const route = request.path
        let response
        if (request.method === 'PUT') {
          const payload = JSON.parse(request.body)
          writes.push(clone(payload))
          if (hold) { hold = false; await new Promise(resolve => { release = resolve }) }
          if (fail) return { status: 503, body: JSON.stringify({ detail: 'fixture unavailable' }) }
          const collection = route.includes('/scripts/') ? scripts : workflows
          collection[collection.findIndex(item => item.id === payload.id)] = clone(payload)
          response = route.includes('/scripts/') ? { script: payload } : { workflow: payload }
        } else if (route.endsWith('/validate')) throw new Error('Draft navigation must allow unfinished nodes')
        else if (route.endsWith('/actions') || route.endsWith('/custom-actions')) response = { actions: [] }
        else if (route.endsWith('/templates')) response = { templates: [] }
        else if (route.endsWith('/scripts')) response = { scripts: clone(scripts) }
        else if (route.endsWith('/versions')) response = { versions: [] }
        else if (route.endsWith('/published')) response = { workflows: [] }
        else if (route === '/api/v1/workflow-definitions') response = { workflows: clone(workflows) }
        else throw new Error('Unexpected request ' + route)
        return { status: 200, body: JSON.stringify(response) }
      } }
      const pinia = createPinia(), workspace = useWorkspaceStore(pinia)
      const workflowPanelOpen = ref(true), workflowLibraryRef = ref(null), activeSection = ref('devices'), selectedProfileId = ref('')
      const setNavigatorVisible = () => {}
      workspace.profiles = []
      ${handlers}
      const instance = createApp({ render: () => h(KeepAlive, null, () => workflowPanelOpen.value ? h(Studio, { ref: workflowLibraryRef, onClose: () => { workflowPanelOpen.value = false } }) : null) })
      instance.use(pinia)
      instance.config.errorHandler = error => errors.push(String(error))
      instance.mount('#test')
      await waitFor(() => workflowLibraryRef.value?.$?.setupState.selected)
      const editor = workflowLibraryRef.value.$.setupState
      const reopen = async () => { workflowPanelOpen.value = true; await nextTick(); check('cached editor retained', workflowLibraryRef.value.$.setupState === editor) }
      const count = writes.length
      await editor.selectWorkflow(editor.workflows[1])
      check('clean switching makes no save request', writes.length === count && editor.selected.id === 'b')
      editor.selected.name = 'Edited unfinished draft'
      await editor.selectWorkflow(editor.workflows[0])
      check('workflow switch persists unfinished draft', workflows[1].name === 'Edited unfinished draft' && editor.selected.id === 'a')
      editor.selected.name = 'Retain after failure'
      fail = true
      await editor.selectWorkflow(editor.workflows[1])
      check('failed workflow switch retains selection and edits', editor.selected.id === 'a' && editor.selected.name === 'Retain after failure' && editor.hasUnsavedChanges)
      await toggleTransferPanel()
      check('failed save keeps Studio open and target panel closed', workflowPanelOpen.value && !workspace.transferPanelOpen && editor.error.includes('fixture unavailable'))
      fail = false
      await toggleTransferPanel()
      check('retry saves then switches panel', !workflowPanelOpen.value && workspace.transferPanelOpen && workflows[0].name === 'Retain after failure')
      await reopen()
      // Switch the selected script before leaving: every dirty script must be saved.
      editor.scripts[0].script = 'def main(): return 2'
      editor.workflowScripts.selectedScriptId.value = 'script-b'
      editor.scripts[1].script = 'def main(): return 3'
      await toggleWorkflowPanel()
      check('exit saves edits in selected and unselected scripts', scripts[0].script.endsWith('2') && scripts[1].script.endsWith('3') && !workflowPanelOpen.value)
      await reopen()
      editor.scripts[0].name = ''
      const invalid = await workflowLibraryRef.value.requestClose()
      check('invalid script draft stays available with inline error', !invalid && workflowPanelOpen.value && editor.scripts[0].name === '' && editor.error.includes('名称不能为空'))
      editor.scripts[0].name = 'Script a'
      workspace.transferPanelOpen = false
      editor.selected.name = 'First pending edit'
      hold = true
      const opening = openSessionUpgrade('session-fixture')
      await waitFor(() => release)
      check('panel switch waits for pending save', workflowPanelOpen.value && !workspace.upgradePanelOpen)
      check('pending navigation displays saving state', document.querySelector('[role="status"]')?.textContent.includes('正在保存'))
      const repeated = await workflowLibraryRef.value.requestClose()
      check('repeated navigation does not launch a second save', !repeated && writes.filter(item => item.name === 'First pending edit').length === 1)
      editor.selected.name = 'Latest pending edit'
      release(); release = undefined
      await opening
      check('late edit is persisted before exit', workflows[0].name === 'Latest pending edit' && !workflowPanelOpen.value && workspace.activeSessionId === 'session-fixture')
      await reopen()
      editor.scripts[0].script = 'def main(): return 4'
      hold = true
      const leaving = setSection('server')
      await waitFor(() => release)
      editor.scripts[0].script = 'def main(): return 5'
      release(); release = undefined
      await leaving
      check('late script edit is persisted before exit', scripts[0].script.endsWith('5') && activeSection.value === 'server' && !workflowPanelOpen.value)
      for (const [name, navigate] of [
        ['device section', () => setSection('devices')],
        ['session transfer', () => openSessionTransfer('session-2')],
        ['transfer panel', () => { workspace.transferPanelOpen = false; return toggleTransferPanel() }],
        ['package panel', () => { workspace.packageBuildPanelOpen = false; return togglePackageBuildPanel() }],
        ['upgrade panel', () => { workspace.upgradePanelOpen = false; return toggleUpgradePanel() }],
      ]) {
        await reopen()
        editor.selected.description = name
        await navigate()
        check(name + ' saves before navigation', !workflowPanelOpen.value && workflows[0].description === name)
      }
      await reopen()
      const beforeCleanExit = writes.length
      document.querySelector('.workflow-library-header button[title="关闭"]').click()
      await waitFor(() => !workflowPanelOpen.value)
      check('clean header close makes no save request', writes.length === beforeCleanExit)
      check('navigation never opens a confirmation dialog', confirmations === 0)
      check('no Vue errors', errors.length === 0)
      instance.unmount()
      return { checks, errors }
    })().catch(error => { console.error(error.stack); throw error })`)
    console.log(JSON.stringify(result, null, 2))
    if (result.checks.some(check => !check.passed) || result.errors.length) throw new Error('Draft navigation checks failed')
    clearTimeout(timer)
    window.destroy()
    await server.close()
    app.exit(0)
  } catch (error) {
    console.error(error)
    clearTimeout(timer)
    if (server) await server.close()
    app.exit(1)
  }
})
