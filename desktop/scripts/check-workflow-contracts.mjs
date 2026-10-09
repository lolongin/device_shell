import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import vm from 'node:vm'
import ts from 'typescript'

const require = createRequire(import.meta.url)
function loadComposable(file) {
  const source = readFileSync(new URL(`../src/renderer/src/composables/${file}.ts`, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } })
  const module = { exports: {} }
  vm.runInNewContext(outputText, { module, exports: module.exports, require: name => name === '../transport/api' ? { desktopApi: {} } : require(name) })
  return module.exports
}

const { ref } = require('vue')
const { useWorkflowNodeConfig } = loadComposable('useWorkflowNodeConfig')
const { buildWorkflowReferences } = loadComposable('workflowReferences')
const actions = [
  { id: 'device.for_each', label: 'Devices', outputFields: [{ name: 'results', label: 'Results', schema: { type: 'array', items: { type: 'object' } } }] },
  { id: 'variable.set', label: 'Variable', outputFields: [{ name: 'value', label: 'Value', schema: {} }] },
]
const loop = { id: 'each', action_id: 'device.for_each', config: { body_mode: 'bounded', body_end: 'capture' } }
const capture = { id: 'capture', action_id: 'variable.set', config: { name: 'version' } }
const save = { id: 'save', action_id: 'result.save', config: {} }
const selectedNode = ref(save)
const context = {
  selected: ref({ nodes: [loop, capture, save], edges: [{ source: 'each', target: 'capture', source_handle: 'loop-body' }, { source: 'capture', target: 'save' }, { source: 'each', target: 'save', source_handle: 'loop-exit' }] }),
  selectedNode, actions, actionsRevision: ref(0), publishedWorkflows: ref([]), subworkflowVersions: ref([]), fieldLabel: name => name,
}
const config = useWorkflowNodeConfig(context)
const references = buildWorkflowReferences({ resultSources: config.resultSources.value })
assert(references.some(item => item.reference === 'each.results.0.value'))
assert(references.some(item => item.reference === 'each.results.0.steps.capture.value'))
assert(config.commandReferences.value.some(item => item.reference === 'each.results.0.steps.capture.value'))
selectedNode.value = { id: 'until', action_id: 'loop.until', config: { condition: '"ready" in result.output' } }
config.loopUntilStopMode.value = 'output_regex'
config.loopUntilPattern.value = String.raw`version \d+\.'quoted'`
assert.equal(config.loopUntilStopMode.value, 'output_regex')
assert.equal(config.loopUntilPattern.value, String.raw`version \d+\.'quoted'`)
assert.equal(selectedNode.value.config.condition, `regex_match(${JSON.stringify(String.raw`version \d+\.'quoted'`)}, result.output)`)
config.loopUntilStopMode.value = 'output_contains'
assert.equal(config.loopUntilPattern.value, String.raw`version \d+\.'quoted'`)
console.log('Workflow contracts: loop fields, command references, regex mode and escaping passed.')
