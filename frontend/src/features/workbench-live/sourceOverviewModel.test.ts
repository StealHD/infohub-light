import { describe, expect, it } from 'vitest'

import type { FeedItem } from '../../api/types'
import { toWorkbenchCardModel } from './workbenchModel'
import { buildSourceOverviewSections } from './sourceOverviewModel'

function item(id: string, options: Partial<FeedItem> = {}) {
  return toWorkbenchCardModel({
    id,
    title: `标题 ${id}`,
    url: `https://example.com/${id}`,
    source: '默认来源',
    source_type: 'rss',
    published_at: '2026-08-01T00:00:00Z',
    topics: [],
    user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
    ...options,
  })
}

describe('source overview model', () => {
  it('groups by the primary source, keeps merged content singular, and orders latest published source first', () => {
    const sections = buildSourceOverviewSections([
      item('old-a', { source_id: 'a', source: '来源 A', published_at: '2026-08-01T00:00:00Z' }),
      item('new-b', { source_id: 'b', source: '来源 B', published_at: '2026-08-03T00:00:00Z' }),
      item('merged-a', { source_id: 'a', source_ids: ['a', 'b'], source: '来源 A', published_at: '2026-08-02T00:00:00Z' }),
    ])

    expect(sections.map((section) => section.id)).toEqual(['source:b', 'source:a'])
    expect(sections[1]?.cards.map((card) => card.id)).toEqual(['old-a', 'merged-a'])
  })

  it('uses stable source and subscription fallbacks when presentation source ids are absent', () => {
    const sections = buildSourceOverviewSections([
      item('source-ids', { source_ids: ['source-fallback'], source: '来源 A' }),
      item('subscription', { subscription_id: 'subscription-fallback', source: '来源 B' }),
      item('display-fallback', { source: '无标识来源', source_type: 'telegram' }),
    ])

    expect(sections.map((section) => section.id)).toEqual([
      'source:source-fallback',
      'source:subscription-fallback',
      'fallback:telegram:无标识来源',
    ])
  })

  it('counts all distinct topics and shows the three most frequent in first-seen order on ties', () => {
    const sections = buildSourceOverviewSections([
      item('one', { source_id: 'a', topics: ['AI', '#产品', 'AI'] }),
      item('two', { source_id: 'a', topics: ['产品', '工程'] }),
      item('three', { source_id: 'a', topics: ['AI', '市场'] }),
    ])

    expect(sections[0]).toMatchObject({ topicCount: 4, topics: ['AI', '产品', '工程'] })
  })

  it('keeps sources without valid published times at the end in first-seen order', () => {
    const sections = buildSourceOverviewSections([
      item('invalid-a', { source_id: 'a', source: 'A', published_at: 'invalid' }),
      item('dated-c', { source_id: 'c', source: 'C', published_at: '2026-08-02T00:00:00Z' }),
      item('missing-b', { source_id: 'b', source: 'B', published_at: undefined }),
    ])

    expect(sections.map((section) => section.id)).toEqual(['source:c', 'source:a', 'source:b'])
  })
})
