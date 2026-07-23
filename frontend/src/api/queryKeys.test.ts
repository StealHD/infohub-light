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
    expect(queryKeys.apifyKeyPool('user-a')).toEqual(['user', 'user-a', 'apify-key-pool'])
    expect(queryKeys.secretQuota('user-a', 'secret-1')).toEqual([
      'user', 'user-a', 'secret-quota', 'secret-1',
    ])
    expect(queryKeys.secretQuota('user-b', 'secret-1')).not.toEqual(
      queryKeys.secretQuota('user-a', 'secret-1'),
    )
  })
})
