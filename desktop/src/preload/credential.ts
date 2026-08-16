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
