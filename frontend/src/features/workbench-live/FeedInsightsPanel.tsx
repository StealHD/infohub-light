import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import type { ServiceApi } from '../../api/service'
import { queryKeys } from '../../api/queryKeys'
import { Button, Icons, Separator, Skeleton } from '../../design-system'
import type { FeedPreference } from '../feed/feedPreference'
import { relativeTime } from '../feed/feedModel'
import { sourceMatchesSubscriptionVisibility } from '../subscriptions/subscriptionModel'
import { useLocalDayReference } from '../feed/useLocalDayReference'
import { buildFeedInsightsModel, type FeedInsightsDistribution } from './feedInsights'

function DistributionList({ title, values }: { title: string; values: FeedInsightsDistribution[] }) {
  const [expanded, setExpanded] = useState(false)
  if (values.length === 0) return null
  const visible = expanded ? values : values.slice(0, 3)
  const remaining = values.length - visible.length
  return <section aria-label={title} className="grid gap-1.5">
    <h3 className="type-label mb-1 text-muted">{title}</h3>
    {visible.map((value) => <div key={value.id} className="type-meta flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-default/60">
      <span className="size-1.5 shrink-0 rounded-full bg-accent/65" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{value.label}</span>
      <span className="shrink-0 text-muted">{value.count}</span>
    </div>)}
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
  includePrivateSources,
  preference,
  query,
}: {
  open: boolean
  onClose: () => void
  api: ServiceApi
  userId: string
  includePrivateSources: boolean
  preference: FeedPreference
  query: string
}) {
  const now = useLocalDayReference()
  const feed = useQuery({
    queryKey: queryKeys.feed(userId, { hideDismissed: false, unreadFirst: false }),
    queryFn: ({ signal }) => api.latestFeed(signal),
    enabled: open,
  })
  const health = useQuery({
    queryKey: queryKeys.sourceHealth(userId),
    queryFn: ({ signal }) => api.sourceHealth(signal),
    enabled: open,
  })
  const sources = useQuery({
    queryKey: queryKeys.sources(userId),
    queryFn: ({ signal }) => api.sources(includePrivateSources, signal),
    enabled: open && preference.subscriptionScope !== 'all',
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
    { label: '今日内容', value: model.todayCount },
    { label: '未读', value: model.unreadCount },
    { label: '已收藏', value: model.savedCount },
    { label: '异常来源', value: model.unhealthySourceCount },
  ]

  return <>
    <header className="flex h-[52px] min-w-0 items-center gap-2 overflow-hidden border-b border-separator px-4">
      <Icons.ChartNoAxesCombined className="shrink-0" size={17} aria-hidden="true" />
      <strong className="min-w-0 flex-1 truncate">信息概览</strong>
      <Button size="sm" variant="ghost" isIconOnly aria-label="关闭信息概览" onPress={onClose}>
        <Icons.X size={17} aria-hidden="true" />
      </Button>
    </header>
    <div className="quiet-scroll-region min-h-0 min-w-0 overflow-x-hidden overflow-y-auto px-5 pb-5" data-testid="feed-insights-panel">
      {(feed.isLoading || health.isLoading || sources.isLoading) && <div className="grid gap-2 pt-4" aria-label="正在读取信息概览">
        {Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-9 rounded-xl" />)}
      </div>}
      {!feed.isLoading && !sources.isLoading && <>
        <section aria-label="概况" className="pt-4">
          <h3 className="type-label mb-2 text-muted">概况</h3>
          <div className="grid grid-cols-2 gap-x-5 gap-y-2">
            {metrics.map((metric) => <div key={metric.label} className="flex min-w-0 items-baseline justify-between gap-2">
              <span className="type-meta min-w-0 truncate text-muted">{metric.label}</span>
              <strong className="type-control shrink-0">{metric.value}</strong>
            </div>)}
          </div>
        </section>
        <Separator className="my-4" />
        <section aria-label="当前视图" className="grid gap-1">
          <h3 className="type-label text-muted">当前视图</h3>
          <div className="flex items-baseline justify-between gap-3">
            <span className="type-body">可见内容</span>
            <strong className="type-control">{model.visibleCount} / {model.totalCount}</strong>
          </div>
          <span className="type-meta text-muted">{model.updatedAt ? `最近更新于 ${relativeTime(model.updatedAt)}` : '尚无更新时间'}</span>
        </section>
        {model.channels.length > 0 && <><Separator className="my-4" /><DistributionList title="主要频道" values={model.channels} /></>}
        {model.formats.length > 0 && <><Separator className="my-4" /><DistributionList title="内容类型" values={model.formats} /></>}
      </>}
    </div>
  </>
}
