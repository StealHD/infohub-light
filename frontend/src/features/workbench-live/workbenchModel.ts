import type { FeedHistory, FeedItem, FeedSnapshot, SavedFeed, UserItemState } from '../../api/types'
import { sortWorkbenchItems } from '../feed/feedModel'

export type WorkbenchKind = 'feed' | 'saved' | 'history'
export type WorkbenchDisplayKind = 'social' | 'article'

export type WorkbenchCardModel = {
  id: string
  displayKind: WorkbenchDisplayKind
  title: string
  summary?: string
  body: string
  primaryText: string
  detailBody: string
  bodyTruncated: boolean
  source: string
  platformLabel: string
  sourceLabel: string
  authorLabel?: string
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
  const title = presentation?.content?.title || item.title || '无标题'
  const candidateSummary = presentation?.analysis?.summary_zh || item.summary_zh
  const displayKind = isSocialItem(item) ? 'social' : 'article'
  const body = presentation?.content?.body_text || presentation?.content?.excerpt || ''
  const primaryText = displayKind === 'social'
    ? presentation?.content?.excerpt || presentation?.content?.body_text || candidateSummary || title
    : title
  const detailBody = displayKind === 'social'
    ? presentation?.content?.body_text || presentation?.content?.excerpt || primaryText
    : body
  const source = presentation?.source?.name || item.source || item.source_type || '未知来源'
  const platformLabel = resolvePlatformLabel(
    presentation?.source?.platform || presentation?.source?.catalog_type || item.source_type || '',
    source,
  )
  const sourceLabel = stripPlatformPrefix(source, platformLabel)
  const candidateAuthor = presentation?.author?.name?.trim()
  const authorLabel = candidateAuthor
    && normalizeDisplayText(candidateAuthor) !== normalizeDisplayText(sourceLabel)
    && normalizeDisplayText(candidateAuthor) !== normalizeDisplayText(source)
    ? candidateAuthor
    : undefined
  const summary = displayKind === 'article' && candidateSummary && !substantiallyRepeats(candidateSummary, title)
    ? candidateSummary.trim()
    : undefined
  return {
    id: item.id,
    displayKind,
    title,
    summary,
    body,
    primaryText,
    detailBody,
    bodyTruncated: Boolean(presentation?.content?.body_truncated ?? presentation?.content?.excerpt_truncated),
    source,
    platformLabel,
    sourceLabel,
    authorLabel,
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

export function workbenchSourceLabels(card: WorkbenchCardModel, includeArticleDetails = false): string[] {
  const values = card.displayKind === 'social' || includeArticleDetails
    ? [card.platformLabel, card.authorLabel, card.sourceLabel]
    : [card.source]
  const seen = new Set<string>()
  return values.flatMap((value) => {
    const label = value?.trim()
    if (!label) return []
    const key = normalizeDisplayText(label)
    if (!key || seen.has(key)) return []
    seen.add(key)
    return [label]
  })
}

function normalizeDisplayText(value: string): string {
  return value
    .normalize('NFKC')
    .toLocaleLowerCase()
    .replace(/^@[^:\s]+:\s*/u, '')
    .replace(/\s+/gu, ' ')
    .trim()
    .replace(/(?:\.{3}|…)+$/u, '')
    .replace(/^[\p{P}\p{S}\s]+|[\p{P}\p{S}\s]+$/gu, '')
}

function substantiallyRepeats(candidate: string, reference: string): boolean {
  const candidateText = normalizeDisplayText(candidate)
  const referenceText = normalizeDisplayText(reference)
  if (!candidateText || !referenceText) return false
  if (candidateText === referenceText) return true
  const [shorter, longer] = candidateText.length <= referenceText.length
    ? [candidateText, referenceText]
    : [referenceText, candidateText]
  return shorter.length >= 20 && shorter.length / longer.length >= 0.7 && longer.startsWith(shorter)
}

function isSocialItem(item: FeedItem): boolean {
  const contentKind = item.presentation?.content?.content_kind
  if (contentKind === 'post_body' || contentKind === 'caption' || contentKind === 'message') return true
  const sourceKinds = [
    item.presentation?.source?.platform,
    item.presentation?.source?.catalog_type,
    item.source_type,
  ].map((value) => value?.trim().toLocaleLowerCase()).filter(Boolean)
  return sourceKinds.some((value) => ['x', 'twitter', 'instagram', 'facebook', 'telegram', 'apify_social'].includes(value!))
}

function readablePlatformLabel(value: string): string {
  const normalized = value.trim().toLocaleLowerCase()
  const labels: Record<string, string> = {
    x: 'X',
    twitter: 'X',
    instagram: 'Instagram',
    facebook: 'Facebook',
    telegram: 'Telegram',
    reddit: 'Reddit',
    rss: 'RSS',
    github: 'GitHub',
    github_release: 'GitHub',
    github_user: 'GitHub',
    hackernews: 'Hacker News',
    apify_social: '社交平台',
  }
  return labels[normalized] || value.trim() || '来源'
}

function resolvePlatformLabel(value: string, source: string): string {
  const normalized = value.trim().toLocaleLowerCase()
  if (!normalized || normalized === 'apify_social') {
    const sourcePlatform = source.match(/^\s*(x|twitter|instagram|facebook|telegram|reddit)\s*(?:[·:|/-]|$)/iu)?.[1]
    if (sourcePlatform) return readablePlatformLabel(sourcePlatform)
  }
  return readablePlatformLabel(value)
}

function stripPlatformPrefix(source: string, platformLabel: string): string {
  if (!platformLabel || platformLabel === '来源') return source
  const escapedPlatform = platformLabel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const stripped = source.replace(new RegExp(`^${escapedPlatform}\\s*[·:|/\\-]\\s*`, 'iu'), '').trim()
  return stripped || source
}

function mergeDetailedItem(snapshot: FeedItem, detail: FeedItem): FeedItem {
  const basePresentation = snapshot.presentation
  const detailPresentation = detail.presentation
  const presentation = detailPresentation && basePresentation ? {
    ...basePresentation,
    ...detailPresentation,
    source: { ...basePresentation.source, ...detailPresentation.source },
    author: { ...basePresentation.author, ...detailPresentation.author },
    timing: { ...basePresentation.timing, ...detailPresentation.timing },
    links: { ...basePresentation.links, ...detailPresentation.links },
    content: { ...basePresentation.content, ...detailPresentation.content },
    media: detailPresentation.media ?? basePresentation.media,
    taxonomy: { ...basePresentation.taxonomy, ...detailPresentation.taxonomy },
    engagement: { ...basePresentation.engagement, ...detailPresentation.engagement },
    analysis: { ...basePresentation.analysis, ...detailPresentation.analysis },
  } : detailPresentation ?? basePresentation
  return {
    ...snapshot,
    ...detail,
    presentation,
    user_state: snapshot.user_state || detail.user_state
      ? { ...snapshot.user_state, ...detail.user_state } as UserItemState
      : undefined,
  }
}

export function mergeDeepLinkedItem(items: FeedItem[], detail?: FeedItem): FeedItem[] {
  if (!detail) return items
  if (items.some((item) => item.id === detail.id)) {
    return sortWorkbenchItems(items.map((item) => item.id === detail.id ? mergeDetailedItem(item, detail) : item))
  }
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
