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
    await api.savedFeed()
    await api.feedItem('article/with space')
    await api.createFeedRefresh()
    await api.updateItemState('article/1', { is_saved: true })
    await api.updateFeedSchedule({ enabled: true, interval_minutes: 360 })
    await api.updateSourceSchedule('sub/1', { enabled: true, interval_minutes: 30 })
    await api.unsubscribe('sub/1')
    await api.sources(true)
    await api.agentDelegations()
    await api.createAgentDelegation('My Mac')
    await api.renameAgentDelegation('agent/1', 'Desktop')
    await api.revokeAgentDelegation('agent/1')

    expect(client.get).toHaveBeenCalledWith('/api/feed/latest', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/feed/saved?limit=200&offset=0', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/feed/items/article%2Fwith%20space', undefined)
    expect(client.post).toHaveBeenCalledWith('/api/jobs/user-feed-refresh', {
      payload: { reason: 'manual_service_refresh' },
      priority: 0,
    })
    expect(client.patch).toHaveBeenCalledWith('/api/me/items/article%2F1/state', { is_saved: true })
    expect(client.patch).toHaveBeenCalledWith('/api/me/feed-schedule', { enabled: true, interval_minutes: 360 })
    expect(client.patch).toHaveBeenCalledWith('/api/me/subscriptions/sub%2F1/schedule', { enabled: true, interval_minutes: 30 })
    expect(client.delete).toHaveBeenCalledWith('/api/me/subscriptions/sub%2F1')
    expect(client.get).toHaveBeenCalledWith('/api/catalog/sources?include_disabled=true', undefined)
    expect(client.get).toHaveBeenCalledWith('/api/me/agent-delegations', undefined)
    expect(client.post).toHaveBeenCalledWith('/api/me/agent-delegations', { name: 'My Mac' })
    expect(client.patch).toHaveBeenCalledWith('/api/me/agent-delegations/agent%2F1', { name: 'Desktop' })
    expect(client.delete).toHaveBeenCalledWith('/api/me/agent-delegations/agent%2F1')
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

    expect(client.post).toHaveBeenCalledWith('/api/admin/secrets', expect.objectContaining({ value: 'write-only' }))
    expect(client.put).toHaveBeenCalledWith('/api/admin/secrets/secret%2F1/value', { value: 'new-value' })
  })
})
