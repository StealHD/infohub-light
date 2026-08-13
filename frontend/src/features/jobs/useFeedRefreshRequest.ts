import { useMutation, type QueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import type { ServiceApi } from '../../api/service'
import type { Job } from '../../api/types'
import type { ActionGeneration, ActionToken } from '../../app/actionGeneration'
import type { FeedNotice } from './jobModel'

type JobsResponse = { jobs: Job[] }

export function useFeedRefreshRequest(options: {
  api: ServiceApi
  userId: string
  guard: ActionGeneration
  queryClient: QueryClient
  nextBlockedKey: (prefix: string) => string
  setRequestNotice: (notice?: FeedNotice) => void
  setJobNotice: (notice?: FeedNotice) => void
}) {
  return useMutation({
    mutationFn: async (token: ActionToken) => {
      void token
      const schedule = await options.api.feedSchedule()
      options.queryClient.setQueryData(queryKeys.feedSchedule(options.userId), schedule)
      if (schedule.worker_status !== 'ready') {
        throw new Error('后台获取服务当前不可用，未创建更新任务。请启动 Worker 后重试。')
      }
      return options.api.createFeedRefresh()
    },
    onMutate: async () => {
      await options.queryClient.cancelQueries({ queryKey: queryKeys.feedJobs(options.userId) })
      options.setRequestNotice(undefined)
      options.setJobNotice(undefined)
    },
    onSuccess: (job, token) => {
      if (!options.guard.isCurrent(token)) return
      options.queryClient.setQueryData(queryKeys.feedJobs(options.userId), (previous: JobsResponse | undefined) => ({
        jobs: [job, ...(previous?.jobs ?? []).filter((entry) => entry.id !== job.id)].slice(0, 20),
      }))
      options.queryClient.setQueryData(queryKeys.jobs(options.userId), (previous: JobsResponse | undefined) => previous ? ({
        ...previous,
        jobs: [job, ...previous.jobs.filter((entry) => entry.id !== job.id)].slice(0, 100),
      }) : previous)
    },
    onError: (error, token) => {
      if (!options.guard.isCurrent(token)) return
      options.setRequestNotice({
        key: options.nextBlockedKey('refresh-blocked'),
        state: 'blocked',
        message: error instanceof Error && error.message.includes('后台获取服务')
          ? error.message
          : '无法检查后台获取服务状态，未创建更新任务。请稍后重试。',
      })
    },
  })
}
