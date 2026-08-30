import { ApiError } from '../../api/client'

const WORKER_STALE_CODE = 'source_fetch_worker_stale'
const WORKER_STATUS_UNKNOWN_CODE = 'source_fetch_worker_status_unknown'

const WORKER_UNAVAILABLE_CODES = new Set([WORKER_STALE_CODE, WORKER_STATUS_UNKNOWN_CODE])

const workerUnavailableMessage = (workerStatus?: string) => workerStatus === 'stale'
  ? '后台 Worker 心跳已过期，本次任务未创建，也未产生抓取费用。恢复 Worker 后再试。'
  : '无法确认后台 Worker 状态，本次任务未创建，也未产生抓取费用。确认 Worker 正常后再试。'

export function requireSourceFetchWorker(workerStatus?: string) {
  if (workerStatus === 'ready') return
  throw new ApiError(503, {
    code: workerStatus === 'stale' ? WORKER_STALE_CODE : WORKER_STATUS_UNKNOWN_CODE,
    message: workerUnavailableMessage(workerStatus),
    retryable: true,
  })
}

export function sourceFetchFailureCopy(sourceName: string, caught: unknown) {
  const notStarted = caught instanceof ApiError
    && WORKER_UNAVAILABLE_CODES.has(caught.code)
  return {
    tone: notStarted ? 'warning' as const : 'danger' as const,
    title: `${sourceName} ${notStarted ? '获取未开始' : '获取失败'}`,
    description: caught instanceof ApiError || caught instanceof Error
      ? caught.message
      : '操作失败，请稍后重试。',
  }
}
