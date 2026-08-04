import { describe, expect, it } from 'vitest'

import {
  preserveSettingsReturnState,
  sanitizeSettingsReturnTo,
  settingsReturnStateForLocation,
  settingsReturnToFromState,
} from './settingsReturnState'

describe('settingsReturnState', () => {
  it('preserves an originating in-app destination including query and hash', () => {
    expect(settingsReturnStateForLocation({
      pathname: '/feed',
      search: '?channel=AI',
      hash: '#item-1',
    })).toEqual({ settingsReturnTo: '/feed?channel=AI#item-1' })
    expect(settingsReturnToFromState({ settingsReturnTo: '/saved?filter=unread' })).toBe('/saved?filter=unread')
  })

  it('rejects loops, login and external-looking destinations', () => {
    expect(sanitizeSettingsReturnTo('/settings/appearance')).toBeNull()
    expect(sanitizeSettingsReturnTo('/login')).toBeNull()
    expect(sanitizeSettingsReturnTo('//example.com/feed')).toBeNull()
    expect(sanitizeSettingsReturnTo('https://example.com/feed')).toBeNull()
    expect(settingsReturnToFromState({ settingsReturnTo: '/settings' })).toBe('/feed')
  })

  it('normalizes missing state to the Feed fallback', () => {
    expect(preserveSettingsReturnState(undefined)).toEqual({ settingsReturnTo: '/feed' })
    expect(settingsReturnToFromState(null)).toBe('/feed')
  })
})
