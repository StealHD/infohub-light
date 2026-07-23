import { describe, expect, it } from 'vitest'

import type { FeedPreference } from '../feed/feedPreference'
import { applyQuickView, detectActiveQuickView } from './workbenchQuickViews'

const base: FeedPreference = {
  unreadFirst: false,
  source: 'source-a',
  channel: '投资',
  topic: 'Codex',
  minScore: 8,
  order: 'oldest',
  sortBasis: 'published',
  dateScope: 'all',
  subscriptionScope: 'all',
}

describe('workbench quick views', () => {
  it('resets every filter with the all view while preserving order', () => {
    const preference = applyQuickView(base, 'all')

    expect(preference).toEqual({
      unreadFirst: false,
      source: '',
      channel: '',
      topic: '',
      minScore: undefined,
      order: 'oldest',
      sortBasis: 'published',
      dateScope: 'all',
      subscriptionScope: 'all',
    })
    expect(detectActiveQuickView(preference)).toBe('all')
  })

  it('applies the browser-local today scope and clears conflicting filters', () => {
    const preference = applyQuickView(base, 'today')

    expect(preference).toMatchObject({
      unreadFirst: false,
      source: '',
      channel: '',
      topic: '',
      minScore: undefined,
      order: 'oldest',
      dateScope: 'today',
      subscriptionScope: 'all',
    })
    expect(detectActiveQuickView(preference)).toBe('today')
  })

  it.each([
    ['public', 'public'],
    ['private', 'private'],
  ] as const)('applies the %s subscription view', (view, subscriptionScope) => {
    const preference = applyQuickView(base, view)
    expect(preference).toMatchObject({ unreadFirst: false, source: '', channel: '', topic: '', minScore: undefined, order: 'oldest', subscriptionScope })
    expect(detectActiveQuickView(preference)).toBe(view)
  })

  it('treats mixed manual filters as custom', () => {
    expect(detectActiveQuickView({ ...applyQuickView(base, 'public'), topic: 'Agent' })).toBeNull()
  })
})
