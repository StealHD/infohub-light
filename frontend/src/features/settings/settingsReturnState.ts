export type SettingsReturnState = {
  settingsReturnTo?: string
}

type LocationLike = {
  pathname: string
  search?: string
  hash?: string
}

export function sanitizeSettingsReturnTo(value: unknown): string | null {
  if (typeof value !== 'string' || !value.startsWith('/') || value.startsWith('//')) return null
  try {
    const parsed = new URL(value, 'https://inteliscope.local')
    if (parsed.origin !== 'https://inteliscope.local') return null
    if (parsed.pathname === '/login' || parsed.pathname === '/settings' || parsed.pathname.startsWith('/settings/')) return null
    return `${parsed.pathname}${parsed.search}${parsed.hash}`
  } catch {
    return null
  }
}

export function settingsReturnToFromState(state: unknown): string {
  if (!state || typeof state !== 'object') return '/feed'
  return sanitizeSettingsReturnTo((state as SettingsReturnState).settingsReturnTo) ?? '/feed'
}

export function settingsReturnStateForLocation(location: LocationLike): SettingsReturnState {
  const current = `${location.pathname}${location.search ?? ''}${location.hash ?? ''}`
  return { settingsReturnTo: sanitizeSettingsReturnTo(current) ?? '/feed' }
}

export function preserveSettingsReturnState(state: unknown): SettingsReturnState {
  return { settingsReturnTo: settingsReturnToFromState(state) }
}
