import type { FeedHistory, FeedItem, FeedSnapshot, SavedFeed, UserItemState } from '../../api/types'
import { sortWorkbenchItems } from '../feed/feedModel'

export type WorkbenchKind = 'feed' | 'saved' | 'history'

export type WorkbenchCardModel = {
  id: string
  title: string
  summary: string
  body: string
  bodyTruncated: boolean
  source: string
  sourceAvatar?: string
  publishedAt?: string
  url: string
  channel: string
  topics: string[]
  imageUrl?: string
  score?: number
  userState: UserItemState
  item: FeedItem
}

type WorkbenchSourceData = {
  snapshot?: FeedSnapshot
  saved?: SavedFeed
  history?: FeedHistory
}

const emptyUserState: UserItemState = {
  is_read: false,
  is_saved: false,
  is_later: false,
  dismissed: false,
}

export function selectWorkbenchSourceItems(kind: WorkbenchKind, data: WorkbenchSourceData): FeedItem[] {
  if (kind === 'saved') return sortWorkbenchItems((data.saved?.items ?? []).filter((item) => item.user_state?.is_saved))
  if (kind === 'history') return sortWorkbenchItems(data.history?.items ?? [])
  return sortWorkbenchItems(data.snapshot?.items ?? [])
}

export function toWorkbenchCardModel(item: FeedItem): WorkbenchCardModel {
  const presentation = item.presentation
  return {
    id: item.id,
    title: presentation?.content?.title || item.title || '无标题',
    summary: presentation?.analysis?.summary_zh || item.summary_zh || '暂无概括；请打开原文核对完整内容。',
    body: presentation?.content?.body_text || presentation?.content?.excerpt || '',
    bodyTruncated: Boolean(presentation?.content?.body_truncated ?? presentation?.content?.excerpt_truncated),
    source: presentation?.source?.name || item.source || item.source_type || '未知来源',
    sourceAvatar: presentation?.source?.avatar_url,
    publishedAt: presentation?.timing?.published_at || item.published_at,
    url: presentation?.links?.canonical_url || item.url,
    channel: presentation?.taxonomy?.channel || item.channel || item.category || '未分类频道',
    topics: presentation?.taxonomy?.topics ?? item.topics ?? item.tags ?? [],
    imageUrl: item.image_url || presentation?.media?.images?.[0]?.url,
    score: item.scoring_disabled ? undefined : item.score,
    userState: { ...emptyUserState, ...item.user_state },
    item,
  }
}

export function mergeDeepLinkedItem(items: FeedItem[], detail?: FeedItem): FeedItem[] {
  if (!detail || items.some((item) => item.id === detail.id)) return items
  return sortWorkbenchItems([...items, detail])
}

export function cleanLegacyModeSearch(search: string): string {
  const params = new URLSearchParams(search)
  params.delete('mode')
  const value = params.toString()
  return value ? `?${value}` : ''
}

export function sampleTickIndexes(itemCount: number, limit = 12): number[] {
  if (itemCount <= 0 || limit <= 0) return []
  const count = Math.min(itemCount, limit)
  if (count === 1) return [0]
  return Array.from({ length: count }, (_, index) => Math.round(index * (itemCount - 1) / (count - 1)))
}
