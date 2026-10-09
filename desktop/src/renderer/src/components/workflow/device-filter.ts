type SearchableDevice = {
  id: string
  name?: string
  label?: string
  address?: string
  model?: string
  status?: string
  detail?: string
  ssh_endpoint?: string | null
  telnet_endpoint?: string | null
  serial_endpoint?: string | null
  serial_display?: string
}

export function filterWorkflowDevices<T extends SearchableDevice>(devices: T[], query: string, ownedDeviceIds?: readonly string[]): T[] {
  const keywords = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  if (!keywords.length && ownedDeviceIds === undefined) return devices
  const owned = ownedDeviceIds === undefined ? undefined : new Set(ownedDeviceIds)
  return devices.filter(device => {
    if (owned && !owned.has(device.id)) return false
    const text = [device.id, device.name, device.label, device.address, device.model, device.status, device.detail,
      device.ssh_endpoint, device.telnet_endpoint, device.serial_endpoint, device.serial_display]
      .filter(Boolean).join(' ').toLocaleLowerCase()
    return keywords.every(keyword => text.includes(keyword))
  })
}
