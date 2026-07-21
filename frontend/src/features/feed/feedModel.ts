import type { FeedItem, FeedSnapshot, SourceHealthItem, SourceHealthStatus } from '../../api/types'
import type { FeedDateScope } from './feedPreference'

export type FeedMode = 'featured' | 'all' | 'daily'

export function sortWorkbenchItems(items: FeedItem[], order: 'oldest' | 'newest' = 'oldest'): FeedItem[] {
  return items.map((item, index) => {
    const value = item.presentation?.timing?.published_at || item.published_at
    const timestamp = value ? new Date(value).getTime() : Number.NaN
    return { item, index, timestamp }
  }).sort((left, right) => {
    const leftValid = Number.isFinite(left.timestamp)
    const rightValid = Number.isFinite(right.timestamp)
    if (leftValid && rightValid) {
      const timeDelta = order === 'newest' ? right.timestamp - left.timestamp : left.timestamp - right.timestamp
      return timeDelta || left.index - right.index
    }
    if (leftValid !== rightValid) return leftValid ? -1 : 1
    return left.index - right.index
  }).map(({ item }) => item)
}

export function selectModeItems(snapshot: FeedSnapshot | undefined, mode: FeedMode): FeedItem[] {
  if (!snapshot) return []
  if (mode === 'featured') return snapshot.featured_items ?? []
  if (mode === 'daily') return snapshot.daily_push_items ?? []
  return sortWorkbenchItems(snapshot.items ?? snapshot.today_items ?? [])
}

export type FeedFilterOptions = {
  query: string
  unreadFirst: boolean
  sourceId?: string
  channel?: string
  topic?: string
  minScore?: number
  dateScope?: FeedDateScope
  now?: Date
}

export function feedItemTimestamp(item: FeedItem): number | null {
  const candidates = [
    item.presentation?.timing?.published_at,
    item.published_at,
    item.presentation?.timing?.fetched_at,
    item.fetched_at,
  ]
  for (const value of candidates) {
    if (!value) continue
    const timestamp = new Date(value).getTime()
    if (Number.isFinite(timestamp)) return timestamp
  }
  return null
}

export function isFeedItemToday(item: FeedItem, now = new Date()): boolean {
  const timestamp = feedItemTimestamp(item)
  if (timestamp === null) return false
  const value = new Date(timestamp)
  return value.getFullYear() === now.getFullYear()
    && value.getMonth() === now.getMonth()
    && value.getDate() === now.getDate()
}

function searchableText(item: FeedItem): string {
  return [
    item.title,
    item.summary_zh,
    item.source,
    item.source_type,
    item.channel,
    item.category,
    ...(item.topics ?? item.tags ?? []),
    item.presentation?.source.name,
    item.presentation?.author.name,
    item.presentation?.content.excerpt,
    item.presentation?.analysis.summary_zh,
    ...(item.presentation?.taxonomy.topics ?? []),
    ...(item.presentation?.taxonomy.entities ?? []),
  ].filter(Boolean).join(' ').toLocaleLowerCase()
}

export function filterFeedItems(items: FeedItem[], filters: FeedFilterOptions): FeedItem[] {
  const query = filters.query.trim().toLocaleLowerCase()
  const filtered = items.filter((item) => {
    const sourceId = item.presentation?.source.id || item.source_id || item.source
    const channel = item.presentation?.taxonomy.channel || item.channel || item.category
    const topics = item.presentation?.taxonomy.topics ?? item.topics ?? item.tags ?? []
    const score = item.presentation?.analysis.score ?? item.score ?? 0
    if (filters.dateScope === 'today' && !isFeedItemToday(item, filters.now)) return false
    if (query && !searchableText(item).includes(query)) return false
    if (filters.sourceId && sourceId !== filters.sourceId) return false
    if (filters.channel && channel !== filters.channel) return false
    if (filters.topic && !topics.includes(filters.topic)) return false
    if (filters.minScore !== undefined && Number(score) < filters.minScore) return false
    return true
  })
  if (!filters.unreadFirst) return filtered
  return filtered.map((item, index) => ({ item, index })).sort((left, right) => {
    const readDelta = Number(Boolean(left.item.user_state?.is_read)) - Number(Boolean(right.item.user_state?.is_read))
    return readDelta || left.index - right.index
  }).map(({ item }) => item)
}

const healthPriority: Record<SourceHealthStatus, number> = {
  healthy: 0,
  unknown: 1,
  degraded: 2,
  failing: 3,
}

export function resolveItemHealth(item: FeedItem, health: SourceHealthItem[]): SourceHealthItem | null {
  const subscriptionIds = new Set([
    ...(item.subscription_ids ?? []),
    ...(item.subscription_id ? [item.subscription_id] : []),
  ])
  const sourceIds = new Set([
    ...(item.source_ids ?? []),
    ...(item.source_id ? [item.source_id] : []),
  ])
  return health.filter((entry) => (
    subscriptionIds.has(entry.subscription_id) || sourceIds.has(entry.source_id)
  )).sort((left, right) => healthPriority[right.status] - healthPriority[left.status])[0] ?? null
}

export function safeExternalUrl(value?: string): string {
  if (!value) return ''
  try {
    const url = new URL(value, window.location.origin)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return ''
    return url.href
  } catch {
    return ''
  }
}

export function relativeTime(value?: string): string {
  if (!value) return '时间未知'
  const timestamp = new Date(value).getTime()
  if (!Number.isFinite(timestamp)) return '时间未知'
  const seconds = Math.max(0, Math.round((Date.now() - timestamp) / 1000))
  if (seconds < 60) return '刚刚'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`
  return `${Math.floor(seconds / 86400)} 天前`
}

export function signalText(item: FeedItem): string {
  if (item.scoring_disabled) return '未评分'
  const score = Number(item.score ?? 0)
  if (score <= 0) return '未评分'
  if (score >= 8.5) return `${score.toFixed(1)} 强信号`
  if (score >= 7) return `${score.toFixed(1)} 中强信号`
  return `${score.toFixed(1)} 观察信号`
}
