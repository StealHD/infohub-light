import { describe, expect, it } from 'vitest'

import { queryKeys } from './queryKeys'

describe('query keys', () => {
  it('scopes every private resource by user id', () => {
    expect(queryKeys.feed('user-a', { hideDismissed: true, unreadFirst: false })).toEqual([
      'user', 'user-a', 'feed', { hideDismissed: true, unreadFirst: false },
    ])
    expect(queryKeys.subscriptions('user-b')).toEqual(['user', 'user-b', 'subscriptions'])
    expect(queryKeys.jobs('user-b')).toEqual(['user', 'user-b', 'jobs'])
    expect(queryKeys.agentDelegations('user-b')).toEqual(['user', 'user-b', 'agent-delegations'])
  })
})
