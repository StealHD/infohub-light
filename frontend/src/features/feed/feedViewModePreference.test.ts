import { afterEach, describe, expect, it } from 'vitest'

import { readFeedViewMode, writeFeedViewMode } from './feedViewModePreference'

describe('feed view mode preference', () => {
  afterEach(() => window.localStorage.clear())

  it('defaults invalid, missing, and malformed values to the timeline', () => {
    expect(readFeedViewMode('member-a')).toBe('timeline')

    window.localStorage.setItem('inteliscope.ui.feed-view.v1:member-a', JSON.stringify('unexpected'))
    expect(readFeedViewMode('member-a')).toBe('timeline')

    window.localStorage.setItem('inteliscope.ui.feed-view.v1:member-a', '{')
    expect(readFeedViewMode('member-a')).toBe('timeline')
  })

  it('persists the chosen mode per user without changing Feed query state', () => {
    writeFeedViewMode('member-a', 'source-overview')
    writeFeedViewMode('member-b', 'timeline')

    expect(readFeedViewMode('member-a')).toBe('source-overview')
    expect(readFeedViewMode('member-b')).toBe('timeline')
    expect(window.localStorage.getItem('inteliscope.ui.feed-view.v1:member-a')).toBe(JSON.stringify('source-overview'))
  })
})
