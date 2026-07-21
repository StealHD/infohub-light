import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

import type { ServiceApi } from '../../api/service'
import { queryKeys } from '../../api/queryKeys'
import { Button, Card, Icons, Skeleton } from '../../design-system'
import type { FeedPreference } from '../feed/feedPreference'
import { relativeTime } from '../feed/feedModel'
import { useLocalDayReference } from '../feed/useLocalDayReference'
import { buildFeedInsightsModel, type FeedInsightsDistribution } from './feedInsights'

function DistributionList({ title, values }: { title: string; values: FeedInsightsDistribution[] }) {
  return <section aria-label={title} className="grid gap-2">
    <h3 className="type-label text-muted">{title}</h3>
    {values.length === 0 && <p className="type-body text-muted">暂无数据</p>}
    {values.slice(0, 6).map((value) => <div key={value.id} className="grid min-w-0 gap-1">
      <div className="type-meta flex min-w-0 items-center gap-2">
        <span className="min-w-0 flex-1 truncate">{value.label}</span>
        <span className="shrink-0 text-muted">{value.count}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-default" aria-hidden="true">
        <span className="block h-full rounded-full bg-accent" style={{ inlineSize: `${Math.max(4, value.ratio * 100)}%` }} />
      </div>
    </div>)}
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
    <div className="min-h-0 min-w-0 overflow-x-hidden overflow-y-auto p-4" data-testid="feed-insights-panel">
      {(feed.isLoading || health.isLoading) && <div className="grid grid-cols-2 gap-2" aria-label="正在读取信息概览">
        {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-20 rounded-xl" />)}
      </div>}
      {!feed.isLoading && <>
        <div className="grid grid-cols-2 gap-2">
          {metrics.map((metric) => <Card key={metric.label} variant="secondary" className="gap-1 p-3">
            <span className="type-label text-muted">{metric.label}</span>
            <strong className="type-section-title">{metric.value}</strong>
          </Card>)}
        </div>
        <Card variant="secondary" className="mt-3 gap-1 p-3">
          <span className="type-label text-muted">当前视图</span>
          <strong className="type-section-title">{model.visibleCount} / {model.totalCount}</strong>
          <span className="type-meta text-muted">{model.updatedAt ? `最近更新于 ${relativeTime(model.updatedAt)}` : '尚无更新时间'}</span>
        </Card>
        <div className="mt-5 grid gap-5">
          <DistributionList title="频道分布" values={model.channels} />
          <DistributionList title="内容类型" values={model.formats} />
        </div>
      </>}
    </div>
  </>
}
