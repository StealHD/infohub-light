import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import {
  actionToast,
  Button,
  CalmSkeleton,
  EmptyState,
  Icons,
  ListBox,
  LoadingReveal,
  PageFrame,
  Popover,
  RemovableTag,
  SearchField,
  Select,
  StatusNotice,
  Switch,
  Tooltip,
  TooltipTriggerButton,
  ViewBar,
  anchoredTooltipProps,
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
import { sourceMatchesSubscriptionVisibility } from '../subscriptions/subscriptionModel'
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
  const { api, user, query, setQuery, activity, refresh, reloadFeed, beginAction, isActionCurrent } = useAppContext()
  const agent = useWorkbenchAgentContext()
  const location = useLocation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [preferenceState, setPreferenceState] = useState(() => ({ userId: user.id, value: readFeedPreference(user.id) }))
  const [collectionSearchOpen, setCollectionSearchOpen] = useState(false)
  const reloadButtonRef = useRef<HTMLButtonElement>(null)
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
  const sourceCatalogQuery = useQuery({
    queryKey: queryKeys.sources(user.id),
    queryFn: ({ signal }) => api.sources(user.role === 'owner' || user.role === 'admin', signal),
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
  const stateMutationError = stateMutation.error
  const stateMutationFailed = stateMutation.isError
  const stateMutationToken = stateMutation.variables?.token
  const resetStateMutation = stateMutation.reset

  useEffect(() => {
    if (!stateMutationFailed) return
    if (!stateMutationToken || !isActionCurrent(stateMutationToken)) {
      resetStateMutation()
      return
    }
    const message = stateMutationError instanceof ApiError
      ? `${stateMutationError.message}，状态已恢复。`
      : '阅读状态保存失败，状态已恢复。'
    actionToast.danger('操作未保存', { description: message })
    resetStateMutation()
  }, [isActionCurrent, resetStateMutation, stateMutationError, stateMutationFailed, stateMutationToken])

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
  const sourceScopeRequested = kind === 'feed' && preference.subscriptionScope !== 'all'
  const allowedSourceIds = useMemo(() => {
    if (!sourceScopeRequested || !sourceCatalogQuery.data) return undefined
    const visibility = preference.subscriptionScope === 'public' ? 'public' : 'private'
    return new Set(sourceCatalogQuery.data.sources
      .filter((source) => sourceMatchesSubscriptionVisibility(source, visibility))
      .map((source) => source.id))
  }, [preference.subscriptionScope, sourceCatalogQuery.data, sourceScopeRequested])
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
        allowedSourceIds,
        now: localDayReference,
      },
    )
    if (!selectedId || !detailQuery.data) return matching
    const matchingIds = new Set(matching.map((item) => item.id))
    const pinned = orderedItems.filter((item) => matchingIds.has(item.id) || item.id === selectedId)
    return filterFeedItems(pinned, { query: '', unreadFirst: preference.unreadFirst })
  }, [allowedSourceIds, detailQuery.data, kind, localDayReference, orderedItems, preference, query, selectedId])
  const cards = useMemo(() => filteredItems.map(toWorkbenchCardModel), [filteredItems])
  const sourceItemIds = useMemo(() => mergedItems.map((item) => item.id), [mergedItems])
  const sources = useMemo(() => Array.from(new Map(sourceItems.map((item) => {
    const value = item.presentation?.source.id || item.source_id || item.source || ''
    return [value, item.presentation?.source?.name || item.source || item.source_type || value] as const
  }).filter(([value]) => Boolean(value))).entries()), [sourceItems])
  const channels = useMemo(() => Array.from(new Set(sourceItems.map((item) => item.presentation?.taxonomy?.channel || item.channel || item.category).filter(Boolean) as string[])).sort(), [sourceItems])
  const topics = useMemo(() => Array.from(new Set(sourceItems.flatMap((item) => item.presentation?.taxonomy?.topics ?? item.topics ?? item.tags ?? []))).sort(), [sourceItems])
  const loading = feedQuery.isLoading || savedQuery.isLoading || historyQuery.isLoading || (sourceScopeRequested && sourceCatalogQuery.isLoading)
  const loadError = (feedQuery.data ? null : feedQuery.error) || savedQuery.error || historyQuery.error || (sourceScopeRequested ? sourceCatalogQuery.error : null)
  const collectionRoute = kind !== 'feed'
  const updating = activity.state === 'queued' || activity.state === 'running'
  const reloading = kind === 'feed' && feedQuery.isFetching
  const activeFilterCount = [
    preference.unreadFirst,
    preference.source,
    preference.channel,
    preference.topic,
    kind === 'feed' && preference.dateScope === 'today',
    kind === 'feed' && preference.subscriptionScope !== 'all',
  ].filter(Boolean).length
  const collectionSearchVisible = collectionSearchOpen || Boolean(query)
  const hasActiveConstraints = Boolean(query) || activeFilterCount > 0
  const activeFilterSummaries = [
    ...(query ? [{ id: 'query', label: `搜索：${query}`, clear: () => setQuery('') }] : []),
    ...(preference.unreadFirst ? [{ id: 'unread', label: '未读优先', clear: () => updatePreference({ unreadFirst: false }) }] : []),
    ...(preference.source ? [{ id: 'source', label: `来源：${sources.find(([id]) => id === preference.source)?.[1] ?? preference.source}`, clear: () => updatePreference({ source: '' }) }] : []),
    ...(preference.channel ? [{ id: 'channel', label: `频道：${preference.channel}`, clear: () => updatePreference({ channel: '' }) }] : []),
    ...(preference.topic ? [{ id: 'topic', label: `主题：${preference.topic}`, clear: () => updatePreference({ topic: '' }) }] : []),
    ...(kind === 'feed' && preference.dateScope === 'today' ? [{ id: 'date', label: '仅今天', clear: () => updatePreference({ dateScope: 'all' }) }] : []),
    ...(kind === 'feed' && preference.subscriptionScope !== 'all' ? [{ id: 'scope', label: preference.subscriptionScope === 'public' ? '公共订阅' : '私人订阅', clear: () => updatePreference({ subscriptionScope: 'all' }) }] : []),
  ]

  function updatePreference(patch: Partial<FeedPreference>, scrollPolicy: 'preserve' | 'reset-top' = 'preserve') {
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

  function updateFeed() {
    window.dispatchEvent(new Event(workbenchRefreshRequestEvent))
    refresh()
  }

  async function reloadFeedData() {
    const token = beginAction()
    window.dispatchEvent(new Event(workbenchRefreshRequestEvent))
    try {
      await reloadFeed()
    } catch (caught) {
      if (!isActionCurrent(token)) return
      actionToast.danger('信息流刷新失败', {
        description: caught instanceof ApiError ? caught.message : '无法加载最新信息流，请稍后重试。',
      })
    }
  }

  return <section aria-label="信息流工作区" data-feed-blank-region className="flex h-full min-h-0 flex-col">
    <div className="shrink-0 bg-background/95 px-3 py-2 supports-[backdrop-filter:blur(1px)]:backdrop-blur-md sm:px-5">
      <PageFrame width="reading">
        <div data-testid={collectionRoute ? 'collection-view-bar' : 'feed-view-bar'}>
        <ViewBar>
        <LoadingReveal
          loading={loading}
          label="正在读取内容数量"
          name="feed-count"
          className="mr-auto min-h-4 min-w-16 shrink-0"
          skeleton={<span data-feed-count-skeleton><CalmSkeleton className="h-4 w-16 rounded-md" /></span>}
        ><span className="type-control min-w-16 shrink-0 whitespace-nowrap text-muted">{cards.length} 条内容</span></LoadingReveal>
        {collectionRoute && <div className={`${collectionSearchVisible ? 'flex' : 'hidden'} min-w-0 flex-1 sm:flex`}>
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
          aria-label={query ? '清除搜索' : collectionSearchOpen ? '收起搜索' : '搜索信息流'}
          aria-expanded={collectionSearchVisible}
          onPress={() => {
            if (query) {
              setQuery('')
              setCollectionSearchOpen(false)
              return
            }
            setCollectionSearchOpen((value) => !value)
          }}
        >{query ? <Icons.X size={14} aria-hidden="true" /> : <Icons.Search size={14} aria-hidden="true" />}</Button>}
        <Button
          size="sm"
          variant="ghost"
          className="type-control"
          aria-label={preference.sortBasis === 'ingested' ? '按入库时间排序' : '按发布时间排序'}
          onPress={() => updatePreference({ sortBasis: preference.sortBasis === 'ingested' ? 'published' : 'ingested' }, 'reset-top')}
        >{preference.sortBasis === 'ingested' ? <Icons.Database size={14} aria-hidden="true" /> : <Icons.Clock3 size={14} aria-hidden="true" />}
          <span className="hidden min-[640px]:inline">{preference.sortBasis === 'ingested' ? '入库时间' : '发布时间'}</span>
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="type-control"
          aria-label={preference.order === 'newest' ? '最新优先' : '最旧优先'}
          onPress={() => updatePreference({ order: preference.order === 'newest' ? 'oldest' : 'newest' }, 'reset-top')}
        ><Icons.ArrowDownUp size={14} aria-hidden="true" />{preference.order === 'newest' ? '最新优先' : '最旧优先'}</Button>
        {!collectionRoute && <Tooltip delay={500}>
          <TooltipTriggerButton
            ref={reloadButtonRef}
            className="type-control min-h-8 gap-1.5 rounded-lg px-2 text-muted hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
            aria-label="重新载入信息流数据"
            aria-busy={reloading || undefined}
            disabled={reloading}
            onClick={() => void reloadFeedData()}
          ><Icons.RefreshCw size={14} className={reloading ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" /><span className="hidden min-[560px]:inline">重新载入</span></TooltipTriggerButton>
          <Tooltip.Content {...anchoredTooltipProps}>重新载入本地信息流数据</Tooltip.Content>
        </Tooltip>}
        {!collectionRoute && <Tooltip delay={500}>
          <TooltipTriggerButton
            className="type-control min-h-8 gap-1.5 rounded-lg px-2 text-muted hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
            aria-label="获取新内容"
            aria-busy={updating || undefined}
            disabled={updating || user.role === 'viewer'}
            onClick={updateFeed}
          >{updating ? <Icons.LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Icons.Download size={14} aria-hidden="true" />}<span className="hidden min-[560px]:inline">{updating ? '获取中' : '获取新内容'}</span></TooltipTriggerButton>
          <Tooltip.Content {...anchoredTooltipProps}>{user.role === 'viewer' ? '只读账户不可获取新内容' : '触发所有已启用订阅获取新内容'}</Tooltip.Content>
        </Tooltip>}
        <Popover>
          <Popover.Trigger aria-label="筛选信息流" className="type-control inline-flex min-h-8 items-center gap-1 rounded-lg px-2 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus">
          <Icons.SlidersHorizontal size={15} aria-hidden="true" />筛选
          {activeFilterCount > 0 && <span aria-label={`已启用 ${activeFilterCount} 项筛选`} className="type-micro rounded-md bg-accent/15 px-1.5 text-accent">{activeFilterCount}</span>}
          </Popover.Trigger>
          <Popover.Content placement="bottom end" className="z-30 w-[min(340px,calc(100vw-24px))] p-0">
            <Popover.Dialog aria-label="信息流筛选" className="grid gap-3 p-4">
              <Popover.Heading className="type-page-title">信息流筛选</Popover.Heading>
              <Switch isSelected={preference.unreadFirst} onChange={(value) => updatePreference({ unreadFirst: value })}>未读优先</Switch>
              {!collectionRoute && <FilterSelect label="订阅范围" value={preference.subscriptionScope} onChange={(value) => updatePreference({ subscriptionScope: value === 'public' || value === 'private' ? value : 'all' })} options={[{ id: 'all', label: '全部订阅' }, { id: 'public', label: '公共订阅' }, { id: 'private', label: '私人订阅' }]} />}
              <FilterSelect label="来源" value={preference.source} onChange={(value) => updatePreference({ source: value })} options={[{ id: '', label: '全部来源' }, ...sources.map(([id, label]) => ({ id, label }))]} />
              <FilterSelect label="频道" value={preference.channel} onChange={(value) => updatePreference({ channel: value })} options={[{ id: '', label: '全部频道' }, ...channels.map((value) => ({ id: value, label: value }))]} />
              <FilterSelect label="主题" value={preference.topic} onChange={(value) => updatePreference({ topic: value })} options={[{ id: '', label: '全部主题' }, ...topics.map((value) => ({ id: value, label: value }))]} />
              <Button size="sm" variant="ghost" onPress={() => updatePreference({ unreadFirst: false, source: '', channel: '', topic: '', dateScope: 'all', subscriptionScope: 'all' })}>清除筛选</Button>
            </Popover.Dialog>
          </Popover.Content>
        </Popover>
        </ViewBar>
        {activeFilterSummaries.length > 0 && <div aria-label="当前筛选条件" className="mt-2 flex min-w-0 flex-wrap items-center gap-2">
          {activeFilterSummaries.map((filter) => <RemovableTag key={filter.id} label={filter.label} onRemove={filter.clear} />)}
          <Button size="sm" variant="ghost" onPress={() => {
            setQuery('')
            updatePreference({ unreadFirst: false, source: '', channel: '', topic: '', dateScope: 'all', subscriptionScope: 'all' })
          }}>清除全部</Button>
        </div>}
        </div>
      </PageFrame>
    </div>

    {deepLinkNotice && <div role="status" className="type-body flex items-center gap-2 border-b border-separator px-4 py-2 text-muted"><span className="flex-1">这条信息已不可用，已移除失效链接；信息流仍可继续使用。</span><Button size="sm" variant="ghost" isIconOnly aria-label="关闭提示" onPress={() => navigate({ pathname: location.pathname, search: location.search }, { replace: true, state: { ...(location.state as object | null), staleItem: false } })}><Icons.X size={15} /></Button></div>}
    {detailQuery.isError && !selectedInSource && !(detailQuery.error instanceof ApiError && detailQuery.error.status === 404) && <div role="alert" className="type-body border-b border-separator px-4 py-2 text-muted">无法读取深链条目；信息流仍可继续使用。</div>}
    <LoadingReveal
      loading={loading}
      label="正在读取信息流"
      name="feed"
      className="min-h-0 flex-1"
      skeleton={<WorkbenchFeedSkeleton />}
    >
    {loadError ? <PageFrame width="reading" className="p-5"><StatusNotice title="信息流加载失败">{loadError instanceof ApiError ? loadError.message : '请稍后重试。'}</StatusNotice></PageFrame>
      : cards.length === 0 ? <PageFrame width="reading" className="m-auto"><EmptyState
        title={hasActiveConstraints
          ? '没有符合当前条件的信息'
          : kind === 'saved'
            ? '还没有收藏'
            : kind === 'history'
              ? '还没有阅读记录'
              : '信息流还是空的'}
        description={hasActiveConstraints
          ? '清除搜索或筛选后再试。'
          : kind === 'saved'
            ? '在信息流中收藏的内容会出现在这里。'
            : kind === 'history'
              ? '打开过的内容会保留在这里。'
              : '先订阅来源，再获取一次新内容。'}
        actions={hasActiveConstraints
          ? <>
            {query && <Button size="sm" variant="ghost" onPress={() => setQuery('')}>清除搜索</Button>}
            {activeFilterCount > 0 && <Button size="sm" variant="ghost" onPress={() => updatePreference({ unreadFirst: false, source: '', channel: '', topic: '', dateScope: 'all', subscriptionScope: 'all' })}>清除筛选</Button>}
          </>
          : kind === 'feed'
            ? <>
              <Button size="sm" variant="ghost" onPress={() => navigate('/subscriptions')}>订阅来源</Button>
              {user.role !== 'viewer' && <Button size="sm" onPress={updateFeed}>获取新内容</Button>}
            </>
            : <Button size="sm" onPress={() => navigate('/feed')}>返回信息流</Button>}
      /></PageFrame>
      : <VirtualFeed
      freshEdge={preference.order === 'newest' ? 'start' : 'end'}
      resetToTopKey={`${preference.sortBasis}:${preference.order}`}
      cards={cards}
      sourceItemIds={sourceItemIds}
      expandedId={selectedId}
      navigationTargetId={deepLinkNotice ? undefined : initialNavigationTargetId}
      contextIds={agent.draft.items.map((item) => item.articleId)}
      detailLoading={detailQuery.isFetching}
      detailError={detailQuery.isError && selectedInSource}
      readonly={user.role === 'viewer'}
      onToggleExpanded={toggleExpanded}
      onToggleSaved={(id, saved) => {
        stateMutation.mutateItem(id, { is_saved: saved })
        if (!saved) {
          actionToast.info('已取消收藏', {
            description: '内容已从收藏列表移除。',
            timeout: 8_000,
            retryLabel: '撤销',
            onRetry: () => stateMutation.mutateItem(id, { is_saved: true }),
          })
        }
      }}
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
      onItemAction={(id, value) => {
        stateMutation.mutateItem(id, { dismissed: value })
        if (value) {
          actionToast.info('已忽略这条内容', {
            description: '8 秒内可以撤销，内容会回到原来的排序位置。',
            timeout: 8_000,
            retryLabel: '撤销',
            onRetry: () => stateMutation.mutateItem(id, { dismissed: false }),
          })
        }
      }}
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
