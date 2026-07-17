import { describe, expect, it } from 'vitest'

import type { FeedItem, FeedSnapshot } from '../../api/types'
import {
  cleanLegacyModeSearch,
  mergeDeepLinkedItem,
  sampleTickIndexes,
  selectWorkbenchSourceItems,
  toWorkbenchCardModel,
} from './workbenchModel'

const item = (id: string, publishedAt?: string): FeedItem => ({
  id,
  title: `标题 ${id}`,
  url: `https://example.com/${id}`,
  published_at: publishedAt,
  source: '测试来源',
  summary_zh: `摘要 ${id}`,
  channel: 'AI',
  topics: ['Codex'],
  user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
})

describe('live workbench model', () => {
  it('reads only snapshot.items for Feed and maps the shared card contract', () => {
    const all = item('all', '2026-07-13T08:00:00Z')
    const snapshot: FeedSnapshot = {
      schema_version: 2,
      items: [all],
      featured_items: [item('featured')],
      daily_push_items: [item('daily')],
    }

    expect(selectWorkbenchSourceItems('feed', { snapshot })).toEqual([all])
    expect(toWorkbenchCardModel(all)).toMatchObject({
      id: 'all',
      title: '标题 all',
      summary: '摘要 all',
      source: '测试来源',
      channel: 'AI',
      topics: ['Codex'],
    })
  })

  it('inserts a deep-linked item chronologically without duplicating an existing item', () => {
    const older = item('older', '2026-07-13T08:00:00Z')
    const newest = item('newest', '2026-07-13T12:00:00Z')
    const middle = item('middle', '2026-07-13T10:00:00Z')

    expect(mergeDeepLinkedItem([older, newest], middle).map(({ id }) => id)).toEqual(['older', 'middle', 'newest'])
    expect(mergeDeepLinkedItem([older, middle], middle)).toHaveLength(2)
  })

  it('replaces a late snapshot copy with fetched v2 detail while preserving user state', () => {
    const snapshot = item('selected', '2026-07-13T10:00:00Z')
    snapshot.user_state = { is_read: false, is_saved: true, is_later: false, dismissed: false }
    const detail: FeedItem = {
      id: 'selected',
      title: '旧兼容标题',
      url: 'https://example.com/selected',
      presentation: {
        version: 2,
        source: { id: 'source-v2', catalog_type: 'rss', platform: 'rss', name: 'V2 来源' },
        author: { name: '作者', kind: 'person' },
        timing: { published_at: '2026-07-13T10:00:00Z', fetched_at: '2026-07-13T10:01:00Z' },
        links: { canonical_url: 'https://example.com/selected', source_url: 'https://example.com/selected' },
        content: { title: '详情标题', title_origin: 'native', excerpt: '详情摘录', body_text: '完整详情正文', content_kind: 'post_body', excerpt_truncated: false, body_truncated: false },
        taxonomy: { channel: '详情频道', configured_topics: [], inferred_topics: [], topics: ['详情主题'], entities: [] },
        engagement: { native_score: null, likes: null, comments: null, reposts: null, shares: null, upvote_ratio: null },
        analysis: { status: 'ai', score: 9, signal_strength: 'strong', signal_type: 'update', summary_zh: '详情概括' },
      },
    }

    const [merged] = mergeDeepLinkedItem([snapshot], detail)
    expect(merged.user_state?.is_saved).toBe(true)
    expect(toWorkbenchCardModel(merged)).toMatchObject({
      title: '详情标题',
      body: '完整详情正文',
      summary: '详情概括',
      source: 'V2 来源',
    })
  })

  it('cleans retired mode parameters while preserving item deep links', () => {
    expect(cleanLegacyModeSearch('?mode=daily&item=article-1&source=rss')).toBe('?item=article-1&source=rss')
  })

  it('samples at most twelve stable tick targets across long feeds', () => {
    const indexes = sampleTickIndexes(200)
    expect(indexes).toHaveLength(12)
    expect(indexes[0]).toBe(0)
    expect(indexes.at(-1)).toBe(199)
    expect(new Set(indexes).size).toBe(indexes.length)
  })
})
