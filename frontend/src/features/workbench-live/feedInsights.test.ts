import { describe, expect, it } from 'vitest'

import type { FeedItem, FeedSnapshot, SourceHealthResponse } from '../../api/types'
import type { FeedPreference } from '../feed/feedPreference'
import { buildFeedInsightsModel } from './feedInsights'

const preference: FeedPreference = {
  unreadFirst: false,
  source: '',
  channel: '',
  topic: '',
  minScore: undefined,
  order: 'newest',
  sortBasis: 'ingested',
  dateScope: 'all',
  subscriptionScope: 'all',
}

function item(id: string, overrides: Partial<FeedItem> = {}): FeedItem {
  return {
    id,
    title: id,
    url: `https://example.com/${id}`,
    source_type: 'rss',
    channel: 'AI',
    published_at: new Date(2026, 6, 21, 8, 0, 0).toISOString(),
    user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
    ...overrides,
  }
}

describe('feed insights', () => {
  it('projects today, state, health, channel, type and current visible counts', () => {
    const snapshot: FeedSnapshot = {
      schema_version: 2,
      generated_at: new Date(2026, 6, 21, 9, 0, 0).toISOString(),
      items: [
        item('today-unread'),
        item('saved-video', {
          channel: '产品机会',
          user_state: { is_read: true, is_saved: true, is_later: false, dismissed: false },
          presentation: {
            version: 2,
            source: { id: 'source-video', catalog_type: 'rss', platform: 'rss', name: 'Video' },
            author: { name: '', kind: 'unknown' },
            timing: { published_at: new Date(2026, 6, 20, 8, 0, 0).toISOString(), fetched_at: '' },
            links: { canonical_url: 'https://youtube.com/watch?v=1', source_url: '' },
            content: { title: 'Video', title_origin: 'native', excerpt: '', content_kind: 'feed_summary', excerpt_truncated: false, format: 'video', format_origin: 'upstream' },
            taxonomy: { channel: '产品机会', configured_topics: [], inferred_topics: [], topics: [], entities: [] },
            engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
            analysis: { status: 'fallback', score: 0, signal_strength: 'thin', signal_type: 'other', summary_zh: '' },
          },
        }),
      ],
    }
    const health: SourceHealthResponse = {
      schema_version: 1,
      scope: 'user',
      summary: { unknown: 0, healthy: 0, degraded: 1, failing: 1, total: 2 },
      items: [
        { subscription_id: 'sub-1', source_id: 'same-source', status: 'degraded', consecutive_failures: 1 },
        { subscription_id: 'sub-2', source_id: 'same-source', status: 'failing', consecutive_failures: 2 },
      ],
    }

    const model = buildFeedInsightsModel({ snapshot, health, preference, query: 'today', now: new Date(2026, 6, 21, 12, 0, 0) })

    expect(model).toMatchObject({ todayCount: 1, unreadCount: 1, savedCount: 1, unhealthySourceCount: 1, visibleCount: 1, totalCount: 2 })
    expect(model.channels.map(({ label, count }) => [label, count])).toEqual(expect.arrayContaining([['AI', 1], ['产品机会', 1]]))
    expect(model.formats.map(({ label }) => label)).toEqual(expect.arrayContaining(['文章', '视频']))
  })

  it('uses the subscription catalog scope for the current visible count', () => {
    const snapshot: FeedSnapshot = {
      schema_version: 2,
      generated_at: new Date(2026, 6, 21, 9, 0, 0).toISOString(),
      items: [
        item('public', { source_id: 'source-public' }),
        item('private', { source_id: 'source-private' }),
      ],
    }
    const scopedPreference = { ...preference, subscriptionScope: 'public' as const }
    const model = buildFeedInsightsModel({
      snapshot,
      preference: scopedPreference,
      query: '',
      allowedSourceIds: new Set(['source-public']),
    })

    expect(model.visibleCount).toBe(1)
    expect(model.totalCount).toBe(2)
  })
})
