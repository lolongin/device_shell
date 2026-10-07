const { app, BrowserWindow } = require('electron')
const path = require('node:path')

app.whenReady().then(async () => {
  const window = new BrowserWindow({ show: false, width: 1000, height: 850, webPreferences: { contextIsolation: true } })
  window.webContents.on('console-message', event => {
    if (event.level === 'error') console.error(event.message)
  })
  try {
    await window.loadURL(process.argv[2] || 'http://localhost:5173')
    const result = await window.webContents.executeJavaScript(`(async () => {
      const source = await (await fetch('/src/components/WorkflowSettingsPanel.vue')).text()
      const vueUrl = source.split('from "').map(part => part.split('"')[0]).find(url => url.includes('/vue.js'))
      const { createApp, h, ref, computed, nextTick } = await import(vueUrl)
      const { default: Settings } = await import('/src/components/WorkflowSettingsPanel.vue')
      const { useWorkflowInputs } = await import('/src/composables/useWorkflowInputs.ts')
      const selected = ref({ name: 'Output editor check', outputs: [{ name: 'device_results', type: 'array', value: '$' + '{save_version}' }] })
      const issues = ref([{ code: 'reference_type_mismatch', message: 'expected array' }])
      const error = ref('expected array'), runMessage = ref('expected array')
      const editor = useWorkflowInputs({ selected, selectedNode: ref(null), issues, error, runMessage, transferRoot: computed(() => '') })
      const host = document.createElement('div')
      host.style.cssText = 'position:fixed;inset:0 auto auto 0;width:360px;height:840px;overflow:auto;background:#111c2f;z-index:99999'
      document.body.append(host)
      const instance = createApp({ render: () => h(Settings, {
        workflow: selected.value, hasUnsavedChanges: true, inputValues: {}, inputsExpanded: false, outputsExpanded: true, runtimeInputsExpanded: false,
        workflowInputHasIssue: () => false, workflowInputDisplay: () => '', isWorkflowFileInput: () => false,
        ...editor, outputReferences: [{ reference: 'each.results', label: 'Loop results' }], onOpenTransferSettings: () => {}
      }) })
      instance.mount(host)
      await nextTick()
      const checks = []
      for (const width of [360, 720]) {
        host.style.width = width + 'px'
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
        const controls = [...host.querySelectorAll('.workflow-output-definition input, .workflow-output-definition select, .workflow-output-definition button')]
        for (const control of controls) {
          const box = control.getBoundingClientRect()
          if (box.left < 0 || box.right > width) throw new Error('Output control exceeds panel width: ' + width)
          if (!control.contains(document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2))) throw new Error('Output control is occluded: ' + control.outerHTML)
        }
        const value = host.querySelector('.workflow-output-value input')
        value.focus()
        value.value = '$' + '{each.results}'
        value.dispatchEvent(new Event('input', { bubbles: true }))
        await nextTick()
        if (selected.value.outputs[0].value !== '$' + '{each.results}') throw new Error('Input edit was blocked')
        if (issues.value.length || error.value || runMessage.value) throw new Error('Stale error remains')
        const type = host.querySelectorAll('.workflow-output-definition select')[0]
        type.value = 'object'
        type.dispatchEvent(new Event('change', { bubbles: true }))
        await nextTick()
        if (selected.value.outputs[0].type !== 'object' || selected.value.outputs[0].primitiveType !== 'object') throw new Error('Type edit was blocked')
        checks.push({ width, controls: controls.length, editable: true })
      }
      return checks
    })()`)
    const capture = await window.webContents.capturePage()
    require('node:fs').writeFileSync(path.join(__dirname, '../out/workflow-output-editor.png'), capture.toPNG())
    console.log(JSON.stringify(result))
    app.exit(0)
  } catch (error) {
    console.error(error)
    app.exit(1)
  }
})
