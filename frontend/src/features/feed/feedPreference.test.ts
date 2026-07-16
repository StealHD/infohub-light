import { beforeEach, describe, expect, it } from 'vitest'

import { readFeedPreference, writeFeedPreference } from './feedPreference'

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

  it('persists feed mode and unread-first independently per user', () => {
    writeFeedPreference('user-a', { mode: 'all', unreadFirst: true })

    expect(readFeedPreference('user-a')).toEqual({ mode: 'all', unreadFirst: true })
    expect(readFeedPreference('user-b')).toEqual({ mode: 'featured', unreadFirst: false })
  })

  it('falls back safely when stored data is malformed', () => {
    window.localStorage.setItem('inteliscope.ui.feed.v1:user-a', '{broken')
    expect(readFeedPreference('user-a')).toEqual({ mode: 'featured', unreadFirst: false })
  })
})
