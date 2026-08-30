import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { ServiceApi } from '../../api/service'
import type { FeedSnapshot, Job, User } from '../../api/types'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import { describeFeedJob, feedJobNotice, latestFeedJob, pollingTimedOut, type FeedNotice } from './jobModel'
import type { ActionGeneration, ActionToken } from '../../app/actionGeneration'
import { useFeedCancellation } from './useFeedCancellation'
import { useFeedRefreshRequest } from './useFeedRefreshRequest'

type ScopedNotice = {
  userId: string
  notice?: FeedNotice
}

type JobsResponse = { jobs: Job[] }

const feedProducer = (job: Job, userId: string) => (
  job.user_id === userId
  && (job.job_type === 'user_feed_refresh' || job.job_type === 'source_fetch')
)
const activeJob = (job: Job) => job.status === 'queued' || job.status === 'running'
const reloadableTerminal = (job: Job) => job.status === 'succeeded' || job.status === 'partial'

export function useFeedActivity(api: ServiceApi, user: User, guard: ActionGeneration) {
  const queryClient = useQueryClient()
  const currentUserId = useRef(user.id)
  const jobsInitialized = useRef(false)
  const observedActiveJobs = useRef(new Set<string>())
  const seenTerminalJobs = useRef(new Set<string>())
  const blockedSequence = useRef(0)
  const reloadFeedInFlight = useRef<{ userId: string; promise: Promise<FeedSnapshot> } | null>(null)
  const [requestNoticeState, setRequestNoticeState] = useState<ScopedNotice>(() => ({ userId: user.id }))
  const [jobNoticeState, setJobNoticeState] = useState<ScopedNotice>(() => ({ userId: user.id }))
  const requestNotice = requestNoticeState.userId === user.id ? requestNoticeState.notice : undefined
  const jobNotice = jobNoticeState.userId === user.id ? jobNoticeState.notice : undefined
  const setRequestNotice = useCallback((notice?: FeedNotice) => setRequestNoticeState({ userId: user.id, notice }), [user.id])
  const setJobNotice = useCallback((notice?: FeedNotice) => setJobNoticeState({ userId: user.id, notice }), [user.id])
  const reloadFeed = useCallback((): Promise<FeedSnapshot> => {
    const existing = reloadFeedInFlight.current
    if (existing?.userId === user.id) return existing.promise
    const promise = queryClient.fetchQuery({
      queryKey: queryKeys.feed(user.id, { hideDismissed: false, unreadFirst: false }),
      queryFn: ({ signal }) => api.latestFeed(signal),
      staleTime: 0,
    }).finally(() => {
      if (reloadFeedInFlight.current?.promise === promise) reloadFeedInFlight.current = null
    })
    reloadFeedInFlight.current = { userId: user.id, promise }
    return promise
  }, [api, queryClient, user.id])
  const jobsQuery = useQuery({
    queryKey: queryKeys.feedJobs(user.id),
    queryFn: ({ signal }) => api.feedJobs(signal),
    staleTime: queryStaleTime.jobs,
    refetchInterval: (query) => (query.state.data?.jobs ?? []).some((job) => (
      feedProducer(job, user.id)
      && activeJob(job)
      && (job.job_type === 'source_fetch' || !pollingTimedOut(job))
    )) ? 2000 : false,
  })
  const currentJob = useMemo(() => latestFeedJob(jobsQuery.data?.jobs ?? [], user.id), [jobsQuery.data, user.id])
  const scheduleQuery = useQuery({
    queryKey: queryKeys.feedSchedule(user.id),
    queryFn: ({ signal }) => api.feedSchedule(signal),
    staleTime: queryStaleTime.catalog,
  })
  const activity = describeFeedJob(currentJob, scheduleQuery.data?.worker_status ?? 'unknown')

  useEffect(() => {
    currentUserId.current = user.id
    jobsInitialized.current = false
    observedActiveJobs.current.clear()
    seenTerminalJobs.current.clear()
    blockedSequence.current = 0
    reloadFeedInFlight.current = null
  }, [user.id])

  useEffect(() => {
    if (!jobsQuery.isSuccess) return
    const jobs = jobsQuery.data?.jobs ?? []
    if (!jobsInitialized.current) {
      for (const job of jobs) {
        if (!feedProducer(job, user.id)) continue
        if (activeJob(job)) observedActiveJobs.current.add(job.id)
        else seenTerminalJobs.current.add(`${job.id}:${job.status}:${job.finished_at ?? ''}`)
      }
      jobsInitialized.current = true
      return
    }
    const settled: Job[] = []
    for (const job of jobs) {
      if (!feedProducer(job, user.id)) continue
      if (activeJob(job)) {
        observedActiveJobs.current.add(job.id)
        continue
      }
      const terminalKey = `${job.id}:${job.status}:${job.finished_at ?? ''}`
      if (seenTerminalJobs.current.has(terminalKey)) continue
      seenTerminalJobs.current.add(terminalKey)
      if (observedActiveJobs.current.has(job.id)) settled.push(job)
    }
    if (settled.length === 0) return
    const reloadable = settled.filter(reloadableTerminal)
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.historyRoot(user.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) }),
      reloadable.length ? queryClient.invalidateQueries({ queryKey: queryKeys.sources(user.id) }) : Promise.resolve(),
    ])
    const newestFullRefresh = settled.filter((job) => job.job_type === 'user_feed_refresh')
      .sort((left, right) => String(right.created_at ?? '').localeCompare(String(left.created_at ?? '')))[0]
    if (newestFullRefresh && !reloadableTerminal(newestFullRefresh)) {
      const notice = feedJobNotice(newestFullRefresh)
      const noticeUserId = user.id
      void Promise.resolve().then(() => {
        if (currentUserId.current === noticeUserId) setJobNotice(notice)
      })
    }
    if (reloadable.length === 0) return
    const reloadOwner = reloadable
      .sort((left, right) => String(right.created_at ?? '').localeCompare(String(left.created_at ?? '')))[0]
    const reloadUserId = user.id
    void reloadFeed()
      .then(() => {
        if (currentUserId.current !== reloadUserId) return
        if (newestFullRefresh && reloadableTerminal(newestFullRefresh)) {
          setJobNotice(feedJobNotice(newestFullRefresh))
        }
      })
      .catch(() => {
        if (currentUserId.current !== reloadUserId) return
        setJobNotice({
          key: `${reloadOwner.id}:${reloadOwner.status}:feed-reload-failed`,
          state: 'reload_failed',
          message: '内容获取已完成，但信息流加载失败。请点击“刷新”重试。',
        })
      })
  }, [jobsQuery.data, jobsQuery.isSuccess, queryClient, reloadFeed, setJobNotice, user.id])

  const refreshMutation = useFeedRefreshRequest({
    api, userId: user.id, guard, queryClient, nextBlockedKey: (prefix) => `${prefix}:${++blockedSequence.current}`,
    setRequestNotice, setJobNotice,
  })
  const retryMutation = useMutation({
    mutationFn: (token: ActionToken) => { void token; return currentJob ? api.retryJob(currentJob.id) : Promise.reject(new Error('没有可重试任务')) },
    onMutate: () => setRequestNotice(undefined),
    onSuccess: (job, token) => {
      if (!guard.isCurrent(token)) return
      setRequestNotice(undefined)
      queryClient.setQueryData(queryKeys.feedJobs(user.id), (previous: JobsResponse | undefined) => ({
        jobs: [job, ...(previous?.jobs ?? []).filter((entry) => entry.id !== job.id)].slice(0, 20),
      }))
      queryClient.setQueryData(queryKeys.jobs(user.id), (previous: JobsResponse | undefined) => previous ? ({
        ...previous,
        jobs: [job, ...previous.jobs.filter((entry) => entry.id !== job.id)].slice(0, 100),
      }) : previous)
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
  const cancellation = useFeedCancellation({
    api,
    userId: user.id,
    guard,
    currentJob,
    queryClient,
    refetchJobs: () => { void jobsQuery.refetch() },
    nextBlockedKey: (prefix) => `${prefix}:${++blockedSequence.current}`,
    setRequestNotice,
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
    canCancelRefresh: cancellation.canCancelRefresh,
    isCancellingRefresh: cancellation.isCancellingRefresh,
    notice: requestNotice ?? (
      (currentJob?.status === 'queued' || currentJob?.status === 'running') && jobNotice?.state !== 'reload_failed'
        ? undefined
        : jobNotice
    ),
    refresh: () => refreshMutation.mutate(guard.capture()),
    cancelRefresh: cancellation.cancelRefresh,
    reloadFeed,
    retry,
    pending: refreshMutation.isPending || retryMutation.isPending || cancellation.cancelPending,
  }
}
