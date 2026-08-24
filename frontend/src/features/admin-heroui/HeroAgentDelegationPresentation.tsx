import type { AgentDelegation, AgentDelegationAccess } from '../../api/types'
import { Icons } from '../../design-system'

export function delegationDateTime(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

export function delegationStatus(connection: AgentDelegation) {
  if (connection.status === 'active') return { label: '有效', tone: 'success' as const, icon: <Icons.CircleCheck size={13} aria-hidden="true" /> }
  if (connection.status === 'expired') return { label: '已过期', tone: 'warning' as const, icon: <Icons.ClockAlert size={13} aria-hidden="true" /> }
  return { label: '已吊销', tone: 'neutral' as const, icon: <Icons.CircleSlash2 size={13} aria-hidden="true" /> }
}

export function delegationAccessLabel(access: AgentDelegationAccess) {
  if (access === 'subscriptions_write') return '可管理订阅'
  return access === 'system_settings_write' ? '系统管理' : '只读'
}
