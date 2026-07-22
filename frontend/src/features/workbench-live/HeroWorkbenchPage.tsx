import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import {
  Button,
  CalmSkeleton,
  EmptyState,
  Icons,
  ListBox,
  LoadingReveal,
  PageFrame,
  Popover,
  SearchField,
  Select,
  StatusNotice,
  Switch,
  ViewBar,
} from '../../design-system'
import { useAppContext } from '../../app/AppContext'
import { filterFeedItems, sortWorkbenchItems } from '../feed/feedModel'
import { useLocalDayReference } from '../feed/useLocalDayReference'
import {
  FEED_PREFERENCE_CHANGED_EVENT,
  readFeedPreference,
  writeFeedPreference,
  type FeedPreference,
} from '../feed/feedPreference'
import { useOptimisticItemState } from '../feed/useOptimisticItemState'
import { useWorkbenchAgentContext } from './workbenchAgentContext'
import { VirtualFeed } from './VirtualFeed'
import { WorkbenchFeedSkeleton } from './WorkbenchLoadingState'
import { workbenchRefreshRequestEvent } from './workbenchRefresh'
import {
  cleanLegacyModeSearch,
  mergeDeepLinkedItem,
  selectWorkbenchSourceItems,
  toWorkbenchCardModel,
  workbenchSourceLabels,
  type WorkbenchKind,
} from './workbenchModel'

export function HeroWorkbenchPage({ kind }: { kind: WorkbenchKind }) {
  const { api, user, query, setQuery, activity, refresh, beginAction, isActionCurrent } = useAppContext()
  const agent = useWorkbenchAgentContext()
  const location = useLocation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [preferenceState, setPreferenceState] = useState(() => ({ userId: user.id, value: readFeedPreference(user.id) }))
  const [collectionSearchOpen, setCollectionSearchOpen] = useState(false)
  const localDayReference = useLocalDayReference()
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
    enabled: Boolean(selectedId && sourceQuerySettled),
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
    () => sortWorkbenchItems(mergedItems, preference.order, preference.sortBasis),
    [mergedItems, preference.order, preference.sortBasis],
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
        dateScope: kind === 'feed' ? preference.dateScope : 'all',
        now: localDayReference,
      },
    )
    if (!selectedId || !detailQuery.data) return matching
    const matchingIds = new Set(matching.map((item) => item.id))
    const pinned = orderedItems.filter((item) => matchingIds.has(item.id) || item.id === selectedId)
    return filterFeedItems(pinned, { query: '', unreadFirst: preference.unreadFirst })
  }, [detailQuery.data, kind, localDayReference, orderedItems, preference, query, selectedId])
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
  const collectionRoute = kind !== 'feed'
  const refreshing = activity.state === 'queued' || activity.state === 'running'
  const activeFilterCount = [
    preference.unreadFirst,
    preference.source,
    preference.channel,
    preference.topic,
    kind === 'feed' && preference.dateScope === 'today',
  ].filter(Boolean).length

  function updatePreference(patch: Partial<FeedPreference>, scrollPolicy: 'preserve' | 'fresh-edge' = 'preserve') {
    const next = { ...preference, ...patch }
    if (scrollPolicy === 'preserve') window.dispatchEvent(new Event(workbenchRefreshRequestEvent))
    setPreferenceState({ userId: user.id, value: next })
    writeFeedPreference(user.id, next)
  }

  function toggleExpanded(id: string) {
    const next = new URLSearchParams(params)
    if (selectedId === id) next.delete('item')
    else next.set('item', id)
    setParams(next)
  }

  function refreshFeed() {
    window.dispatchEvent(new Event(workbenchRefreshRequestEvent))
    refresh()
  }

  return <section aria-label="信息流工作区" className="flex h-full min-h-0 flex-col">
    <div className="shrink-0 bg-background/95 px-3 py-2 supports-[backdrop-filter:blur(1px)]:backdrop-blur-md sm:px-5">
      <PageFrame width="reading">
        <div data-testid={collectionRoute ? 'collection-view-bar' : 'feed-view-bar'}>
        <ViewBar>
        <LoadingReveal
          loading={loading}
          label="正在读取内容数量"
          name="feed-count"
          className="mr-auto min-h-4 w-16 shrink-0"
          skeleton={<span data-feed-count-skeleton><CalmSkeleton className="h-4 w-16 rounded-md" /></span>}
        ><span className="type-control shrink-0 text-muted">{cards.length} 条内容</span></LoadingReveal>
        {collectionRoute && <div className={`${collectionSearchOpen ? 'flex' : 'hidden'} min-w-0 flex-1 sm:flex`}>
          <SearchField aria-label="搜索信息流" value={query} onChange={setQuery} className="min-w-0 flex-1" fullWidth variant="secondary">
            <SearchField.Group className="min-h-8 border-0 bg-transparent shadow-none">
              <SearchField.SearchIcon><Icons.Search size={14} /></SearchField.SearchIcon>
              <SearchField.Input className="type-control" placeholder="搜索标题、来源或主题" />
              <SearchField.ClearButton aria-label="清除搜索" />
            </SearchField.Group>
          </SearchField>
        </div>}
        {collectionRoute && <Button
          size="sm"
          variant="ghost"
          isIconOnly
          className="sm:hidden"
          aria-label={collectionSearchOpen ? '收起搜索' : '搜索信息流'}
          aria-expanded={collectionSearchOpen}
          onPress={() => setCollectionSearchOpen((value) => !value)}
        ><Icons.Search size={14} aria-hidden="true" /></Button>}
        <Button
          size="sm"
          variant="ghost"
          className="type-control"
          aria-label={preference.sortBasis === 'ingested' ? '按入库时间排序' : '按发布时间排序'}
          onPress={() => updatePreference({ sortBasis: preference.sortBasis === 'ingested' ? 'published' : 'ingested' }, 'fresh-edge')}
        >{preference.sortBasis === 'ingested' ? <Icons.Database size={14} aria-hidden="true" /> : <Icons.Clock3 size={14} aria-hidden="true" />}
          <span className="hidden min-[640px]:inline">{preference.sortBasis === 'ingested' ? '入库时间' : '发布时间'}</span>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="type-control"
          aria-label={preference.order === 'newest' ? '最新优先' : '最旧优先'}
          onPress={() => updatePreference({ order: preference.order === 'newest' ? 'oldest' : 'newest' }, 'fresh-edge')}
        ><Icons.ArrowDownUp size={14} aria-hidden="true" />{preference.order === 'newest' ? '最新优先' : '最旧优先'}</Button>
        {!collectionRoute && <Button
          size="sm"
          variant="ghost"
          className="type-control"
          aria-label="更新信息流"
          isDisabled={refreshing || user.role === 'viewer'}
          onPress={refreshFeed}
        ><Icons.RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} aria-hidden="true" /><span className="hidden min-[560px]:inline">{refreshing ? '更新中' : '更新'}</span></Button>}
        <Popover>
          <Popover.Trigger aria-label="筛选信息流" className="type-control inline-flex min-h-8 items-center gap-1 rounded-lg px-2 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus">
          <Icons.SlidersHorizontal size={15} aria-hidden="true" />筛选
          {activeFilterCount > 0 && <span aria-label={`已启用 ${activeFilterCount} 项筛选`} className="type-micro rounded-md bg-accent/15 px-1.5 text-accent">{activeFilterCount}</span>}
          </Popover.Trigger>
          <Popover.Content placement="bottom end" className="z-30 w-[min(340px,calc(100vw-24px))] p-0">
            <Popover.Dialog aria-label="信息流筛选" className="grid gap-3 p-4">
              <Popover.Heading className="type-page-title">信息流筛选</Popover.Heading>
              <Switch isSelected={preference.unreadFirst} onChange={(value) => updatePreference({ unreadFirst: value })}>未读优先</Switch>
              <FilterSelect label="来源" value={preference.source} onChange={(value) => updatePreference({ source: value })} options={[{ id: '', label: '全部来源' }, ...sources.map(([id, label]) => ({ id, label }))]} />
              <FilterSelect label="频道" value={preference.channel} onChange={(value) => updatePreference({ channel: value })} options={[{ id: '', label: '全部频道' }, ...channels.map((value) => ({ id: value, label: value }))]} />
              <FilterSelect label="主题" value={preference.topic} onChange={(value) => updatePreference({ topic: value })} options={[{ id: '', label: '全部主题' }, ...topics.map((value) => ({ id: value, label: value }))]} />
              <Button size="sm" variant="ghost" onPress={() => updatePreference({ unreadFirst: false, source: '', channel: '', topic: '', dateScope: 'all' })}>清除筛选</Button>
            </Popover.Dialog>
          </Popover.Content>
        </Popover>
        </ViewBar>
        </div>
      </PageFrame>
    </div>

    {deepLinkNotice && <div role="status" className="type-body flex items-center gap-2 border-b border-separator px-4 py-2 text-muted"><span className="flex-1">这条信息已不可用，已移除失效链接；信息流仍可继续使用。</span><Button size="sm" variant="ghost" isIconOnly aria-label="关闭提示" onPress={() => navigate({ pathname: location.pathname, search: location.search }, { replace: true, state: { ...(location.state as object | null), staleItem: false } })}><Icons.X size={15} /></Button></div>}
    {stateMutation.isError && <div role="alert" className="type-body flex items-center gap-2 border-b border-separator px-4 py-2 text-muted">
      <span className="flex-1">{stateMutation.error instanceof ApiError ? `${stateMutation.error.message}，状态已恢复。` : '阅读状态保存失败，状态已恢复。'}</span>
      <Button size="sm" variant="ghost" isIconOnly aria-label="关闭操作错误" onPress={() => stateMutation.reset()}><Icons.X size={15} /></Button>
    </div>}
    {detailQuery.isError && !selectedInSource && !(detailQuery.error instanceof ApiError && detailQuery.error.status === 404) && <div role="alert" className="type-body border-b border-separator px-4 py-2 text-muted">无法读取深链条目；信息流仍可继续使用。</div>}
    <LoadingReveal
      loading={loading}
      label="正在读取信息流"
      name="feed"
      className="min-h-0 flex-1"
      skeleton={<WorkbenchFeedSkeleton />}
    >
    {loadError ? <PageFrame width="reading" className="p-5"><StatusNotice title="信息流加载失败">{loadError instanceof ApiError ? loadError.message : '请稍后重试。'}</StatusNotice></PageFrame>
      : cards.length === 0 ? <PageFrame width="reading" className="m-auto"><EmptyState title="没有匹配的信息" description="清除筛选或等待下一次更新。" /></PageFrame>
      : <VirtualFeed
      freshEdge={preference.order === 'newest' ? 'start' : 'end'}
      resetToFreshEdgeKey={`${preference.sortBasis}:${preference.order}`}
      cards={cards}
      sourceItemIds={sourceItemIds}
      expandedId={selectedId}
      navigationTargetId={deepLinkNotice ? undefined : initialNavigationTargetId}
      contextIds={agent.draft.items.map((item) => item.articleId)}
      detailLoading={detailQuery.isFetching}
      detailError={detailQuery.isError && selectedInSource}
      readonly={user.role === 'viewer'}
      onToggleExpanded={toggleExpanded}
      onToggleSaved={(id, saved) => stateMutation.mutateItem(id, { is_saved: saved })}
      onToggleContext={(card) => {
        const alreadySelected = agent.draft.items.some((item) => item.articleId === card.id)
        agent.toggleItem({
          articleId: card.id,
          title: card.displayKind === 'social' ? card.primaryText : card.title,
          sourceName: workbenchSourceLabels(card, true).join(' · ') || card.source,
          publishedAt: card.publishedAt,
        })
        if (!alreadySelected) agent.openComposer()
      }}
      onItemAction={(id, value) => stateMutation.mutateItem(id, { dismissed: value })}
    />}
    </LoadingReveal>
  </section>
}

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: Array<{ id: string; label: string }>; onChange: (value: string) => void }) {
  return <Select aria-label={label} selectedKey={value} onSelectionChange={(key) => key !== null && onChange(String(key))}>
    <Select.Trigger><Select.Value /><Select.Indicator><Icons.ChevronDown size={15} /></Select.Indicator></Select.Trigger>
    <Select.Popover><ListBox items={options}>{(item) => <ListBox.Item id={item.id} textValue={item.label}>{item.label}</ListBox.Item>}</ListBox></Select.Popover>
  </Select>
}
