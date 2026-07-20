import { describe, expect, it } from 'vitest'

import type { FeedSnapshot } from '../../api/types'
import { patchItemStateInData } from './feedCache'

describe('feed cache', () => {
  it('updates every copy of an article without mutating the previous response', () => {
    const previous: FeedSnapshot = {
      schema_version: 2,
      items: [{
        id: 'article-1', title: 'Title', url: 'https://example.com',
        user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
      }],
      featured_items: [{
        id: 'article-1', title: 'Title', url: 'https://example.com',
        user_state: { is_read: false, is_saved: false, is_later: false, dismissed: false },
      }],
    }

    const next = patchItemStateInData(previous, 'article-1', { is_saved: true }) as FeedSnapshot

    expect(next.items[0].user_state?.is_saved).toBe(true)
    expect(next.featured_items?.[0].user_state?.is_saved).toBe(true)
    expect(previous.items[0].user_state?.is_saved).toBe(false)
  })

  it('updates standalone detail responses as well as saved collections', () => {
    const detail = {
      id: 'article-1',
      title: 'Detail',
      url: 'https://example.com/detail',
      user_state: { is_read: false, is_saved: true, is_later: false, dismissed: false },
    }
    const saved = { schema_version: 1, scope: 'user', items: [detail], item_count: 1, limit: 200, offset: 0 }

    const nextDetail = patchItemStateInData(detail, 'article-1', { is_saved: false }) as typeof detail
    const nextSaved = patchItemStateInData(saved, 'article-1', { is_saved: false }) as typeof saved

    expect(nextDetail.user_state.is_saved).toBe(false)
    expect(nextSaved.items[0].user_state.is_saved).toBe(false)
  })
})
