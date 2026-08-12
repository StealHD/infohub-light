import { describe, expect, it } from 'vitest'

import type { FeedItem } from '../../api/types'
import { filterFeedItems, isFeedItemToday, safeExternalUrl, sortWorkbenchItems } from './feedModel'

const item = (overrides: Partial<FeedItem> = {}): FeedItem => ({
  id: 'article-1',
  title: 'Codex 协作工作流',
  url: 'https://example.com/article',
  source: 'OpenAI Blog',
  summary_zh: '更清晰的任务分解。',
  topics: ['Codex'],
  channel: 'AI',
  score: 9.2,
  published_at: '2026-07-13T08:00:00Z',
  subscription_ids: ['sub-a'],
  user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
  ...overrides,
})

describe('feed model', () => {
  it('orders all Feed items from older to newer while keeping invalid timestamps stable', () => {
    const invalidFirst = item({ id: 'invalid-first', published_at: 'unknown' })
    const newer = item({ id: 'newer', published_at: '2026-07-13T10:00:00Z' })
    const older = item({ id: 'older', published_at: '2026-07-13T08:00:00Z' })
    const invalidSecond = item({ id: 'invalid-second', published_at: '' })

    expect(sortWorkbenchItems(
      [invalidFirst, newer, older, invalidSecond],
      'oldest',
    ).map(({ id }) => id)).toEqual(['older', 'newer', 'invalid-first', 'invalid-second'])
  })

  it('supports a stable newest-first view while keeping invalid timestamps at the trailing edge', () => {
    const values = [
      item({ id: 'invalid-first', published_at: 'unknown' }),
      item({ id: 'newer', published_at: '2026-07-13T10:00:00Z' }),
      item({ id: 'older', published_at: '2026-07-13T08:00:00Z' }),
      item({ id: 'invalid-second', published_at: '' }),
    ]

    expect(sortWorkbenchItems(values, 'newest').map(({ id }) => id)).toEqual(['newer', 'older', 'invalid-first', 'invalid-second'])
    expect(sortWorkbenchItems(values, 'oldest').map(({ id }) => id)).toEqual(['older', 'newer', 'invalid-first', 'invalid-second'])
  })

  it('can sort by the user feed ingestion timestamp independently from publication time', () => {
    const values = [
      item({ id: 'published-newer', published_at: '2026-07-13T10:00:00Z', ingested_at: '2026-07-13T11:00:00Z' }),
      item({ id: 'ingested-newer', published_at: '2026-07-13T08:00:00Z', ingested_at: '2026-07-13T12:00:00Z' }),
      item({ id: 'legacy-fetched', published_at: '2026-07-13T09:00:00Z', ingested_at: '', fetched_at: '2026-07-13T11:30:00Z' }),
    ]

    expect(sortWorkbenchItems(values, 'newest', 'published').map(({ id }) => id)).toEqual(['published-newer', 'legacy-fetched', 'ingested-newer'])
    expect(sortWorkbenchItems(values, 'newest', 'ingested').map(({ id }) => id)).toEqual(['ingested-newer', 'legacy-fetched', 'published-newer'])
  })

  it('does not mix publication and ingestion timestamps and keeps exact ties stable', () => {
    const values = [
      item({ id: 'tie-first', published_at: '2026-07-13T10:00:00Z', fetched_at: '2026-07-13T11:00:00Z' }),
      item({ id: 'missing-published', published_at: '', fetched_at: '2026-07-13T12:00:00Z' }),
      item({ id: 'tie-second', published_at: '2026-07-13T10:00:00Z', fetched_at: '2026-07-13T09:00:00Z' }),
      item({ id: 'older', published_at: '2026-07-13T08:00:00Z', fetched_at: '2026-07-13T13:00:00Z' }),
    ]

    expect(sortWorkbenchItems(values, 'newest', 'published').map(({ id }) => id)).toEqual([
      'tie-first',
      'tie-second',
      'older',
      'missing-published',
    ])
    expect(sortWorkbenchItems(values, 'oldest', 'published').map(({ id }) => id)).toEqual([
      'older',
      'tie-first',
      'tie-second',
      'missing-published',
    ])
  })

  it('searches real item fields and keeps unread items before read items', () => {
    const values = [
      item({ id: 'read', title: 'Other', user_state: { is_read: true, is_saved: false, is_later: false, dismissed: false } }),
      item({ id: 'match', presentation: {
        version: 1,
        source: { id: 'source-a', catalog_type: 'rss', platform: 'rss', name: 'Official Feed' },
        author: { name: 'Author', kind: 'person' },
        timing: { published_at: '', fetched_at: '' },
        links: { canonical_url: 'https://example.com/article', source_url: 'https://example.com/article' },
        content: { title: 'Title', title_origin: 'native', excerpt: '重点关注上下文连续性', content_kind: 'feed_summary', excerpt_truncated: false },
        taxonomy: { channel: 'AI', configured_topics: [], inferred_topics: [], topics: [], entities: [] },
        engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
        analysis: { status: 'fallback', score: 0, signal_strength: 'thin', signal_type: 'other', summary_zh: '概括', action_suggestion: '' },
      } }),
    ]

    expect(filterFeedItems(values, { query: '上下文', unreadFirst: true })).toHaveLength(1)
    expect(filterFeedItems(values, { query: '', unreadFirst: true }).map((value) => value.id)).toEqual(['match', 'read'])
  })

  it('does not use legacy suggested actions as a React search field', () => {
    const values = [item({ action_suggestion: '只存在于旧建议动作中的唯一词' })]

    expect(filterFeedItems(values, { query: '唯一词', unreadFirst: false })).toEqual([])
  })

  it('applies source, channel, topic and minimum-score filters together', () => {
    const values = [
      item({ id: 'match', source_id: 'source-a', channel: 'AI', topics: ['Codex'], score: 8.2 }),
      item({ id: 'low', source_id: 'source-a', channel: 'AI', topics: ['Codex'], score: 6.5 }),
      item({ id: 'other', source_id: 'source-b', channel: '产品', topics: ['创业'], score: 9.1 }),
    ]

    expect(filterFeedItems(values, {
      query: '', unreadFirst: false, sourceId: 'source-a', channel: 'AI', topic: 'Codex', minScore: 8,
    }).map((value) => value.id)).toEqual(['match'])
  })

  it('uses the server timeline bucket and keeps a local fallback for legacy items', () => {
    const localNow = new Date(2026, 6, 21, 12, 0, 0)
    const today = item({ id: 'today', published_at: new Date(2026, 6, 21, 0, 5, 0).toISOString() })
    const fetchedToday = item({
      id: 'fetched-today',
      published_at: '',
      fetched_at: new Date(2026, 6, 21, 8, 0, 0).toISOString(),
    })
    const yesterday = item({ id: 'yesterday', published_at: new Date(2026, 6, 20, 23, 59, 0).toISOString() })
    const unknown = item({ id: 'unknown', published_at: '', fetched_at: '' })
    const serverToday = item({
      id: 'server-today',
      published_at: new Date(2026, 6, 20, 23, 59, 0).toISOString(),
      timeline_bucket: 'today',
    })
    const serverFeed = item({
      id: 'server-feed',
      published_at: new Date(2026, 6, 21, 8, 0, 0).toISOString(),
      timeline_bucket: 'feed',
    })

    expect(isFeedItemToday(today, localNow)).toBe(true)
    expect(filterFeedItems([today, fetchedToday, yesterday, unknown, serverToday, serverFeed], {
      query: '', unreadFirst: false, dateScope: 'today', now: localNow,
    }).map((value) => value.id)).toEqual(['today', 'fetched-today', 'server-today'])
  })

  it('filters with canonical presentation fields before legacy fallbacks', () => {
    const canonical = item({
      id: 'canonical',
      source_id: 'legacy-source',
      channel: '旧频道',
      topics: ['旧主题'],
      score: 1,
      presentation: {
        version: 2,
        source: { id: 'canonical-source', catalog_type: 'rss', platform: 'rss', name: 'Canonical Source' },
        author: { name: 'Author', kind: 'person' },
        timing: { published_at: '2026-07-13T08:00:00Z', fetched_at: '2026-07-13T08:01:00Z' },
        links: { canonical_url: 'https://example.com/canonical', source_url: 'https://example.com/canonical' },
        content: { title: 'Canonical', title_origin: 'native', excerpt: 'canonical body', content_kind: 'feed_summary', excerpt_truncated: false },
        taxonomy: { channel: '新频道', configured_topics: [], inferred_topics: [], topics: ['新主题'], entities: [] },
        engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
        analysis: { status: 'ai', score: 8.5, signal_strength: 'strong', signal_type: 'update', summary_zh: '概括' },
      },
    })

    expect(filterFeedItems([canonical], {
      query: '', unreadFirst: false, sourceId: 'canonical-source', channel: '新频道', topic: '新主题', minScore: 8,
    })).toEqual([canonical])
  })

  it('filters subscription scope against every canonical and provenance source id', () => {
    const canonical = item({ id: 'canonical', source_id: 'legacy-private', source_ids: ['provenance-private'], presentation: {
      version: 2,
      source: { id: 'canonical-public', catalog_type: 'rss', platform: 'rss', name: 'Canonical Source' },
      author: { name: 'Author', kind: 'person' },
      timing: { published_at: '2026-07-13T08:00:00Z', fetched_at: '2026-07-13T08:01:00Z' },
      links: { canonical_url: 'https://example.com/canonical', source_url: 'https://example.com/canonical' },
      content: { title: 'Canonical', title_origin: 'native', excerpt: 'body', content_kind: 'feed_summary', excerpt_truncated: false },
      taxonomy: { channel: '其他', configured_topics: [], inferred_topics: [], topics: [], entities: [] },
      engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
      analysis: { status: 'fallback', score: 0, signal_strength: 'thin', signal_type: 'other', summary_zh: '概括' },
    } })
    const legacy = item({ id: 'legacy', source_id: 'legacy-private', source_ids: ['public-provenance'] })

    expect(filterFeedItems([canonical, legacy], {
      query: '', unreadFirst: false, allowedSourceIds: new Set(['canonical-public']),
    }).map(({ id }) => id)).toEqual(['canonical'])
    expect(filterFeedItems([canonical, legacy], {
      query: '', unreadFirst: false, allowedSourceIds: new Set(['public-provenance']),
    }).map(({ id }) => id)).toEqual(['legacy'])
    expect(filterFeedItems([canonical, legacy], {
      query: '', unreadFirst: false, allowedSourceIds: new Set(),
    })).toEqual([])
  })

  it('keeps legacy history items usable when timeline metadata is the only presentation section', () => {
    const legacy = item({
      id: 'legacy-history',
      source_id: 'legacy-source',
      source: 'Legacy Source',
      presentation: {
        timing: { effective_at: '2026-05-01T08:00:00Z' },
      } as unknown as FeedItem['presentation'],
    })

    expect(filterFeedItems([legacy], {
      query: 'codex',
      unreadFirst: false,
      sourceId: 'legacy-source',
    })).toEqual([legacy])
  })

  it('rejects script, credential and non-http external URLs', () => {
    expect(safeExternalUrl('https://example.com/read')).toBe('https://example.com/read')
    expect(safeExternalUrl('https://user:pass@example.com/read')).toBe('')
    expect(safeExternalUrl('javascript:alert(1)')).toBe('')
  })
})
