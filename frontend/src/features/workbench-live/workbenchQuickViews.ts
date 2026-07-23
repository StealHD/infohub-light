import type { FeedPreference } from '../feed/feedPreference'

export type WorkbenchQuickViewId = 'all' | 'today' | 'public' | 'private'

export const WORKBENCH_QUICK_VIEWS: ReadonlyArray<{ id: WorkbenchQuickViewId; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'today', label: '当天' },
  { id: 'public', label: '公共订阅' },
  { id: 'private', label: '私人订阅' },
]

export function applyQuickView(preference: FeedPreference, view: WorkbenchQuickViewId): FeedPreference {
  return {
    ...preference,
    unreadFirst: false,
    source: '',
    channel: '',
    topic: '',
    minScore: undefined,
    dateScope: view === 'today' ? 'today' : 'all',
    subscriptionScope: view === 'public' || view === 'private' ? view : 'all',
  }
}

export function detectActiveQuickView(preference: FeedPreference): WorkbenchQuickViewId | null {
  const hasClearedOverrides = preference.source === ''
    && preference.channel === ''
    && preference.topic === ''
    && preference.minScore === undefined
    && !preference.unreadFirst
  if (!hasClearedOverrides) return null
  if (preference.dateScope === 'today' && preference.subscriptionScope === 'all') return 'today'
  if (preference.dateScope !== 'all') return null
  if (preference.subscriptionScope === 'public' || preference.subscriptionScope === 'private') return preference.subscriptionScope
  return preference.subscriptionScope === 'all' ? 'all' : null
}
