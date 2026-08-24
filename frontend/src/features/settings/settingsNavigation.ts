import { Icons, type LucideIcon } from '../../design-system'

export type SettingsRole = 'owner' | 'admin' | 'member' | 'viewer'
export type SettingsNavigationId = 'overview' | 'sources' | 'fetching' | 'ignored' | 'ai' | 'notifications' | 'appearance' | 'system' | 'secrets' | 'actorops' | 'storage'

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
    items: [
      { id: 'sources', label: '来源', href: '/subscriptions', icon: Icons.Rss, bridge: true },
      { id: 'fetching', label: '获取与主题', href: '/settings/fetching', icon: Icons.Clock3, adminOnly: true },
      { id: 'ignored', label: '已忽略内容', href: '/settings/ignored', icon: Icons.EyeOff },
    ],
  },
  {
    id: 'intelligence',
    label: '智能',
    items: [{ id: 'ai', label: 'AI', href: '/settings/ai', icon: Icons.Sparkles }],
  },
  {
    id: 'communication',
    label: '通信',
    items: [{ id: 'notifications', label: '通知', href: '/settings/notifications', icon: Icons.Bell }],
  },
  {
    id: 'system',
    label: '系统',
    items: [
      { id: 'appearance', label: '外观', href: '/settings/appearance', icon: Icons.SunMoon },
      { id: 'system', label: '系统参数', href: '/settings/system', icon: Icons.SlidersHorizontal, adminOnly: true },
    ],
  },
  {
    id: 'developer',
    label: '开发者',
    items: [
      { id: 'secrets', label: '密钥', href: '/settings/secrets', icon: Icons.KeyRound, adminOnly: true },
      { id: 'actorops', label: 'ActorOps', href: '/settings/actorops', icon: Icons.Route, adminOnly: true },
      { id: 'storage', label: '存储与归档', href: '/settings/storage', icon: Icons.Archive, adminOnly: true },
    ],
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

export function activeSettingsNavigationId(pathname: string, hash: string): SettingsNavigationId {
  if (pathname === '/settings/notifications') return 'notifications'
  if (pathname === '/settings/appearance') return 'appearance'
  if (pathname === '/settings/ai') return 'ai'
  if (pathname === '/settings/fetching') return 'fetching'
  if (pathname === '/settings/ignored') return 'ignored'
  if (pathname === '/settings/secrets') return 'secrets'
  if (pathname === '/settings/actorops') return 'actorops'
  if (pathname === '/settings/storage') return 'storage'
  if (pathname === '/settings/system') return 'system'
  if (pathname === '/settings/legacy' && hash.replace(/^#/, '') === 'settings-storage') return 'storage'
  return 'overview'
}

export function settingsWorkspaceTitle(pathname: string, hash: string): string {
  const active = activeSettingsNavigationId(pathname, hash)
  return SETTINGS_NAVIGATION_GROUPS.flatMap((group) => group.items).find((item) => item.id === active)?.label ?? '设置'
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
