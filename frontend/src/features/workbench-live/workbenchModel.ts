import type { ContentFormat, ContentFormatOrigin, FeedHistory, FeedItem, FeedSnapshot, SavedFeed, UserItemState } from '../../api/types'
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
  excerptTruncated: boolean
  bodyCompleteness?: 'captured' | 'excerpt_only'
  hasDistinctDetail: boolean
  format: ContentFormat
  formatOrigin: ContentFormatOrigin
  formatLabel: string
  mediaImages: Array<{ url: string; alt: string; width?: number; height?: number }>
  displayImageCount: number
  totalImageCount: number
  mediaTruncated: boolean
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

export function cardLabelForViewer(card: WorkbenchCardModel): string {
  return card.displayKind === 'social' ? `${card.sourceLabel}: ${card.primaryText}` : card.title
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
  const rawSource = presentation?.source?.name || item.source || item.source_type || '未知来源'
  const platformLabel = resolvePlatformLabel(
    presentation?.source?.platform || presentation?.source?.catalog_type || item.source_type || '',
    rawSource,
  )
  const sourceLabel = displayKind === 'social'
    ? resolveSocialSourceLabel(item, rawSource, platformLabel)
    : stripPlatformPrefix(rawSource, platformLabel)
  const source = displayKind === 'social'
    ? resolveSocialSourceName(item, rawSource, platformLabel, sourceLabel)
    : rawSource
  const rawAuthor = presentation?.author?.name?.trim()
  const candidateAuthor = rawAuthor && !isUrlDisplayLabel(rawAuthor, platformLabel)
    ? rawAuthor
    : undefined
  const authorLabel = candidateAuthor
    && normalizeDisplayText(candidateAuthor) !== normalizeDisplayText(sourceLabel)
    && normalizeDisplayText(candidateAuthor) !== normalizeDisplayText(source)
    ? candidateAuthor
    : undefined
  const summary = displayKind === 'article' && candidateSummary && !substantiallyRepeats(candidateSummary, title)
    ? candidateSummary.trim()
    : undefined
  const mediaImages = uniqueLocalMedia(item)
  const [format, inferredFormatOrigin] = resolveContentFormat(item, displayKind, mediaImages.length)
  const declaredImageCount = Number(presentation?.media?.total_image_count)
  const totalImageCount = Math.max(
    mediaImages.length,
    Number.isFinite(declaredImageCount) ? Math.max(0, declaredImageCount) : 0,
  )
  const hasDistinctDetail = displayKind === 'social'
    ? Boolean(detailBody && normalizeDisplayText(detailBody) !== normalizeDisplayText(primaryText))
    : Boolean(
      detailBody
      && normalizeDisplayText(detailBody) !== normalizeDisplayText(title)
      && (!summary || normalizeDisplayText(detailBody) !== normalizeDisplayText(summary)),
    )
  return {
    id: item.id,
    displayKind,
    title,
    summary,
    body,
    primaryText,
    detailBody,
    bodyTruncated: Boolean(presentation?.content?.body_truncated ?? presentation?.content?.excerpt_truncated),
    excerptTruncated: Boolean(presentation?.content?.excerpt_truncated),
    bodyCompleteness: presentation?.content?.body_completeness,
    hasDistinctDetail,
    format,
    formatOrigin: presentation?.content?.format_origin || inferredFormatOrigin,
    formatLabel: CONTENT_FORMAT_LABELS[format],
    mediaImages,
    displayImageCount: mediaImages.length,
    totalImageCount,
    mediaTruncated: Boolean(presentation?.media?.truncated || totalImageCount > mediaImages.length),
    source,
    platformLabel,
    sourceLabel,
    authorLabel,
    sourceAvatar: presentation?.source?.avatar_url,
    publishedAt: presentation?.timing?.effective_at || presentation?.timing?.published_at || item.published_at,
    url: presentation?.links?.canonical_url || item.url,
    channel: presentation?.taxonomy?.channel || item.channel || item.category || '未分类频道',
    topics: presentation?.taxonomy?.topics ?? item.topics ?? item.tags ?? [],
    imageUrl: mediaImages[0]?.url,
    score: item.scoring_disabled ? undefined : item.score,
    userState: { ...emptyUserState, ...item.user_state },
    item,
  }
}

const CONTENT_FORMAT_LABELS: Record<ContentFormat, string> = {
  article: '文章',
  video: '视频',
  image: '图片',
  gallery: '图集',
  audio: '音频',
  social_post: '社交动态',
  discussion: '讨论',
  release: '版本发布',
  other: '其他',
}

function uniqueLocalMedia(item: FeedItem): WorkbenchCardModel['mediaImages'] {
  const presentationImages = item.presentation?.media?.images ?? []
  const candidates = [
    ...presentationImages.map((image) => ({ url: image.url, alt: image.alt, width: image.width, height: image.height })),
    ...(item.media_urls ?? []).map((url) => ({ url, alt: item.title })),
    ...(item.image_url ? [{ url: item.image_url, alt: item.title }] : []),
  ]
  const seen = new Set<string>()
  return candidates.flatMap((image) => {
    const url = image.url?.trim()
    if (!url?.startsWith('/api/media/') || seen.has(url) || seen.size >= 6) return []
    seen.add(url)
    return [{ ...image, url, alt: image.alt || item.title || '内容图片' }]
  })
}

function resolveContentFormat(item: FeedItem, displayKind: WorkbenchDisplayKind, imageCount: number): [ContentFormat, ContentFormatOrigin] {
  const explicit = item.presentation?.content?.format
  if (explicit && explicit in CONTENT_FORMAT_LABELS) return [explicit, item.presentation?.content?.format_origin || 'fallback']
  const url = item.presentation?.links?.canonical_url || item.url
  try {
    const host = new URL(url).hostname.toLocaleLowerCase()
    if (['youtu.be', 'youtube.com', 'www.youtube.com', 'b23.tv', 'bilibili.com', 'www.bilibili.com', 'm.bilibili.com'].includes(host)) return ['video', 'deterministic']
  } catch {
    // Legacy invalid URLs safely continue through source fallbacks.
  }
  const kind = item.presentation?.content?.content_kind
  const catalog = item.presentation?.source?.catalog_type?.toLocaleLowerCase()
  if (kind === 'release_notes' || catalog === 'github_release') return ['release', 'deterministic']
  if (kind === 'discussion' || ['reddit', 'hackernews'].includes(catalog || '')) return ['discussion', 'deterministic']
  if (imageCount > 1) return ['gallery', 'deterministic']
  if (imageCount === 1 && displayKind === 'social') return ['image', 'deterministic']
  if (displayKind === 'social') return ['social_post', 'fallback']
  if (catalog === 'rss' || item.source_type === 'rss') return ['article', 'fallback']
  if (catalog === 'github_user' || item.source_type === 'github') return ['article', 'fallback']
  return ['other', 'fallback']
}

export function workbenchSourceLabels(card: WorkbenchCardModel, includeArticleDetails = false): string[] {
  const channelKey = card.displayKind === 'social' ? normalizeDisplayText(card.channel) : ''
  const sourceLabel = channelKey && normalizeDisplayText(card.sourceLabel) === channelKey
    ? undefined
    : card.sourceLabel
  const values = card.displayKind === 'social' || includeArticleDetails
    ? [card.platformLabel, card.authorLabel, sourceLabel]
    : [card.source]
  const seen = new Set<string>()
  return values.flatMap((value) => {
    const label = value?.trim()
    if (!label || isUrlDisplayLabel(label, card.platformLabel)) return []
    const key = normalizeDisplayText(label)
    if (!key || seen.has(key)) return []
    seen.add(key)
    return [label]
  })
}

function resolveSocialSourceLabel(item: FeedItem, rawSource: string, platformLabel: string): string {
  const namedLabel = [rawSource, item.source]
    .map((value) => stripPlatformPrefix(value?.trim() || '', platformLabel))
    .find((value) => value && !isUrlDisplayLabel(value, platformLabel))
  return namedLabel || socialAccountLabel(item, platformLabel) || platformLabel
}

function resolveSocialSourceName(item: FeedItem, rawSource: string, platformLabel: string, sourceLabel: string): string {
  const namedSource = [rawSource, item.source]
    .map((value) => value?.trim())
    .find((value) => value && !isUrlDisplayLabel(value, platformLabel))
  if (namedSource) return namedSource
  return normalizeDisplayText(sourceLabel) === normalizeDisplayText(platformLabel)
    ? platformLabel
    : `${platformLabel} · ${sourceLabel}`
}

function isUrlDisplayLabel(value: string, platformLabel = ''): boolean {
  const candidate = stripPlatformPrefix(value.trim(), platformLabel)
  return /^(?:https?:\/\/|www\.)\S+$/iu.test(candidate)
}

function socialAccountLabel(item: FeedItem, platformLabel: string): string | undefined {
  const candidates = [item.presentation?.links?.source_url, item.presentation?.links?.canonical_url, item.url]
  for (const value of candidates) {
    try {
      const url = new URL(value || '')
      const segment = decodeURIComponent(url.pathname.split('/').filter(Boolean)[0] || '')
      if (!segment || SOCIAL_CONTENT_PATHS.has(segment.toLocaleLowerCase())) continue
      if (platformLabel === 'X' || platformLabel === 'Telegram') return `@${segment.replace(/^@/, '')}`
      if (platformLabel === 'Instagram' || platformLabel === 'Facebook') return segment.replace(/^@/, '')
    } catch {
      // Malformed legacy URLs fall through to the next safe display candidate.
    }
  }
  return undefined
}

const SOCIAL_CONTENT_PATHS = new Set([
  'explore', 'home', 'i', 'p', 'reel', 'reels', 'search', 'shorts', 'status', 'stories', 'tv', 'watch',
])

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
