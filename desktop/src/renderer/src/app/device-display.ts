import type { DeviceSummary } from '../types'

export function deviceRowCopyText(device: DeviceSummary): string {
  return [device.board_id || device.id, device.name, device.board_type || device.device_type || '—', device.cpu || '—', device.slot || device.rack || '—', device.status_text || device.status || '—'].join('\t')
}

export function deviceConnectionCopyText(device: DeviceSummary): string {
  return [`设备: ${device.name}`, `设备序号: ${device.board_id || device.id}`, `Telnet: ${device.telnet_endpoint || '—'}`, `串口: ${device.serial_display || device.serial_endpoint || '—'}`, `SSH: ${device.ssh_endpoint || '—'}`].join('\n')
}

export function endpointHost(endpoint: string | null | undefined): string {
  if (!endpoint) return ''
  if (endpoint.startsWith('[')) {
    const end = endpoint.indexOf(']')
    return end > 0 ? endpoint.slice(1, end) : endpoint
  }
  const portSeparator = endpoint.lastIndexOf(':')
  return portSeparator > 0 ? endpoint.slice(0, portSeparator) : endpoint
}

export function copyableSerialText(device: DeviceSummary): string {
  const endpoint = device.serial_endpoint || device.serial_display || ''
  return device.can_connect_serial ? endpointHost(endpoint) : ''
}

export function visibleDeviceFieldValue(value: string | null | undefined, fallback = '—'): string {
  return value && value.trim() ? value : fallback
}

export function dynamicDeviceFieldValue(device: DeviceSummary, key: string): string {
  const value = device.attributes?.[key] ?? device.extensions?.[key]
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
