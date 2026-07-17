import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { Button, Card, Chip, Icons, Popover, Skeleton, Switch } from '../../design-system'
import { useAppContext } from '../../app/AppContext'
import { filterFeedItems } from '../feed/feedModel'
import { readFeedPreference, writeFeedPreference, type FeedPreference } from '../feed/feedPreference'
import { useOptimisticItemState } from '../feed/useOptimisticItemState'
import { useWorkbenchAgentContext } from './workbenchAgentContext'
import { VirtualFeed } from './VirtualFeed'
import {
  cleanLegacyModeSearch,
  mergeDeepLinkedItem,
  selectWorkbenchSourceItems,
  toWorkbenchCardModel,
  type WorkbenchKind,
} from './workbenchModel'

export function HeroWorkbenchPage({ kind }: { kind: WorkbenchKind }) {
  const { api, user, query, beginAction, isActionCurrent } = useAppContext()
  const agent = useWorkbenchAgentContext()
  const location = useLocation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [preferenceState, setPreferenceState] = useState(() => ({ userId: user.id, value: readFeedPreference(user.id) }))
  const deepLinkNotice = Boolean((location.state as { staleItem?: boolean } | null)?.staleItem)
  const preference = preferenceState.userId === user.id ? preferenceState.value : readFeedPreference(user.id)
  const selectedId = params.get('item') ?? undefined
  const [initialNavigationTargetId] = useState(selectedId)
  const feedQuery = useQuery({
    queryKey: queryKeys.feed(user.id, { hideDismissed: false, unreadFirst: false }),
    queryFn: ({ signal }) => api.latestFeed(signal),
    enabled: kind === 'feed',
  })
  const savedQuery = useQuery({ queryKey: queryKeys.saved(user.id), queryFn: ({ signal }) => api.savedFeed(200, 0, signal), enabled: kind === 'saved' })
  const historyQuery = useQuery({ queryKey: queryKeys.history(user.id), queryFn: ({ signal }) => api.historyFeed(signal), enabled: kind === 'history' })
  const sourceItems = useMemo(() => selectWorkbenchSourceItems(kind, {
    snapshot: feedQuery.data,
    saved: savedQuery.data,
    history: historyQuery.data,
  }), [feedQuery.data, historyQuery.data, kind, savedQuery.data])
  const sourceQuerySucceeded = kind === 'feed' ? feedQuery.isSuccess : kind === 'saved' ? savedQuery.isSuccess : historyQuery.isSuccess
  const selectedInSource = Boolean(selectedId && sourceItems.some((item) => item.id === selectedId))
  const detailQuery = useQuery({
    queryKey: queryKeys.feedItem(user.id, selectedId || ''),
    queryFn: ({ signal }) => api.feedItem(selectedId!, signal),
    enabled: Boolean(selectedId),
    retry: false,
  })
  const stateMutation = useOptimisticItemState({ api, user, beginAction, isActionCurrent, publishFeedback: false })

  useEffect(() => {
    if (!params.has('mode')) return
    navigate({ pathname: location.pathname, search: cleanLegacyModeSearch(location.search) }, { replace: true })
  }, [location.pathname, location.search, navigate, params])

  useEffect(() => {
    if (!detailQuery.isError || !(detailQuery.error instanceof ApiError) || detailQuery.error.status !== 404 || !sourceQuerySucceeded || selectedInSource) return
    const next = new URLSearchParams(params)
    next.delete('item')
    navigate({ pathname: location.pathname, search: next.toString() ? `?${next.toString()}` : '' }, {
      replace: true,
      state: { ...(location.state as object | null), staleItem: true },
    })
  }, [detailQuery.error, detailQuery.isError, location.pathname, location.state, navigate, params, selectedInSource, sourceQuerySucceeded])

  const mergedItems = useMemo(() => mergeDeepLinkedItem(sourceItems, detailQuery.data), [detailQuery.data, sourceItems])
  const filteredItems = useMemo(() => {
    const matching = filterFeedItems(
      mergedItems.filter((item) => !item.user_state?.dismissed),
      {
        query,
        unreadFirst: preference.unreadFirst,
        sourceId: preference.source || undefined,
        channel: preference.channel || undefined,
        topic: preference.topic || undefined,
        minScore: preference.minScore,
      },
    )
    if (!selectedId || !detailQuery.data) return matching
    const matchingIds = new Set(matching.map((item) => item.id))
    return mergedItems.filter((item) => matchingIds.has(item.id) || item.id === selectedId)
  }, [detailQuery.data, mergedItems, preference, query, selectedId])
  const cards = useMemo(() => filteredItems.map(toWorkbenchCardModel), [filteredItems])
  const sourceItemIds = useMemo(() => mergedItems.map((item) => item.id), [mergedItems])
  const sources = useMemo(() => Array.from(new Map(sourceItems.map((item) => {
    const value = item.presentation?.source.id || item.source_id || item.source || ''
    return [value, item.presentation?.source?.name || item.source || item.source_type || value] as const
  }).filter(([value]) => Boolean(value))).entries()), [sourceItems])
  const channels = useMemo(() => Array.from(new Set(sourceItems.map((item) => item.presentation?.taxonomy?.channel || item.channel || item.category).filter(Boolean) as string[])).sort(), [sourceItems])
  const topics = useMemo(() => Array.from(new Set(sourceItems.flatMap((item) => item.presentation?.taxonomy?.topics ?? item.topics ?? item.tags ?? []))).sort(), [sourceItems])
  const loading = feedQuery.isLoading || savedQuery.isLoading || historyQuery.isLoading
  const loadError = feedQuery.error || savedQuery.error || historyQuery.error

  function updatePreference(patch: Partial<FeedPreference>) {
    const next = { ...preference, ...patch }
    setPreferenceState({ userId: user.id, value: next })
    writeFeedPreference(user.id, next)
  }

  function toggleExpanded(id: string) {
    const next = new URLSearchParams(params)
    if (selectedId === id) next.delete('item')
    else next.set('item', id)
    setParams(next)
  }

  return <section aria-label="信息流工作区" className="flex h-full min-h-0 flex-col">
    <div className="flex min-h-[48px] flex-wrap items-center gap-2 border-b border-separator px-3 py-2 sm:px-5">
      <span className="text-xs text-muted">旧内容在上，最新内容在下 · {cards.length} 条</span>
      <Chip size="sm" color="accent" variant="soft"><Chip.Label>全部</Chip.Label></Chip>
      {preference.unreadFirst && <Chip size="sm" variant="soft"><Chip.Label>未读优先</Chip.Label></Chip>}
      <Popover>
        <Popover.Trigger aria-label="筛选信息流" className="flex min-h-8 items-center gap-2 rounded-xl px-3 text-sm text-muted hover:bg-default hover:text-foreground">
          <Icons.SlidersHorizontal size={15} />筛选
        </Popover.Trigger>
        <Popover.Content placement="bottom end" className="w-[min(340px,calc(100vw-24px))]">
          <Popover.Dialog className="grid gap-3 p-4">
            <Popover.Heading className="font-semibold">信息流筛选</Popover.Heading>
            <Switch isSelected={preference.unreadFirst} onChange={(value) => updatePreference({ unreadFirst: value })}>未读优先</Switch>
            <label className="grid gap-1 text-sm">来源
              <select aria-label="来源" value={preference.source} onChange={(event) => updatePreference({ source: event.target.value })} className="min-h-10 rounded-xl border border-field-border bg-field-background px-3">
                <option value="">全部来源</option>{sources.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-sm">频道
              <select aria-label="频道" value={preference.channel} onChange={(event) => updatePreference({ channel: event.target.value })} className="min-h-10 rounded-xl border border-field-border bg-field-background px-3">
                <option value="">全部频道</option>{channels.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-sm">主题
              <select aria-label="主题" value={preference.topic} onChange={(event) => updatePreference({ topic: event.target.value })} className="min-h-10 rounded-xl border border-field-border bg-field-background px-3">
                <option value="">全部主题</option>{topics.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label className="grid gap-1 text-sm">最低分
              <input aria-label="最低分" type="number" min="0" max="10" step="0.5" value={preference.minScore ?? ''} onChange={(event) => updatePreference({ minScore: event.target.value === '' ? undefined : Number(event.target.value) })} className="min-h-10 rounded-xl border border-field-border bg-field-background px-3" />
            </label>
            <Button size="sm" variant="ghost" onPress={() => updatePreference({ unreadFirst: false, source: '', channel: '', topic: '', minScore: undefined })}>清除筛选</Button>
          </Popover.Dialog>
        </Popover.Content>
      </Popover>
    </div>

    {deepLinkNotice && <div role="status" className="flex items-center gap-2 border-b border-separator px-4 py-2 text-sm text-muted"><span className="flex-1">这条信息已不可用，已移除失效链接；信息流仍可继续使用。</span><Button size="sm" variant="ghost" isIconOnly aria-label="关闭提示" onPress={() => navigate({ pathname: location.pathname, search: location.search }, { replace: true, state: { ...(location.state as object | null), staleItem: false } })}><Icons.X size={15} /></Button></div>}
    {stateMutation.isError && <div role="alert" className="flex items-center gap-2 border-b border-separator px-4 py-2 text-sm text-muted">
      <span className="flex-1">{stateMutation.error instanceof ApiError ? `${stateMutation.error.message}，状态已恢复。` : '阅读状态保存失败，状态已恢复。'}</span>
      <Button size="sm" variant="ghost" isIconOnly aria-label="关闭操作错误" onPress={() => stateMutation.reset()}><Icons.X size={15} /></Button>
    </div>}
    {detailQuery.isError && !(detailQuery.error instanceof ApiError && detailQuery.error.status === 404) && <div role="alert" className="border-b border-separator px-4 py-2 text-sm text-muted">无法读取深链条目；信息流仍可继续使用。</div>}
    {loading && <div aria-label="正在读取信息流" className="grid gap-3 p-5">{Array.from({ length: 5 }, (_, index) => <Skeleton key={index} className="h-40 rounded-2xl" />)}</div>}
    {loadError && <Card variant="transparent" className="m-5 p-5" role="alert"><Card.Title>信息流加载失败</Card.Title><Card.Description>{loadError instanceof ApiError ? loadError.message : '请稍后重试。'}</Card.Description></Card>}
    {!loading && !loadError && cards.length === 0 && <Card variant="transparent" className="m-auto p-6 text-center"><Card.Title>没有匹配的信息</Card.Title><Card.Description>清除筛选或等待下一次更新。</Card.Description></Card>}
    {!loading && !loadError && cards.length > 0 && <VirtualFeed
      cards={cards}
      sourceItemIds={sourceItemIds}
      expandedId={selectedId}
      navigationTargetId={deepLinkNotice ? undefined : initialNavigationTargetId}
      contextIds={agent.draft.itemIds}
      readonly={user.role === 'viewer'}
      onToggleExpanded={toggleExpanded}
      onToggleSaved={(id, saved) => stateMutation.mutateItem(id, { is_saved: saved })}
      onToggleContext={agent.toggleItem}
      onItemAction={(id, action, value) => stateMutation.mutateItem(id, { [action]: value })}
    />}
  </section>
}
