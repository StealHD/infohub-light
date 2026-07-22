import type { FeedSnapshot, SourceHealthResponse } from '../../api/types'
import { filterFeedItems, isFeedItemToday } from '../feed/feedModel'
import type { FeedPreference } from '../feed/feedPreference'
import { toWorkbenchCardModel } from './workbenchModel'

export type FeedInsightsDistribution = {
  id: string
  label: string
  count: number
  ratio: number
}

export type FeedInsightsModel = {
  todayCount: number
  unreadCount: number
  savedCount: number
  unhealthySourceCount: number
  visibleCount: number
  totalCount: number
  updatedAt?: string
  channels: FeedInsightsDistribution[]
  formats: FeedInsightsDistribution[]
}

function distribution(values: string[]): FeedInsightsDistribution[] {
  const counts = new Map<string, number>()
  for (const value of values) counts.set(value, (counts.get(value) ?? 0) + 1)
  const total = Math.max(1, values.length)
  return Array.from(counts, ([label, count]) => ({
    id: label,
    label,
    count,
    ratio: count / total,
  })).sort((left, right) => right.count - left.count || left.label.localeCompare(right.label, 'zh-CN'))
}

export function buildFeedInsightsModel({
  snapshot,
  health,
  preference,
  query,
  now = new Date(),
}: {
  snapshot?: FeedSnapshot
  health?: SourceHealthResponse
  preference: FeedPreference
  query: string
  now?: Date
}): FeedInsightsModel {
  const items = (snapshot?.items ?? []).filter((item) => !item.user_state?.dismissed)
  const visible = filterFeedItems(items, {
    query,
    unreadFirst: preference.unreadFirst,
    sourceId: preference.source || undefined,
    channel: preference.channel || undefined,
    topic: preference.topic || undefined,
    dateScope: preference.dateScope,
    now,
  })
  const cards = items.map(toWorkbenchCardModel)
  const unhealthySources = new Set(
    (health?.items ?? [])
      .filter((item) => item.status === 'degraded' || item.status === 'failing')
      .map((item) => item.source_id),
  )
  return {
    todayCount: items.filter((item) => isFeedItemToday(item, now)).length,
    unreadCount: items.filter((item) => !item.user_state?.is_read).length,
    savedCount: items.filter((item) => item.user_state?.is_saved).length,
    unhealthySourceCount: unhealthySources.size,
    visibleCount: visible.length,
    totalCount: items.length,
    updatedAt: snapshot?.updated_at || snapshot?.generated_at,
    channels: distribution(cards.map((card) => card.channel || '未分类频道')),
    formats: distribution(cards.map((card) => card.formatLabel)),
  }
}
