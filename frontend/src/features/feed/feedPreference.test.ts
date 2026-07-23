import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  FEED_PREFERENCE_CHANGED_EVENT,
  readFeedPreference,
  writeFeedPreference,
} from './feedPreference'

function memoryStorage(): Storage {
  const values = new Map<string, string>()
  return {
    get length() { return values.size },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => Array.from(values.keys())[index] ?? null,
    removeItem: (key) => { values.delete(key) },
    setItem: (key, value) => { values.set(key, String(value)) },
  }
}

describe('feed preference', () => {
  beforeEach(() => Object.defineProperty(window, 'localStorage', { configurable: true, value: memoryStorage() }))

  it('persists only the v2 workbench filters independently per user', () => {
    writeFeedPreference('user-a', {
      unreadFirst: true,
      source: 'source-a',
      channel: 'AI',
      topic: 'Codex',
      minScore: 8,
      order: 'oldest',
      sortBasis: 'published',
      dateScope: 'today',
      subscriptionScope: 'public',
    })

    expect(readFeedPreference('user-a')).toEqual({
      unreadFirst: true,
      source: 'source-a',
      channel: 'AI',
      topic: 'Codex',
      minScore: undefined,
      order: 'oldest',
      sortBasis: 'published',
      dateScope: 'today',
      subscriptionScope: 'public',
    })
    expect(readFeedPreference('user-b')).toEqual({ unreadFirst: false, source: '', channel: '', topic: '', minScore: undefined, order: 'newest', sortBasis: 'published', dateScope: 'all', subscriptionScope: 'all' })
    expect(window.localStorage.getItem('inteliscope.ui.feed.v2:user-a')).not.toBeNull()
  })

  it('migrates only unread-first from v1 and ignores the retired mode', () => {
    window.localStorage.setItem('inteliscope.ui.feed.v1:user-a', JSON.stringify({ mode: 'daily', unreadFirst: true }))

    expect(readFeedPreference('user-a')).toEqual({ unreadFirst: true, source: '', channel: '', topic: '', minScore: undefined, order: 'newest', sortBasis: 'published', dateScope: 'all', subscriptionScope: 'all' })
    expect(JSON.parse(window.localStorage.getItem('inteliscope.ui.feed.v2:user-a') || '{}')).toEqual({ unreadFirst: true })
  })

  it('falls back safely when v2 data is malformed', () => {
    window.localStorage.setItem('inteliscope.ui.feed.v2:user-a', '{broken')
    expect(readFeedPreference('user-a')).toEqual({ unreadFirst: false, source: '', channel: '', topic: '', minScore: undefined, order: 'newest', sortBasis: 'published', dateScope: 'all', subscriptionScope: 'all' })
  })

  it('sanitizes an invalid persisted order to newest', () => {
    window.localStorage.setItem('inteliscope.ui.feed.v2:user-a', JSON.stringify({ order: 'sideways' }))

    expect(readFeedPreference('user-a').order).toBe('newest')
  })

  it('emits one account-scoped same-tab event after writing', () => {
    const onChanged = vi.fn()
    window.addEventListener(FEED_PREFERENCE_CHANGED_EVENT, onChanged)

    writeFeedPreference('user-a', {
      unreadFirst: false,
      source: '',
      channel: '',
      topic: '',
      minScore: undefined,
      order: 'newest',
      sortBasis: 'ingested',
      dateScope: 'all',
      subscriptionScope: 'private',
    })

    expect(onChanged).toHaveBeenCalledTimes(1)
    expect((onChanged.mock.calls[0]?.[0] as CustomEvent).detail).toEqual({ userId: 'user-a' })
    window.removeEventListener(FEED_PREFERENCE_CHANGED_EVENT, onChanged)
  })

  it('sanitizes legacy and invalid subscription scopes to all', () => {
    window.localStorage.setItem('inteliscope.ui.feed.v2:user-a', JSON.stringify({ subscriptionScope: 'workspace' }))
    expect(readFeedPreference('user-a').subscriptionScope).toBe('all')
  })
})
