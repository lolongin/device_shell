import assert from 'node:assert/strict'
import { createServer } from 'node:http'
import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { app, BrowserWindow, ipcMain, type WebContents } from 'electron'
import { AgentWindow, registerAgentWindowIpc } from '../src/main/agent-window'
import { registerRuntimeIpc } from '../src/main/runtime-ipc'

// Real BrowserWindows, preload, renderer and IPC; deterministic HTTP/model fixture.
const token = 'smoke-main-process-only'
let sequence = 0
const task = { id: 'task-alpha', workflow_id: '检查设备版本', device_id: 'demo-device', status: 'running', progress_percent: 40, message: '检查版本并生成报告' }
type Event = { sequence: number; type: string; data: Record<string, unknown>; created_at: number }
type Conversation = { title: string; busy: boolean; events: Event[]; history: Array<Record<string, unknown>>; approvals: Array<Record<string, unknown>> }
const conversations = new Map<string, Conversation>()
const pending = new Map<string, () => void>()
const controls: string[] = []
function conversation(id: string): Conversation {
  if (!conversations.has(id)) conversations.set(id, { title: id, busy: false, events: [], history: [], approvals: [] })
  return conversations.get(id)!
}
function event(id: string, type: string, data: Record<string, unknown>): void {
  conversation(id).events.push({ sequence: ++sequence, type, data, created_at: Date.now() / 1000 })
}
const alpha = conversation('alpha')
alpha.title = '设备版本检查'
alpha.approvals = [{ id: 'approval-alpha', tool: 'workflow_run', status: 'pending', arguments: { device_id: 'demo-device' }, preview: { workflow: '检查设备版本' }, content_hash: 'fixture', expires_at: Date.now() / 1000 + 3600 }]
event('alpha', 'agent.started', { message: '检查设备版本，执行前请确认。' })
event('alpha', 'agent.message', { content: '已生成检查计划，等待确认后运行。' })
event('alpha', 'agent.tool.output', { tool: 'task_get', output: { task } })
const beta = conversation('beta')
beta.title = '已保存的会话'
beta.history = [{ role: 'user', content: 'saved question' }, { role: 'assistant', content: 'saved response' }]

const server = createServer(async (request, response) => {
  try {
    assert.equal(request.headers.authorization, `Bearer ${token}`)
    const url = new URL(request.url!, 'http://localhost')
    let raw = ''
    for await (const chunk of request) raw += chunk
    const body = raw ? JSON.parse(raw) : {}
    const reply = (payload: unknown): void => { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(payload)) }
    if (url.pathname === '/api/v1/ai/agent/conversations') {
      reply({ conversations: [...conversations].map(([id, item]) => ({ conversation_id: id, title: item.title, last_message: String(item.history.at(-1)?.content || '检查设备与执行记录'), message_count: item.history.length || item.events.length, updated_at: Date.now() / 1000 })) }); return
    }
    if (url.pathname === '/api/v1/ai/chat') {
      const id = body.conversation_id
      const item = conversation(id)
      item.busy = true
      event(id, 'agent.started', { message: body.message })
      if (body.message.startsWith('delayed')) await new Promise<void>(resolve => pending.set(id, resolve))
      item.history.push({ role: 'user', content: body.message }, { role: 'assistant', content: `reply: ${body.message}` })
      event(id, 'agent.message', { content: `reply: ${body.message}` })
      item.busy = false
      reply({ conversation_id: id }); return
    }
    const match = url.pathname.match(/^\/api\/v1\/ai\/agent\/conversations\/([^/]+)(?:\/approvals\/([^/]+)\/(approve|reject))?$/)
    if (match) {
      const [, id, approvalId, decision] = match
      const item = conversation(id)
      if (approvalId) {
        const approval = item.approvals.find(value => value.id === approvalId)!
        approval.status = decision === 'approve' ? 'completed' : 'rejected'
        reply({ approval }); return
      }
      if (request.method === 'PUT') { item.title = body.title; reply({ conversation: { title: item.title } }); return }
      if (request.method === 'DELETE') { conversations.delete(id); reply({ ok: true }); return }
      reply({ cursor: sequence, busy: item.busy, events: item.events.filter(value => value.sequence > Number(url.searchParams.get('after') || 0)), approvals: item.approvals, history: item.history }); return
    }
    const taskMatch = url.pathname.match(/^\/api\/v1\/tasks\/task-alpha(?:\/(pause|resume|cancel))?$/)
    if (taskMatch) {
      const action = taskMatch[1]
      if (action) { controls.push(action); task.status = { pause: 'paused', resume: 'running', cancel: 'cancelled' }[action]! }
      reply({ task }); return
    }
    response.statusCode = 404; reply({ detail: `Unexpected fixture endpoint ${url.pathname}` })
  } catch (error) { response.statusCode = 500; response.end(String(error)) }
})

async function waitFor(check: () => boolean | Promise<boolean>, label: string): Promise<void> {
  const deadline = Date.now() + 12_000
  while (Date.now() < deadline) {
    if (await check()) return
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error(`Timed out: ${label}`)
}
const run = <T = unknown>(contents: WebContents, code: string): Promise<T> => contents.executeJavaScript(code, true)
const click = (contents: WebContents, selector: string): Promise<unknown> => run(contents, `document.querySelector(${JSON.stringify(selector)}).click()`)
const has = (contents: WebContents, text: string): Promise<boolean> => run(contents, `document.body.innerText.includes(${JSON.stringify(text)})`)
const timelineHas = (contents: WebContents, text: string): Promise<boolean> => run(contents, `Boolean(document.querySelector('.agent-timeline')?.innerText.includes(${JSON.stringify(text)}))`)
const ready = (contents: WebContents): Promise<void> => waitFor(() => run(contents, `!!document.querySelector('#agent-message') && !document.querySelector('#agent-message').disabled`), 'composer ready')
async function send(contents: WebContents, message: string): Promise<void> {
  await ready(contents)
  await run(contents, `(() => { const input = document.querySelector('#agent-message'); input.value = ${JSON.stringify(message)}; input.dispatchEvent(new Event('input', { bubbles: true })); })()`)
  await click(contents, '.agent-send')
}
async function denied(contents: WebContents, code: string, reason: string): Promise<void> {
  const error = await run<string>(contents, `(async () => { try { await (${code}); return '' } catch (e) { return String(e) } })()`)
  assert.ok(error.includes(reason), error || 'Expected IPC rejection')
}

app.whenReady().then(async () => {
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const address = server.address() as { port: number }
  const main = new BrowserWindow({ show: false, webPreferences: { preload: path.join(__dirname, '../preload/index.js'), sandbox: true, contextIsolation: true, nodeIntegration: false } })
  await main.loadURL('data:text/html,<title>Agent smoke controller</title>')
  const agent = new AgentWindow()
  registerAgentWindowIpc(ipcMain, () => main.webContents, agent)
  registerRuntimeIpc({ ipcMain, getRenderer: () => main.webContents, getAgentRenderer: () => agent.webContents,
    getRuntime: () => ({ apiBaseUrl: `http://127.0.0.1:${address.port}`, token, apiVersion: 1 }),
    validateRequest: request => { assert.ok(request.path.startsWith('/api/v1/')); assert.ok(!request.path.includes('..')) }
  })
  const open = (id?: string): Promise<unknown> => run(main.webContents, `window.desktopApi.openAgentWindow(${JSON.stringify(id) || ''})`)
  await denied(main.webContents, `window.desktopApi.openAgentWindow('../invalid')`, 'Invalid conversation ID')
  await Promise.all([open('alpha'), open('alpha')])
  const first = agent.webContents!
  const firstId = first.id
  await waitFor(() => has(first, '待确认操作'), 'initial approval')
  assert.equal(BrowserWindow.getAllWindows().length, 2)
  await open('alpha')
  assert.equal(agent.webContents, first)
  assert.ok(BrowserWindow.fromWebContents(first)!.isVisible())
  const runtime = await run<Record<string, unknown>>(first, 'window.desktopApi.getRuntimeConfig()')
  assert.ok(!('token' in runtime))
  assert.equal(await run(first, 'typeof require'), 'undefined')
  await denied(first, `window.desktopApi.request({ path: '/api/v1/devices', method: 'GET' })`, 'Endpoint unavailable')
  await denied(first, 'window.desktopApi.openAgentWindow()', 'Untrusted Agent window caller')
  const untrusted = new BrowserWindow({ show: false, webPreferences: { preload: path.join(__dirname, '../preload/index.js'), sandbox: true, contextIsolation: true } })
  await untrusted.loadURL('data:text/html,untrusted')
  await denied(untrusted.webContents, 'window.desktopApi.getRuntimeConfig()', 'Untrusted runtime caller')
  await denied(untrusted.webContents, `window.desktopApi.request({ path: '/api/v1/ai/agent/conversations' })`, 'Untrusted backend API caller')
  untrusted.destroy()
  await click(first, '.agent-approval-actions .agent-primary')
  await waitFor(() => alpha.approvals[0].status === 'completed', 'approval executed')
  await ready(first)
  await click(first, '.agent-tabs button:nth-child(2)')
  for (const [action, title, status] of [['pause', '暂停任务', 'paused'], ['resume', '恢复任务', 'running'], ['cancel', '取消任务', 'cancelled']]) {
    await waitFor(() => run(first, `!!document.querySelector('[title="${title}"]')`), `${action} control`)
    await click(first, `[title="${title}"]`)
    await waitFor(() => task.status === status, `task ${action}`)
  }
  assert.deepEqual(controls, ['pause', 'resume', 'cancel'])
  await click(first, '.agent-tabs button:first-child')
  await send(first, 'delayed switch')
  await waitFor(() => pending.has('alpha'), 'first pending chat')
  await open('beta')
  await ready(first)
  await waitFor(() => timelineHas(first, 'saved response'), 'persisted history fallback')
  pending.get('alpha')!(); pending.delete('alpha')
  await waitFor(() => !alpha.busy, 'first request completion')
  assert.ok(!(await timelineHas(first, 'reply: delayed switch')), 'stale completion replaced selected conversation')
  assert.equal(await run(first, `localStorage.getItem('odyterm.agent.window-conversation')`), 'beta')
  await open('alpha')
  await ready(first)
  await waitFor(() => timelineHas(first, 'reply: delayed switch'), 'switch back restores response')
  await send(first, 'delayed close')
  await waitFor(() => pending.has('alpha'), 'second pending chat')
  BrowserWindow.fromWebContents(first)!.close()
  await waitFor(() => agent.webContents === null, 'agent closed')
  assert.ok(!main.isDestroyed())
  pending.get('alpha')!(); pending.delete('alpha')
  await waitFor(() => !alpha.busy, 'request completes after close')
  await open()
  const reopened = agent.webContents!
  assert.notEqual(reopened.id, firstId)
  await ready(reopened)
  await waitFor(() => timelineHas(reopened, 'reply: delayed close'), 'reopened history')
  assert.equal(await run(reopened, `localStorage.getItem('odyterm.agent.window-conversation')`), 'alpha')
  // Exercise the shared conversation manager in the full workspace.
  await click(reopened, '.agent-session-list li.active [aria-label="重命名会话"]')
  await run(reopened, `(() => { const input = document.querySelector('[aria-label="会话名称"]'); input.value = '设备检查记录'; input.dispatchEvent(new Event('input', { bubbles: true })); })()`)
  await click(reopened, '[aria-label="保存名称"]')
  await waitFor(() => alpha.title === '设备检查记录', 'rename')
  const window = BrowserWindow.fromWebContents(reopened)!
  const captureDir = process.env.AGENT_SMOKE_CAPTURE_DIR!
  writeFileSync(path.join(captureDir, 'agent-workspace-dark.png'), (await window.capturePage()).toPNG())
  await run(reopened, `localStorage.setItem('odyterm.desktop-v2.theme', 'light'); window.dispatchEvent(new Event('storage'))`)
  window.setSize(860, 620)
  await waitFor(() => run(reopened, 'window.innerWidth <= 860'), 'minimum window size')
  assert.ok(await run(reopened, `(() => { const input = document.querySelector('#agent-message').getBoundingClientRect(); const rail = document.querySelector('.agent-session-manager').getBoundingClientRect(); return document.documentElement.scrollWidth <= innerWidth && input.right <= innerWidth && input.bottom <= innerHeight && input.left >= rail.right })()`), 'minimum size layout overflow')
  writeFileSync(path.join(captureDir, 'agent-workspace-light-min.png'), (await window.capturePage()).toPNG())
  await click(reopened, '.agent-session-create')
  await ready(reopened)
  const createdId = await run<string>(reopened, `localStorage.getItem('odyterm.agent.window-conversation')`)
  assert.notEqual(createdId, 'alpha')
  await send(reopened, 'new conversation')
  await waitFor(() => timelineHas(reopened, 'reply: new conversation'), 'new conversation response')
  await ready(reopened)
  await waitFor(() => run(reopened, `!!document.querySelector('.agent-session-list li.active [aria-label="删除会话"]')`), 'created conversation in list')
  await run(reopened, 'void (window.confirm = () => true)')
  await click(reopened, '.agent-session-list li.active [aria-label="删除会话"]')
  await waitFor(() => !conversations.has(createdId), 'delete conversation')
  console.log('agentWorkspacePassed=true (singleton, IPC, approvals, task controls, switch, close/reopen, history, rename/create/delete, minimum layout)')
  app.exit(0)
}).catch(error => { console.error(error); app.exit(1) })
