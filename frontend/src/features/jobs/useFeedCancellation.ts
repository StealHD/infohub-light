import { useMutation, type QueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import type { ServiceApi } from '../../api/service'
import type { Job } from '../../api/types'
import type { ActionGeneration, ActionToken } from '../../app/actionGeneration'
import type { FeedNotice } from './jobModel'

type JobsResponse = { jobs: Job[] }

const activeJob = (job: Job) => job.status === 'queued' || job.status === 'running'

export function useFeedCancellation(options: {
  api: ServiceApi
  userId: string
  guard: ActionGeneration
  currentJob?: Job
  queryClient: QueryClient
  refetchJobs: () => void
  nextBlockedKey: (prefix: string) => string
  setRequestNotice: (notice?: FeedNotice) => void
}) {
  const mutation = useMutation({
    mutationFn: ({ token, jobId }: { token: ActionToken; jobId: string }) => {
      void token
      return options.api.cancelJob(jobId)
    },
    onMutate: async ({ jobId }) => {
      await options.queryClient.cancelQueries({ queryKey: queryKeys.feedJobs(options.userId) })
      options.setRequestNotice(undefined)
      const markStopping = (previous: JobsResponse | undefined) => previous ? ({
        ...previous,
        jobs: previous.jobs.map((job) => job.id === jobId && job.status === 'running'
          ? { ...job, cancelled_at: job.cancelled_at ?? new Date().toISOString() }
          : job),
      }) : previous
      options.queryClient.setQueryData(queryKeys.feedJobs(options.userId), markStopping)
      options.queryClient.setQueryData(queryKeys.jobs(options.userId), markStopping)
    },
    onSuccess: (job, { token }) => {
      if (!options.guard.isCurrent(token)) return
      const replaceJob = (previous: JobsResponse | undefined) => previous ? ({
        ...previous,
        jobs: [job, ...previous.jobs.filter((entry) => entry.id !== job.id)],
      }) : { jobs: [job] }
      options.queryClient.setQueryData(queryKeys.feedJobs(options.userId), replaceJob)
      options.queryClient.setQueryData(queryKeys.jobs(options.userId), replaceJob)
    },
    onError: (error, { token }) => {
      if (!options.guard.isCurrent(token)) return
      options.refetchJobs()
      options.setRequestNotice({
        key: options.nextBlockedKey('cancel-blocked'),
        state: 'blocked',
        message: error instanceof Error ? error.message : '安全停止请求提交失败，请稍后再试。',
      })
    },
  })
  const active = Boolean(options.currentJob && activeJob(options.currentJob))
  return {
    canCancelRefresh: Boolean(active && !options.currentJob?.cancelled_at && !mutation.isPending),
    isCancellingRefresh: Boolean(mutation.isPending || (active && options.currentJob?.cancelled_at)),
    cancelRefresh: () => {
      const job = options.currentJob
      if (!job || !activeJob(job) || job.cancelled_at) return
      mutation.mutate({ token: options.guard.capture(), jobId: job.id })
    },
    cancelPending: mutation.isPending,
  }
}
