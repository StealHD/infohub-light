import type { FeedItem, FeedSnapshot, SourceHealthItem, SourceHealthStatus } from '../../api/types'

export type FeedMode = 'featured' | 'all' | 'daily'

export function selectModeItems(snapshot: FeedSnapshot | undefined, mode: FeedMode): FeedItem[] {
  if (!snapshot) return []
  if (mode === 'featured') return snapshot.featured_items ?? []
  if (mode === 'daily') return snapshot.daily_push_items ?? []
  return snapshot.items ?? snapshot.today_items ?? []
}

export type FeedFilterOptions = {
  query: string
  unreadFirst: boolean
  sourceId?: string
  channel?: string
  topic?: string
  minScore?: number
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
    if (query && !searchableText(item).includes(query)) return false
    if (filters.sourceId && item.source_id !== filters.sourceId && item.source !== filters.sourceId) return false
    if (filters.channel && (item.channel ?? item.category) !== filters.channel) return false
    if (filters.topic && !(item.topics ?? item.tags ?? []).includes(filters.topic)) return false
    if (filters.minScore !== undefined && Number(item.score ?? 0) < filters.minScore) return false
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
