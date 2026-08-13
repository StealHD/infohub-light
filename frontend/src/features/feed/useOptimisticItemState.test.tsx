import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { queryKeys } from '../../api/queryKeys'
import type { ServiceApi } from '../../api/service'
import type { User, UserItemState } from '../../api/types'
import { ActionGeneration } from '../../app/actionGeneration'
import { ActionFeedbackProvider } from '../../app/ActionFeedback'
import { isItemStateQueryKey, useOptimisticItemState } from './useOptimisticItemState'

const user: User = { id: 'user-1', username: 'owner', role: 'owner', enabled: true }
const otherUser: User = { id: 'user-2', username: 'member', role: 'member', enabled: true }
const feedOptions = { hideDismissed: false, unreadFirst: false }
const historyOptions = { q: '', sourceId: '', limit: 50 }
const searchOptions = { q: 'article', limit: 50, submitted: true }

function item(isSaved = false, id = 'article-1') {
  return {
    id,
    title: 'Article',
    url: `https://example.com/${id}`,
    user_state: { is_read: false, is_saved: isSaved, is_later: false, dismissed: false },
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((next, fail) => {
    resolve = next
    reject = fail
  })
  return { promise, resolve, reject }
}

function setup(updateItemState: ServiceApi['updateItemState']) {
  const api = { updateItemState } as unknown as ServiceApi
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const generation = new ActionGeneration(user.id)
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ActionFeedbackProvider userId={user.id}>{children}</ActionFeedbackProvider>
    </QueryClientProvider>
  )
  const hook = renderHook(() => useOptimisticItemState({
    api,
    user,
    beginAction: () => generation.capture(),
    isActionCurrent: (token) => generation.isCurrent(token),
    publishFeedback: false,
  }), { wrapper })
  return { ...hook, client }
}

function seedCaches(client: QueryClient) {
  const relevantKeys = [
    queryKeys.feed(user.id, feedOptions),
    queryKeys.feedItem(user.id, 'article-1'),
    queryKeys.history(user.id, historyOptions),
    queryKeys.search(user.id, searchOptions),
    queryKeys.saved(user.id),
    queryKeys.ignored(user.id),
  ]
  for (const key of relevantKeys) client.setQueryData(key, { schema_version: 1, items: [item()] })

  const unrelated = {
    subscriptions: { subscriptions: [item()] },
    jobs: { jobs: [item()] },
    config: { items: [item()] },
    otherUserFeed: { schema_version: 1, items: [item()] },
  }
  client.setQueryData(queryKeys.subscriptions(user.id), unrelated.subscriptions)
  client.setQueryData(queryKeys.jobs(user.id), unrelated.jobs)
  client.setQueryData(queryKeys.config(user.id), unrelated.config)
  client.setQueryData(queryKeys.feed(otherUser.id, feedOptions), unrelated.otherUserFeed)
  return { relevantKeys, unrelated }
}

function cachedSavedState(client: QueryClient, key: readonly unknown[]): boolean | undefined {
  return cachedItemState(client, key)?.is_saved
}

function cachedItemState(
  client: QueryClient,
  key: readonly unknown[],
  articleId = 'article-1',
): UserItemState | undefined {
  const data = client.getQueryData<{ items: Array<{ id: string; user_state?: UserItemState }> }>(key)
  return data?.items.find((entry) => entry.id === articleId)?.user_state
}

describe('useOptimisticItemState', () => {
  it('recognizes only current-user item-bearing query families', () => {
    expect(isItemStateQueryKey(queryKeys.feed(user.id, feedOptions), user.id)).toBe(true)
    expect(isItemStateQueryKey(queryKeys.feedItem(user.id, 'article-1'), user.id)).toBe(true)
    expect(isItemStateQueryKey(queryKeys.history(user.id, historyOptions), user.id)).toBe(true)
    expect(isItemStateQueryKey(queryKeys.search(user.id, searchOptions), user.id)).toBe(true)
    expect(isItemStateQueryKey(queryKeys.saved(user.id), user.id)).toBe(true)
    expect(isItemStateQueryKey(queryKeys.ignored(user.id), user.id)).toBe(true)
    expect(isItemStateQueryKey(queryKeys.subscriptions(user.id), user.id)).toBe(false)
    expect(isItemStateQueryKey(queryKeys.jobs(user.id), user.id)).toBe(false)
    expect(isItemStateQueryKey(queryKeys.config(user.id), user.id)).toBe(false)
    expect(isItemStateQueryKey(queryKeys.feed(otherUser.id, feedOptions), user.id)).toBe(false)
  })

  it('optimistically updates and settles only item-bearing caches for the current user', async () => {
    const response = deferred<UserItemState>()
    const updateItemState = vi.fn().mockReturnValue(response.promise)
    const hook = setup(updateItemState)
    const seeded = seedCaches(hook.client)

    act(() => hook.result.current.mutateItem('article-1', { is_saved: true }))

    await waitFor(() => expect(updateItemState).toHaveBeenCalledWith('article-1', { is_saved: true }))
    for (const key of seeded.relevantKeys) expect(cachedSavedState(hook.client, key)).toBe(true)
    expect(hook.client.getQueryData(queryKeys.subscriptions(user.id))).toBe(seeded.unrelated.subscriptions)
    expect(hook.client.getQueryData(queryKeys.jobs(user.id))).toBe(seeded.unrelated.jobs)
    expect(hook.client.getQueryData(queryKeys.config(user.id))).toBe(seeded.unrelated.config)
    expect(hook.client.getQueryData(queryKeys.feed(otherUser.id, feedOptions))).toBe(seeded.unrelated.otherUserFeed)

    act(() => response.resolve({ is_read: false, is_saved: true, is_later: true, dismissed: false }))
    await waitFor(() => {
      const saved = hook.client.getQueryData<{ items: Array<{ user_state?: UserItemState }> }>(queryKeys.saved(user.id))
      expect(saved?.items[0]?.user_state?.is_later).toBe(true)
    })
    expect(hook.client.getQueryData(queryKeys.subscriptions(user.id))).toBe(seeded.unrelated.subscriptions)
    expect(hook.client.getQueryData(queryKeys.feed(otherUser.id, feedOptions))).toBe(seeded.unrelated.otherUserFeed)
  })

  it('invalidates a previously cached saved collection after a successful save', async () => {
    const updateItemState = vi.fn().mockResolvedValue({
      is_read: false,
      is_saved: true,
      is_later: false,
      dismissed: false,
    })
    const hook = setup(updateItemState)
    const feedKey = queryKeys.feed(user.id, feedOptions)
    const savedKey = queryKeys.saved(user.id)
    hook.client.setQueryData(feedKey, { schema_version: 1, items: [item()] })
    hook.client.setQueryData(savedKey, {
      pages: [{ schema_version: 1, scope: 'user', items: [], item_count: 0, limit: 50, offset: 0 }],
      pageParams: [0],
    })

    act(() => hook.result.current.mutateItem('article-1', { is_saved: true }))

    await waitFor(() => expect(updateItemState).toHaveBeenCalledWith('article-1', { is_saved: true }))
    await waitFor(() => expect(hook.client.getQueryState(savedKey)?.isInvalidated).toBe(true))
  })

  it('rolls back relevant caches without restoring or rewriting unrelated caches', async () => {
    const response = deferred<UserItemState>()
    const updateItemState = vi.fn().mockReturnValue(response.promise)
    const hook = setup(updateItemState)
    const seeded = seedCaches(hook.client)

    act(() => hook.result.current.mutateItem('article-1', { is_saved: true }))
    await waitFor(() => expect(cachedSavedState(hook.client, queryKeys.saved(user.id))).toBe(true))

    const newerSubscriptions = { subscriptions: [{ ...item(), title: 'New unrelated data' }] }
    hook.client.setQueryData(queryKeys.subscriptions(user.id), newerSubscriptions)
    act(() => response.reject(new Error('save failed')))

    await waitFor(() => expect(hook.result.current.isError).toBe(true))
    for (const key of seeded.relevantKeys) expect(cachedSavedState(hook.client, key)).toBe(false)
    expect(hook.client.getQueryData(queryKeys.subscriptions(user.id))).toStrictEqual(newerSubscriptions)
    expect(hook.client.getQueryData(queryKeys.jobs(user.id))).toBe(seeded.unrelated.jobs)
    expect(hook.client.getQueryData(queryKeys.feed(otherUser.id, feedOptions))).toBe(seeded.unrelated.otherUserFeed)
  })

  it('preserves each query family baseline while an item change is pending and rolls back', async () => {
    const response = deferred<UserItemState>()
    const updateItemState = vi.fn().mockReturnValue(response.promise)
    const hook = setup(updateItemState)
    seedCaches(hook.client)
    const feedKey = queryKeys.feed(user.id, feedOptions)
    const detailKey = queryKeys.feedItem(user.id, 'article-1')
    hook.client.setQueryData(feedKey, { schema_version: 1, items: [item(false)] })
    hook.client.setQueryData(detailKey, item(true))

    act(() => hook.result.current.mutateItem('article-1', { is_later: true }))
    await waitFor(() => {
      expect(cachedItemState(hook.client, feedKey)).toMatchObject({
        is_saved: false,
        is_later: true,
      })
      expect(hook.client.getQueryData<{ user_state: UserItemState }>(detailKey)?.user_state).toMatchObject({
        is_saved: true,
        is_later: true,
      })
    })

    act(() => response.reject(new Error('later failed')))
    await waitFor(() => {
      expect(cachedItemState(hook.client, feedKey)).toMatchObject({
        is_saved: false,
        is_later: false,
      })
      expect(hook.client.getQueryData<{ user_state: UserItemState }>(detailKey)?.user_state).toMatchObject({
        is_saved: true,
        is_later: false,
      })
    })
  })

  it('does not let an older failure replace a newer successful state for the same item', async () => {
    const older = deferred<UserItemState>()
    const newer = deferred<UserItemState>()
    const updateItemState = vi.fn()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise)
    const hook = setup(updateItemState)
    seedCaches(hook.client)

    act(() => hook.result.current.mutateItem('article-1', { is_saved: true }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(1))
    act(() => hook.result.current.mutateItem('article-1', { is_later: true }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(2))

    act(() => newer.resolve({
      is_read: false,
      is_saved: true,
      is_later: true,
      dismissed: true,
    }))
    await waitFor(() => {
      expect(cachedItemState(hook.client, queryKeys.feed(user.id, feedOptions))).toMatchObject({
        is_saved: true,
        is_later: true,
        dismissed: true,
      })
    })

    act(() => older.reject(new Error('older save failed')))
    await waitFor(() => {
      expect(cachedItemState(hook.client, queryKeys.feed(user.id, feedOptions))).toMatchObject({
        is_saved: true,
        is_later: true,
        dismissed: true,
      })
    })
  })

  it('keeps an older pending field when a newer different field succeeds first', async () => {
    const older = deferred<UserItemState>()
    const newer = deferred<UserItemState>()
    const updateItemState = vi.fn()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise)
    const hook = setup(updateItemState)
    seedCaches(hook.client)
    const feedKey = queryKeys.feed(user.id, feedOptions)

    act(() => hook.result.current.mutateItem('article-1', { is_saved: true }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(1))
    act(() => hook.result.current.mutateItem('article-1', { is_later: true }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(2))

    act(() => newer.resolve({
      is_read: false,
      is_saved: false,
      is_later: true,
      dismissed: false,
    }))
    await waitFor(() => expect(cachedItemState(hook.client, feedKey)).toMatchObject({
      is_saved: true,
      is_later: true,
    }))

    act(() => older.resolve({
      is_read: false,
      is_saved: true,
      is_later: true,
      dismissed: false,
    }))
    await waitFor(() => expect(cachedItemState(hook.client, feedKey)).toMatchObject({
      is_saved: true,
      is_later: true,
    }))
  })

  it('keeps the later intent when same-field successes settle out of order', async () => {
    const older = deferred<UserItemState>()
    const newer = deferred<UserItemState>()
    const updateItemState = vi.fn()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise)
    const hook = setup(updateItemState)
    seedCaches(hook.client)
    const feedKey = queryKeys.feed(user.id, feedOptions)

    act(() => hook.result.current.mutateItem('article-1', { is_saved: true }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(1))
    act(() => hook.result.current.mutateItem('article-1', { is_saved: false }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(2))

    act(() => newer.resolve({
      is_read: false,
      is_saved: false,
      is_later: false,
      dismissed: false,
    }))
    await waitFor(() => expect(cachedItemState(hook.client, feedKey)?.is_saved).toBe(false))

    act(() => older.resolve({
      is_read: false,
      is_saved: true,
      is_later: false,
      dismissed: false,
    }))
    await waitFor(() => expect(cachedItemState(hook.client, feedKey)?.is_saved).toBe(false))
  })

  it('rolls back only the failed item while preserving a newer successful item', async () => {
    const older = deferred<UserItemState>()
    const newer = deferred<UserItemState>()
    const updateItemState = vi.fn()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise)
    const hook = setup(updateItemState)
    seedCaches(hook.client)
    const feedKey = queryKeys.feed(user.id, feedOptions)
    hook.client.setQueryData(feedKey, {
      schema_version: 1,
      items: [item(false, 'article-1'), item(false, 'article-2')],
    })

    act(() => hook.result.current.mutateItem('article-1', { is_saved: true }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(1))
    act(() => hook.result.current.mutateItem('article-2', { is_saved: true }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(2))

    act(() => newer.resolve({
      is_read: false,
      is_saved: true,
      is_later: true,
      dismissed: false,
    }))
    await waitFor(() => expect(cachedItemState(hook.client, feedKey, 'article-2')).toMatchObject({
      is_saved: true,
      is_later: true,
    }))

    act(() => older.reject(new Error('first item save failed')))
    await waitFor(() => {
      expect(cachedItemState(hook.client, feedKey, 'article-1')?.is_saved).toBe(false)
      expect(cachedItemState(hook.client, feedKey, 'article-2')).toMatchObject({
        is_saved: true,
        is_later: true,
      })
    })
  })

  it('returns to the original item state when concurrent changes both fail', async () => {
    const older = deferred<UserItemState>()
    const newer = deferred<UserItemState>()
    const updateItemState = vi.fn()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise)
    const hook = setup(updateItemState)
    seedCaches(hook.client)
    const feedKey = queryKeys.feed(user.id, feedOptions)

    act(() => hook.result.current.mutateItem('article-1', { is_saved: true }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(1))
    act(() => hook.result.current.mutateItem('article-1', { is_later: true }))
    await waitFor(() => expect(updateItemState).toHaveBeenCalledTimes(2))

    act(() => older.reject(new Error('save failed')))
    await waitFor(() => expect(cachedItemState(hook.client, feedKey)).toMatchObject({
      is_saved: false,
      is_later: true,
    }))

    act(() => newer.reject(new Error('later failed')))
    await waitFor(() => expect(cachedItemState(hook.client, feedKey)).toMatchObject({
      is_saved: false,
      is_later: false,
    }))
  })
})
