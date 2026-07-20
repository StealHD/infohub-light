import type { Job } from '../../api/types'

export type FeedActivity = {
  state: 'idle' | 'queued' | 'running' | 'succeeded' | 'partial' | 'failed'
  message?: string
  retryable: boolean
  terminal: boolean
}

export type FeedNotice = {
  key: string
  state: FeedActivity['state'] | 'blocked'
  message: string
}

const resultOf = (job: Job) => job.result ?? job.result_json ?? {}
const POLLING_TIMEOUT_MS = 180_000

export function pollingTimedOut(job: Job | undefined, now = Date.now()): boolean {
  if (!job || (job.status !== 'queued' && job.status !== 'running')) return false
  const startedAt = Date.parse(job.created_at || job.started_at || '')
  return Number.isFinite(startedAt) && now - startedAt >= POLLING_TIMEOUT_MS
}

export function latestFeedJob(jobs: Job[], userId: string): Job | undefined {
  return jobs
    .filter((job) => job.user_id === userId && job.job_type === 'user_feed_refresh')
    .sort((left, right) => String(right.created_at ?? '').localeCompare(String(left.created_at ?? '')))[0]
}

export function describeFeedJob(job: Job | undefined, workerStatus = 'ready', now = Date.now()): FeedActivity {
  if (!job) return { state: 'idle', retryable: false, terminal: true }
  if (pollingTimedOut(job, now)) {
    return {
      state: 'failed',
      message: '已达到 180 秒轮询上限，任务可能仍在后台运行；请稍后刷新页面查看结果。',
      retryable: false,
      terminal: true,
    }
  }
  if (job.status === 'queued') {
    const message = workerStatus === 'ready'
      ? '更新任务已开始，将从全部已启用订阅抓取并整理新内容。'
      : '更新任务正在等待后台服务恢复。'
    return { state: 'queued', message, retryable: false, terminal: false }
  }
  if (job.status === 'running') {
    return { state: 'running', message: '正在从订阅源获取并整理新内容…', retryable: false, terminal: false }
  }
  const result = resultOf(job)
  const itemCount = Number(result.item_count ?? 0)
  const snapshotCreated = result.snapshot_created === true
  const outcomes = Array.isArray(result.source_outcomes) ? result.source_outcomes as Array<{ status?: string }> : []
  const failedCount = outcomes.filter((outcome) => outcome.status === 'failed').length
  if (job.status === 'partial') {
    return {
      state: 'partial',
      message: snapshotCreated
        ? `已更新 ${itemCount} 条可用内容，${failedCount} 个来源失败。`
        : `本次检查得到 ${itemCount} 条可用内容，但未更新信息流；${failedCount} 个来源失败。`,
      retryable: true,
      terminal: true,
    }
  }
  if (job.status === 'succeeded') {
    return {
      state: 'succeeded',
      message: snapshotCreated ? `信息流已更新，共 ${itemCount} 条。` : '检查完成，信息流没有变化。',
      retryable: false,
      terminal: true,
    }
  }
  if (job.status === 'failed') {
    const code = job.error_code ? `（${job.error_code}）` : ''
    return {
      state: 'failed',
      message: `${job.error_message || '获取失败'}${code}`,
      retryable: Boolean(job.retryable),
      terminal: true,
    }
  }
  return { state: 'idle', message: '任务已取消。', retryable: false, terminal: true }
}

/**
 * Convert a terminal feed job into the one-shot notification it is allowed to
 * emit. A successful no-op is intentionally silent: completion state belongs
 * on the initiating control, while the global snackbar is reserved for a new
 * snapshot or an actionable partial/failure result.
 */
export function feedJobNotice(job: Job | undefined): FeedNotice | undefined {
  if (!job || (job.status !== 'succeeded' && job.status !== 'partial' && job.status !== 'failed')) return undefined
  const result = resultOf(job)
  if (job.status === 'succeeded' && result.snapshot_created !== true) return undefined
  const activity = describeFeedJob(job)
  if (!activity.message) return undefined
  return {
    key: `${job.id}:${job.status}`,
    state: activity.state,
    message: activity.message,
  }
}
