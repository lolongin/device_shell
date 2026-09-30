import type { ConnectionProfileSummary, ProfileType } from '../types'

export function filterProfiles(profiles: ConnectionProfileSummary[], profileType: ProfileType | 'devices' | '', query: string): ConnectionProfileSummary[] {
  const needle = query.trim().toLocaleLowerCase()
  return profiles.filter((profile) => profile.profile_type === profileType && (!needle || [profile.name, profile.group, profile.ssh.host, profile.telnet.host, profile.serial.host, profile.notes].join(' ').toLocaleLowerCase().includes(needle)))
}

export function groupProfiles(profiles: ConnectionProfileSummary[], knownGroups: string[], includeEmptyGroups: boolean): Array<{ name: string; profiles: ConnectionProfileSummary[] }> {
  const groups = new Map<string, ConnectionProfileSummary[]>()
  if (includeEmptyGroups) for (const group of knownGroups) groups.set(group, [])
  for (const profile of profiles) {
    const group = profile.group || '未分组'
    groups.set(group, [...(groups.get(group) || []), profile])
  }
  return [...groups.entries()].sort(([left], [right]) => left === '未分组' ? 1 : right === '未分组' ? -1 : left.localeCompare(right)).map(([name, groupProfiles]) => ({ name, profiles: groupProfiles }))
}

export function profileCredentialCount(profiles: ConnectionProfileSummary[]): number {
  return profiles.filter((profile) => profile[profile.preferred_protocol].has_password).length
}
