export interface ProfileCredentialRequest {
  profileId: string
  profileName: string
  protocol: 'ssh' | 'telnet' | 'serial'
  endpoint: string
  hasPassword: boolean
}

export interface DeviceConnectionRequest {
  deviceId: string
  deviceName: string
  protocol: 'ssh' | 'telnet' | 'serial'
  host: string
  port: number
  username: string
}

export interface InternalLoginPromptRequest {
  sourceLabel: string
  username: string
  cid: string
  remembered: boolean
  autoLogin: boolean
}

export interface CredentialDialogResult {
  action: 'submit' | 'remove' | 'cancel'
  password: string
  save: boolean
  host?: string
  port?: number
  username?: string
  cid?: string
  autoLogin?: boolean
}
