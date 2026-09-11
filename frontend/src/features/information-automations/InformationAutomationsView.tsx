import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { Button, RefreshButton, StableAsyncButton } from '../../design-system'
import { ResourceDetailsPanel } from '../../design-system/ResourceDetailsPanel'
import { useInformationContext } from './useInformationContext'
import { InformationTaskList } from './InformationTaskList'
import { InformationTaskDetails } from './InformationTaskDetails'
import { useInformationTests } from './useInformationTests'

export default function InformationAutomationsView({ canMutate }: { canMutate: boolean }) {
  const { api, userId } = useInformationContext()
  const cache = useQueryClient()
  const key = ['information-rules', userId]
  const query = useInfiniteQuery({ queryKey: key, initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => api.informationRules(pageParam, signal),
    getNextPageParam: (page) => page.next_offset ?? undefined, refetchInterval: 15000 })
  const [selected, setSelected] = useState<string | null>(null)
  const tests = useInformationTests()
  const busy = useRef(false)
  const trigger = useRef<HTMLElement | null>(null)
  const rules = query.data?.pages.flatMap((page) => page.items) || []
  const rule = rules.find((item) => item.id === selected)
  const restore = tests.restore
  useEffect(() => { if (rule) void restore(rule.id, rule.version) }, [restore, rule])
  const close = () => { if (!busy.current) { setSelected(null); (trigger.current?.isConnected ? trigger.current : document.getElementById(`information-task-${selected}`) || document.getElementById('information-task-search'))?.focus() } }
  const select = (id: string) => { if (!busy.current) { trigger.current = document.activeElement as HTMLElement; setSelected(id) } }
  return <div className="flex h-full min-h-0 min-w-0">
    <div className="quiet-scroll-region min-h-0 min-w-0 flex-1 overflow-y-auto px-4 pb-6 pt-[var(--inteliscope-size-page-header)] min-[768px]:px-6"><div className="mx-auto grid max-w-4xl gap-4">
      <div className="flex flex-wrap items-center gap-2"><p className="type-body min-w-0 flex-1 text-muted">安排任务，让关注的信息按时送达。</p>
        <RefreshButton variant="ghost" pending={query.isFetching} aria-label="刷新提醒列表" onPress={() => query.refetch()} />
        <Button isDisabled={!canMutate} onPress={() => select('new')}>新建自动化</Button></div>
      {!canMutate && <p className="type-meta text-muted">当前为只读模式，可以查看任务与运行记录。</p>}
      {query.isError && <p role="alert">提醒列表读取失败，请重试。已加载任务仍可查看。</p>}
      {query.isPending && <p role="status">正在读取个人提醒…</p>}
      <InformationTaskList rules={rules} selected={selected} onSelect={select} loading={query.isPending} hasMore={query.hasNextPage}
        testStatuses={Object.fromEntries(rules.map((item) => [item.id, tests.session(item.id, item.version).phase]))} />
      {query.hasNextPage && <StableAsyncButton pending={query.isFetchingNextPage} pendingContent="正在加载…" onPress={() => query.fetchNextPage()}>加载更多提醒</StableAsyncButton>}
      <Link to="/agent/automations?advanced=cron" className="type-meta text-muted underline">高级 Gateway Cron</Link>
    </div></div>
    <ResourceDetailsPanel open={Boolean(selected)} onClose={close} userId={userId} title={selected === 'new' ? '新建自动化' : rule?.config.name || '任务详情'}>
      <InformationTaskDetails key={selected || 'empty'} rule={rule} creating={selected === 'new'} canMutate={canMutate} onClose={close}
        testSession={rule ? tests.session(rule.id, rule.version) : undefined}
        onTestSelect={(value) => { if (rule) tests.select(rule.id, rule.version, value) }}
        onTestStart={async () => { if (rule) await tests.start(rule.id, rule.version) }}
        onBusyChange={(value) => { busy.current = value }} onSaved={async (saved) => {
          await cache.invalidateQueries({ queryKey: key }); if (selected === 'new') setSelected(saved.id)
        }} />
    </ResourceDetailsPanel>
  </div>
}
