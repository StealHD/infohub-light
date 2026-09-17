import type { SettingsRole } from './settingsNavigation'

export function canAdministerSettings(role: SettingsRole): boolean {
  return role === 'owner' || role === 'admin'
}

export function settingsDestinationFromLegacyHash(hash: string, role: SettingsRole): string {
  const id = hash.replace(/^#/, '')
  if (!id || id === 'settings-about') return '/settings'
  if (id === 'settings-notifications') return '/settings/notifications'
  if (id === 'settings-ai') return '/settings/ai'
  if (id === 'settings-fetching' && canAdministerSettings(role)) return '/settings/fetching'
  if (id === 'settings-ignored') return '/settings/ignored'
  if (id === 'settings-secrets' && canAdministerSettings(role)) return '/settings/secrets'
  if (id === 'settings-actorops' && canAdministerSettings(role)) return '/settings/actorops'
  if (id === 'settings-storage' && canAdministerSettings(role)) return '/settings/storage'
  if (id === 'settings-system' && canAdministerSettings(role)) return '/settings/system'
  return '/settings'
}
