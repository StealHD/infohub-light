import type { FeedPreference } from '../feed/feedPreference'

export type WorkbenchQuickViewId = 'all' | 'unread' | 'ai' | 'friends' | 'product'

export const WORKBENCH_QUICK_VIEWS: ReadonlyArray<{ id: WorkbenchQuickViewId; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'unread', label: '未读' },
  { id: 'ai', label: 'AI' },
  { id: 'friends', label: '朋友动态' },
  { id: 'product', label: '产品机会' },
]

const channelByView: Record<Exclude<WorkbenchQuickViewId, 'all' | 'unread'>, string> = {
  ai: 'AI',
  friends: '朋友动态',
  product: '产品机会',
}

export function applyQuickView(preference: FeedPreference, view: WorkbenchQuickViewId): FeedPreference {
  return {
    ...preference,
    unreadFirst: view === 'unread',
    source: '',
    channel: view === 'all' || view === 'unread' ? '' : channelByView[view],
    topic: '',
    minScore: undefined,
  }
}

export function detectActiveQuickView(preference: FeedPreference): WorkbenchQuickViewId | null {
  const hasClearedOverrides = preference.source === '' && preference.topic === '' && preference.minScore === undefined
  if (!hasClearedOverrides) return null
  if (preference.unreadFirst && preference.channel === '') return 'unread'
  if (preference.unreadFirst) return null
  if (preference.channel === '') return 'all'
  const match = (Object.entries(channelByView) as Array<[Exclude<WorkbenchQuickViewId, 'all' | 'unread'>, string]>)
    .find(([, channel]) => channel === preference.channel)
  return match?.[0] ?? null
}
