// Exercise both context menus in Electron using the actual Vue components.
const { app, BrowserWindow } = require('electron')
const path = require('node:path')
const fs = require('node:fs')

app.whenReady().then(async () => {
  let server
  const timer = setTimeout(() => { console.error('Command menu check timed out'); app.exit(1) }, 30000)
  try {
    const { createServer } = await import('vite')
    const { default: vue } = await import('@vitejs/plugin-vue')
    server = await createServer({
      configFile: false, root: path.resolve(__dirname, '../src/renderer'),
      plugins: [vue(), { name: 'menu-fixture', configureServer(server) {
        server.middlewares.use('/__command-menus', (_req, res) => {
          res.setHeader('Content-Type', 'text/html')
          res.end('<!doctype html><html><body><div id="test"></div></body></html>')
        })
      } }], server: { host: '127.0.0.1', port: 5199 },
    })
    await server.listen()
    const window = new BrowserWindow({ show: false, width: 1000, height: 640, webPreferences: { backgroundThrottling: false, offscreen: true } })
    await window.loadURL(`http://127.0.0.1:${server.httpServer.address().port}/__command-menus`)
    const result = await window.webContents.executeJavaScript(`(async () => {
      const source = await (await fetch('/src/components/CommandWorkspace.vue')).text()
      const storeSource = await (await fetch('/src/stores/workspace.ts')).text()
      const dependency = (source, name) => source.split('from "').map(part => part.split('"')[0]).find(url => url.includes('/' + name + '.js'))
      const { createApp, h, nextTick } = await import(dependency(source, 'vue'))
      const { createPinia } = await import(dependency(storeSource, 'pinia'))
      const { useWorkspaceStore } = await import('/src/stores/workspace.ts')
      const { default: Commands } = await import('/src/components/CommandWorkspace.vue')
      const { default: Quick } = await import('/src/components/QuickActionsBar.vue')
      await import('/src/styles.css')
      const checks = [], errors = [], calls = []
      const pause = () => new Promise(resolve => setTimeout(resolve, 70))
      const check = (name, passed, details) => checks.push({ name, passed: Boolean(passed), details })
      const fixture = [{ id: 'quick-a', type: 'command', name: 'First quick', command: 'test' }, { id: 'quick-b', type: 'workflow', name: 'Second quick', workflowId: 'workflow-b' }]
      localStorage.setItem('odyterm.desktop-v2.quick-actions', JSON.stringify(fixture))
      const pinia = createPinia(), workspace = useWorkspaceStore(pinia)
      workspace.commandGroups = [{ id: 'group-a', name: 'First group', content: 'first draft' }, { id: 'group-b', name: 'Second group', content: 'second draft' }]
      workspace.currentCommandGroupId = 'group-a'
      workspace.commandPanelOpen = true
      workspace.updateCommandGroup = async (id, update) => {
        calls.push({ type: 'rename-group', id, update })
        Object.assign(workspace.commandGroups.find(item => item.id === id), update)
        return true
      }
      workspace.deleteCommandGroup = async id => { calls.push({ type: 'delete-group', id }); workspace.commandGroups = workspace.commandGroups.filter(item => item.id !== id) }
      workspace.createCommandGroup = async () => { calls.push({ type: 'add-group' }); workspace.commandGroups.push({ id: 'group-c', name: 'New group', content: '' }) }
      workspace.dispatchCommand = async () => { calls.push({ type: 'dispatch' }) }
      const instance = createApp({ render: () => [h(Quick, { onRunWorkflow: () => calls.push({ type: 'run-workflow' }) }), h(Commands)] })
      instance.use(pinia)
      instance.config.errorHandler = error => errors.push(String(error))
      const host = document.querySelector('#test')
      host.style.cssText = 'position:fixed;left:180px;right:40px;bottom:24px'
      instance.mount(host)
      await pause()
      function open(selector, pointOverride) {
        const trigger = document.querySelector(selector)
        const box = trigger.getBoundingClientRect()
        const point = pointOverride || { x: box.left + box.width / 2, y: box.top + box.height / 2 }
        trigger.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: point.x, clientY: point.y }))
        return point
      }
      function positioned(selector, point, openUpward = false) {
        const menu = document.querySelector(selector), box = menu.getBoundingClientRect()
        const y = openUpward && point.y + box.height > innerHeight - 8 ? point.y - box.height : point.y
        const expected = { x: Math.min(point.x, innerWidth - box.width - 8), y: Math.max(8, Math.min(y, innerHeight - box.height - 8)) }
        const button = menu.querySelector('button'), item = button.getBoundingClientRect()
        return { placed: Math.abs(box.left - expected.x) < 2 && Math.abs(box.top - expected.y) < 2,
          clickable: button.contains(document.elementFromPoint(item.left + item.width / 2, item.top + item.height / 2)),
          actual: { x: box.left, y: box.top }, expected }
      }
      const groupPoint = open('.command-tab:nth-child(2) [role="tab"]')
      await pause()
      const groupPosition = positioned('.command-context-menu', groupPoint, true)
      check('group menu at pointer and clickable', groupPosition.placed && groupPosition.clickable, groupPosition)
      const tabBox = document.querySelector('.command-tab:nth-child(2)').getBoundingClientRect()
      for (const point of [{ x: tabBox.left + 2, y: tabBox.top + 3 }, { x: tabBox.right - 2, y: tabBox.bottom - 3 }]) {
        open('.command-tab:nth-child(2)', point)
        await pause()
        const position = positioned('.command-context-menu', point, true)
        check('bottom tab menu follows click at ' + point.x + ',' + point.y, position.placed && position.clickable, position)
      }
      document.querySelector('.command-context-menu button').click()
      await pause()
      const groupName = document.querySelector('input[aria-label="页签名称"]')
      check('rename targets right-clicked group', groupName?.value === 'Second group', groupName?.value)
      if (groupName) {
        groupName.value = 'Renamed group'; groupName.dispatchEvent(new Event('input', { bubbles: true }))
        groupName.closest('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
        await pause()
      }
      check('group rename persisted to correct ID', calls.some(call => call.type === 'rename-group' && call.id === 'group-b' && call.update.name === 'Renamed group'), calls)
      check('active editor draft preserved', document.querySelector('textarea[aria-label="常用命令"]').value === 'first draft')
      const quickPoint = open('.quick-action-button:nth-of-type(3)')
      await pause()
      const quickPosition = positioned('.quick-actions-context', quickPoint)
      check('quick menu at pointer and clickable', quickPosition.placed && quickPosition.clickable, quickPosition)
      document.querySelector('.quick-actions-context button').click()
      await pause()
      const quickDialog = document.querySelector('[role="dialog"]')
      check('quick rename opens editable dialog', Boolean(quickDialog?.querySelector('input')), errors)
      if (quickDialog?.querySelector('input')) {
        const input = quickDialog.querySelector('input')
        input.value = 'Renamed quick'; input.dispatchEvent(new Event('input', { bubbles: true }))
        quickDialog.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
        await pause()
      }
      const persisted = JSON.parse(localStorage.getItem('odyterm.desktop-v2.quick-actions'))
      check('quick rename persisted to correct ID', persisted[1].name === 'Renamed quick' && persisted[0].name === 'First quick', persisted)
      open('.command-tab:nth-child(2) [role="tab"]')
      await pause()
      open('.quick-action-button:nth-of-type(3)')
      await pause()
      check('only one context menu remains open', !document.querySelector('.command-context-menu') && Boolean(document.querySelector('.quick-actions-context')))
      const firstPoint = open('.quick-action-button:nth-of-type(2)')
      await pause()
      const reopened = positioned('.quick-actions-context', firstPoint)
      check('open quick menu follows next right click', reopened.placed && reopened.clickable && document.querySelector('.quick-actions-context strong').textContent === 'First quick', reopened)
      document.querySelector('.quick-actions-context').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await pause()
      check('escape closes menu and restores trigger focus', !document.querySelector('.quick-actions-context') && document.activeElement === document.querySelector('.quick-action-button:nth-of-type(2)'))
      open('.quick-action-button:nth-of-type(3)')
      await pause()
      document.querySelector('.quick-actions-context button').click()
      await pause()
      document.querySelector('[role="dialog"]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
      await pause()
      check('cancel quick rename preserves saved name', !document.querySelector('[role="dialog"]') && JSON.parse(localStorage.getItem('odyterm.desktop-v2.quick-actions'))[1].name === 'Renamed quick')
      let confirmResult = false
      window.confirm = () => confirmResult
      open('.command-tab:nth-child(2) [role="tab"]')
      await pause()
      document.querySelector('.command-context-menu .danger-menu-item').click()
      await pause()
      check('cancel group deletion preserves group', workspace.commandGroups.some(item => item.id === 'group-b'))
      confirmResult = true
      open('.command-tab:nth-child(2) [role="tab"]')
      await pause()
      document.querySelector('.command-context-menu .danger-menu-item').click()
      await pause()
      check('delete targets right-clicked group', calls.some(call => call.type === 'delete-group' && call.id === 'group-b') && workspace.commandGroups.length === 1 && workspace.commandGroups[0].id === 'group-a')
      open('.command-tab [role="tab"]')
      await pause()
      check('last group cannot be deleted from menu', !document.querySelector('.command-context-menu .danger-menu-item'))
      document.querySelector('.command-context-menu button:nth-of-type(2)').click()
      await pause()
      check('new group menu action works', calls.some(call => call.type === 'add-group'))
      confirmResult = false
      open('.quick-action-button:nth-of-type(3)')
      await pause()
      document.querySelector('.quick-actions-context .danger').click()
      await pause()
      check('cancel quick removal preserves shortcut', JSON.parse(localStorage.getItem('odyterm.desktop-v2.quick-actions')).length === 2)
      confirmResult = true
      document.querySelector('.quick-actions-context .danger').click()
      await pause()
      const remaining = JSON.parse(localStorage.getItem('odyterm.desktop-v2.quick-actions'))
      check('remove targets right-clicked shortcut', remaining.length === 1 && remaining[0].id === 'quick-a', remaining)
      check('context actions never execute commands or workflows', !calls.some(call => ['dispatch', 'run-workflow'].includes(call.type)))
      check('no renderer exceptions', errors.length === 0, errors)
      return { checks, passed: checks.every(item => item.passed) }
    })()`)
    fs.mkdirSync(path.resolve(__dirname, '../out'), { recursive: true })
    fs.writeFileSync(path.resolve(__dirname, '../out/command-menus.png'), (await window.webContents.capturePage()).toPNG())
    console.log(JSON.stringify(result, null, 2))
    clearTimeout(timer)
    await server.close()
    app.exit(result.passed ? 0 : 1)
  } catch (error) {
    console.error(error)
    if (server) await server.close()
    app.exit(1)
  }
})
