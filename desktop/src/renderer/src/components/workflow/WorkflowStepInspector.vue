<script setup lang="ts">
import WorkflowActionPreview from '../workflow-config/WorkflowActionPreview.vue'
import WorkflowNodeProperties from '../workflow-config/WorkflowNodeProperties.vue'
import AdvancedNodeConfig from '../workflow-config/AdvancedNodeConfig.vue'
import type { ActionItem } from '../workflow-config/types'

type Action = ActionItem
type Node = { id: string; action_id: string; config: Record<string, unknown>; input_mapping?: Record<string, unknown>; position?: { x: number; y: number } }
type Callback = (...args: any[]) => unknown
const props = defineProps<{
  selectedCatalogAction: Action | null
  selectedNode: Node | null
  deviceLoopId: string
  availableDevices: any[]
  workflowInputs: any[]
  commandReferences: any[]
  resultSources: any[]
  scripts: any[]
  actions: Action[]
  nodeOptions: Array<{ id: string; label: string }>
  predecessorId: string
  successorId: string
  scriptSaving: boolean
  workflow: any
  publishedWorkflows: any[]
  subworkflowVersions: any[]
  selectedSubworkflow: any
  loopChildActions: Action[]
  advancedNode: boolean
  loopItemsMode: any
  loopItemsSourceId: string
  loopItemsField: string
  loopUntilStopMode: any
  loopUntilPattern: string
  conditionRules: any[]
  conditionLogicalOperator: any
  conditionTargets: { trueTarget: string; falseTarget: string }
  variableValueSourceId: string
  variableValueField: string
  variableExtractEnabled: boolean
  configString: (key: string) => string
  variableExtractString: (key: string) => string
  variableExtractConfig: () => Record<string, unknown>
  onSetPredecessor: (id: string) => void | Promise<void>
  onSetSuccessor: (id: string) => void | Promise<void>
  onRename: Callback
  onRemove: Callback
  onTest: Callback
  onSaveAsAction: Callback
  onOpenScriptStudio: Callback
  onSaveScript: Callback
  onChooseUploadSource: Callback
  onSelectSubworkflow: (id: string) => void
  onSelectSubworkflowVersion: Callback
  onUpdateSubworkflowInput: Callback
  onUpdateConfigString: Callback
  onUpdateConfigJson: Callback
  onSetLoopItemsSource: Callback
  onSetLoopItemsField: Callback
  onSetVariableValueReference: Callback
  onToggleVariableExtract: Callback
  onUpdateVariableExtractString: Callback
  onUpdateVariableExtractMode: Callback
  onUpdateVariableExtractNumber: Callback
  onUpdateVariableExtractBoolean: Callback
  onSetConditionTarget: Callback
  onAddCondition: Callback
  onResultFieldChange: Callback
}>()
const emit = defineEmits<{ update: [value: any]; 'update:loopItemsMode': [value: any]; 'update:loopUntilStopMode': [value: any]; 'update:loopUntilPattern': [value: any]; 'update-condition-operator': [value: any] }>()
</script>

<template>
  <WorkflowActionPreview v-if="props.selectedCatalogAction" :action="props.selectedCatalogAction" />
  <WorkflowNodeProperties
    v-else-if="props.selectedNode"
    :node="props.selectedNode"
    :device-loop-id="props.deviceLoopId"
    :available-devices="props.availableDevices"
    :workflow-inputs="props.workflowInputs"
    :command-references="props.commandReferences"
    :result-sources="props.resultSources"
    :scripts="props.scripts"
    :actions="props.actions"
    :node-options="props.nodeOptions"
    :predecessor-id="props.predecessorId"
    :successor-id="props.successorId"
    :script-saving="props.scriptSaving"
    @update="emit('update', $event)"
    @update:predecessor-id="props.onSetPredecessor"
    @update:successor-id="props.onSetSuccessor"
    @rename="props.onRename"
    @remove="props.onRemove"
    @test="props.onTest"
    @save-as-action="props.onSaveAsAction"
    @open-script-studio="props.onOpenScriptStudio"
    @save-script="props.onSaveScript"
    @choose-upload-source="props.onChooseUploadSource"
  >
    <AdvancedNodeConfig
      v-if="props.advancedNode"
      :node="props.selectedNode"
      :available-devices="props.availableDevices"
      :workflow-inputs="props.workflowInputs"
      :workflow="props.workflow"
      :published-workflows="props.publishedWorkflows"
      :subworkflow-versions="props.subworkflowVersions"
      :selected-subworkflow="props.selectedSubworkflow"
      :result-sources="props.resultSources"
      :actions="props.actions"
      :loop-child-actions="props.loopChildActions"
      :loop-items-mode="props.loopItemsMode"
      :loop-items-source-id="props.loopItemsSourceId"
      :loop-items-field="props.loopItemsField"
      :loop-until-stop-mode="props.loopUntilStopMode"
      :loop-until-pattern="props.loopUntilPattern"
      :condition-rules="props.conditionRules"
      :condition-logical-operator="props.conditionLogicalOperator"
      :condition-targets="props.conditionTargets"
      :variable-value-source-id="props.variableValueSourceId"
      :variable-value-field="props.variableValueField"
      :variable-extract-enabled="props.variableExtractEnabled"
      :config-string="props.configString"
      :variable-extract-string="props.variableExtractString"
      :variable-extract-config="props.variableExtractConfig"
      :on-select-subworkflow="props.onSelectSubworkflow"
      :on-select-subworkflow-version="props.onSelectSubworkflowVersion"
      :on-update-subworkflow-input="props.onUpdateSubworkflowInput"
      :on-update-config-string="props.onUpdateConfigString"
      :on-update-config-json="props.onUpdateConfigJson"
      :on-set-loop-items-source="props.onSetLoopItemsSource"
      :on-set-loop-items-field="props.onSetLoopItemsField"
      :on-set-variable-value-reference="props.onSetVariableValueReference"
      :on-toggle-variable-extract="props.onToggleVariableExtract"
      :on-update-variable-extract-string="props.onUpdateVariableExtractString"
      :on-update-variable-extract-mode="props.onUpdateVariableExtractMode"
      :on-update-variable-extract-number="props.onUpdateVariableExtractNumber"
      :on-update-variable-extract-boolean="props.onUpdateVariableExtractBoolean"
      :on-set-condition-target="props.onSetConditionTarget"
      :on-add-condition="props.onAddCondition"
      :on-result-field-change="props.onResultFieldChange"
      @update="emit('update', $event)"
      @loop-items-mode="emit('update:loopItemsMode', $event)"
      @loop-until-stop-mode="emit('update:loopUntilStopMode', $event)"
      @update:loop-until-pattern="emit('update:loopUntilPattern', $event)"
      @update-condition-operator="emit('update-condition-operator', $event)"
    />
  </WorkflowNodeProperties>
</template>
