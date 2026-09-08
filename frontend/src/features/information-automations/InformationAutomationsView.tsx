import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, RefreshButton, StableAsyncButton } from '../../design-system'
import { useInformationContext } from './useInformationContext'
import { InformationRuleEditor } from './InformationRuleEditor'
import { emptyInformationRule, ruleStateLabels } from './informationRuleModel'

export default function InformationAutomationsView({ canMutate }: { canMutate: boolean }) {
  const { api, userId } = useInformationContext()
  const cache = useQueryClient()
  const key = ['information-rules', userId]
  const query = useInfiniteQuery({ queryKey: key, initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => api.informationRules(pageParam, signal),
    getNextPageParam: (page) => page.next_offset ?? undefined })
  const [editing, setEditing] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [error, setError] = useState('')
  async function create(mode: 'keyword' | 'semantic') {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try {
      const config = emptyInformationRule(mode)
      if (mode === 'keyword') { config.name = 'AI 新动态'; config.conditions.any = ['AI', '人工智能'] }
      else { config.name = '值得关注的研究'; config.requirement = '判断文章是否介绍有明确实验依据的新研究成果，并给出对应文章依据。证据不足时不要推测。' }
      const rule = await api.createInformationRule(config)
      await cache.invalidateQueries({ queryKey: key }); setEditing(rule.id)
    } catch (failure) { setError(failure instanceof Error ? failure.message : '草稿创建失败。') }
    finally { lock.current = false; setBusy(false) }
  }
  return <div className="quiet-scroll-region h-full min-h-0 overflow-y-auto px-4 pb-6 pt-[var(--inteliscope-size-page-header)] min-[768px]:px-6"><div className="mx-auto grid max-w-4xl gap-4">
    <div className="flex flex-wrap items-center gap-2">
      <StableAsyncButton pending={busy} pendingContent="正在创建…" isDisabled={!canMutate} onPress={() => create('keyword')}>新建关键词草稿</StableAsyncButton>
      <Button variant="secondary" isDisabled={!canMutate || busy} onPress={() => create('semantic')}>填写语义示例</Button>
      <RefreshButton pending={query.isFetching} aria-label="刷新提醒列表" onPress={() => query.refetch()} />
      <Link to="/agent/automations?advanced=cron" className="type-meta underline">高级 Gateway Cron</Link>
    </div>
    <p className="type-body text-muted">示例只创建可编辑草稿。保存、测试并确认后才会启用。</p>
    {(error || query.isError) && <p role="alert">{error || '提醒列表读取失败，请重试。'}</p>}
    {query.isPending && <p role="status">正在读取个人提醒…</p>}
    {query.data?.pages[0].items.length === 0 && <p className="type-body">暂无提醒，可以从示例或聊天创建草稿。</p>}
    {query.data?.pages.flatMap((page) => page.items).map((rule) => <Card key={rule.id} variant="secondary" className="p-4">
      <Card.Title>{rule.config.name}</Card.Title><Card.Description>{ruleStateLabels[rule.state]}</Card.Description>
      <Button variant="ghost" onPress={() => setEditing(editing === rule.id ? null : rule.id)}>{editing === rule.id ? '收起' : '查看与编辑'}</Button>
      {editing === rule.id && <InformationRuleEditor key={`${userId}:${rule.id}`} rule={rule} canMutate={canMutate}
        onSaved={async () => { await cache.invalidateQueries({ queryKey: key }) }} />}
    </Card>)}
    {query.hasNextPage && <StableAsyncButton pending={query.isFetchingNextPage} pendingContent="正在加载…" onPress={() => query.fetchNextPage()}>加载更多提醒</StableAsyncButton>}
  </div></div>
}
