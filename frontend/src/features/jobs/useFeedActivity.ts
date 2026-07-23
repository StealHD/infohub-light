import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { ServiceApi } from '../../api/service'
import type { User } from '../../api/types'
import { queryKeys } from '../../api/queryKeys'
import { describeFeedJob, feedJobNotice, latestFeedJob, pollingTimedOut, type FeedNotice } from './jobModel'
import type { ActionGeneration, ActionToken } from '../../app/actionGeneration'

type ScopedNotice = {
  userId: string
  notice?: FeedNotice
}

export function useFeedActivity(api: ServiceApi, user: User, guard: ActionGeneration) {
  const queryClient = useQueryClient()
  const terminalHandled = useRef('')
  const jobsInitialized = useRef(false)
  const observedActiveJobs = useRef(new Set<string>())
  const seenTerminalJobs = useRef(new Set<string>())
  const blockedSequence = useRef(0)
  const [requestNoticeState, setRequestNoticeState] = useState<ScopedNotice>(() => ({ userId: user.id }))
  const [jobNoticeState, setJobNoticeState] = useState<ScopedNotice>(() => ({ userId: user.id }))
  const requestNotice = requestNoticeState.userId === user.id ? requestNoticeState.notice : undefined
  const jobNotice = jobNoticeState.userId === user.id ? jobNoticeState.notice : undefined
  const setRequestNotice = useCallback((notice?: FeedNotice) => setRequestNoticeState({ userId: user.id, notice }), [user.id])
  const setJobNotice = useCallback((notice?: FeedNotice) => setJobNoticeState({ userId: user.id, notice }), [user.id])
  const jobsQuery = useQuery({
    queryKey: queryKeys.jobs(user.id),
    queryFn: ({ signal }) => api.jobs(signal),
    refetchInterval: (query) => {
      const current = latestFeedJob(query.state.data?.jobs ?? [], user.id)
      return current && !pollingTimedOut(current) && (current.status === 'queued' || current.status === 'running') ? 2000 : false
    },
  })
  const currentJob = useMemo(() => latestFeedJob(jobsQuery.data?.jobs ?? [], user.id), [jobsQuery.data, user.id])
  const scheduleQuery = useQuery({
    queryKey: queryKeys.feedSchedule(user.id),
    queryFn: ({ signal }) => api.feedSchedule(signal),
  })
  const activity = describeFeedJob(currentJob, scheduleQuery.data?.worker_status ?? 'unknown')

  useEffect(() => {
    terminalHandled.current = ''
    jobsInitialized.current = false
    observedActiveJobs.current.clear()
    seenTerminalJobs.current.clear()
    blockedSequence.current = 0
  }, [user.id])

  useEffect(() => {
    if (!jobsQuery.isSuccess) return
    const jobs = jobsQuery.data?.jobs ?? []
    if (!jobsInitialized.current) {
      for (const job of jobs) {
        if (job.user_id !== user.id || job.job_type !== 'user_feed_refresh') continue
        if (job.status === 'queued' || job.status === 'running') observedActiveJobs.current.add(job.id)
        else seenTerminalJobs.current.add(`${job.id}:${job.status}`)
      }
      jobsInitialized.current = true
      return
    }
    if (!currentJob) return
    if (currentJob.status === 'queued' || currentJob.status === 'running') {
      observedActiveJobs.current.add(currentJob.id)
      return
    }
    const terminalKey = `${currentJob.id}:${currentJob.status}`
    if (seenTerminalJobs.current.has(terminalKey)) return
    seenTerminalJobs.current.add(terminalKey)
    if (!observedActiveJobs.current.has(currentJob.id)) return
    setJobNotice(feedJobNotice(currentJob))
  }, [currentJob, jobsQuery.data, jobsQuery.isSuccess, setJobNotice, user.id])

  useEffect(() => {
    if (!currentJob || !activity.terminal || terminalHandled.current === `${currentJob.id}:${currentJob.status}`) return
    terminalHandled.current = `${currentJob.id}:${currentJob.status}`
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.feed(user.id, { hideDismissed: false, unreadFirst: false }) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.history(user.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) }),
    ])
  }, [activity.terminal, currentJob, queryClient, user.id])

  const refreshMutation = useMutation({
    mutationFn: async (token: ActionToken) => {
      void token
      const currentSchedule = await api.feedSchedule()
      queryClient.setQueryData(queryKeys.feedSchedule(user.id), currentSchedule)
      if (currentSchedule.worker_status !== 'ready') {
        throw new Error('后台获取服务当前不可用，未创建更新任务。请启动 Worker 后重试。')
      }
      return api.createFeedRefresh()
    },
    onMutate: () => {
      setRequestNotice(undefined)
      setJobNotice(undefined)
    },
    onSuccess: (job, token) => {
      if (!guard.isCurrent(token)) return
      queryClient.setQueryData(queryKeys.jobs(user.id), (previous: { jobs: typeof job[] } | undefined) => ({
        jobs: [job, ...(previous?.jobs ?? []).filter((entry) => entry.id !== job.id)],
      }))
    },
    onError: (error, token) => {
      if (!guard.isCurrent(token)) return
      blockedSequence.current += 1
      setRequestNotice({
        key: `refresh-blocked:${blockedSequence.current}`,
        state: 'blocked',
        message: error instanceof Error && error.message.includes('后台获取服务')
          ? error.message
          : '无法检查后台获取服务状态，未创建更新任务。请稍后重试。',
      })
    },
  })
  const retryMutation = useMutation({
    mutationFn: (token: ActionToken) => { void token; return currentJob ? api.retryJob(currentJob.id) : Promise.reject(new Error('没有可重试任务')) },
    onMutate: () => setRequestNotice(undefined),
    onSuccess: (_job, token) => {
      if (!guard.isCurrent(token)) return
      setRequestNotice(undefined)
      return queryClient.invalidateQueries({ queryKey: queryKeys.jobs(user.id) })
    },
    onError: (error, token) => {
      if (!guard.isCurrent(token)) return
      blockedSequence.current += 1
      setRequestNotice({
        key: `retry-blocked:${blockedSequence.current}`,
        state: 'blocked',
        message: error instanceof Error ? error.message : '任务重试提交失败，请稍后再试。',
      })
    },
  })
  const retryRequest = () => retryMutation.mutate(guard.capture())
  const retry = requestNotice?.key.startsWith('refresh-blocked:')
    ? () => refreshMutation.mutate(guard.capture())
    : requestNotice?.key.startsWith('retry-blocked:') || activity.retryable
      ? retryRequest
      : undefined

  return {
    currentJob,
    activity,
    notice: requestNotice ?? (
      currentJob?.status === 'queued' || currentJob?.status === 'running'
        ? undefined
        : jobNotice
    ),
    refresh: () => refreshMutation.mutate(guard.capture()),
    retry,
    pending: refreshMutation.isPending || retryMutation.isPending,
  }
}
