import { contextBridge, ipcRenderer } from 'electron'

interface CredentialSubmission {
  password: string
  save: boolean
  host?: string
  port?: number
  username?: string
  cid?: string
  autoLogin?: boolean
}

const credentialDialogApi = {
  onInit: (callback: (value: { password: string }) => void): (() => void) => {
    const listener = (_event: Electron.IpcRendererEvent, value: unknown): void => {
      if (!value || typeof value !== 'object' || typeof (value as { password?: unknown }).password !== 'string') return
      callback({ password: (value as { password: string }).password })
    }
    ipcRenderer.on('credential-dialog:init', listener)
    return () => ipcRenderer.removeListener('credential-dialog:init', listener)
  },
  submit: (submission: CredentialSubmission): void => {
    ipcRenderer.send('credential-dialog:submit', submission)
  },
  remove: (): void => {
    ipcRenderer.send('credential-dialog:remove')
  },
  cancel: (): void => {
    ipcRenderer.send('credential-dialog:cancel')
  }
}

contextBridge.exposeInMainWorld('credentialDialogApi', credentialDialogApi)
