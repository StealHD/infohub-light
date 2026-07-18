import { describe, expect, it } from 'vitest'

import type { FeedItem, SourceHealthItem } from '../../api/types'
import { filterFeedItems, resolveItemHealth, safeExternalUrl, selectModeItems, sortWorkbenchItems } from './feedModel'

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
  it('selects featured, all and daily collections without inventing items', () => {
    const all = [item({ id: 'all' })]
    const featured = [item({ id: 'featured' })]
    const daily = [item({ id: 'daily' })]
    const snapshot = { schema_version: 2, items: all, featured_items: featured, daily_push_items: daily }

    expect(selectModeItems(snapshot, 'all')).toEqual(all)
    expect(selectModeItems(snapshot, 'featured')).toEqual(featured)
    expect(selectModeItems(snapshot, 'daily')).toEqual(daily)
  })

  it('orders all Feed items from older to newer while keeping invalid timestamps stable', () => {
    const invalidFirst = item({ id: 'invalid-first', published_at: 'unknown' })
    const newer = item({ id: 'newer', published_at: '2026-07-13T10:00:00Z' })
    const older = item({ id: 'older', published_at: '2026-07-13T08:00:00Z' })
    const invalidSecond = item({ id: 'invalid-second', published_at: '' })

    expect(selectModeItems({
      schema_version: 2,
      items: [invalidFirst, newer, older, invalidSecond],
    }, 'all').map(({ id }) => id)).toEqual(['older', 'newer', 'invalid-first', 'invalid-second'])
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

  it('uses the most concerning source health across duplicate provenance', () => {
    const health: SourceHealthItem[] = [
      { subscription_id: 'sub-a', source_id: 'source-a', status: 'healthy', consecutive_failures: 0 },
      { subscription_id: 'sub-b', source_id: 'source-b', status: 'failing', consecutive_failures: 3 },
    ]

    expect(resolveItemHealth(item({ subscription_ids: ['sub-a', 'sub-b'] }), health)?.status).toBe('failing')
  })

  it('rejects script, credential and non-http external URLs', () => {
    expect(safeExternalUrl('https://example.com/read')).toBe('https://example.com/read')
    expect(safeExternalUrl('https://user:pass@example.com/read')).toBe('')
    expect(safeExternalUrl('javascript:alert(1)')).toBe('')
  })
})
