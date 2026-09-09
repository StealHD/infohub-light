import { useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Button, Card, Icons, RefreshButton, StableAsyncButton } from '../../design-system'
import { useInformationContext } from './useInformationContext'
import { judgmentLabels, notificationLabels, reminderReasonLabels } from './informationRuleModel'

export function InformationRuleRuns({ ruleId }: { ruleId: string }) {
  const { api, userId } = useInformationContext()
  const [expanded, setExpanded] = useState<string | null>(null)
  const query = useInfiniteQuery({ queryKey: ['information-runs', userId, ruleId], initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => api.informationRuns(ruleId, pageParam, signal),
    getNextPageParam: (page) => page.next_offset ?? undefined, refetchInterval: 15000 })
  return <section className="grid gap-3" aria-label="提醒运行记录">
    <div className="flex items-center gap-2"><h3 className="type-section-title">运行记录</h3>
      <RefreshButton pending={query.isFetching} aria-label="刷新运行记录" onPress={() => query.refetch()} /></div>
    {query.isError && <p role="alert">运行记录读取失败，请重试。</p>}
    {query.isPending && <p role="status">正在读取运行记录…</p>}
    {query.data?.pages.flatMap((page) => page.items).map((run) => {
      const open = expanded === run.id
      const notification = run.notification_status === 'sent' && !run.receipt ? '没有可验证回执' : notificationLabels[run.notification_status]
      return <Card key={run.id} className="p-0" variant="secondary">
        <Button variant="ghost" className="h-auto w-full justify-start rounded-[var(--inteliscope-radius-card)] p-3 text-left" aria-expanded={open}
          onPress={() => setExpanded((current) => current === run.id ? null : run.id)}>
          <span className="min-w-0 flex-1"><span className="type-meta block text-muted">{new Date(run.created_at).toLocaleString()}</span>
            <span className="type-body mt-1 block break-words">{judgmentLabels[run.status]} · {notification}</span></span>
          <Icons.ChevronDown size={15} className={`shrink-0 transition-transform motion-reduce:transition-none ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
        </Button>
        {open && <div className="grid gap-2 border-t border-separator px-4 py-3">
          <p className="type-meta text-muted">规则版本 {run.version}{run.range ? ` · 本批 ${run.range.item_count} 条` : ''}{run.model?.id ? ` · ${run.model.id}` : ''}</p>
          {run.progress && <p className="type-meta">分析进度：{run.progress.completed} / {run.progress.total}</p>}
          {run.result && <><p className="type-body">{run.result.summary}</p><p className="type-body">{run.result.reason}</p>
            {run.result.evidence.map((item, index) => <blockquote key={index} className="type-body border-l border-separator pl-3">{item.quote} — {item.note}{item.url && <a className="block underline" href={item.url} target="_blank" rel="noopener noreferrer">{item.title || '查看原文'}</a>}</blockquote>)}</>}
          {!run.result && run.reason && <p className="type-body">{reminderReasonLabels[run.reason] || '本次运行未完成，请检查接入与通知设置。'}</p>}
          {run.evidence.map((item) => <p key={item.article_id} className="type-body">{item.title || '订阅文章'}：{judgmentLabels[item.status]}</p>)}
          {run.receipt && <p className="type-meta">回执：{run.receipt.channel} · {run.receipt.verification}</p>}
        </div>}
      </Card>
    })}
    {query.data?.pages[0].items.length === 0 && <p className="type-body text-muted">暂无运行。启用后只处理新增内容。</p>}
    {query.hasNextPage && <StableAsyncButton pending={query.isFetchingNextPage} pendingContent="正在加载…" onPress={() => query.fetchNextPage()}>加载更多运行</StableAsyncButton>}
  </section>
}
