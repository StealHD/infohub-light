import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  readSessionDeleteConfirmation,
  sessionDeleteConfirmPreferenceKey,
  writeSessionDeleteConfirmation,
} from './sessionDeletePreference'

describe('session delete confirmation preference', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.restoreAllMocks()
  })

  it('defaults to confirmation and isolates the opt-out by account', () => {
    expect(readSessionDeleteConfirmation('user-a')).toBe(true)
    expect(writeSessionDeleteConfirmation('user-a', false)).toBe(true)
    expect(readSessionDeleteConfirmation('user-a')).toBe(false)
    expect(readSessionDeleteConfirmation('user-b')).toBe(true)

    expect(writeSessionDeleteConfirmation('user-a', true)).toBe(true)
    expect(readSessionDeleteConfirmation('user-a')).toBe(true)
  })

  it('treats invalid values and unavailable storage as confirmation enabled', () => {
    window.localStorage.setItem(sessionDeleteConfirmPreferenceKey('user-a'), 'invalid')
    expect(readSessionDeleteConfirmation('user-a')).toBe(true)

    vi.spyOn(Storage.prototype, 'getItem').mockImplementationOnce(() => { throw new Error('blocked') })
    expect(readSessionDeleteConfirmation('user-a')).toBe(true)
    vi.spyOn(Storage.prototype, 'setItem').mockImplementationOnce(() => { throw new Error('blocked') })
    expect(writeSessionDeleteConfirmation('user-b', false)).toBe(false)
  })
})
