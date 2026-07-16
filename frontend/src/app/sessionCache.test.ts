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
})
