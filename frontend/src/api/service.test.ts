import { describe, expect, it, vi } from 'vitest'

import type { ApiClient } from './client'
import { createServiceApi } from './service'

describe('service api', () => {
  it('uses the existing feed, job and item-state endpoints', async () => {
    const client = {
      get: vi.fn().mockResolvedValue({}),
      post: vi.fn().mockResolvedValue({}),
      patch: vi.fn().mockResolvedValue({}),
      put: vi.fn().mockResolvedValue({}),
      delete: vi.fn().mockResolvedValue({}),
    } as unknown as ApiClient
    const api = createServiceApi(client)

    await api.latestFeed()
    await api.feedEndMessages()
    await api.refreshFeedEndMessages()
    await api.feedJobs()
    await api.jobs()
    await api.subscriptions()
    await api.feedSchedule()
    await api.job('job/1')
    const historySignal = new AbortController().signal
    await api.historyFeed({
      q: 'tsucha ri',
      sourceId: 'source/with space',
      limit: 50,
      offset: 100,
    }, historySignal)
    await api.savedFeed()
    await api.feedItem('article/with space')
    await api.createFeedRefresh()
    await api.updateItemState('article/1', { is_saved: true })
    await api.updateFeedSchedule({ enabled: true, interval_minutes: 360 })
    await api.updateSourceSchedule('sub/1', { enabled: true, interval_minutes: 30 })
    await api.notificationSettings()
    await api.updateNotificationSettings({ enabled: true, channels: ['email', 'webhook', 'telegram'], webhook_url: 'write-only' })
    await api.testNotificationSettings('telegram')
    await api.testNotificationSettings()
    await api.notificationEmailTransport()
    await api.updateNotificationEmailTransport({
      provider: 'qq',
      sender_email: 'notice@qq.com',
      sender_name: 'InfoHub',
      credential: 'write-only-email-credential',
    })
    await api.testNotificationEmailTransport('reader@example.com')
    await api.deleteNotificationEmailTransport()
    await api.notificationTelegramTransport()
    await api.updateNotificationTelegramTransport({
      bot_token: 'write-only-telegram-token',
    })
    await api.testNotificationTelegramTransport('@test_channel')
    await api.deleteNotificationTelegramTransport()
    await api.apifyActorAlertSettings()
    await api.updateApifyActorAlertSettings({
      enabled: true,
      channels: ['email', 'webhook', 'telegram'],
      events: ['actor_switched', 'recovered'],
      webhook_url: 'write-only-actor-webhook',
    })
    await api.testApifyActorAlertSettings('webhook')
    await api.testApifyActorAlertSettings()
    await api.apifyActorAlertIncidents()
    await api.unsubscribe('sub/1')
    await api.sources(true)
    await api.agentDelegations()
    await api.createAgentDelegation('My Mac', 'subscriptions_write')
    await api.createAgentDelegation('Read Mac')
    await api.createAgentDelegation('Workspace Mac', 'read', 'workspace')
    await api.renameAgentDelegation('agent/1', 'Desktop')
    await api.revokeAgentDelegation('agent/1')
    await api.storageSummary()
    await api.storageArchives()
    await api.createStoragePlan('restore', { batch_id: 'archive/1' })
    await api.applyStoragePlan('plan/1', '永久删除归档 archive/1')

    expect(client.get).toHaveBeenCalledWith('/api/feed/latest?view=canonical', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/feed/end-messages', undefined)
    expect(client.post).toHaveBeenCalledWith('/api/admin/feed-end-messages/refresh')
    expect(client.get).toHaveBeenCalledWith(
      '/api/jobs?view=summary&scope=me&limit=20&include_active=true&job_type=user_feed_refresh&job_type=source_fetch',
      undefined,
    )
    expect(client.get).toHaveBeenCalledWith('/api/jobs?view=summary&scope=me&limit=100&include_active=true', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/me/subscriptions?schedule_view=summary', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/me/feed-schedule?view=summary', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/jobs/job%2F1', undefined)
    expect(client.get).toHaveBeenCalledWith(
      '/api/feed/history?q=tsucha+ri&source_id=source%2Fwith+space&limit=50&offset=100',
      historySignal,
    )
    expect(client.get).toHaveBeenCalledWith('/api/feed/saved?limit=200&offset=0', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/feed/items/article%2Fwith%20space', undefined)
    expect(client.post).toHaveBeenCalledWith('/api/jobs/user-feed-refresh', {
      payload: { reason: 'manual_service_refresh' },
      priority: 0,
    })
    expect(client.patch).toHaveBeenCalledWith('/api/me/items/article%2F1/state', { is_saved: true })
    expect(client.patch).toHaveBeenCalledWith('/api/me/feed-schedule', { enabled: true, interval_minutes: 360 })
    expect(client.patch).toHaveBeenCalledWith('/api/me/subscriptions/sub%2F1/schedule', { enabled: true, interval_minutes: 30 })
    expect(client.get).toHaveBeenCalledWith('/api/me/notification-settings', undefined)
    expect(client.patch).toHaveBeenCalledWith('/api/me/notification-settings', {
      enabled: true,
      channels: ['email', 'webhook', 'telegram'],
      webhook_url: 'write-only',
    })
    expect(client.post).toHaveBeenCalledWith('/api/me/notification-settings/test', { channel: 'telegram' })
    expect(client.post).toHaveBeenCalledWith('/api/me/notification-settings/test', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/admin/notification-email-transport', undefined)
    expect(client.patch).toHaveBeenCalledWith('/api/admin/notification-email-transport', {
      provider: 'qq',
      sender_email: 'notice@qq.com',
      sender_name: 'InfoHub',
      credential: 'write-only-email-credential',
    })
    expect(client.post).toHaveBeenCalledWith('/api/admin/notification-email-transport/test', {
      recipient_email: 'reader@example.com',
    })
    expect(client.delete).toHaveBeenCalledWith('/api/admin/notification-email-transport')
    expect(client.get).toHaveBeenCalledWith('/api/admin/notification-telegram-transport', undefined)
    expect(client.patch).toHaveBeenCalledWith('/api/admin/notification-telegram-transport', {
      bot_token: 'write-only-telegram-token',
    })
    expect(client.post).toHaveBeenCalledWith('/api/admin/notification-telegram-transport/test', {
      chat_id: '@test_channel',
    })
    expect(client.delete).toHaveBeenCalledWith('/api/admin/notification-telegram-transport')
    expect(client.get).toHaveBeenCalledWith('/api/admin/apify-actor-alert-settings', undefined)
    expect(client.patch).toHaveBeenCalledWith('/api/admin/apify-actor-alert-settings', {
      enabled: true,
      channels: ['email', 'webhook', 'telegram'],
      events: ['actor_switched', 'recovered'],
      webhook_url: 'write-only-actor-webhook',
    })
    expect(client.post).toHaveBeenCalledWith('/api/admin/apify-actor-alert-settings/test', { channel: 'webhook' })
    expect(client.post).toHaveBeenCalledWith('/api/admin/apify-actor-alert-settings/test', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/admin/apify-actor-alert-incidents?limit=20', undefined)
    expect(client.delete).toHaveBeenCalledWith('/api/me/subscriptions/sub%2F1')
    expect(client.get).toHaveBeenCalledWith('/api/catalog/sources?include_disabled=true', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/me/agent-delegations', undefined)
    expect(client.post).toHaveBeenCalledWith('/api/me/agent-delegations', {
      name: 'My Mac',
      access: 'subscriptions_write',
      diagnostics_scope: 'self',
    })
    expect(client.post).toHaveBeenCalledWith('/api/me/agent-delegations', {
      name: 'Read Mac',
      access: 'read',
      diagnostics_scope: 'self',
    })
    expect(client.post).toHaveBeenCalledWith('/api/me/agent-delegations', {
      name: 'Workspace Mac',
      access: 'read',
      diagnostics_scope: 'workspace',
    })
    expect(client.patch).toHaveBeenCalledWith('/api/me/agent-delegations/agent%2F1', { name: 'Desktop' })
    expect(client.delete).toHaveBeenCalledWith('/api/me/agent-delegations/agent%2F1')
    expect(client.get).toHaveBeenCalledWith('/api/admin/storage/summary', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/admin/storage/archives', undefined)
    expect(client.post).toHaveBeenCalledWith('/api/admin/storage/plans', {
      operation: 'restore',
      payload: { batch_id: 'archive/1' },
    })
    expect(client.post).toHaveBeenCalledWith('/api/admin/storage/plans/plan%2F1/apply', {
      confirmation: '永久删除归档 archive/1',
    })
  })

  it('keeps secret values write-only in create and rotate requests', async () => {
    const client = {
      get: vi.fn().mockResolvedValue({}),
      post: vi.fn().mockResolvedValue({}),
      patch: vi.fn().mockResolvedValue({}),
      put: vi.fn().mockResolvedValue({}),
      delete: vi.fn().mockResolvedValue({}),
    } as unknown as ApiClient
    const api = createServiceApi(client)

    await api.createSecret({ name: 'Primary', kind: 'ai', provider: 'gemini', env_name: 'GOOGLE_API_KEY', value: 'write-only' })
    await api.rotateSecret('secret/1', 'new-value')
    await api.secretQuota('secret/1')
    await api.apifyKeyPool()
    await api.reorderApifyKeyPool(['secret/1', 'secret-2'], 7)
    await api.drainApifyKey('secret/1')
    await api.apifyActorXProfileRoute()
    await api.reorderApifyActorXProfileRoute(['scrape/badger', 'dami'], 11)
    await api.enableApifyActorXProfileCandidate('scrape/badger', 11)
    await api.disableApifyActorXProfileCandidate('dami/studio', 12)
    await api.canaryApifyActorXProfileCandidate('xquik/actor', 'source/1', 13, '确认付费试跑')

    expect(client.post).toHaveBeenCalledWith('/api/admin/secrets', expect.objectContaining({ value: 'write-only' }))
    expect(client.put).toHaveBeenCalledWith('/api/admin/secrets/secret%2F1/value', { value: 'new-value' })
    expect(client.get).toHaveBeenCalledWith('/api/admin/secrets/secret%2F1/quota', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/admin/apify-key-pool', undefined)
    expect(client.put).toHaveBeenCalledWith('/api/admin/apify-key-pool/order', {
      secret_ids: ['secret/1', 'secret-2'],
      expected_generation: 7,
    })
    expect(client.post).toHaveBeenCalledWith('/api/admin/apify-key-pool/secret%2F1/drain')
    expect(client.get).toHaveBeenCalledWith('/api/admin/apify-actor-routes/x/profile', undefined)
    expect(client.put).toHaveBeenCalledWith('/api/admin/apify-actor-routes/x/profile/order', {
      candidate_ids: ['scrape/badger', 'dami'],
      expected_generation: 11,
    })
    expect(client.post).toHaveBeenCalledWith(
      '/api/admin/apify-actor-routes/x/profile/candidates/scrape%2Fbadger/enable',
      { expected_generation: 11 },
    )
    expect(client.post).toHaveBeenCalledWith(
      '/api/admin/apify-actor-routes/x/profile/candidates/dami%2Fstudio/disable',
      { expected_generation: 12 },
    )
    expect(client.post).toHaveBeenCalledWith(
      '/api/admin/apify-actor-routes/x/profile/candidates/xquik%2Factor/canary',
      {
        source_id: 'source/1',
        expected_generation: 13,
        confirmation: '确认付费试跑',
      },
    )
  })
})
