export type SettingsRole = 'owner' | 'admin' | 'member' | 'viewer'

export type SettingsSection = {
  id: `settings-${string}`
  label: string
  adminOnly?: boolean
}

export const SETTINGS_SECTIONS: readonly SettingsSection[] = [
  { id: 'settings-about', label: '关于 Inteliscope' },
  { id: 'settings-notifications', label: '消息通知' },
  { id: 'settings-ai', label: '助手与 AI' },
  { id: 'settings-ignored', label: '已忽略内容' },
  { id: 'settings-fetching', label: '获取与主题', adminOnly: true },
  { id: 'settings-storage', label: '存储与归档', adminOnly: true },
  { id: 'settings-secrets', label: '密钥', adminOnly: true },
]

export const LEGACY_SETTINGS_SECTIONS: readonly SettingsSection[] = [
  { id: 'settings-fetching', label: '获取与主题', adminOnly: true },
  { id: 'settings-storage', label: '存储与归档', adminOnly: true },
]

export function settingsSectionsForRole(role: SettingsRole): readonly SettingsSection[] {
  const canAdminister = role === 'owner' || role === 'admin'
  return SETTINGS_SECTIONS.filter((section) => canAdminister || !section.adminOnly)
}

export function settingsSectionFromHash(hash: string, role: SettingsRole): SettingsSection | null {
  const id = hash.replace(/^#/, '')
  return settingsSectionsForRole(role).find((section) => section.id === id) ?? null
}

export function legacySettingsSectionsForRole(role: SettingsRole): readonly SettingsSection[] {
  const canAdminister = role === 'owner' || role === 'admin'
  return LEGACY_SETTINGS_SECTIONS.filter((section) => canAdminister || !section.adminOnly)
}

export function legacySettingsSectionFromHash(hash: string, role: SettingsRole): SettingsSection | null {
  const id = hash.replace(/^#/, '')
  return legacySettingsSectionsForRole(role).find((section) => section.id === id) ?? null
}
