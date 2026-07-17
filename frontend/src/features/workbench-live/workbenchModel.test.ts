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
