import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import electronPath from 'electron'
import { build } from 'esbuild'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
if (!existsSync(path.join(root, 'out/renderer/index.html'))) throw new Error('Run npm run build first.')
const entry = path.join(root, 'out/main/agent-workspace-smoke.cjs')
await build({ entryPoints: [path.join(root, 'scripts/agent-workspace-smoke.ts')], outfile: entry, bundle: true, platform: 'node', format: 'cjs', external: ['electron'] })
const userData = mkdtempSync(path.join(tmpdir(), 'odyterm-agent-smoke-'))
const captureDir = path.join(root, 'out/smoke')
mkdirSync(captureDir, { recursive: true })
const env = { ...process.env, AGENT_SMOKE_CAPTURE_DIR: captureDir }
delete env.ELECTRON_RUN_AS_NODE
delete env.ELECTRON_RENDERER_URL
// Optional Chromium flags support restricted test hosts; production keeps its sandbox.
const child = spawn(electronPath, [entry, `--user-data-dir=${userData}`, ...process.argv.slice(2)], { cwd: root, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
let output = ''
child.stdout.on('data', chunk => { output += chunk; process.stdout.write(chunk) })
child.stderr.on('data', chunk => process.stderr.write(chunk))
const timer = setTimeout(() => child.kill(), 90_000)
const code = await new Promise((resolve, reject) => { child.once('exit', resolve); child.once('error', reject) })
clearTimeout(timer)
// Only this runner's freshly created temporary profile may be removed.
if (path.dirname(userData) !== tmpdir() || !path.basename(userData).startsWith('odyterm-agent-smoke-')) throw new Error('Unexpected smoke profile path')
try { rmSync(userData, { recursive: true, force: true }) } catch { /* Electron may still hold profile locks on Windows. */ }
if (code !== 0 || !output.includes('agentWorkspacePassed=true')) throw new Error(`Agent workspace smoke failed (exit ${code})`)
