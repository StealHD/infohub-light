export function hasInteliscopeTools(value: unknown, agentId?: string): boolean {
  try {
    if (JSON.stringify(value).toLowerCase().includes('inteliscope')) return true
    if (!agentId || !/^ih-[a-f0-9]{32}$/.test(agentId)) return false
    const prefix = `ih_${agentId.slice(3, 27)}__`
    const groups = (value as { groups?: { tools?: { id?: string; name?: string }[] }[] })?.groups
    return Array.isArray(groups) && groups.some(group => Array.isArray(group?.tools)
      && group.tools.some(tool => String(tool?.id ?? tool?.name ?? '').startsWith(prefix)))
  } catch {
    return false
  }
}
