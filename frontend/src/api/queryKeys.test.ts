import { describe, expect, it } from 'vitest'

import { queryKeys } from './queryKeys'

describe('query keys', () => {
  it('scopes every private resource by user id', () => {
    expect(queryKeys.feedRoot('user-a')).toEqual(['user', 'user-a', 'feed'])
    expect(queryKeys.feed('user-a', { hideDismissed: true, unreadFirst: false })).toEqual([
      'user', 'user-a', 'feed', { hideDismissed: true, unreadFirst: false },
    ])
    expect(queryKeys.history('user-a', { q: 'needle', sourceId: 'source-1', limit: 50 })).toEqual([
      'user', 'user-a', 'history', { q: 'needle', sourceId: 'source-1', limit: 50 },
    ])
    expect(queryKeys.subscriptions('user-b')).toEqual(['user', 'user-b', 'subscriptions'])
    expect(queryKeys.feedJobs('user-b')).toEqual(['user', 'user-b', 'feed-jobs'])
    expect(queryKeys.jobs('user-b')).toEqual(['user', 'user-b', 'jobs'])
    expect(queryKeys.notificationSettings('user-b')).toEqual(['user', 'user-b', 'notification-settings'])
    expect(queryKeys.notificationTargets('user-b')).toEqual(['user', 'user-b', 'notification-targets'])
    expect(queryKeys.notificationEmailTransport('user-b')).toEqual([
      'user', 'user-b', 'notification-email-transport',
    ])
    expect(queryKeys.notificationTelegramTransport('user-b')).toEqual([
      'user', 'user-b', 'notification-telegram-transport',
    ])
    expect(queryKeys.agentDelegations('user-b')).toEqual(['user', 'user-b', 'agent-delegations'])
    expect(queryKeys.apifyKeyPool('user-a')).toEqual(['user', 'user-a', 'apify-key-pool'])
    expect(queryKeys.storageSummary('user-a')).toEqual(['user', 'user-a', 'storage-summary'])
    expect(queryKeys.storageArchives('user-a')).toEqual(['user', 'user-a', 'storage-archives'])
    expect(queryKeys.secretQuota('user-a', 'secret-1')).toEqual([
      'user', 'user-a', 'secret-quota', 'secret-1',
    ])
    expect(queryKeys.secretQuota('user-b', 'secret-1')).not.toEqual(
      queryKeys.secretQuota('user-a', 'secret-1'),
    )
    expect(queryKeys.notificationSettings('user-b')).not.toEqual(
      queryKeys.notificationSettings('user-a'),
    )
    expect(queryKeys.notificationTargets('user-b')).not.toEqual(
      queryKeys.notificationTargets('user-a'),
    )
    expect(queryKeys.notificationEmailTransport('user-b')).not.toEqual(
      queryKeys.notificationEmailTransport('user-a'),
    )
    expect(queryKeys.notificationTelegramTransport('user-b')).not.toEqual(
      queryKeys.notificationTelegramTransport('user-a'),
    )
  })
})
