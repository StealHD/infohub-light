import type { ReactNode } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { FeedSchedule, Job, User } from '../../api/types'
import { ActionGeneration } from '../../app/actionGeneration'
import { useFeedActivity } from './useFeedActivity'

const user: User = { id: 'user-1', username: 'owner', role: 'owner', enabled: true }
const schedule = (worker_status: string): FeedSchedule => ({ enabled: false, interval_minutes: 360, worker_status })
const queuedJob: Job = {
  id: 'job-1', user_id: user.id, job_type: 'user_feed_refresh', status: 'queued', created_at: '2026-07-14T06:00:00Z',
}

function setup(workerStatus: string, initialJobs: Job[] = []) {
  const feedSchedule = vi.fn().mockResolvedValue(schedule(workerStatus))
  const createFeedRefresh = vi.fn().mockResolvedValue(queuedJob)
  const api = {
    jobs: vi.fn().mockResolvedValue({ jobs: initialJobs }),
    feedSchedule,
    createFeedRefresh,
  } as unknown as ServiceApi
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  const result = renderHook(() => useFeedActivity(api, user, new ActionGeneration(user.id)), { wrapper })
  return { ...result, client, feedSchedule, createFeedRefresh }
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
})
