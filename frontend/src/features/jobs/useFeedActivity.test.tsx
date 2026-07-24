import type { ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import { queryKeys } from '../../api/queryKeys'
import type { ServiceApi } from '../../api/service'
import type { FeedSchedule, Job, User } from '../../api/types'
import { ActionGeneration } from '../../app/actionGeneration'
import { useFeedActivity } from './useFeedActivity'

const user: User = { id: 'user-1', username: 'owner', role: 'owner', enabled: true }
const schedule = (worker_status: string): FeedSchedule => ({ enabled: false, interval_minutes: 360, worker_status })
const queuedJob: Job = {
  id: 'job-1', user_id: user.id, job_type: 'user_feed_refresh', status: 'queued', created_at: '2026-07-14T06:00:00Z',
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

function setup(workerStatus: string, initialJobs: Job[] = []) {
  const feedSchedule = vi.fn().mockResolvedValue(schedule(workerStatus))
  const createFeedRefresh = vi.fn().mockResolvedValue(queuedJob)
  const latestFeed = vi.fn().mockResolvedValue({
    schema_version: 2,
    items: [{ id: 'latest-item', title: '最新条目' }],
  })
  const api = {
    jobs: vi.fn().mockResolvedValue({ jobs: initialJobs }),
    feedSchedule,
    createFeedRefresh,
    latestFeed,
  } as unknown as ServiceApi
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const result = renderHook(() => useFeedActivity(api, user, new ActionGeneration(user.id)), { wrapper })
  return { ...result, client, feedSchedule, createFeedRefresh, latestFeed }
}

describe('useFeedActivity', () => {
  it('checks Worker state again and blocks refresh without creating a job when unavailable', async () => {
    const hook = setup('stale')
    await waitFor(() => expect(hook.feedSchedule).toHaveBeenCalledTimes(1))

    act(() => hook.result.current.refresh())

    await waitFor(() => expect(hook.result.current.notice).toMatchObject({ state: 'blocked' }))
    expect(hook.result.current.notice?.message).toContain('后台获取服务')
    expect(hook.feedSchedule).toHaveBeenCalledTimes(2)
    expect(hook.createFeedRefresh).not.toHaveBeenCalled()

    expect(hook.result.current.retry).toEqual(expect.any(Function))
    act(() => hook.result.current.retry?.())
    await waitFor(() => expect(hook.feedSchedule).toHaveBeenCalledTimes(3))
    expect(hook.createFeedRefresh).not.toHaveBeenCalled()
  })

  it('creates the refresh only after a fresh ready check', async () => {
    const hook = setup('ready')
    await waitFor(() => expect(hook.feedSchedule).toHaveBeenCalledTimes(1))

    act(() => hook.result.current.refresh())

    await waitFor(() => expect(hook.createFeedRefresh).toHaveBeenCalledTimes(1))
    expect(hook.feedSchedule).toHaveBeenCalledTimes(2)
  })

  it('does not replay a historical terminal job when the page first loads', async () => {
    const hook = setup('ready', [{
      ...queuedJob,
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: true },
    }])

    await waitFor(() => expect(hook.result.current.currentJob?.status).toBe('succeeded'))
    expect(hook.result.current.notice).toBeUndefined()
    expect(hook.latestFeed).not.toHaveBeenCalled()
  })

  it('notifies once after an observed active job creates a new snapshot', async () => {
    const hook = setup('ready', [queuedJob])
    await waitFor(() => expect(hook.result.current.currentJob?.status).toBe('queued'))

    act(() => hook.client.setQueryData(['user', user.id, 'jobs'], { jobs: [{
      ...queuedJob,
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: true },
    }] }))

    await waitFor(() => expect(hook.result.current.notice).toMatchObject({
      key: 'job-1:succeeded',
      state: 'succeeded',
    }))
    expect(hook.latestFeed).toHaveBeenCalledOnce()
  })

  it('waits for the latest Feed read before publishing a full-refresh completion notice', async () => {
    const feed = deferred<{ schema_version: number; items: Array<{ id: string; title: string }> }>()
    const hook = setup('ready', [queuedJob])
    hook.latestFeed.mockReturnValueOnce(feed.promise)
    await waitFor(() => expect(hook.result.current.currentJob?.status).toBe('queued'))

    act(() => hook.client.setQueryData(queryKeys.jobs(user.id), { jobs: [{
      ...queuedJob,
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: true },
    }] }))

    await waitFor(() => expect(hook.latestFeed).toHaveBeenCalledOnce())
    expect(hook.result.current.notice).toBeUndefined()
    act(() => feed.resolve({ schema_version: 2, items: [{ id: 'new-item', title: '新条目' }] }))

    await waitFor(() => expect(hook.result.current.notice).toMatchObject({ state: 'succeeded' }))
    expect(hook.client.getQueryData(queryKeys.feed(user.id, { hideDismissed: false, unreadFirst: false }))).toMatchObject({
      items: [{ id: 'new-item' }],
    })
  })

  it.each(['succeeded', 'partial'] as const)('reloads the canonical Feed after an observed source fetch becomes %s', async (status) => {
    const sourceJob: Job = {
      id: `source-job-${status}`,
      user_id: user.id,
      job_type: 'source_fetch',
      source_id: 'source-1',
      status: 'queued',
      created_at: '2026-07-14T06:00:00Z',
    }
    const hook = setup('ready', [sourceJob])
    await waitFor(() => expect(hook.client.getQueryData(queryKeys.jobs(user.id))).toBeDefined())

    act(() => hook.client.setQueryData(queryKeys.jobs(user.id), { jobs: [{
      ...sourceJob,
      status,
      result: { item_count: 5, snapshot_created: true },
    }] }))

    await waitFor(() => expect(hook.latestFeed).toHaveBeenCalledOnce())
    expect(hook.result.current.notice).toBeUndefined()
  })

  it('reports a reload-specific failure after content production succeeds', async () => {
    const sourceJob: Job = {
      id: 'source-job-failed-reload',
      user_id: user.id,
      job_type: 'source_fetch',
      source_id: 'source-1',
      status: 'queued',
      created_at: '2026-07-14T06:00:00Z',
    }
    const hook = setup('ready', [sourceJob])
    hook.latestFeed.mockRejectedValueOnce(new Error('latest Feed unavailable'))
    await waitFor(() => expect(hook.client.getQueryData(queryKeys.jobs(user.id))).toBeDefined())

    act(() => hook.client.setQueryData(queryKeys.jobs(user.id), { jobs: [{
      ...sourceJob,
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: true },
    }] }))

    await waitFor(() => expect(hook.result.current.notice).toMatchObject({
      key: 'source-job-failed-reload:succeeded:feed-reload-failed',
      state: 'reload_failed',
    }))
  })

  it.each(['failed', 'cancelled'] as const)('does not reload Feed after an observed source fetch becomes %s', async (status) => {
    const sourceJob: Job = {
      id: `source-job-${status}`,
      user_id: user.id,
      job_type: 'source_fetch',
      source_id: 'source-1',
      status: 'queued',
      created_at: '2026-07-14T06:00:00Z',
    }
    const hook = setup('ready', [sourceJob])
    const invalidate = vi.spyOn(hook.client, 'invalidateQueries')
    await waitFor(() => expect(hook.client.getQueryData(queryKeys.jobs(user.id))).toBeDefined())

    act(() => hook.client.setQueryData(queryKeys.jobs(user.id), { jobs: [{
      ...sourceJob,
      status,
      error_message: status === 'failed' ? 'upstream unavailable' : undefined,
    }] }))

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.history(user.id) }))
    expect(hook.latestFeed).not.toHaveBeenCalled()
    expect(hook.result.current.notice).toBeUndefined()
  })

  it('hides the previous terminal notice when a newer job becomes active', async () => {
    const hook = setup('ready', [queuedJob])
    await waitFor(() => expect(hook.result.current.currentJob?.status).toBe('queued'))

    act(() => hook.client.setQueryData(['user', user.id, 'jobs'], { jobs: [{
      ...queuedJob,
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: true },
    }] }))
    await waitFor(() => expect(hook.result.current.notice?.key).toBe('job-1:succeeded'))

    act(() => hook.client.setQueryData(['user', user.id, 'jobs'], { jobs: [{
      ...queuedJob,
      id: 'job-2',
      created_at: '2026-07-14T07:00:00Z',
    }] }))

    await waitFor(() => expect(hook.result.current.currentJob?.id).toBe('job-2'))
    expect(hook.result.current.notice).toBeUndefined()
  })

  it('stays silent after an observed active job completes without a new snapshot', async () => {
    const hook = setup('ready', [queuedJob])
    await waitFor(() => expect(hook.result.current.currentJob?.status).toBe('queued'))

    act(() => hook.client.setQueryData(['user', user.id, 'jobs'], { jobs: [{
      ...queuedJob,
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: false },
    }] }))

    await waitFor(() => expect(hook.result.current.currentJob?.status).toBe('succeeded'))
    expect(hook.result.current.notice).toBeUndefined()
  })

  it('does not carry a terminal notice into a replacement account', async () => {
    const replacement: User = { id: 'user-2', username: 'member', role: 'member', enabled: true }
    const api = {
      jobs: vi.fn().mockResolvedValue({ jobs: [queuedJob] }),
      feedSchedule: vi.fn().mockResolvedValue(schedule('ready')),
      latestFeed: vi.fn().mockResolvedValue({ schema_version: 2, items: [] }),
    } as unknown as ServiceApi
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const guards: Record<string, ActionGeneration> = {
      [user.id]: new ActionGeneration(user.id),
      [replacement.id]: new ActionGeneration(replacement.id),
    }
    const hook = renderHook(
      ({ currentUser }: { currentUser: User }) => useFeedActivity(api, currentUser, guards[currentUser.id]),
      { wrapper, initialProps: { currentUser: user } },
    )
    await waitFor(() => expect(hook.result.current.currentJob?.status).toBe('queued'))

    act(() => client.setQueryData(['user', user.id, 'jobs'], { jobs: [{
      ...queuedJob,
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: true },
    }] }))
    await waitFor(() => expect(hook.result.current.notice?.key).toBe('job-1:succeeded'))

    hook.rerender({ currentUser: replacement })
    expect(hook.result.current.notice).toBeUndefined()
  })

  it('does not reload for an old account when its job settles after an account switch', async () => {
    const replacement: User = { id: 'user-2', username: 'member', role: 'member', enabled: true }
    const latestFeed = vi.fn().mockResolvedValue({ schema_version: 2, items: [] })
    const api = {
      jobs: vi.fn().mockImplementation(() => Promise.resolve({ jobs: [queuedJob] })),
      feedSchedule: vi.fn().mockResolvedValue(schedule('ready')),
      latestFeed,
    } as unknown as ServiceApi
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
    const guards: Record<string, ActionGeneration> = {
      [user.id]: new ActionGeneration(user.id),
      [replacement.id]: new ActionGeneration(replacement.id),
    }
    const hook = renderHook(
      ({ currentUser }: { currentUser: User }) => useFeedActivity(api, currentUser, guards[currentUser.id]),
      { wrapper, initialProps: { currentUser: user } },
    )
    await waitFor(() => expect(hook.result.current.currentJob?.status).toBe('queued'))

    hook.rerender({ currentUser: replacement })
    await waitFor(() => expect(hook.result.current.currentJob).toBeUndefined())
    act(() => client.setQueryData(queryKeys.jobs(user.id), { jobs: [{
      ...queuedJob,
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: true },
    }] }))

    await act(async () => Promise.resolve())
    expect(latestFeed).not.toHaveBeenCalled()
    expect(hook.result.current.notice).toBeUndefined()
  })
})
