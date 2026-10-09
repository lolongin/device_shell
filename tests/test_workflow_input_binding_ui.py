import json
import subprocess
from pathlib import Path

import pytest

from device_tui.application.workflow_studio.catalog import build_action_catalog


@pytest.mark.parametrize("action_id", ["device.select", "device.connect"])
def test_device_picker_selects_workflow_inputs(action_id: str) -> None:
    script = r"""
      import assert from 'node:assert/strict'
      import fs from 'node:fs'
      import { createRequire } from 'node:module'
      import { build } from 'esbuild'
      import { parse, compileScript } from '@vue/compiler-sfc'
      const require = createRequire(import.meta.url)
      global.window = { localStorage: { getItem: () => null, setItem() {} } }
      const result = await build({
        stdin: { contents: `
          import GenericNodeConfig from './src/renderer/src/components/workflow-config/GenericNodeConfig.vue'
          import { createRenderer, h, reactive, nextTick } from 'vue'
          export async function exercise(actionId) {
            const node = reactive({ id: 'target', action_id: actionId, config: { device_id: 'fixed-device' } })
            const inputs = reactive([{ name: 'target_device', type: 'device' }])
            const changes = []
            const action = JSON.parse(process.argv[2])
            const renderer = createRenderer({
              createElement: tag => ({ tag, props: {}, children: [], parent: null }),
              createText: text => ({ text, children: [] }),
              createComment: text => ({ text, children: [] }),
              setText: (node, text) => { node.text = text },
              setElementText: (node, text) => { node.text = text; node.children = [] },
              patchProp: (node, key, previous, value) => { node.props[key] = value },
              insert: (node, parent, anchor) => { node.parent = parent; const at = anchor ? parent.children.indexOf(anchor) : -1; parent.children.splice(at < 0 ? parent.children.length : at, 0, node) },
              remove: node => { const at = node.parent?.children.indexOf(node); if (at >= 0) node.parent.children.splice(at, 1) },
              parentNode: node => node.parent,
              nextSibling: node => node.parent?.children[node.parent.children.indexOf(node) + 1] || null,
            })
            const root = { children: [] }
            const app = renderer.createApp({ render: () => h(GenericNodeConfig, {
              node, workflowInputs: inputs, availableDevices: [{ id: 'fixed-device', name: 'Fixed' }],
              actions: [action], commandReferences: [], resultSources: [],
              onUpdate: value => changes.push(value.config.device_id),
            }) })
            app.mount(root)
            const walk = element => [element, ...(element.children || []).flatMap(walk)]
            const picker = () => walk(root).find(element => element.tag === 'select' && ['选择设备或变量', '连接目标设备'].includes(element.props['aria-label']))
            const reference = name => '$' + '{inputs.' + name + '}'
            const choose = async name => {
              const control = picker()
              if (!walk(control).some(element => element.tag === 'option' && element.props.value === reference(name))) throw new Error('Workflow input missing from device picker: ' + name)
              control.props.onChange({ target: { value: reference(name) } })
              await nextTick()
              if (node.config.device_id !== reference(name)) throw new Error('Workflow input selection was not saved')
              if (picker().props.value !== reference(name)) throw new Error('Workflow input selection disappeared on render')
            }
            await choose('target_device')
            inputs.push({ name: 'new_target', type: 'string' })
            await nextTick()
            await choose('new_target')
            inputs.push({ name: 'structured_target', type: 'object' })
            await nextTick()
            await choose('structured_target')
            inputs.push({ name: 'device_list', type: 'devices' })
            await nextTick()
            if (walk(picker()).some(element => element.tag === 'option' && element.props.value === reference('device_list'))) throw new Error('Device list must not be offered as a single device')
            app.unmount()
            return changes
          }
        `, resolveDir: process.cwd(), loader: 'ts' },
        plugins: [{ name: 'vue-sfc', setup(builder) {
          builder.onLoad({ filter: /\.vue$/ }, args => {
            const { descriptor } = parse(fs.readFileSync(args.path, 'utf8'), { filename: args.path })
            const compiled = compileScript(descriptor, { id: args.path, inlineTemplate: true, fs: {
              fileExists: fs.existsSync, readFile: filename => fs.readFileSync(filename, 'utf8'),
            } })
            return { contents: compiled.content, loader: 'ts' }
          })
        } }], bundle: true, platform: 'node', format: 'cjs', external: ['vue'], write: false,
      })
      const module = { exports: {} }
      new Function('require', 'exports', 'module', result.outputFiles[0].text)(require, module.exports, module)
      const changes = await module.exports.exercise(process.argv[1])
      assert.equal(changes.length, 3)
    """
    action = build_action_catalog().get(action_id)
    assert action is not None
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script, action_id, json.dumps({"id": action_id, "inputSchema": action.input_schema})],
        cwd="desktop", capture_output=True, text=True, encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr[-5000:]


def test_workflow_editor_input_selection_in_real_dom(tmp_path: Path) -> None:
    """Drive input definitions and node bindings through the complete editor."""
    catalog = build_action_catalog()
    fixture = {
        "actions": [
            {"id": action.id, "name": action.name, "category": action.category,
             "input_schema": action.input_schema, "output_schema": action.output_schema,
             "risk": action.risk}
            for action in catalog.list()
        ],
        "workflows": [
            {"id": "select_flow", "name": "Select regression", "version": "draft",
             "inputs": [], "nodes": [{"id": "target", "action_id": "device.select", "config": {}}], "edges": []},
            {"id": "loop_flow", "name": "Loop regression", "version": "draft",
             "inputs": [{"name": "target_device", "type": "device"}],
             "nodes": [
                 {"id": "each", "action_id": "device.for_each", "config": {"devices": ["fixed-device"], "body_mode": "downstream"}},
                 {"id": "target", "action_id": "device.connect", "config": {"device_id": "${device_id}"}},
             ], "edges": [{"source": "each", "target": "target", "source_handle": "loop-body"}]},
        ],
    }
    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")
    script = r"""
      import fs from 'node:fs'
      import path from 'node:path'
      import { spawnSync } from 'node:child_process'
      import electron from 'electron'
      import { build } from 'esbuild'
      import { parse, compileScript } from '@vue/compiler-sfc'
      const directory = process.argv[1]
      const fixture = fs.readFileSync(path.join(directory, 'fixture.json'), 'utf8')
      const result = await build({
        stdin: { contents: `
          import WorkflowLibrary from './src/renderer/src/components/WorkflowLibrary.vue'
          import WorkflowRunDialog from './src/renderer/src/components/WorkflowRunDialog.vue'
          import { useWorkspaceStore } from './src/renderer/src/stores/workspace'
          import { createApp, nextTick } from 'vue'
          import { createPinia } from 'pinia'
          globalThis.runWorkflowInputRegression = async () => {
            const fixture = ${fixture}
            const saved = []
            const runs = []
            const clone = value => JSON.parse(JSON.stringify(value))
            window.desktopApi = { request: async request => {
              const route = request.path
              let response
              if (route.endsWith('/actions')) response = { actions: fixture.actions }
              else if (route.endsWith('/custom-actions')) response = { actions: [] }
              else if (route.endsWith('/templates')) response = { templates: [] }
              else if (route.endsWith('/scripts')) response = { scripts: [] }
              else if (route.endsWith('/published')) response = { workflows: [{
                id: 'batch', name: 'Batch regression', version: 1, step_count: 1,
                inputs: [{ name: 'devices', type: 'devices', semanticType: 'device_list' }],
              }] }
              else if (route.endsWith('/versions')) response = { versions: [] }
              else if (route.endsWith('/validate')) response = { valid: true, errors: [] }
              else if (route.endsWith('/run')) { runs.push(JSON.parse(request.body)); response = {} }
              else if (request.method === 'PUT') {
                const workflow = JSON.parse(request.body)
                saved.push(clone(workflow))
                fixture.workflows[fixture.workflows.findIndex(item => item.id === workflow.id)] = clone(workflow)
                response = { workflow }
              } else if (route === '/api/v1/workflow-definitions') response = { workflows: clone(fixture.workflows) }
              else throw new Error('Unexpected request: ' + route)
              return { status: 200, body: JSON.stringify(response) }
            } }
            const pinia = createPinia()
            const workspace = useWorkspaceStore(pinia)
            workspace.devices = [
              { id: 'fixed-device', row_id: 'row-1', name: 'Core Router', ssh_endpoint: '10.0.0.1:22', model: 'NE40', status: 'online', cpu: '', domain: '' },
              { id: 'edge-device', row_id: 'row-2', name: 'Edge Switch', telnet_endpoint: '10.0.0.2:23', model: 'S5700', status: 'offline', cpu: '', domain: '' },
            ]
            workspace.ownedDeviceIds = ['fixed-device']
            const app = createApp(WorkflowLibrary).use(pinia)
            app.mount('#app')
            const check = (value, message) => { if (!value) throw new Error(message) }
            const waitFor = async (find, message) => {
              for (let attempt = 0; attempt < 100; attempt++) {
                await nextTick()
                const result = find()
                if (result) return result
                await new Promise(resolve => setTimeout(resolve, 10))
              }
              throw new Error(message)
            }
            const button = text => {
              const found = Array.from(document.querySelectorAll('button')).find(item => item.textContent.trim().startsWith(text))
              check(found, 'Button missing: ' + text)
              return found
            }
            const change = async (element, value, event = 'change') => {
              element.value = value
              element.dispatchEvent(new Event(event, { bubbles: true }))
              await nextTick()
            }
            await waitFor(() => document.querySelector('[aria-label="添加流程输入"]'), 'Workflow settings did not load')
            document.querySelector('button[aria-label="选择运行目标设备"]').click()
            await nextTick()
            await change(document.querySelector('[aria-label="搜索设备"]'), 'EDGE-DEVICE', 'input')
            check(document.querySelectorAll('.workflow-target-option').length === 1 && document.querySelector('.workflow-target-option').textContent.includes('Edge Switch'), 'Toolbar ID filter failed')
            const toolbarMine = document.querySelector('[aria-label="运行目标仅显示我的占用"]')
            toolbarMine.click()
            await nextTick()
            check(!document.querySelectorAll('.workflow-target-option').length, 'Toolbar must combine search and ownership')
            await change(document.querySelector('[aria-label="搜索设备"]'), '', 'input')
            check(document.querySelectorAll('.workflow-target-option').length === 1 && document.querySelector('.workflow-target-option').textContent.includes('Core Router'), 'Toolbar ownership filter failed')
            workspace.ownedDeviceIds = []
            await nextTick()
            check(!document.querySelectorAll('.workflow-target-option').length, 'No owned devices must show no results')
            workspace.ownedDeviceIds = ['fixed-device']
            toolbarMine.click()
            await nextTick()
            check(document.querySelectorAll('.workflow-target-option').length === 2, 'Disabling ownership filter must restore toolbar list')
            button('完成').click()
            await nextTick()
            document.querySelector('[aria-label="添加流程输入"]').click()
            await nextTick()
            const definition = document.querySelector('.workflow-input-definition')
            await change(definition.querySelector('input'), 'target_device', 'input')
            await change(definition.querySelector('select'), 'device')
            const openTarget = async () => {
              const node = await waitFor(() => document.querySelector('.vue-flow__node[data-id="target"]'), 'Canvas target missing')
              node.click()
              return waitFor(() => document.querySelector('select[aria-label="选择设备或变量"], select[aria-label="连接目标设备"]'), 'Node settings did not open')
            }
            const reference = '$' + '{inputs.target_device}'
            let picker = await openTarget()
            check(Array.from(picker.options).some(item => item.value === reference), 'New workflow input missing from real device picker')
            await change(picker, reference)
            check(picker.value === reference, 'Device input selection disappeared in real DOM')
            button('保存草稿').click()
            await waitFor(() => saved.length === 1, 'Selection was not saved')
            check(saved[0].nodes.find(item => item.id === 'target').config.device_id === reference, 'Saved workflow lost input selection')
            button('Loop regression').click()
            picker = await openTarget()
            check(picker.value === '$' + '{device_id}', 'Loop connection must initially use current device')
            await change(picker, reference)
            check(picker.value === reference, 'Loop connection overwrote the chosen workflow input')
            button('保存草稿').click()
            await waitFor(() => saved.length === 2, 'Loop input selection was not saved')
            check(saved[1].nodes.find(item => item.id === 'target').config.device_id === reference, 'Saved loop lost workflow input binding')
            button('Select regression').click()
            picker = await openTarget()
            check(picker.value === reference, 'Reopening workflow lost input binding')
            button('Loop regression').click()
            picker = await openTarget()
            check(picker.value === reference, 'Reopening loop overwrote explicit workflow input')
            document.querySelector('.vue-flow__node[data-id="each"]').click()
            const deviceSearch = await waitFor(() => document.querySelector('[aria-label="筛选遍历设备"]'), 'Device loop search missing')
            const loopOptions = () => Array.from(document.querySelectorAll('.device-for-each-option'))
            await change(deviceSearch, '  s5700  ', 'input')
            check(loopOptions().length === 1 && loopOptions()[0].textContent.includes('edge-device'), 'Loop model filter failed')
            const edgeCheckbox = loopOptions()[0].querySelector('input')
            edgeCheckbox.checked = true
            edgeCheckbox.dispatchEvent(new Event('change', { bubbles: true }))
            await change(deviceSearch, '10.0.0.1 CORE', 'input')
            check(loopOptions().length === 1 && loopOptions()[0].querySelector('input').checked, 'Filtering lost original loop selection')
            await change(deviceSearch, 'missing-device', 'input')
            check(!loopOptions().length && document.querySelector('.device-for-each-empty').textContent.includes('没有匹配'), 'Loop empty results missing')
            await change(deviceSearch, '', 'input')
            check(loopOptions().length === 2 && loopOptions().every(option => option.querySelector('input').checked), 'Clearing loop filter lost hidden selection')
            const loopMine = document.querySelector('[aria-label="遍历设备仅显示我的占用"]')
            loopMine.click()
            await nextTick()
            check(loopOptions().length === 1 && loopOptions()[0].textContent.includes('fixed-device'), 'Loop ownership filter failed')
            await change(deviceSearch, 'S5700', 'input')
            check(!loopOptions().length, 'Loop must combine ownership and model search')
            workspace.ownedDeviceIds = ['edge-device']
            await nextTick()
            check(loopOptions().length === 1 && loopOptions()[0].querySelector('input').checked, 'Loop must react to ownership changes without losing selection')
            loopMine.click()
            await change(deviceSearch, '', 'input')
            check(loopOptions().length === 2 && loopOptions().every(option => option.querySelector('input').checked), 'Ownership filter lost hidden loop selection')
            workspace.ownedDeviceIds = ['fixed-device']
            button('保存草稿').click()
            await waitFor(() => saved.length === 3, 'Filtered device selection was not saved')
            check(JSON.stringify(saved[2].nodes.find(item => item.id === 'each').config.devices) === JSON.stringify(['fixed-device', 'edge-device']), 'Filter changed saved device list')
            app.unmount()
            const runApp = createApp(WorkflowRunDialog, { initialDeviceId: 'fixed-device' }).use(pinia)
            runApp.mount('#app')
            const targetSearch = await waitFor(() => document.querySelector('[aria-label="筛选目标设备"]'), 'Run target search missing')
            const targetOptions = () => Array.from(document.querySelectorAll('[aria-label="目标设备选择"] .workflow-device-option'))
            await change(targetSearch, 'EDGE-DEVICE', 'input')
            check(targetOptions().length === 1 && targetOptions()[0].textContent.includes('Edge Switch'), 'Run device ID filter failed')
            targetOptions()[0].querySelector('input').click()
            await change(targetSearch, '10.0.0.1', 'input')
            check(targetOptions().length === 1 && targetOptions()[0].querySelector('input').checked, 'Run address filter lost prior selection')
            await change(targetSearch, 'absent', 'input')
            check(!targetOptions().length && document.querySelector('[aria-label="目标设备选择"]').textContent.includes('没有匹配'), 'Run empty results missing')
            await change(targetSearch, '   ', 'input')
            check(targetOptions().length === 2 && targetOptions().every(option => option.querySelector('input').checked), 'Run filter lost hidden selection')
            const targetMine = document.querySelector('[aria-label="目标设备仅显示我的占用"]')
            targetMine.click()
            await nextTick()
            check(targetOptions().length === 1 && targetOptions()[0].textContent.includes('Core Router'), 'Run ownership filter failed')
            await change(targetSearch, 'Edge', 'input')
            check(!targetOptions().length, 'Run must combine ownership and search')
            workspace.ownedDeviceIds = ['edge-device']
            await nextTick()
            check(targetOptions().length === 1 && targetOptions()[0].querySelector('input').checked, 'Run ownership changes must preserve selected targets')
            workspace.ownedDeviceIds = []
            await nextTick()
            check(!targetOptions().length, 'Empty occupancy must not show all run targets')
            document.querySelector('.workflow-run-form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
            await waitFor(() => runs.length === 1, 'Filtered targets were not submitted')
            check(JSON.stringify(runs[0].device_ids) === JSON.stringify(['fixed-device', 'edge-device']), 'Filtered run changed target devices')
            check(JSON.stringify(runs[0].inputs.devices) === JSON.stringify(runs[0].device_ids), 'Filtered run changed workflow device input')
            runApp.unmount()
            return 'Workflow input DOM regression passed'
          }
        `, resolveDir: process.cwd(), loader: 'ts' },
        plugins: [{ name: 'vue-sfc', setup(builder) {
          builder.onLoad({ filter: /\.vue$/ }, args => {
            const { descriptor } = parse(fs.readFileSync(args.path, 'utf8'), { filename: args.path })
            const compiled = compileScript(descriptor, { id: args.path, inlineTemplate: true, fs: {
              fileExists: fs.existsSync, readFile: filename => fs.readFileSync(filename, 'utf8'),
            } })
            return { contents: compiled.content, loader: 'ts' }
          })
          builder.onLoad({ filter: /\.css$/ }, () => ({ contents: '', loader: 'js' }))
        } }], bundle: true, platform: 'browser', format: 'iife', write: false,
        define: { 'import.meta.env': '{}', 'process.env.NODE_ENV': '"production"' },
      })
      fs.writeFileSync(path.join(directory, 'bundle.js'), result.outputFiles[0].text)
      fs.writeFileSync(path.join(directory, 'index.html'), '<div id="app"></div>')
      fs.writeFileSync(path.join(directory, 'main.cjs'), `
        const fs = require('node:fs')
        const path = require('node:path')
        const { app, BrowserWindow } = require('electron')
        app.setPath('userData', path.join(__dirname, 'user-data'))
        app.whenReady().then(async () => {
          const window = new BrowserWindow({ show: false, width: 1440, height: 1000 })
          try {
            await window.loadFile(path.join(__dirname, 'index.html'))
            await window.webContents.executeJavaScript(fs.readFileSync(path.join(__dirname, 'bundle.js'), 'utf8'))
            console.log(await window.webContents.executeJavaScript('runWorkflowInputRegression()'))
            app.exit(0)
          } catch (error) { console.error(error.stack); app.exit(1) }
        })
      `)
      const env = { ...process.env }
      delete env.ELECTRON_RUN_AS_NODE
      const execution = spawnSync(electron, [path.join(directory, 'main.cjs')], {
        env, windowsHide: true, encoding: 'utf8', timeout: 30000,
      })
      if (execution.status !== 0) throw new Error(execution.stderr + execution.stdout)
      console.log(execution.stdout)
    """
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(tmp_path)],
        cwd="desktop", capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stderr[-6000:]
