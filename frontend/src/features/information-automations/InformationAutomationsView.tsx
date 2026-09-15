import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query'
import { Button, RefreshButton, StableAsyncButton } from '../../design-system'
import type { InformationPage, InformationRule } from '../../api/informationAutomationService'
import type { InformationRuleActionState, InformationRuleTransitionAction } from './InformationRuleActivation'
import { ResourceDetailsPanel } from '../../design-system/ResourceDetailsPanel'
import { useInformationContext } from './useInformationContext'
import { InformationTaskList } from './InformationTaskList'
import { InformationTaskDetails } from './InformationTaskDetails'
import { retainInformationRuleOrder } from './informationRuleOrder'
import { useInformationTests } from './useInformationTests'

export default function InformationAutomationsView({ canMutate, header }: { canMutate: boolean; header?: ReactNode }) {
  const { api, userId } = useInformationContext()
  const cache = useQueryClient()
  const key = ['information-rules', userId]
  const query = useInfiniteQuery({ queryKey: key, initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => api.informationRules(pageParam, signal),
    getNextPageParam: (page) => page.next_offset ?? undefined, refetchInterval: 15000,
    structuralSharing: retainInformationRuleOrder })
  const [selected, setSelected] = useState<string | null>(null)
  const [dirtyRuleId, setDirtyRuleId] = useState<string | null>(null)
  const [action, setAction] = useState<InformationRuleActionState>(null)
  const [transitionError, setTransitionError] = useState<{ ruleId: string; message: string } | null>(null)
  const tests = useInformationTests()
  const busy = useRef(false)
  const transitionLock = useRef(false)
  const trigger = useRef<HTMLElement | null>(null)
  const rules = query.data?.pages.flatMap((page) => page.items) || []
  const rule = rules.find((item) => item.id === selected)
  const restore = tests.restore
  useEffect(() => { if (rule) void restore(rule.id, rule.version) }, [restore, rule])
  const close = () => { if (!busy.current) { setSelected(null); (trigger.current?.isConnected ? trigger.current : document.getElementById(`information-task-${selected}`) || document.getElementById('information-task-search'))?.focus() } }
  const select = (id: string) => { if (!busy.current) { trigger.current = document.activeElement as HTMLElement; setDirtyRuleId(null); setSelected(id) } }
  const save = async (saved: InformationRule) => {
    cache.setQueryData<InfiniteData<InformationPage<InformationRule>>>(key, (current) => current && {
      ...current, pages: current.pages.map((page) => ({ ...page, items: page.items.map((item) => item.id === saved.id ? saved : item) })),
    })
    await cache.invalidateQueries({ queryKey: key })
    if (selected === 'new') setSelected(saved.id)
  }
  const transition = async (target: InformationRule, next: InformationRuleTransitionAction) => {
    if (transitionLock.current || (selected === target.id && dirtyRuleId === target.id)) return
    transitionLock.current = true; busy.current = true; setAction({ ruleId: target.id, action: next }); setTransitionError(null)
    try { await save(await api.transitionInformationRule(target.id, target.version, next)) }
    catch (failure) { setTransitionError({ ruleId: target.id, message: failure instanceof Error ? failure.message : '任务状态更新失败，请重试。' }) }
    finally { transitionLock.current = false; busy.current = false; setAction(null) }
  }
  const remove = async (target: InformationRule) => {
    if (transitionLock.current || (selected === target.id && dirtyRuleId === target.id)) throw new Error('请先保存修改，再删除任务。')
    transitionLock.current = true; busy.current = true; setAction({ ruleId: target.id, action: 'delete' }); setTransitionError(null)
    try {
      await api.deleteInformationRule(target.id, target.version)
      cache.setQueryData<InfiniteData<InformationPage<InformationRule>>>(key, (current) => current && {
        ...current, pages: current.pages.map((page) => ({ ...page, items: page.items.filter((item) => item.id !== target.id) })),
      })
      if (selected === target.id) { setSelected(null); setDirtyRuleId(null) }
      await cache.invalidateQueries({ queryKey: key })
      requestAnimationFrame(() => document.getElementById('information-task-search')?.focus())
    } finally { transitionLock.current = false; busy.current = false; setAction(null) }
  }
  return <div className="flex h-full min-h-0 min-w-0">
    <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">{header}
    <div className="quiet-scroll-region min-h-0 min-w-0 flex-1 overflow-y-auto px-4 pb-6 pt-[var(--inteliscope-size-page-header)] min-[768px]:px-6"><div className="mx-auto grid max-w-4xl gap-4">
      <div className="flex flex-wrap items-center gap-2"><p className="type-body min-w-0 flex-1 text-muted">安排任务，让关注的信息按时送达。</p>
        <RefreshButton variant="ghost" pending={query.isFetching} aria-label="刷新提醒列表" onPress={() => query.refetch()} />
        <Button isDisabled={!canMutate} onPress={() => select('new')}>新建自动化</Button></div>
      {!canMutate && <p className="type-meta text-muted">当前为只读模式，可以查看任务与运行记录。</p>}
      {query.isError && <p role="alert">提醒列表读取失败，请重试。已加载任务仍可查看。</p>}
      {query.isPending && <p role="status">正在读取个人提醒…</p>}
      {transitionError && <p role="alert">{transitionError.message}</p>}
      <InformationTaskList rules={rules} selected={selected} onSelect={select} loading={query.isPending} hasMore={query.hasNextPage}
        testStatuses={Object.fromEntries(rules.map((item) => [item.id, tests.session(item.id, item.version).phase]))}
        canMutate={canMutate} action={action} dirtyRuleId={dirtyRuleId} onTransition={transition} onDelete={remove} />
      {query.hasNextPage && <StableAsyncButton pending={query.isFetchingNextPage} pendingContent="正在加载…" onPress={() => query.fetchNextPage()}>加载更多提醒</StableAsyncButton>}
      <Link to="/agent/automations?advanced=cron" className="type-meta text-muted underline">高级 Gateway Cron</Link>
    </div></div></div>
    <ResourceDetailsPanel open={Boolean(selected)} onClose={close} userId={userId} reservePageHeader={false} title={selected === 'new' ? '新建自动化' : rule?.config.name || '任务详情'}>
      <InformationTaskDetails key={selected || 'empty'} rule={rule} creating={selected === 'new'} canMutate={canMutate} onClose={close}
        testSession={rule ? tests.session(rule.id, rule.version) : undefined}
        onTestSelect={(value) => { if (rule) tests.select(rule.id, rule.version, value) }}
        onTestTextChange={(value) => { if (rule) tests.setCustomText(rule.id, rule.version, value) }}
        onTestConfigureNotification={(send, target) => { if (rule) tests.configureNotification(rule.id, rule.version, send, target) }}
        onTestStart={async () => { if (rule) await tests.start(rule.id, rule.version) }}
        onBusyChange={(value) => { busy.current = value }} onDirtyChange={(value) => setDirtyRuleId(value && rule ? rule.id : null)} onSaved={save} action={action} onTransition={transition} onDelete={remove}
        transitionError={transitionError && transitionError.ruleId === rule?.id ? transitionError.message : undefined} />
    </ResourceDetailsPanel>
  </div>
}
