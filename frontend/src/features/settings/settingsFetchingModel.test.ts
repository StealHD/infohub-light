import { describe, expect, it } from 'vitest'

import {
  buildFilteringPayload,
  buildRsshubPayload,
  configuredFilteringPayload,
  configuredRsshubPayload,
  configuredTopics,
  normalizeTopics,
  sameFetchingPayload,
} from './settingsFetchingModel'

function formWith(values: Record<string, string>): HTMLFormElement {
  const form = document.createElement('form')
  Object.entries(values).forEach(([name, value]) => {
    const input = document.createElement('input')
    input.name = name
    input.value = value
    form.append(input)
  })
  return form
}

describe('settingsFetchingModel', () => {
  it('builds the existing RSSHub and filtering payload shapes', () => {
    expect(buildRsshubPayload(formWith({ base_url: ' https://rsshub.example.com/ ' }))).toEqual({ base_url: 'https://rsshub.example.com/' })
    expect(buildFilteringPayload({
      form: formWith({ time_window_hours: '48', feed_window_days: '14', rss_initial_fetch_window_hours: '720', recent_item_limit: '40' }),
      configured: { preserve_unknown_filter: true },
    })).toEqual({
      preserve_unknown_filter: true,
      time_window_hours: 48,
      feed_window_days: 14,
      rss_initial_fetch_window_hours: 720,
      recent_item_limit: 40,
    })
  })

  it('keeps configured comparisons, topic fallbacks and normalization stable', () => {
    expect(configuredRsshubPayload({})).toEqual({ base_url: 'http://rsshub:1200' })
    expect(configuredFilteringPayload({ time_window_hours: 12 })).toMatchObject({
      time_window_hours: 12,
      feed_window_days: 7,
      rss_initial_fetch_window_hours: 168,
      recent_item_limit: 20,
    })
    expect(configuredTopics({ tags: ['Legacy'] }, ['AI', 3])).toEqual(['AI'])
    expect(normalizeTopics([' #AI ', 'ai', '', '# Design'])).toEqual(['AI', 'Design'])
    expect(sameFetchingPayload({ a: 1 }, { a: 1 })).toBe(true)
  })
})
