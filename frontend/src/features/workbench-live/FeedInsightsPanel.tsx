import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import type { ServiceApi } from '../../api/service'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import { Button, Icons, Separator, Skeleton } from '../../design-system'
import type { FeedPreference } from '../feed/feedPreference'
import { relativeTime } from '../feed/feedModel'
import { sourceMatchesSubscriptionVisibility } from '../subscriptions/subscriptionModel'
import { useLocalDayReference } from '../feed/useLocalDayReference'
import { buildFeedInsightsModel, type FeedInsightsDistribution } from './feedInsights'

export type FeedInsightsMetric =
  | 'today'
  | 'unread'
  | 'saved'
  | 'unhealthy'
  | 'subscriptions'
  | 'sources'
  | 'recent_runs'

function DistributionList({ title, values, onSelect }: { title: string; values: FeedInsightsDistribution[]; onSelect?: (value: FeedInsightsDistribution) => void }) {
  const [expanded, setExpanded] = useState(false)
  if (values.length === 0) return null
  const visible = expanded ? values : values.slice(0, 3)
  const remaining = values.length - visible.length
  return <section aria-label={title} className="grid gap-1.5">
    <h3 className="type-label mb-1 text-muted">{title}</h3>
    {visible.map((value) => {
      const content = <>
      <span className="size-1.5 shrink-0 rounded-full bg-accent/65" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{value.label}</span>
      <span className="shrink-0 text-muted">{value.count}</span>
      </>
      return onSelect
        ? <button key={value.id} type="button" className="type-meta flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1 text-left hover:bg-default/60 focus-visible:outline-2 focus-visible:outline-focus" onClick={() => onSelect(value)}>{content}</button>
        : <div key={value.id} className="type-meta flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1">{content}</div>
    })}
    {values.length > 3 && <Button
      size="sm"
      variant="ghost"
      className="type-meta mt-0.5 h-7 justify-start px-1.5 text-muted"
      aria-expanded={expanded}
      onPress={() => setExpanded((value) => !value)}
    >{expanded ? '收起' : `查看更多 ${remaining} 项`}<Icons.ChevronDown size={13} className={`transition-transform motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`} aria-hidden="true" /></Button>}
  </section>
}

export function FeedInsightsPanel({
  open,
  onClose,
  api,
  userId,
  includeDisabledSources,
  preference,
  query,
  onMetricAction,
  onChannelAction,
}: {
  open: boolean
  onClose: () => void
  api: ServiceApi
  userId: string
  includeDisabledSources: boolean
  preference: FeedPreference
  query: string
  onMetricAction?: (metric: FeedInsightsMetric) => void
  onChannelAction?: (channel: string) => void
}) {
  const now = useLocalDayReference()
  const feed = useQuery({
    queryKey: queryKeys.feed(userId, { hideDismissed: false, unreadFirst: false }),
    queryFn: ({ signal }) => api.latestFeed(signal),
    enabled: open,
    staleTime: queryStaleTime.feed,
  })
  const health = useQuery({
    queryKey: queryKeys.sourceHealth(userId),
    queryFn: ({ signal }) => api.sourceHealth(signal),
    enabled: open,
    staleTime: queryStaleTime.catalog,
  })
  const sources = useQuery({
    queryKey: queryKeys.sources(userId),
    queryFn: ({ signal }) => api.sources(includeDisabledSources, signal),
    enabled: open,
    staleTime: queryStaleTime.catalog,
  })
  const subscriptions = useQuery({
    queryKey: queryKeys.subscriptions(userId),
    queryFn: ({ signal }) => api.subscriptions(signal),
    enabled: open,
    staleTime: queryStaleTime.catalog,
  })
  const jobs = useQuery({
    queryKey: queryKeys.jobs(userId),
    queryFn: ({ signal }) => api.jobs(signal),
    enabled: open,
    staleTime: queryStaleTime.jobs,
  })
  const allowedSourceIds = useMemo(() => {
    if (preference.subscriptionScope === 'all') return undefined
    const visibility = preference.subscriptionScope === 'public' ? 'public' : 'private'
    return new Set((sources.data?.sources ?? [])
      .filter((source) => sourceMatchesSubscriptionVisibility(source, visibility))
      .map((source) => source.id))
  }, [preference.subscriptionScope, sources.data?.sources])
  const model = useMemo(() => buildFeedInsightsModel({
    snapshot: feed.data,
    health: health.data,
    preference,
    query,
    allowedSourceIds,
    now,
  }), [allowedSourceIds, feed.data, health.data, now, preference, query])
  const metrics = [
    { id: 'today' as const, label: '今日内容', value: model.todayCount },
    { id: 'unread' as const, label: '未读', value: model.unreadCount },
    { id: 'saved' as const, label: '已收藏', value: model.savedCount },
    { id: 'unhealthy' as const, label: '异常来源', value: model.unhealthySourceCount },
  ]
  const subscriptionMetrics = [
    {
      id: 'subscriptions' as const,
      label: '我的订阅',
      value: subscriptions.isError ? null : subscriptions.data?.subscriptions.length,
      loading: subscriptions.isLoading,
    },
    {
      id: 'sources' as const,
      label: '来源库',
      value: sources.isError ? null : sources.data?.sources.length,
      loading: sources.isLoading,
    },
    {
      id: 'recent_runs' as const,
      label: '最近运行',
      value: jobs.isError ? null : jobs.data?.jobs.filter((job) => job.user_id === userId).length,
      loading: jobs.isLoading,
    },
  ]
  const insightsLoading = feed.isLoading
    || health.isLoading
    || (preference.subscriptionScope !== 'all' && sources.isLoading)

  return <>
    <header className="flex h-[52px] min-w-0 items-center gap-2 overflow-hidden border-b border-separator px-4">
      <Icons.ChartNoAxesCombined className="shrink-0" size={17} aria-hidden="true" />
      <strong className="min-w-0 flex-1 truncate">信息概览</strong>
      <Button size="sm" variant="ghost" isIconOnly aria-label="关闭信息概览" onPress={onClose}>
        <Icons.X size={17} aria-hidden="true" />
      </Button>
    </header>
    <div className="quiet-scroll-region min-h-0 min-w-0 overflow-x-hidden overflow-y-auto px-5 pb-5" data-testid="feed-insights-panel">
      {insightsLoading && <div className="grid gap-2 pt-4" aria-label="正在读取信息概览">
        {Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-9 rounded-xl" />)}
      </div>}
      {!insightsLoading && <>
        <section aria-label="概况" className="pt-4">
          <h3 className="type-label mb-2 text-muted">概况</h3>
          <div className="grid grid-cols-2 gap-x-5 gap-y-2">
            {metrics.map((metric) => <button
              key={metric.label}
              type="button"
              className="flex min-w-0 items-baseline justify-between gap-2 rounded-lg px-1 py-0.5 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus disabled:pointer-events-none"
              disabled={!onMetricAction}
              aria-label={`${metric.label} ${metric.value}，打开相关内容`}
              onClick={() => onMetricAction?.(metric.id)}
            >
              <span className="type-meta min-w-0 truncate text-muted">{metric.label}</span>
              <strong className="type-control shrink-0">{metric.value}</strong>
            </button>)}
          </div>
        </section>
        <Separator className="my-4" />
      </>}
      <section aria-label="订阅与运行" className={insightsLoading ? 'mt-4 border-t border-separator pt-4' : ''}>
        <h3 className="type-label mb-2 text-muted">订阅与运行</h3>
        <div className="grid grid-cols-3 gap-2">
          {subscriptionMetrics.map((metric) => <button
            key={metric.id}
            type="button"
            className="grid min-w-0 gap-0.5 rounded-lg px-1.5 py-1 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus disabled:pointer-events-none"
            disabled={!onMetricAction || metric.loading || metric.value === null || metric.value === undefined}
            aria-label={metric.loading
              ? `${metric.label}正在读取`
              : metric.value === null || metric.value === undefined
                ? `${metric.label}暂时无法读取`
                : `${metric.label} ${metric.value}，打开相关页面`}
            onClick={() => onMetricAction?.(metric.id)}
          >
            <span className="type-meta truncate text-muted">{metric.label}</span>
            {metric.loading
              ? <Skeleton className="mt-1 h-5 w-8 rounded-md" />
              : <strong className="type-control">{metric.value ?? '—'}</strong>}
          </button>)}
        </div>
        <p className="type-label mt-2 text-muted">最近运行只统计最近加载的记录，最多 100 条。</p>
      </section>
      {!insightsLoading && <>
        <Separator className="my-4" />
        <section aria-label="当前视图" className="grid gap-1">
          <h3 className="type-label text-muted">当前视图</h3>
          <div className="flex items-baseline justify-between gap-3">
            <span className="type-body">可见内容</span>
            <strong className="type-control">{model.visibleCount} / {model.totalCount}</strong>
          </div>
          <span className="type-meta text-muted">{model.updatedAt ? `最近更新于 ${relativeTime(model.updatedAt)}` : '尚无更新时间'}</span>
        </section>
        {model.channels.length > 0 && <><Separator className="my-4" /><DistributionList title="主要频道" values={model.channels} onSelect={onChannelAction ? (value) => onChannelAction(value.id) : undefined} /></>}
        {model.formats.length > 0 && <><Separator className="my-4" /><DistributionList title="内容类型" values={model.formats} /></>}
      </>}
    </div>
  </>
}
