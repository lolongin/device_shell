import type { DeviceSummary, WorkflowRuntimeInput } from '../types'

export interface WorkflowPlatformAdapter {
  pickFile(input: WorkflowRuntimeInput): Promise<string | null>
  pickDirectory(input: WorkflowRuntimeInput, defaultPath?: string): Promise<string | null>
  deviceOptions(): DeviceSummary[]
}

/** Electron is one adapter; a browser/mobile adapter can implement the same seam. */
export function createWorkflowPlatformAdapter(devices: () => DeviceSummary[]): WorkflowPlatformAdapter {
  return {
    async pickFile(input) {
      return window.desktopApi.chooseWorkflowFile({ label: `选择${input.name}`, extensions: ['*'] })
    },
    async pickDirectory(input, defaultPath) {
      return window.desktopApi.chooseWorkflowDirectory({ defaultPath, label: `选择${input.name}文件夹` })
    },
    deviceOptions: devices
  }
}
