// Runs the real Vue pane and xterm renderer with transport doubles in Chromium.
const { app, BrowserWindow } = require('electron')
const path = require('node:path')
const fs = require('node:fs')

app.whenReady().then(async () => {
  let server
  const timeout = setTimeout(() => { console.error('Terminal layout check timed out'); app.exit(1) }, 30000)
  try {
    const { createServer } = await import('vite')
    const { default: vue } = await import('@vitejs/plugin-vue')
    server = await createServer({
      configFile: false,
      root: path.resolve(__dirname, '../src/renderer'),
      plugins: [vue(), {
        name: 'terminal-layout-fixture',
        configureServer(server) {
          server.middlewares.use('/__terminal-layout', (_req, res) => {
            res.setHeader('Content-Type', 'text/html')
            res.end('<!doctype html><html><body><div id="test"></div></body></html>')
          })
        },
      }],
      server: { host: '127.0.0.1', port: 5199 },
    })
    await server.listen()
    const port = server.httpServer.address().port
    const window = new BrowserWindow({ show: false, width: 1000, height: 640, webPreferences: { backgroundThrottling: false, offscreen: true } })
    await window.loadURL(`http://127.0.0.1:${port}/__terminal-layout`)
    const result = await window.webContents.executeJavaScript(`(async () => {
      const source = await (await fetch('/src/components/TerminalPane.vue')).text()
      const vueUrl = source.split('from "').map(part => part.split('"')[0]).find(url => url.includes('/vue.js'))
      const { createApp, h, ref, nextTick } = await import(vueUrl)
      const { default: Pane } = await import('/src/components/TerminalPane.vue')
      await import('/src/styles.css')
      await import('/@fs/' + ${JSON.stringify(path.resolve(__dirname, '../node_modules/@xterm/xterm/css/xterm.css').replaceAll('\\', '/'))})
      const host = document.querySelector('#test')
      host.style.cssText = 'display:grid;grid-template-rows:minmax(0,1fr);width:733px;height:420px'
      const checks = [], sizes = [], failures = []
      const pause = () => new Promise(resolve => setTimeout(resolve, 200))
      const status = ref('connected'), active = ref(true)
      let dataListener, statusListener
      window.desktopApi = {
        onLocalTerminalData: callback => { dataListener = callback; return () => {} },
        onLocalTerminalStatus: callback => { statusListener = callback; return () => {} },
        subscribeLocalTerminal: async () => ({ session: { sequence: 1, status: 'connected' }, output: '' }),
        resizeLocalTerminal: async (_id, cols, rows) => { sizes.push({ cols, rows }); return true },
        reconnectLocalTerminal: async () => ({ status: 'connected', sequence: 3 }),
        getRuntimeConfig: async () => ({ apiBaseUrl: 'http://127.0.0.1:1' }),
        request: async () => ({ status: 200, body: JSON.stringify({ ticket: 'fixture' }) }),
      }
      function mount(kind) {
        return createApp({ render: () => h(Pane, {
          session: { id: 'fixture', device_id: 'fixture', title: 'Terminal layout', kind, status: status.value },
          active: active.value, protocolActions: [], splitAvailable: false,
        }) }).mount(host)
      }
      let component = mount('local')
      function check(name, condition, details) {
        checks.push({ name, passed: Boolean(condition), details: JSON.parse(JSON.stringify(details)) })
        if (!condition) failures.push(name)
      }
      function geometry() {
        const screen = host.querySelector('.xterm-screen').getBoundingClientRect()
        const bounds = host.querySelector('.terminal-host').getBoundingClientRect()
        return { fits: screen.left >= bounds.left && screen.right <= bounds.right && screen.bottom <= bounds.bottom,
          screenWidth: screen.width, hostWidth: bounds.width }
      }
      await pause()
      check('local initial size synchronized', sizes.length > 0, sizes)
      for (const width of [460, 320, 733]) {
        host.style.width = width + 'px'
        await pause()
        const box = geometry()
        check('screen fits at ' + width, box.fits, box)
      }
      for (const size of [18, 9, 13]) {
        window.dispatchEvent(new CustomEvent('odyterm:terminal-font-size', { detail: size }))
        await pause()
        check('screen fits at font size ' + size, geometry().fits, geometry())
        const appliedSize = Number.parseFloat(getComputedStyle(host.querySelector('.xterm-rows')).fontSize)
        check('font size applied ' + size, appliedSize === size, { appliedSize, grid: sizes.at(-1) })
      }
      // A hidden warm tab must keep its last grid; otherwise incoming output
      // wraps into two columns and cannot be reconstructed when shown again.
      const previous = sizes.at(-1), count = sizes.length
      host.style.display = 'none'
      active.value = false
      await nextTick()
      await pause()
      check('hidden tab keeps size', sizes.length === count, sizes.slice(count))
      dataListener({ sessionId: 'fixture', sequence: 2, data: 'bin     dev     home    initrd.img.old  lib64   media   opt   root   sbin   sys   usr\\r\\n' })
      await pause()
      host.style.display = 'grid'
      active.value = true
      await pause()
      check('restored tab keeps directory columns', ![...host.querySelectorAll('.xterm-rows > div')].some(row => row.textContent.trim() === 'bi'), previous)
      status.value = 'disconnected'
      await nextTick()
      await pause()
      const beforeReconnect = sizes.length
      host.querySelector('.terminal-recovery-banner button').click()
      await pause()
      check('local reconnect synchronizes size', sizes.length > beforeReconnect, sizes.slice(beforeReconnect))
      // Probe remote startup: the socket can open while the SSH handshake is
      // still pending, so connected status must send the final visible size.
      component.$.appContext.app.unmount()
      sizes.length = 0
      status.value = 'connecting'
      let processConnected = false, remoteGrid = { cols: 160, rows: 40 }
      class Socket extends EventTarget {
        static OPEN = 1
        readyState = 1
        constructor() { super(); window.testSocket = this; setTimeout(() => this.dispatchEvent(new Event('open')), 0) }
        send(data) {
          const value = JSON.parse(data)
          if (value.type === 'terminal.resize') {
            sizes.push(value)
            if (processConnected) remoteGrid = value
          }
        }
        close() {}
      }
      window.WebSocket = Socket
      component = mount('ssh')
      await pause()
      const startupCount = sizes.length
      processConnected = true
      window.testSocket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type: 'terminal.status', status: 'connected', sequence: 1 }) }))
      await pause()
      check('remote connected status synchronizes size', sizes.length > startupCount, sizes.slice(startupCount))
      let sequence = 1
      for (const width of [733, 460, 320, 180]) {
        host.style.width = width + 'px'
        await pause()
        check('remote screen fits at ' + width, geometry().fits, geometry())
        const lines = ['bin'.padEnd(remoteGrid.cols - 8) + 'lib64', 'boot'.padEnd(remoteGrid.cols - 8) + 'media']
        window.testSocket.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({
          type: 'terminal.output', sequence: ++sequence, data: '\\x1b[2J\\x1b[H' + lines.join('\\r\\n') + '\\r\\n$ '
        }) }))
        await pause()
        const visibleLines = [...host.querySelectorAll('.xterm-rows > div')].map(row => row.textContent.trimEnd()).filter(Boolean)
        check('directory columns do not wrap at ' + width, JSON.stringify(visibleLines) === JSON.stringify([...lines, '$']), visibleLines)
      }
      host.style.height = '90px'
      await pause()
      check('short pane sends one row', remoteGrid.rows === 1, remoteGrid)
      host.style.width = '460px'
      host.style.height = '420px'
      await pause()
      return { checks, failures }
    })()`)
    const outputDir = path.resolve(__dirname, '../out')
    fs.mkdirSync(outputDir, { recursive: true })
    fs.writeFileSync(path.join(outputDir, 'terminal-layout.png'), (await window.webContents.capturePage()).toPNG())
    console.log(JSON.stringify(result, null, 2))
    clearTimeout(timeout)
    await server.close()
    app.exit(result.failures.length ? 1 : 0)
  } catch (error) {
    console.error(error)
    if (server) await server.close()
    app.exit(1)
  }
})
