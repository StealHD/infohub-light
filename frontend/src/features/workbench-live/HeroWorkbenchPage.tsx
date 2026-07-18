import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { Button, Card, Chip, Icons, ListBox, NumberField, Popover, Select, Skeleton, Switch } from '../../design-system'
import { useAppContext } from '../../app/AppContext'
import { filterFeedItems, sortWorkbenchItems } from '../feed/feedModel'
import {
  FEED_PREFERENCE_CHANGED_EVENT,
  readFeedPreference,
  writeFeedPreference,
  type FeedPreference,
} from '../feed/feedPreference'
import { useOptimisticItemState } from '../feed/useOptimisticItemState'
import { useWorkbenchAgentContext } from './workbenchAgentContext'
import { VirtualFeed } from './VirtualFeed'
import { workbenchRefreshRequestEvent } from './workbenchRefresh'
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
  const sourceQuerySettled = kind === 'feed'
    ? feedQuery.isSuccess && !feedQuery.isFetching
    : kind === 'saved'
      ? savedQuery.isSuccess && !savedQuery.isFetching
      : historyQuery.isSuccess && !historyQuery.isFetching
  const selectedInSource = Boolean(selectedId && sourceItems.some((item) => item.id === selectedId))
  const detailQuery = useQuery({
    queryKey: queryKeys.feedItem(user.id, selectedId || ''),
    queryFn: ({ signal }) => api.feedItem(selectedId!, signal),
    enabled: Boolean(selectedId && sourceQuerySettled && !selectedInSource),
    retry: false,
  })
  const stateMutation = useOptimisticItemState({ api, user, beginAction, isActionCurrent, publishFeedback: false })

  useEffect(() => {
    if (!params.has('mode')) return
    navigate({ pathname: location.pathname, search: cleanLegacyModeSearch(location.search) }, { replace: true })
  }, [location.pathname, location.search, navigate, params])

  useEffect(() => {
    const syncPreference = (event: Event) => {
      if ((event as CustomEvent<{ userId?: string }>).detail?.userId !== user.id) return
      setPreferenceState({ userId: user.id, value: readFeedPreference(user.id) })
    }
    window.addEventListener(FEED_PREFERENCE_CHANGED_EVENT, syncPreference)
    return () => window.removeEventListener(FEED_PREFERENCE_CHANGED_EVENT, syncPreference)
  }, [user.id])

  useEffect(() => {
    if (!detailQuery.isError || !(detailQuery.error instanceof ApiError) || detailQuery.error.status !== 404 || !sourceQuerySettled || selectedInSource) return
    const next = new URLSearchParams(params)
    next.delete('item')
    navigate({ pathname: location.pathname, search: next.toString() ? `?${next.toString()}` : '' }, {
      replace: true,
      state: { ...(location.state as object | null), staleItem: true },
    })
  }, [detailQuery.error, detailQuery.isError, location.pathname, location.state, navigate, params, selectedInSource, sourceQuerySettled])

  const mergedItems = useMemo(() => mergeDeepLinkedItem(sourceItems, detailQuery.data), [detailQuery.data, sourceItems])
  const orderedItems = useMemo(
    () => kind === 'feed' ? sortWorkbenchItems(mergedItems, preference.order) : mergedItems,
    [kind, mergedItems, preference.order],
  )
  const filteredItems = useMemo(() => {
    const matching = filterFeedItems(
      orderedItems.filter((item) => !item.user_state?.dismissed),
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
    const pinned = orderedItems.filter((item) => matchingIds.has(item.id) || item.id === selectedId)
    return filterFeedItems(pinned, { query: '', unreadFirst: preference.unreadFirst })
  }, [detailQuery.data, orderedItems, preference, query, selectedId])
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
  const quietStudio = kind === 'feed'
  const activeFilterCount = [
    preference.unreadFirst,
    preference.source,
    preference.channel,
    preference.topic,
    preference.minScore !== undefined,
  ].filter(Boolean).length

  function updatePreference(patch: Partial<FeedPreference>) {
    const next = { ...preference, ...patch }
    window.dispatchEvent(new Event(workbenchRefreshRequestEvent))
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
    <div className={quietStudio
      ? 'shrink-0 bg-background/95 px-3 py-2 supports-[backdrop-filter:blur(1px)]:backdrop-blur-md sm:px-5'
      : 'flex min-h-[48px] flex-wrap items-center gap-2 border-b border-separator px-3 py-2 sm:px-5'}>
      <div
        data-testid={quietStudio ? 'feed-view-bar' : undefined}
        className={quietStudio
          ? 'mx-auto flex min-h-10 w-full max-w-[820px] items-center gap-1 rounded-xl border border-separator/80 bg-surface-secondary/70 px-2.5'
          : 'flex w-full flex-wrap items-center gap-2'}
      >
        <span className="mr-auto text-xs text-muted">{quietStudio ? `${cards.length} 条内容` : `旧内容在上，最新内容在下 · ${cards.length} 条`}</span>
        {!quietStudio && <Chip size="sm" color="accent" variant="soft"><Chip.Label>全部</Chip.Label></Chip>}
        {!quietStudio && preference.unreadFirst && <Chip size="sm" variant="soft"><Chip.Label>未读优先</Chip.Label></Chip>}
        {quietStudio && <Button
          size="sm"
          variant="ghost"
          aria-label={preference.order === 'newest' ? '最新优先' : '最旧优先'}
          onPress={() => updatePreference({ order: preference.order === 'newest' ? 'oldest' : 'newest' })}
        ><Icons.ArrowDownUp size={14} aria-hidden="true" />{preference.order === 'newest' ? '最新优先' : '最旧优先'}</Button>}
        <Popover>
          <Popover.Trigger aria-label="筛选信息流" className="inline-flex min-h-8 items-center gap-1 rounded-lg px-2 text-sm text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus">
          <Icons.SlidersHorizontal size={15} aria-hidden="true" />筛选
          {quietStudio && activeFilterCount > 0 && <span aria-label={`已启用 ${activeFilterCount} 项筛选`} className="rounded-md bg-accent/15 px-1.5 text-xs text-accent">{activeFilterCount}</span>}
          </Popover.Trigger>
          <Popover.Content placement="bottom end" className="z-30 w-[min(340px,calc(100vw-24px))] p-0">
            <Popover.Dialog aria-label="信息流筛选" className="grid gap-3 p-4">
              <Popover.Heading className="font-semibold">信息流筛选</Popover.Heading>
              <Switch isSelected={preference.unreadFirst} onChange={(value) => updatePreference({ unreadFirst: value })}>未读优先</Switch>
              <FilterSelect label="来源" value={preference.source} onChange={(value) => updatePreference({ source: value })} options={[{ id: '', label: '全部来源' }, ...sources.map(([id, label]) => ({ id, label }))]} />
              <FilterSelect label="频道" value={preference.channel} onChange={(value) => updatePreference({ channel: value })} options={[{ id: '', label: '全部频道' }, ...channels.map((value) => ({ id: value, label: value }))]} />
              <FilterSelect label="主题" value={preference.topic} onChange={(value) => updatePreference({ topic: value })} options={[{ id: '', label: '全部主题' }, ...topics.map((value) => ({ id: value, label: value }))]} />
              <NumberField aria-label="最低分" value={preference.minScore} minValue={0} maxValue={10} step={0.5} onChange={(value) => updatePreference({ minScore: value ?? undefined })}>
                <NumberField.Group><NumberField.Input /></NumberField.Group>
              </NumberField>
              <Button size="sm" variant="ghost" onPress={() => updatePreference({ unreadFirst: false, source: '', channel: '', topic: '', minScore: undefined })}>清除筛选</Button>
            </Popover.Dialog>
          </Popover.Content>
        </Popover>
      </div>
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
      visualVariant={kind === 'feed' ? 'quiet-studio' : 'collection'}
      freshEdge={kind === 'feed' && preference.order === 'newest' ? 'start' : 'end'}
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

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: Array<{ id: string; label: string }>; onChange: (value: string) => void }) {
  return <Select aria-label={label} selectedKey={value} onSelectionChange={(key) => key !== null && onChange(String(key))}>
    <Select.Trigger><Select.Value /><Select.Indicator><Icons.ChevronDown size={15} /></Select.Indicator></Select.Trigger>
    <Select.Popover><ListBox items={options}>{(item) => <ListBox.Item id={item.id} textValue={item.label}>{item.label}</ListBox.Item>}</ListBox></Select.Popover>
  </Select>
}
