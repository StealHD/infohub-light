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
    })
    expect(detectActiveQuickView(preference)).toBe('all')
  })

  it('applies unread without changing the selected order', () => {
    expect(applyQuickView(base, 'unread')).toEqual({
      unreadFirst: true,
      source: '',
      channel: '',
      topic: '',
      minScore: undefined,
      order: 'oldest',
    })
    expect(base.channel).toBe('投资')
  })

  it.each([
    ['ai', 'AI'],
    ['friends', '朋友动态'],
    ['product', '产品机会'],
  ] as const)('applies the %s channel view', (view, channel) => {
    const preference = applyQuickView(base, view)
    expect(preference).toMatchObject({ unreadFirst: false, source: '', channel, topic: '', minScore: undefined, order: 'oldest' })
    expect(detectActiveQuickView(preference)).toBe(view)
  })

  it('detects unread and treats mixed manual filters as custom', () => {
    expect(detectActiveQuickView(applyQuickView(base, 'unread'))).toBe('unread')
    expect(detectActiveQuickView({ ...applyQuickView(base, 'ai'), topic: 'Agent' })).toBeNull()
  })
})
