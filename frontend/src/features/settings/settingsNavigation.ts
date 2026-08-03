import { Icons, type LucideIcon } from '../../design-system'

export type SettingsRole = 'owner' | 'admin' | 'member' | 'viewer'
export type SettingsNavigationId = 'overview' | 'sources' | 'ai' | 'notifications' | 'appearance' | 'advanced'

export type SettingsNavigationItem = {
  id: SettingsNavigationId
  label: string
  href: string
  icon: LucideIcon
  adminOnly?: boolean
  bridge?: boolean
}

export type SettingsNavigationGroup = {
  id: string
  label?: string
  items: readonly SettingsNavigationItem[]
}

export const SETTINGS_NAVIGATION_GROUPS: readonly SettingsNavigationGroup[] = [
  {
    id: 'overview',
    items: [{ id: 'overview', label: '概览', href: '/settings', icon: Icons.LayoutDashboard }],
  },
  {
    id: 'workspace',
    label: '工作区',
    items: [{ id: 'sources', label: '来源', href: '/subscriptions', icon: Icons.Rss, bridge: true }],
  },
  {
    id: 'intelligence',
    label: '智能',
    items: [{ id: 'ai', label: 'AI', href: '/settings/legacy#settings-ai', icon: Icons.Sparkles }],
  },
  {
    id: 'communication',
    label: '通信',
    items: [{ id: 'notifications', label: '通知', href: '/settings/notifications', icon: Icons.Bell }],
  },
  {
    id: 'system',
    label: '系统',
    items: [{ id: 'appearance', label: '外观', href: '/settings/appearance', icon: Icons.SunMoon }],
  },
  {
    id: 'developer',
    label: '开发者',
    items: [{ id: 'advanced', label: '高级', href: '/settings/legacy#settings-fetching', icon: Icons.SlidersHorizontal, adminOnly: true }],
  },
]

export function canAdministerSettings(role: SettingsRole): boolean {
  return role === 'owner' || role === 'admin'
}

export function settingsNavigationForRole(role: SettingsRole): readonly SettingsNavigationGroup[] {
  const canAdminister = canAdministerSettings(role)
  return SETTINGS_NAVIGATION_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => canAdminister || !item.adminOnly),
  })).filter((group) => group.items.length > 0)
}

const advancedHashes = new Set(['settings-fetching', 'settings-storage', 'settings-secrets'])

export function activeSettingsNavigationId(pathname: string, hash: string): SettingsNavigationId {
  if (pathname === '/settings/notifications') return 'notifications'
  if (pathname === '/settings/appearance') return 'appearance'
  if (pathname === '/settings/legacy') {
    const id = hash.replace(/^#/, '')
    if (!id || id === 'settings-ai') return 'ai'
    if (advancedHashes.has(id)) return 'advanced'
  }
  return 'overview'
}

export function settingsWorkspaceTitle(pathname: string, hash: string): string {
  if (pathname === '/settings/legacy' && hash === '#settings-ignored') return '已忽略内容'
  const active = activeSettingsNavigationId(pathname, hash)
  return SETTINGS_NAVIGATION_GROUPS.flatMap((group) => group.items).find((item) => item.id === active)?.label ?? '设置'
}

export function settingsDestinationFromLegacyHash(hash: string, role: SettingsRole): string {
  const id = hash.replace(/^#/, '')
  if (!id || id === 'settings-about') return '/settings'
  if (id === 'settings-notifications') return '/settings/notifications'
  if (id === 'settings-ai' || id === 'settings-ignored') return `/settings/legacy#${id}`
  if (advancedHashes.has(id) && canAdministerSettings(role)) return `/settings/legacy#${id}`
  return '/settings'
}
