import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it } from 'vitest'

import { clearUserCache } from './sessionCache'

describe('session cache isolation', () => {
  it('removes only the previous user data when identity changes', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['user', 'user-a', 'feed'], { items: ['a'] })
    queryClient.setQueryData(['user', 'user-b', 'feed'], { items: ['b'] })

    await clearUserCache(queryClient, 'user-a')

    expect(queryClient.getQueryData(['user', 'user-a', 'feed'])).toBeUndefined()
    expect(queryClient.getQueryData(['user', 'user-b', 'feed'])).toEqual({ items: ['b'] })
  })

  it('clears only the departing user Agent context draft', async () => {
    const queryClient = new QueryClient()
    window.sessionStorage.setItem('inteliscope.agent-context.v1:user-a', '{"itemIds":["a"]}')
    window.sessionStorage.setItem('inteliscope.agent-context.v1:user-b', '{"itemIds":["b"]}')

    await clearUserCache(queryClient, 'user-a')

    expect(window.sessionStorage.getItem('inteliscope.agent-context.v1:user-a')).toBeNull()
    expect(window.sessionStorage.getItem('inteliscope.agent-context.v1:user-b')).not.toBeNull()
  })

  it('clears only the departing user feed-end tab session', async () => {
    const queryClient = new QueryClient()
    window.sessionStorage.setItem('inteliscope.feed-end-messages.v1.user-a', '{"endVisits":2}')
    window.sessionStorage.setItem('inteliscope.feed-end-messages.v1.user-b', '{"endVisits":3}')

    await clearUserCache(queryClient, 'user-a')

    expect(window.sessionStorage.getItem('inteliscope.feed-end-messages.v1.user-a')).toBeNull()
    expect(window.sessionStorage.getItem('inteliscope.feed-end-messages.v1.user-b')).not.toBeNull()
  })

  it('clears only the departing user persistent source summaries', async () => {
    const queryClient = new QueryClient()
    window.localStorage.setItem('inteliscope.source-summary.v1:user-a', '{"entries":{}}')
    window.localStorage.setItem('inteliscope.source-summary.v1:user-b', '{"entries":{}}')
    window.localStorage.setItem('inteliscope.source-summary.v2:user-a', '{"entries":{}}')
    window.localStorage.setItem('inteliscope.source-summary.v2:user-b', '{"entries":{}}')

    await clearUserCache(queryClient, 'user-a')

    expect(window.localStorage.getItem('inteliscope.source-summary.v1:user-a')).toBeNull()
    expect(window.localStorage.getItem('inteliscope.source-summary.v1:user-b')).not.toBeNull()
    expect(window.localStorage.getItem('inteliscope.source-summary.v2:user-a')).toBeNull()
    expect(window.localStorage.getItem('inteliscope.source-summary.v2:user-b')).not.toBeNull()
    window.localStorage.removeItem('inteliscope.source-summary.v1:user-b')
    window.localStorage.removeItem('inteliscope.source-summary.v2:user-b')
  })
})
