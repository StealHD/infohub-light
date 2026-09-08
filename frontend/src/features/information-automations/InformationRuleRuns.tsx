import { useInfiniteQuery } from '@tanstack/react-query'
import { Card, RefreshButton, StableAsyncButton } from '../../design-system'
import { useInformationContext } from './useInformationContext'
import { judgmentLabels, notificationLabels, reminderReasonLabels } from './informationRuleModel'

export function InformationRuleRuns({ ruleId }: { ruleId: string }) {
  const { api, userId } = useInformationContext()
  const query = useInfiniteQuery({ queryKey: ['information-runs', userId, ruleId], initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => api.informationRuns(ruleId, pageParam, signal),
    getNextPageParam: (page) => page.next_offset ?? undefined })
  return <section className="grid gap-3" aria-label="提醒运行记录">
    <div className="flex items-center gap-2"><h3 className="type-section-title">运行记录</h3>
      <RefreshButton pending={query.isFetching} aria-label="刷新运行记录" onPress={() => query.refetch()} /></div>
    {query.isError && <p role="alert">运行记录读取失败，请重试。</p>}
    {query.isPending && <p role="status">正在读取运行记录…</p>}
    {query.data?.pages.flatMap((page) => page.items).map((run) => <Card key={run.id} className="p-4" variant="secondary">
      <p className="type-body">判断：{judgmentLabels[run.status]}</p>
      <p className="type-body">通知：{run.notification_status === 'sent' && !run.receipt ? '没有可验证回执' : notificationLabels[run.notification_status]}</p>
      <p className="type-meta text-muted">{new Date(run.created_at).toLocaleString()} · 规则版本 {run.version}</p>
      {run.reason && <p className="type-body">{reminderReasonLabels[run.reason] || '本次运行未完成，请检查接入与通知设置。'}</p>}
      {run.evidence.map((item) => <p key={item.article_id} className="type-body">{item.title || '订阅文章'}：{judgmentLabels[item.status]}</p>)}
      {run.receipt && <p className="type-meta">回执：{run.receipt.channel} · {run.receipt.verification}</p>}
    </Card>)}
    {query.data?.pages[0].items.length === 0 && <p className="type-body text-muted">暂无运行。启用后只处理新增内容。</p>}
    {query.hasNextPage && <StableAsyncButton pending={query.isFetchingNextPage} pendingContent="正在加载…" onPress={() => query.fetchNextPage()}>加载更多运行</StableAsyncButton>}
  </section>
}
