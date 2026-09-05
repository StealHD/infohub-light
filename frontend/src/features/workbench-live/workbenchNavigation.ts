import { Icons } from '../../design-system'

export const browseNavigation = [
  { id: 'feed', label: '信息流', href: '/feed', icon: Icons.Radio },
  { id: 'saved', label: '收藏', href: '/saved', icon: Icons.Star },
  { id: 'history', label: '历史', href: '/history', icon: Icons.History },
] as const
export const managementNavigation = [
  { id: 'subscriptions', label: '订阅', href: '/subscriptions', icon: Icons.Bell },
  { id: 'agents', label: '助手连接', href: '/agents', icon: Icons.Bot },
  { id: 'users', label: '账户与成员', href: '/users', icon: Icons.Users },
  { id: 'settings', label: '设置', href: '/settings', icon: Icons.Settings },
] as const
export const mobilePrimaryNavigation = [browseNavigation[0], browseNavigation[1], managementNavigation[0]] as const

export type PendingNavigation = {
  index: number
  align: 'start' | 'center' | 'end'
}

export function clampPendingNavigation(navigation: PendingNavigation, itemCount: number): PendingNavigation {
  return {
    ...navigation,
    index: Math.max(0, Math.min(navigation.index, itemCount - 1)),
  }
}
