import { describe, expect, it } from 'vitest'

import type { Job } from '../../api/types'
import { describeFeedJob, feedJobNotice, latestFeedJob, pollingTimedOut } from './jobModel'

const job = (overrides: Partial<Job>): Job => ({
  id: 'job-1',
  user_id: 'user-a',
  job_type: 'user_feed_refresh',
  status: 'queued',
  ...overrides,
})

describe('feed job model', () => {
  it('selects only the current user latest full refresh', () => {
    const result = latestFeedJob([
      job({ id: 'other', user_id: 'user-b', created_at: '2026-07-13T12:00:00Z' }),
      job({ id: 'source', job_type: 'source_fetch', created_at: '2026-07-13T13:00:00Z' }),
      job({ id: 'latest', created_at: '2026-07-13T11:00:00Z' }),
    ], 'user-a')

    expect(result?.id).toBe('latest')
  })

  it('describes queued, partial and failed terminal states without hiding diagnostics', () => {
    expect(describeFeedJob(job({ status: 'queued' }), 'ready').message).toContain('更新任务已开始')
    expect(describeFeedJob(job({ status: 'queued' }), 'stale').message).toContain('等待后台服务恢复')
    expect(describeFeedJob(job({
      status: 'partial',
      result: { item_count: 12, source_outcomes: [{ status: 'succeeded' }, { status: 'failed' }] },
    }), 'ready').message).toContain('12')
    expect(describeFeedJob(job({ status: 'failed', error_code: 'upstream_error', error_message: '上游失败', retryable: true }), 'ready')).toMatchObject({
      state: 'failed',
      retryable: true,
    })
  })

  it('emits a success notice only when the worker created a new snapshot', () => {
    expect(feedJobNotice(job({
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: true },
    }))).toMatchObject({ state: 'succeeded', message: '信息流已更新，共 5 条。' })

    expect(feedJobNotice(job({
      status: 'succeeded',
      result: { item_count: 5, snapshot_created: false },
    }))).toBeUndefined()
  })

  it('reports a partial no-op without claiming that the feed was updated', () => {
    const notice = feedJobNotice(job({
      status: 'partial',
      result: {
        item_count: 5,
        snapshot_created: false,
        source_outcomes: [{ status: 'succeeded' }, { status: 'failed' }],
      },
    }))

    expect(notice?.state).toBe('partial')
    expect(notice?.message).toContain('未更新信息流')
    expect(notice?.message).not.toContain('已更新 5 条')
  })

  it('stops treating an active job as pollable after 180 seconds', () => {
    const oldJob = job({ status: 'running', created_at: '2026-07-13T10:00:00Z', started_at: '2026-07-13T10:02:00Z' })
    const now = Date.parse('2026-07-13T10:03:01Z')

    expect(pollingTimedOut(oldJob, now)).toBe(true)
    expect(describeFeedJob(oldJob, 'ready', now)).toMatchObject({
      state: 'failed',
      retryable: false,
      terminal: true,
    })
    expect(describeFeedJob(oldJob, 'ready', now).message).toContain('180 秒')
  })
})
