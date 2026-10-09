import subprocess

import pytest


@pytest.mark.parametrize("scenario", [
    "serial", "no_device", "temporary", "changed_focus", "closed", "disconnected",
    "quick_action", "switch_device", "choose_telnet", "batch", "batch_disconnected",
])
def test_quick_workflow_uses_the_selected_terminal_session(scenario: str) -> None:
    script = r"""
      const assert = require('node:assert/strict')
      const fs = require('node:fs')
      const { parse, compileScript } = require('@vue/compiler-sfc')
      const ts = require('typescript')
      const vue = require('vue')
      const scenario = process.argv[1]
      const serial = { id: 'serial-session', device_id: 'router-1', kind: 'serial', title: 'COM3', status: 'connected' }
      const telnet = { id: 'telnet-session', device_id: 'router-1', kind: 'telnet', title: 'Telnet', status: 'connected' }
      const other = { id: 'other-session', device_id: 'router-2', kind: 'ssh', title: 'Other', status: 'connected' }
      const workspace = vue.reactive({
        selectedDeviceId: scenario === 'no_device' || scenario === 'temporary' ? '' : 'router-1',
        devices: scenario === 'temporary' ? [] : [{ id: 'router-1', row_id: 'row-1', name: 'Router' }],
        sessions: [telnet, serial], activeSessionId: serial.id, tasks: [],
        selectDevice() {},
        get activeSession() { return this.sessions.find(item => item.id === this.activeSessionId) || null }
      })
      const calls = [], events = [], mounted = []
      const workflow = { id: 'workflow', version: 1, name: 'Command', inputs: [], requires_confirmation: false }
      if (scenario.startsWith('batch')) workflow.inputs = [{ name: 'devices', type: 'devices', semanticType: 'device_list' }]
      const api = {
        publishedWorkflowDefinitions: async () => ({ workflows: [workflow] }),
        runWorkflowDefinition: async (id, payload) => { calls.push(payload); return {} }
      }
      global.localStorage = { getItem: () => '[]', setItem() {} }
      function setup(filename, props) {
        const { descriptor } = parse(fs.readFileSync(filename, 'utf8'))
        const source = compileScript(descriptor, { id: 'session-test' }).content
        const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
        const exports = {}
        function dependencies(id) {
          if (id === 'vue') return { ...vue, onMounted: fn => mounted.push(fn), onBeforeUnmount() {} }
          if (id.endsWith('/stores/workspace')) return { useWorkspaceStore: () => workspace }
          if (id.endsWith('/transport/api')) return { desktopApi: api }
          if (id.endsWith('/useDialogFocus')) return { useDialogFocus: () => ({ handleDialogKeydown() {} }) }
          if (id.endsWith('/useWorkflowPlatform')) return { createWorkflowPlatformAdapter: () => ({}) }
          if (id.endsWith('/contextMenu')) return { announceContextMenuOpen() {}, subscribeContextMenuOpen() {} }
          if (id === '../app/session-display' || id === '../sessionStatus') {
            const helper = fs.readFileSync('src/renderer/src/' + id.slice(3) + '.ts', 'utf8')
            const compiledHelper = ts.transpileModule(helper, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
            const helperExports = {}
            new Function('require', 'exports', compiledHelper)(dependencies, helperExports)
            return helperExports
          }
          if (id === 'lucide-vue-next') return {}
          if (id === './workflow/device-filter') {
            const helper = fs.readFileSync('src/renderer/src/components/workflow/device-filter.ts', 'utf8')
            const helperExports = {}
            new Function('exports', ts.transpileModule(helper, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText)(helperExports)
            return helperExports
          }
          return require(id)
        }
        new Function('require', 'exports', compiled)(dependencies, exports)
        return exports.default.setup(props, { expose() {}, emit: (...args) => events.push(args) })
      }
      ;(async () => {
        if (scenario === 'quick_action') {
          const quick = setup('src/renderer/src/components/QuickActionsBar.vue', {})
          await quick.activate({ type: 'workflow', workflowId: 'workflow' })
          assert.equal(events[0][1].sessionId, serial.id, 'quick action must capture the serial session')
          assert.equal(events[0][1].deviceId, serial.device_id)
          return
        }
        const runner = setup('src/renderer/src/components/WorkflowRunDialog.vue', {
          initialDeviceId: workspace.selectedDeviceId, initialWorkflowId: 'workflow',
          initialSessionId: serial.id, autoRun: !['switch_device', 'choose_telnet'].includes(scenario)
        })
        if (scenario === 'changed_focus') workspace.activeSessionId = telnet.id
        if (scenario === 'closed') workspace.sessions = [telnet]
        if (scenario === 'disconnected' || scenario === 'batch_disconnected') workspace.sessions[1].status = 'disconnected'
        for (const hook of mounted) await hook()
        if (['closed', 'disconnected', 'batch_disconnected'].includes(scenario)) {
          await runner.runWorkflow()
          assert.equal(calls.length, 0, 'closed serial session must not fall back to Telnet')
          assert.equal(runner.dialogVisible.value, true)
          return
        }
        if (scenario === 'switch_device') {
          workspace.devices.push({ id: 'router-2', row_id: 'row-2', name: 'Other' })
          workspace.sessions.push(other)
          runner.selectedDeviceId.value = other.device_id
          await vue.nextTick()
          await runner.runWorkflow()
          assert.equal(calls[0].device_id, other.device_id)
          assert.equal(calls[0].session_id, other.id, 'changing devices must clear the serial session')
          assert.equal(calls[0].protocol, 'ssh')
          return
        }
        if (scenario === 'choose_telnet') {
          runner.selectedSessionId.value = telnet.id
          await runner.runWorkflow()
          assert.equal(calls[0].session_id, telnet.id)
          assert.equal(calls[0].protocol, 'telnet')
          return
        }
        if (scenario === 'batch') {
          runner.selectedTargetDeviceIds.value = [serial.device_id, other.device_id]
          await runner.runWorkflow()
          assert.equal(calls.length, 1)
          assert.deepEqual(calls[0].device_ids, [serial.device_id, other.device_id])
          assert.deepEqual(calls[0].session_ids, { [serial.device_id]: serial.id })
          assert.equal(calls[0].session_id, undefined, 'serial session must not apply to other devices')
          assert.equal(calls[0].protocol, 'auto')
          return
        }
        assert.equal(calls.length, 1, 'quick workflow should run using the active terminal without a selected device')
        assert.equal(calls[0].session_id, serial.id, 'workflow was sent to Telnet instead of serial')
        assert.equal(calls[0].device_id, serial.device_id)
        assert.equal(calls[0].protocol, 'serial')
      })().catch(error => { console.error(error); process.exitCode = 1 })
    """
    result = subprocess.run(
        ["node", "--eval", script, scenario], cwd="desktop", capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr[-3000:]
