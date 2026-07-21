import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import type { ServiceApi } from '../../api/service'
import { queryKeys } from '../../api/queryKeys'
import { Button, Icons, Separator, Skeleton } from '../../design-system'
import type { FeedPreference } from '../feed/feedPreference'
import { relativeTime } from '../feed/feedModel'
import { useLocalDayReference } from '../feed/useLocalDayReference'
import { buildFeedInsightsModel, type FeedInsightsDistribution } from './feedInsights'

function DistributionList({ title, values }: { title: string; values: FeedInsightsDistribution[] }) {
  const visible = values.slice(0, 5)
  return <section aria-label={title} className="grid gap-1.5">
    <h3 className="type-label mb-1 text-muted">{title}</h3>
    {values.length === 0 && <p className="type-body text-muted">暂无数据</p>}
    {visible.map((value) => <div key={value.id} className="type-meta flex min-w-0 items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-default/60">
      <span className="size-1.5 shrink-0 rounded-full bg-accent/65" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{value.label}</span>
      <span className="shrink-0 text-muted">{value.count}</span>
    </div>)}
    {values.length > visible.length && <p className="type-meta px-1.5 text-muted">再显示 {values.length - visible.length} 项</p>}
  </section>
}

export function FeedInsightsPanel({
  open,
  onClose,
  api,
  userId,
  preference,
  query,
}: {
  open: boolean
  onClose: () => void
  api: ServiceApi
  userId: string
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
  const model = useMemo(() => buildFeedInsightsModel({
    snapshot: feed.data,
    health: health.data,
    preference,
    query,
    now,
  }), [feed.data, health.data, now, preference, query])
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
    <div className="quiet-scroll-region min-h-0 min-w-0 overflow-x-hidden overflow-y-auto px-4 pb-4" data-testid="feed-insights-panel">
      {(feed.isLoading || health.isLoading) && <div className="grid gap-2 pt-4" aria-label="正在读取信息概览">
        {Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-9 rounded-xl" />)}
      </div>}
      {!feed.isLoading && <>
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
        <Separator className="my-4" />
        <DistributionList title="频道" values={model.channels} />
        <Separator className="my-4" />
        <DistributionList title="内容类型" values={model.formats} />
      </>}
    </div>
  </>
}
