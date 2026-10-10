import type { InjectionKey, Ref } from 'vue'
import type { WorkflowValueReference } from './types'
export type ReferenceTarget = { label: string; candidates: WorkflowValueReference[]; select: (reference: string) => void }
export const referenceEditorKey: InjectionKey<{ target: Ref<ReferenceTarget | null> }> = Symbol('workflow-reference-editor')
