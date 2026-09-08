import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, RefreshButton, StableAsyncButton } from '../../design-system'
import { useInformationContext } from './useInformationContext'
const InformationRuleEditor = lazy(() => import('./InformationRuleEditor').then((module) => ({ default: module.InformationRuleEditor })))
const InformationNewRule = lazy(() => import('./InformationNewRule').then((module) => ({ default: module.InformationNewRule })))
import { judgmentLabels, ruleStateLabels, triggerLabel } from './informationRuleModel'

export default function InformationAutomationsView({ canMutate }: { canMutate: boolean }) {
  const { api, userId } = useInformationContext()
  const cache = useQueryClient()
  const key = ['information-rules', userId]
  const query = useInfiniteQuery({ queryKey: key, initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => api.informationRules(pageParam, signal),
    getNextPageParam: (page) => page.next_offset ?? undefined, refetchInterval: 15000 })
  const [editing, setEditing] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  return <div className="quiet-scroll-region h-full min-h-0 overflow-y-auto px-4 pb-6 pt-[var(--inteliscope-size-page-header)] min-[768px]:px-6"><div className="mx-auto grid max-w-4xl gap-4">
    <div className="flex flex-wrap items-center gap-2">
      <Button isDisabled={!canMutate || creating} onPress={() => setCreating(true)}>新建自动化</Button>
      <RefreshButton pending={query.isFetching} aria-label="刷新提醒列表" onPress={() => query.refetch()} />
      <Link to="/agent/automations?advanced=cron" className="type-meta underline">高级 Gateway Cron</Link>
    </div>
    <p className="type-body text-muted">用完整描述统一判断内容，选择触发方式与模型，符合要求时通知。</p>
    {creating && <Suspense fallback={<p role="status">正在加载新建表单…</p>}><InformationNewRule onCancel={() => setCreating(false)} onSaved={async (rule) => {
      await cache.invalidateQueries({ queryKey: key }); setCreating(false); setEditing(rule.id)
    }} /></Suspense>}
    {query.isError && <p role="alert">提醒列表读取失败，请重试。</p>}
    {query.isPending && <p role="status">正在读取个人提醒…</p>}
    {query.data?.pages[0].items.length === 0 && <p className="type-body">暂无自动化，可以创建任务或通过聊天准备草稿。</p>}
    {query.data?.pages.flatMap((page) => page.items).map((rule) => <Card key={rule.id} variant="secondary" className="grid gap-3 p-4">
      <Card.Title>{rule.config.name}</Card.Title><Card.Description>{ruleStateLabels[rule.state]} · {triggerLabel(rule.config.trigger)}</Card.Description>
      <p className="type-body whitespace-pre-wrap break-words">{rule.config.requirement || '尚未填写任务描述'}</p>
      <p className="type-meta text-muted">{rule.source_names?.join('、') || `${rule.config.source_ids.length} 个订阅源`} · {rule.config.trigger.kind === 'count' ? `已累计 ${rule.pending_count || 0} / ${rule.config.trigger.count} 条` : `待处理 ${rule.pending_count || 0} 条`}
        {rule.next_due ? ` · 下次处理 ${new Date(rule.next_due).toLocaleString()}` : ''}</p>
      {rule.latest_run && <p className="type-meta">最近分析：{judgmentLabels[rule.latest_run.status]}</p>}
      <Button variant="ghost" onPress={() => setEditing(editing === rule.id ? null : rule.id)}>{editing === rule.id ? '收起' : '查看与编辑'}</Button>
      {editing === rule.id && <Suspense fallback={<p role="status">正在加载任务详情…</p>}><InformationRuleEditor key={`${userId}:${rule.id}`} rule={rule} canMutate={canMutate}
        onSaved={async () => { await cache.invalidateQueries({ queryKey: key }) }} /></Suspense>}
    </Card>)}
    {query.hasNextPage && <StableAsyncButton pending={query.isFetchingNextPage} pendingContent="正在加载…" onPress={() => query.fetchNextPage()}>加载更多提醒</StableAsyncButton>}
  </div></div>
}
