import { contextBridge, ipcRenderer } from 'electron'

interface CredentialSubmission {
  password: string
  save: boolean
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
