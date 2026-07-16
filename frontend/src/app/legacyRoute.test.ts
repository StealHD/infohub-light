import { describe, expect, it } from 'vitest'

import { legacyViewDestination } from './legacyRoute'

describe('legacy view migration', () => {
  it.each([
    ['featured', '/feed?mode=featured'],
    ['all', '/feed?mode=all'],
    ['daily', '/feed?mode=daily'],
    ['readLater', '/later'],
    ['history', '/history'],
    ['subscriptions', '/subscriptions'],
    ['config', '/settings'],
  ])('maps %s to %s', (view, destination) => {
    expect(legacyViewDestination(view)).toBe(destination)
  })

  it('ignores unknown views', () => {
    expect(legacyViewDestination('graph')).toBeNull()
  })
})
