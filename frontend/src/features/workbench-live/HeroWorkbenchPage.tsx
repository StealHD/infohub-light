import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import {
  actionToast,
  Button,
  CalmSkeleton,
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
  Tabs,
  Tooltip,
  TooltipTriggerButton,
  ViewBar,
  bottomAnchoredTooltipProps,
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
import { readFeedViewMode, writeFeedViewMode, type FeedViewMode } from '../feed/feedViewModePreference'
import { sourceMatchesSubscriptionVisibility } from '../subscriptions/subscriptionModel'
import { useWorkbenchAgentContext } from './workbenchAgentContext'
import { VirtualFeed } from './VirtualFeed'
import { readSourceOverviewViewportAnchor, SourceOverviewFeed, type SourceOverviewViewportAnchor } from './SourceOverviewFeed'
import { buildSourceOverviewSections } from './sourceOverviewModel'
import { WorkbenchFeedSkeleton } from './WorkbenchLoadingState'
import { workbenchRefreshRequestEvent } from './workbenchRefresh'
import {
  builtinFeedEndMessages,
  selectEmptyFeedMessage,
  selectTerminalFeedMessage,
} from './feedEndMessageSession'
import {
  cleanLegacyModeSearch,
  mergeDeepLinkedItem,
  selectWorkbenchSourceItems,
  toWorkbenchCardModel,
  workbenchSourceLabels,
  type WorkbenchKind,
} from './workbenchModel'

function FeedModeLayer({ mode, children }: { mode: FeedViewMode; children: ReactNode }) {
  return <div
    data-feed-mode-layer={mode}
    className="inteliscope-content-reveal flex min-h-0 flex-1 flex-col overflow-hidden"
  >{children}</div>
}

export function HeroWorkbenchPage({ kind }: { kind: WorkbenchKind }) {
  const { api, user, query, setQuery, activity, refresh, reloadFeed, beginAction, isActionCurrent } = useAppContext()
  const queryClient = useQueryClient()
  const agent = useWorkbenchAgentContext()
  const location = useLocation()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const [preferenceState, setPreferenceState] = useState(() => ({ userId: user.id, value: readFeedPreference(user.id) }))
  const [viewModeState, setViewModeState] = useState(() => ({ userId: user.id, value: readFeedViewMode(user.id) }))
  const [collectionSearchOpen, setCollectionSearchOpen] = useState(false)
  const [submittedSingleSearch, setSubmittedSingleSearch] = useState('')
  const [terminalEndMessage, setTerminalEndMessage] = useState<{ key: string; message: string } | null>(null)
  const reloadButtonRef = useRef<HTMLButtonElement>(null)
  const feedToolbarRef = useRef<HTMLDivElement>(null)
  const feedToolbarInsetRef = useRef(64)
  const [sourceOverviewResumeAnchor, setSourceOverviewResumeAnchor] = useState<SourceOverviewViewportAnchor | null>(null)
  const [sourceOverviewExpandedSourceId, setSourceOverviewExpandedSourceId] = useState<string | null>(null)
  const [feedToolbarInset, setFeedToolbarInset] = useState(64)
  const localDayReference = useLocalDayReference()
  const deepLinkNotice = Boolean((location.state as { staleItem?: boolean } | null)?.staleItem)
  const preference = preferenceState.userId === user.id ? preferenceState.value : readFeedPreference(user.id)
  const storedViewMode = viewModeState.userId === user.id ? viewModeState.value : readFeedViewMode(user.id)
  const selectedId = params.get('item') ?? undefined
  const historySourceId = kind === 'history' ? params.get('source_id')?.trim() || '' : ''
  const searchValue = kind === 'history' ? params.get('q') ?? '' : query
  const debouncedHistoryQuery = useDebouncedValue(searchValue.trim(), 300)
  const debouncedGlobalQuery = useDebouncedValue(searchValue.trim(), 300)
  const normalizedSearchValue = searchValue.trim()
  const globalSearchTerm = kind === 'feed'
    ? debouncedGlobalQuery.length >= 2
      ? debouncedGlobalQuery
      : submittedSingleSearch === normalizedSearchValue
        ? submittedSingleSearch
        : ''
    : ''
  const globalSearchRequested = kind === 'feed' && Boolean(normalizedSearchValue)
  const globalSearchActive = Boolean(globalSearchTerm)
  const globalSearchTransition = globalSearchRequested || globalSearchActive
  const effectiveViewMode: FeedViewMode = kind === 'feed' && !globalSearchTransition ? storedViewMode : 'timeline'
  const historyPageSize = 50
  const savedPageSize = 50
  const [initialNavigationTargetId] = useState(selectedId)
  const feedQuery = useQuery({
    queryKey: queryKeys.feed(user.id, { hideDismissed: false, unreadFirst: false }),
    queryFn: ({ signal }) => api.latestFeed(signal),
    enabled: kind === 'feed',
    staleTime: queryStaleTime.feed,
    refetchOnMount: selectedId ? 'always' : true,
  })
  const endMessagesQuery = useQuery({
    queryKey: queryKeys.feedEndMessages(user.id),
    queryFn: ({ signal }) => api.feedEndMessages(signal),
    staleTime: queryStaleTime.settings,
    retry: false,
  })
  const globalSearchQuery = useInfiniteQuery({
    queryKey: queryKeys.search(user.id, {
      q: globalSearchTerm,
      limit: 50,
      submitted: globalSearchTerm.length === 1,
    }),
    queryFn: ({ pageParam, signal }) => api.searchFeed({
      q: globalSearchTerm,
      limit: 50,
      cursor: pageParam || undefined,
      submitted: globalSearchTerm.length === 1,
    }, signal),
    initialPageParam: '',
    getNextPageParam: (lastPage) => lastPage.has_more
      ? lastPage.next_cursor || undefined
      : undefined,
    enabled: kind === 'feed' && globalSearchActive,
    retry: false,
  })
  const sourceCatalogQuery = useQuery({
    queryKey: queryKeys.sources(user.id),
    queryFn: ({ signal }) => api.sources(user.role === 'owner' || user.role === 'admin', signal),
    enabled: kind === 'feed' || (kind === 'history' && Boolean(historySourceId)),
    staleTime: queryStaleTime.catalog,
  })
  const savedQuery = useInfiniteQuery({
    queryKey: queryKeys.saved(user.id),
    queryFn: ({ pageParam, signal }) => api.savedFeed(savedPageSize, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      if (lastPage.items.length === 0) return undefined
      const nextOffset = lastPage.offset + lastPage.items.length
      return nextOffset < lastPage.item_count ? nextOffset : undefined
    },
    enabled: kind === 'saved',
    staleTime: queryStaleTime.collection,
  })
  const historyQuery = useInfiniteQuery({
    queryKey: queryKeys.history(user.id, {
      q: debouncedHistoryQuery,
      sourceId: historySourceId,
      limit: historyPageSize,
    }),
    queryFn: ({ pageParam, signal }) => api.historyFeed({
      q: debouncedHistoryQuery || undefined,
      sourceId: historySourceId || undefined,
      limit: historyPageSize,
      offset: pageParam,
    }, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage.has_more
      ? lastPage.offset + lastPage.items.length
      : undefined,
    enabled: kind === 'history',
    retry: false,
    staleTime: queryStaleTime.collection,
  })
  const historyItems = useMemo(() => {
    const seen = new Set<string>()
    return (historyQuery.data?.pages ?? []).flatMap((page) => page.items).filter((item) => {
      if (seen.has(item.id)) return false
      seen.add(item.id)
      return true
    })
  }, [historyQuery.data?.pages])
  const savedItems = useMemo(() => {
    const seen = new Set<string>()
    return (savedQuery.data?.pages ?? []).flatMap((page) => page.items).filter((item) => {
      if (seen.has(item.id)) return false
      seen.add(item.id)
      return true
    })
  }, [savedQuery.data?.pages])
  const globalSearchItems = useMemo(() => {
    const seen = new Set<string>()
    return (globalSearchQuery.data?.pages ?? []).flatMap((page) => page.items).filter((item) => {
      if (seen.has(item.id)) return false
      seen.add(item.id)
      return true
    })
  }, [globalSearchQuery.data?.pages])
  const sourceItems = useMemo(() => globalSearchRequested
    ? globalSearchItems
    : selectWorkbenchSourceItems(kind, {
    snapshot: feedQuery.data,
    saved: kind === 'saved'
      ? {
        schema_version: 1,
        scope: 'user',
        items: savedItems,
        item_count: savedQuery.data?.pages[0]?.item_count ?? savedItems.length,
        limit: savedPageSize,
        offset: 0,
      }
      : undefined,
    history: kind === 'history'
      ? {
        schema_version: 2,
        scope: 'user',
        items: historyItems,
        featured_items: [],
        item_count: historyItems.length,
        total_count: historyQuery.data?.pages[0]?.total_count ?? 0,
        limit: historyPageSize,
        offset: 0,
        has_more: historyQuery.hasNextPage,
        snapshots: historyQuery.data?.pages[0]?.snapshots ?? [],
      }
      : undefined,
  }), [feedQuery.data, globalSearchItems, globalSearchRequested, historyItems, historyQuery.data?.pages, historyQuery.hasNextPage, kind, savedItems, savedQuery.data?.pages])
  const sourceQuerySettled = kind === 'feed'
    ? globalSearchRequested
      ? (!globalSearchActive || globalSearchQuery.isSuccess) && !globalSearchQuery.isFetchingNextPage
      : feedQuery.isSuccess && !feedQuery.isFetching
    : kind === 'saved'
      ? savedQuery.isSuccess && !savedQuery.isFetching
    : historyQuery.isSuccess && !historyQuery.isFetchingNextPage
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
    () => globalSearchRequested
      ? mergedItems
      : sortWorkbenchItems(mergedItems, preference.order, preference.sortBasis),
    [globalSearchRequested, mergedItems, preference.order, preference.sortBasis],
  )
  const sourceScopeRequested = kind === 'feed' && !globalSearchRequested && preference.subscriptionScope !== 'all'
  const allowedSourceIds = useMemo(() => {
    if (!sourceScopeRequested || !sourceCatalogQuery.data) return undefined
    const visibility = preference.subscriptionScope === 'public' ? 'public' : 'private'
    return new Set(sourceCatalogQuery.data.sources
      .filter((source) => sourceMatchesSubscriptionVisibility(source, visibility))
      .map((source) => source.id))
  }, [preference.subscriptionScope, sourceCatalogQuery.data, sourceScopeRequested])
  const filteredItems = useMemo(() => {
    if (globalSearchRequested) {
      return orderedItems.filter((item) => !item.user_state?.dismissed)
    }
    const matching = filterFeedItems(
      orderedItems.filter((item) => !item.user_state?.dismissed),
      {
        query: kind === 'history' ? '' : query,
        unreadFirst: preference.unreadFirst,
        sourceId: kind === 'history' ? undefined : preference.source || undefined,
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
  }, [allowedSourceIds, detailQuery.data, globalSearchRequested, kind, localDayReference, orderedItems, preference, query, selectedId])
  const cards = useMemo(() => filteredItems.map(toWorkbenchCardModel), [filteredItems])
  const sourceOverviewSections = useMemo(() => buildSourceOverviewSections(cards), [cards])
  const selectedSourceSectionId = useMemo(() => selectedId
    ? sourceOverviewSections.find((section) => section.cards.some((card) => card.id === selectedId))?.id ?? null
    : null, [selectedId, sourceOverviewSections])
  const activeSourceOverviewSectionId = selectedSourceSectionId ?? sourceOverviewExpandedSourceId
  const sourceItemIds = useMemo(() => mergedItems.map((item) => item.id), [mergedItems])
  const sources = useMemo(() => Array.from(new Map(sourceItems.map((item) => {
    const value = item.presentation?.source?.id || item.source_id || item.source || ''
    return [value, item.presentation?.source?.name || item.source || item.source_type || value] as const
  }).filter(([value]) => Boolean(value))).entries()), [sourceItems])
  const channels = useMemo(() => Array.from(new Set(sourceItems.map((item) => item.presentation?.taxonomy?.channel || item.channel || item.category).filter(Boolean) as string[])).sort(), [sourceItems])
  const topics = useMemo(() => Array.from(new Set(sourceItems.flatMap((item) => item.presentation?.taxonomy?.topics ?? item.topics ?? item.tags ?? []))).sort(), [sourceItems])
  const loading = (kind === 'feed'
    ? globalSearchRequested
      ? globalSearchActive && globalSearchQuery.isLoading
      : feedQuery.isLoading
    : false)
    || savedQuery.isLoading
    || historyQuery.isLoading
    || (sourceScopeRequested && sourceCatalogQuery.isLoading)
  const loadError = (kind === 'feed' && globalSearchRequested
    ? globalSearchQuery.data ? null : globalSearchQuery.error
    : feedQuery.data ? null : feedQuery.error)
    || (savedQuery.data ? null : savedQuery.error)
    || (historyQuery.data ? null : historyQuery.error)
    || (sourceScopeRequested ? sourceCatalogQuery.error : null)
  const collectionRoute = kind !== 'feed'
  const updating = activity.state === 'queued' || activity.state === 'running'
  const reloading = kind === 'feed' && feedQuery.isFetching
  const activeFilterCount = globalSearchRequested ? 0 : [
    preference.unreadFirst,
    kind !== 'history' && preference.source,
    preference.channel,
    preference.topic,
    kind === 'feed' && preference.dateScope === 'today',
    kind === 'feed' && preference.subscriptionScope !== 'all',
  ].filter(Boolean).length
  const collectionSearchVisible = collectionSearchOpen || Boolean(searchValue)
  const historySourceName = sourceCatalogQuery.data?.sources.find((source) => source.id === historySourceId)?.display_name
  const historyTotalCount = historyQuery.data?.pages[0]?.total_count ?? cards.length
  const globalSearchTotalCount = globalSearchQuery.data?.pages[0]?.total_count ?? cards.length
  const savedTotalCount = savedQuery.data?.pages[0]?.item_count ?? cards.length
  const activeWindow = globalSearchQuery.data?.pages[0]?.window
    ?? historyQuery.data?.pages[0]?.window
    ?? feedQuery.data?.window
  const feedWindowDays = activeWindow?.feed_days ?? 7
  const countLabel = kind === 'feed'
    ? globalSearchRequested
      ? globalSearchActive
        ? `全部内容搜索 · ${globalSearchTotalCount} 条`
        : '全部内容搜索 · 按回车'
      : `近${feedWindowDays}天 · ${cards.length} 条`
    : `${kind === 'history' ? historyTotalCount : savedTotalCount} 条内容`
  const activeFilterSummaries = [
    ...(searchValue ? [{ id: 'query', label: `搜索：${searchValue}`, clear: () => setSearchValue('') }] : []),
    ...(!globalSearchRequested ? [
    ...(historySourceId ? [{
      id: 'history-source',
      label: `来源：${historySourceName ?? historySourceId}`,
      clear: clearHistorySource,
    }] : []),
    ...(preference.unreadFirst ? [{ id: 'unread', label: '未读优先', clear: () => updatePreference({ unreadFirst: false }) }] : []),
    ...(kind !== 'history' && preference.source ? [{ id: 'source', label: `来源：${sources.find(([id]) => id === preference.source)?.[1] ?? preference.source}`, clear: () => updatePreference({ source: '' }) }] : []),
    ...(preference.channel ? [{ id: 'channel', label: `频道：${preference.channel}`, clear: () => updatePreference({ channel: '' }) }] : []),
    ...(preference.topic ? [{ id: 'topic', label: `主题：${preference.topic}`, clear: () => updatePreference({ topic: '' }) }] : []),
    ...(kind === 'feed' && preference.dateScope === 'today' ? [{ id: 'date', label: '仅今天', clear: () => updatePreference({ dateScope: 'all' }) }] : []),
    ...(kind === 'feed' && preference.subscriptionScope !== 'all' ? [{ id: 'scope', label: preference.subscriptionScope === 'public' ? '公共订阅' : '私人订阅', clear: () => updatePreference({ subscriptionScope: 'all' }) }] : []),
    ] : []),
  ]

  useEffect(() => {
    if (!activeWindow?.today_start) return
    const nextShanghaiMidnight = Date.parse(activeWindow.today_start) + 24 * 60 * 60 * 1000
    if (!Number.isFinite(nextShanghaiMidnight)) return
    const timer = window.setTimeout(() => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.feedRoot(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.historyRoot(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.searchRoot(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) }),
      ])
    }, Math.max(1_000, nextShanghaiMidnight - Date.now() + 250))
    return () => window.clearTimeout(timer)
  }, [activeWindow?.today_start, queryClient, user.id])

  function updatePreference(patch: Partial<FeedPreference>, scrollPolicy: 'preserve' | 'reset-top' = 'preserve') {
    const next = { ...preference, ...patch }
    if (scrollPolicy === 'preserve') window.dispatchEvent(new Event(workbenchRefreshRequestEvent))
    setPreferenceState({ userId: user.id, value: next })
    writeFeedPreference(user.id, next)
  }

  function updateViewMode(mode: FeedViewMode) {
    if (kind !== 'feed' || globalSearchRequested || mode === storedViewMode) return
    setViewModeState({ userId: user.id, value: mode })
    writeFeedViewMode(user.id, mode)
  }

  function setSearchValue(value: string) {
    if (kind === 'feed' && value.trim()) {
      const viewport = document.querySelector<HTMLDivElement>('[data-feed-mode="source-overview"]')
      if (viewport) setSourceOverviewResumeAnchor(readSourceOverviewViewportAnchor(viewport, feedContentInset))
    }
    if (kind === 'feed' && value.trim() !== submittedSingleSearch) {
      setSubmittedSingleSearch('')
    }
    if (kind !== 'history') {
      setQuery(value)
      return
    }
    const next = new URLSearchParams(params)
    if (value) next.set('q', value)
    else next.delete('q')
    setParams(next, { replace: true })
  }

  function submitSearch() {
    if (kind === 'feed' && normalizedSearchValue.length === 1) {
      setSubmittedSingleSearch(normalizedSearchValue)
    }
  }

  function clearHistorySource() {
    const next = new URLSearchParams(params)
    next.delete('source_id')
    setParams(next, { replace: true })
  }

  function toggleExpanded(id: string) {
    const next = new URLSearchParams(params)
    if (selectedId === id) next.delete('item')
    else next.set('item', id)
    setParams(next)
  }

  function toggleSourceOverviewSection(sourceId: string) {
    const sourceForSelectedItem = selectedId
      ? sourceOverviewSections.find((section) => section.cards.some((card) => card.id === selectedId))?.id
      : undefined
    const next = new URLSearchParams(params)
    if (activeSourceOverviewSectionId === sourceId) {
      setSourceOverviewExpandedSourceId(null)
      if (sourceForSelectedItem === sourceId) {
        next.delete('item')
        setParams(next)
      }
      return
    }
    setSourceOverviewExpandedSourceId(sourceId)
    if (selectedId && sourceForSelectedItem !== sourceId) {
      next.delete('item')
      setParams(next)
    }
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

  const paginationQuery = globalSearchActive
    ? globalSearchQuery
    : kind === 'saved'
      ? savedQuery
    : kind === 'history'
      ? historyQuery
      : null
  const paginationTotal = globalSearchActive
    ? globalSearchTotalCount
    : kind === 'saved'
      ? savedTotalCount
      : historyTotalCount
  const paginationFooter = paginationQuery
    && (paginationQuery.hasNextPage || paginationQuery.isFetchNextPageError)
    ? <div className="flex flex-col items-center gap-2 pt-1">
      {paginationQuery.isFetchNextPageError && <p role="alert" className="type-meta text-danger">更多内容加载失败，已加载内容仍可继续查看。</p>}
      <Button
        size="sm"
        variant="secondary"
        aria-busy={paginationQuery.isFetchingNextPage || undefined}
        isDisabled={paginationQuery.isFetchingNextPage}
        onPress={() => void paginationQuery.fetchNextPage()}
      >
        {paginationQuery.isFetchingNextPage
          ? <><Icons.LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />正在加载</>
          : paginationQuery.isFetchNextPageError ? '重试加载更多' : `加载更多（已显示 ${cards.length}/${paginationTotal}）`}
      </Button>
    </div>
    : undefined
  const waitingForSingleCharacterSubmit = globalSearchRequested && !globalSearchActive
  const hasUnloadedPages = Boolean(paginationQuery?.hasNextPage)
  const terminalReady = sourceQuerySettled
    && !loading
    && !loadError
    && !waitingForSingleCharacterSubmit
    && !hasUnloadedPages
    && !paginationQuery?.isFetching
  const terminalContextKey = [
    kind,
    globalSearchTerm,
    normalizedSearchValue,
    historySourceId,
    preference.source,
    preference.channel,
    preference.topic,
    preference.dateScope,
    preference.subscriptionScope,
  ].join('|')
  const endMessageScenes = endMessagesQuery.data?.scenes ?? builtinFeedEndMessages

  const handleTerminalReach = useCallback(() => {
    setTerminalEndMessage({
      key: terminalContextKey,
      message: selectTerminalFeedMessage(user.id, endMessageScenes).message,
    })
  }, [endMessageScenes, terminalContextKey, user.id])

  const terminalLabel = globalSearchActive
    ? '搜索结果已全部显示'
    : kind === 'saved'
      ? '收藏已全部显示'
      : kind === 'history'
        ? '历史记录已全部显示'
        : '当前信息流已全部显示'
  const terminalContent = terminalReady && cards.length > 0
    ? <FeedEndMessageLine
      data-testid="feed-end-message"
      label={terminalLabel}
      message={terminalEndMessage?.key === terminalContextKey ? terminalEndMessage.message : ''}
    />
    : undefined

  const detailErrorNotice = detailQuery.isError
    && !selectedInSource
    && !(detailQuery.error instanceof ApiError && detailQuery.error.status === 404)
  const hasFeedNotice = deepLinkNotice || detailErrorNotice
  const feedContentInset = hasFeedNotice ? 0 : feedToolbarInset

  useLayoutEffect(() => {
    const toolbar = feedToolbarRef.current
    if (!toolbar) return
    const updateInset = () => {
      const measuredHeight = Math.ceil(toolbar.getBoundingClientRect().height)
      const nextInset = measuredHeight > 0 ? measuredHeight + 8 : 64
      if (feedToolbarInsetRef.current === nextInset) return
      window.dispatchEvent(new Event(workbenchRefreshRequestEvent))
      feedToolbarInsetRef.current = nextInset
      setFeedToolbarInset(nextInset)
    }
    updateInset()
    window.addEventListener('resize', updateInset)
    if (typeof ResizeObserver === 'undefined') {
      return () => window.removeEventListener('resize', updateInset)
    }
    const observer = new ResizeObserver(updateInset)
    observer.observe(toolbar)
    return () => {
      window.removeEventListener('resize', updateInset)
      observer.disconnect()
    }
  }, [])

  return <section aria-label="信息流工作区" data-feed-blank-region className="relative flex h-full min-h-0 flex-col">
    <div ref={feedToolbarRef} data-testid="workbench-feed-toolbar" className="quiet-scroll-region absolute inset-x-0 top-0 z-10 overflow-y-scroll px-3 py-2 sm:px-5">
      <PageFrame width="reading">
        <div data-testid={collectionRoute ? 'collection-view-bar' : 'feed-view-bar'} className="rounded-xl bg-background/70 supports-[backdrop-filter:blur(1px)]:backdrop-blur-md">
        <ViewBar>
        {kind === 'feed' && <Tabs data-feed-mode-switch variant="primary" selectedKey={effectiveViewMode} onSelectionChange={(key) => updateViewMode(String(key) as FeedViewMode)} className="shrink-0 gap-0">
          <Tabs.ListContainer className="rounded-[var(--inteliscope-radius-control)] bg-default/70">
            <Tabs.List aria-label={globalSearchTransition ? '信息流阅读模式，搜索结果固定为时间流' : '信息流阅读模式'} className="!w-auto !min-w-0 gap-0.5 p-0.5">
              <Tabs.Tab
                id="timeline"
                isDisabled={globalSearchTransition}
                aria-label="时间流"
                className="!size-8 !min-w-8 !rounded-[var(--inteliscope-radius-compact)] !px-0 text-muted"
              >
                <span title="时间流"><Icons.Rows3 data-feed-mode-icon="timeline" size={15} aria-hidden="true" /></span>
                <span className="sr-only">时间流</span>
                <Tabs.Indicator className="!rounded-[var(--inteliscope-radius-compact)]" />
              </Tabs.Tab>
              <Tabs.Tab
                id="source-overview"
                isDisabled={globalSearchTransition}
                aria-label="专题速览"
                className="!size-8 !min-w-8 !rounded-[var(--inteliscope-radius-compact)] !px-0 text-muted"
              >
                <span title="专题速览"><Icons.Layers3 data-feed-mode-icon="source-overview" size={15} aria-hidden="true" /></span>
                <span className="sr-only">专题速览</span>
                <Tabs.Indicator className="!rounded-[var(--inteliscope-radius-compact)]" />
              </Tabs.Tab>
            </Tabs.List>
          </Tabs.ListContainer>
          <Tabs.Panel id="timeline" className="sr-only">时间流</Tabs.Panel>
          <Tabs.Panel id="source-overview" className="sr-only">专题速览</Tabs.Panel>
        </Tabs>}
        {kind !== 'feed' && <LoadingReveal
          loading={loading}
          label="正在读取内容数量"
          name="feed-count"
          className="mr-auto min-h-4 min-w-16 shrink-0"
          skeleton={<span data-feed-count-skeleton><CalmSkeleton className="h-4 w-16 rounded-md" /></span>}
        ><span className="type-control min-w-16 shrink-0 whitespace-nowrap text-muted">{countLabel}</span></LoadingReveal>}
        <div className="hidden min-w-0 flex-1 sm:flex">
          <SearchField aria-label={kind === 'history' ? '搜索历史内容' : kind === 'feed' ? '搜索全部内容' : '搜索当前列表'} value={searchValue} onChange={setSearchValue} className="min-w-0 flex-1" fullWidth variant="secondary">
            <SearchField.Group className="min-h-8 border-0 bg-transparent shadow-none">
              <SearchField.SearchIcon><Icons.Search size={14} /></SearchField.SearchIcon>
              <SearchField.Input
                className="type-control"
                placeholder={kind === 'feed' ? '搜索全部内容' : kind === 'history' ? '搜索全部历史内容' : '搜索当前列表'}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') submitSearch()
                }}
              />
              <SearchField.ClearButton aria-label="清除搜索" />
            </SearchField.Group>
          </SearchField>
        </div>
        <Tooltip delay={350}>
          <TooltipTriggerButton
            className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground sm:hidden"
            aria-label={searchValue ? '清除搜索' : collectionSearchOpen ? '收起搜索' : kind === 'history' ? '搜索历史内容' : '搜索信息流'}
            aria-expanded={collectionSearchVisible}
            onClick={() => {
              if (searchValue) {
                setSearchValue('')
                setCollectionSearchOpen(false)
                return
              }
              setCollectionSearchOpen((value) => !value)
            }}
          >{searchValue ? <Icons.X size={14} aria-hidden="true" /> : <Icons.Search size={14} aria-hidden="true" />}</TooltipTriggerButton>
          <Tooltip.Content {...bottomAnchoredTooltipProps}>
            {searchValue ? '清除搜索' : collectionSearchOpen ? '收起搜索' : kind === 'history' ? '搜索历史内容' : '搜索信息流'}
          </Tooltip.Content>
        </Tooltip>
        <Tooltip delay={350}>
          <TooltipTriggerButton
            className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
            aria-label={preference.sortBasis === 'ingested' ? '排序依据：入库时间' : '排序依据：发布时间'}
            disabled={globalSearchRequested}
            onClick={() => updatePreference({ sortBasis: preference.sortBasis === 'ingested' ? 'published' : 'ingested' }, 'reset-top')}
          >{preference.sortBasis === 'ingested' ? <Icons.Database size={14} aria-hidden="true" /> : <Icons.Clock3 size={14} aria-hidden="true" />}</TooltipTriggerButton>
          <Tooltip.Content {...bottomAnchoredTooltipProps}>
            {globalSearchRequested ? '全部内容搜索固定按最新优先' : preference.sortBasis === 'ingested' ? '当前按入库时间；点击改为发布时间' : '当前按发布时间；点击改为入库时间'}
          </Tooltip.Content>
        </Tooltip>
        <Tooltip delay={350}>
          <TooltipTriggerButton
            className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
            aria-label={preference.order === 'newest' ? '排序顺序：最新优先' : '排序顺序：最旧优先'}
            disabled={globalSearchRequested}
            onClick={() => updatePreference({ order: preference.order === 'newest' ? 'oldest' : 'newest' }, 'reset-top')}
          ><Icons.ArrowDownUp size={14} aria-hidden="true" /></TooltipTriggerButton>
          <Tooltip.Content {...bottomAnchoredTooltipProps}>
            {globalSearchRequested ? '全部内容搜索固定按最新优先' : preference.order === 'newest' ? '当前最新优先；点击改为最旧优先' : '当前最旧优先；点击改为最新优先'}
          </Tooltip.Content>
        </Tooltip>
        {!collectionRoute && <Tooltip delay={500}>
          <TooltipTriggerButton
            ref={reloadButtonRef}
            className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
            aria-label="重新载入信息流数据"
            aria-busy={reloading || undefined}
            disabled={reloading}
            onClick={() => void reloadFeedData()}
          ><Icons.RefreshCw size={14} className={reloading ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" /></TooltipTriggerButton>
          <Tooltip.Content {...bottomAnchoredTooltipProps}>重新载入本地信息流数据</Tooltip.Content>
        </Tooltip>}
        {!collectionRoute && <Tooltip delay={500}>
          <TooltipTriggerButton
            className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
            aria-label="获取新内容"
            aria-busy={updating || undefined}
            disabled={updating || user.role === 'viewer'}
            onClick={updateFeed}
          >{updating ? <Icons.LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : <Icons.Download size={14} aria-hidden="true" />}</TooltipTriggerButton>
          <Tooltip.Content {...bottomAnchoredTooltipProps}>{user.role === 'viewer' ? '只读账户不可获取新内容' : '触发所有已启用订阅获取新内容'}</Tooltip.Content>
        </Tooltip>}
        <Popover>
          <Popover.Trigger
            aria-label={`筛选信息流${activeFilterCount > 0 ? `，已启用 ${activeFilterCount} 项` : ''}`}
            title={activeFilterCount > 0 ? `筛选信息流 · 已启用 ${activeFilterCount} 项` : '筛选信息流'}
            className="relative inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
          >
          <Icons.SlidersHorizontal size={15} aria-hidden="true" />
          {activeFilterCount > 0 && <span aria-hidden="true" className="type-micro absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-accent px-1 text-center text-accent-foreground">{activeFilterCount}</span>}
          </Popover.Trigger>
          <Popover.Content placement="bottom end" className="z-30 w-[min(340px,calc(100vw-24px))] p-0">
            <Popover.Dialog aria-label="信息流筛选" className="grid gap-3 p-4">
              <Popover.Heading className="type-page-title">信息流筛选</Popover.Heading>
              <Switch isSelected={preference.unreadFirst} onChange={(value) => updatePreference({ unreadFirst: value })}>未读优先</Switch>
              {!collectionRoute && <FilterSelect label="订阅范围" value={preference.subscriptionScope} onChange={(value) => updatePreference({ subscriptionScope: value === 'public' || value === 'private' ? value : 'all' })} options={[{ id: 'all', label: '全部订阅' }, { id: 'public', label: '公共订阅' }, { id: 'private', label: '私人订阅' }]} />}
              {kind !== 'history' && <FilterSelect label="来源" value={preference.source} onChange={(value) => updatePreference({ source: value })} options={[{ id: '', label: '全部来源' }, ...sources.map(([id, label]) => ({ id, label }))]} />}
              <FilterSelect label="频道" value={preference.channel} onChange={(value) => updatePreference({ channel: value })} options={[{ id: '', label: '全部频道' }, ...channels.map((value) => ({ id: value, label: value }))]} />
              <FilterSelect label="主题" value={preference.topic} onChange={(value) => updatePreference({ topic: value })} options={[{ id: '', label: '全部主题' }, ...topics.map((value) => ({ id: value, label: value }))]} />
              <Button size="sm" variant="ghost" onPress={() => updatePreference({ unreadFirst: false, source: '', channel: '', topic: '', dateScope: 'all', subscriptionScope: 'all' })}>清除筛选</Button>
            </Popover.Dialog>
          </Popover.Content>
        </Popover>
        </ViewBar>
        {collectionSearchVisible && <div className="mt-2 min-w-0 sm:hidden">
          <SearchField aria-label={kind === 'history' ? '移动端搜索历史内容' : kind === 'feed' ? '移动端搜索全部内容' : '移动端搜索当前列表'} value={searchValue} onChange={setSearchValue} fullWidth variant="secondary">
            <SearchField.Group>
              <SearchField.SearchIcon><Icons.Search size={14} /></SearchField.SearchIcon>
              <SearchField.Input
                className="type-control"
                placeholder={kind === 'feed' ? '搜索全部内容' : kind === 'history' ? '搜索全部历史内容' : '搜索当前列表'}
                autoFocus
                onKeyDown={(event) => {
                  if (event.key === 'Enter') submitSearch()
                }}
              />
              <SearchField.ClearButton aria-label="清除搜索" />
            </SearchField.Group>
          </SearchField>
        </div>}
        {activeFilterSummaries.length > 0 && <div aria-label="当前筛选条件" className="mt-2 flex min-w-0 flex-wrap items-center gap-2">
          {activeFilterSummaries.map((filter) => <RemovableTag key={filter.id} label={filter.label} onRemove={filter.clear} transparent />)}
          <button
            type="button"
            className="type-meta inline-flex min-h-7 items-center gap-1 rounded-lg border border-transparent px-2 text-muted transition-colors duration-[var(--inteliscope-motion-standard)] hover:border-separator/70 hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus motion-reduce:transition-none"
            onClick={() => {
              setSearchValue('')
              if (historySourceId) clearHistorySource()
              updatePreference({ unreadFirst: false, source: '', channel: '', topic: '', dateScope: 'all', subscriptionScope: 'all' })
            }}
          ><Icons.X size={13} aria-hidden="true" />清除全部</button>
        </div>}
        </div>
      </PageFrame>
    </div>

    {hasFeedNotice && <div className="flex flex-col" style={{ marginTop: feedToolbarInset }}>
      {deepLinkNotice && <div role="status" className="type-body flex items-center gap-2 border-b border-separator px-4 py-2 text-muted"><span className="flex-1">这条信息已不可用，已移除失效链接；信息流仍可继续使用。</span><Button size="sm" variant="ghost" isIconOnly aria-label="关闭提示" onPress={() => navigate({ pathname: location.pathname, search: location.search }, { replace: true, state: { ...(location.state as object | null), staleItem: false } })}><Icons.X size={15} /></Button></div>}
      {detailErrorNotice && <div role="alert" className="type-body border-b border-separator px-4 py-2 text-muted">无法读取深链条目；信息流仍可继续使用。</div>}
    </div>}
    <LoadingReveal
      loading={loading}
      label="正在读取信息流"
      name="feed"
      className="min-h-0 flex-1"
      skeleton={<div className="min-h-0" style={{ paddingTop: feedContentInset }}><WorkbenchFeedSkeleton /></div>}
    >
    {loadError ? <div className="flex min-h-0 flex-1" style={{ paddingTop: feedContentInset }}><PageFrame width="reading" className="p-5"><StatusNotice title="信息流加载失败">{loadError instanceof ApiError ? loadError.message : '请稍后重试。'}</StatusNotice></PageFrame></div>
      : cards.length === 0 && hasUnloadedPages ? <div className="flex min-h-0 flex-1" style={{ paddingTop: feedContentInset }}><PageFrame width="reading" className="m-auto">
        <div className="grid gap-3 text-center">
          <p className="type-control text-foreground">已加载内容中没有符合条件的信息</p>
          <p className="type-meta text-muted">仍有内容尚未加载，可以继续查看下一页。</p>
          {paginationFooter}
        </div>
      </PageFrame></div>
      : cards.length === 0 && waitingForSingleCharacterSubmit ? <div className="flex min-h-0 flex-1" style={{ paddingTop: feedContentInset }}><PageFrame width="reading" className="m-auto">
        <FeedEndMessageLine
          data-testid="feed-search-submit-message"
          label="单字符搜索等待提交"
          message="输入单个字符后按回车搜索"
        />
      </PageFrame></div>
      : cards.length === 0 && terminalReady ? <div className="flex min-h-0 flex-1" style={{ paddingTop: feedContentInset }}><PageFrame width="reading" className="m-auto">
        <EmptyFeedEndMessage
          key={`${user.id}:${terminalContextKey}`}
          userId={user.id}
          label={globalSearchActive
            ? '搜索结果为空'
            : kind === 'saved'
              ? '收藏为空'
              : kind === 'history'
                ? '历史记录为空'
                : '信息流为空'}
          messages={endMessageScenes.empty}
        />
      </PageFrame></div>
      : cards.length === 0 ? null
      : effectiveViewMode === 'source-overview' ? <FeedModeLayer key="source-overview" mode="source-overview">
        <SourceOverviewFeed
      topInset={feedContentInset}
      resetToTopKey={`source-overview:${preference.sortBasis}:${preference.order}`}
      sections={sourceOverviewSections}
      sourceItemIds={sourceItemIds}
      trackNewItems={kind !== 'history' && !globalSearchRequested}
      feedWindowDays={feedWindowDays}
      footer={paginationFooter}
      terminal={terminalContent}
      terminalKey={terminalContextKey}
      expandedSourceId={activeSourceOverviewSectionId}
      expandedId={selectedId}
      navigationTargetId={deepLinkNotice ? undefined : initialNavigationTargetId}
      contextIds={agent.draft.items.map((item) => item.articleId)}
      detailLoading={detailQuery.isFetching}
      detailError={detailQuery.isError && selectedInSource}
      readonly={user.role === 'viewer'}
      resumeAnchor={sourceOverviewResumeAnchor}
      onResumeAnchorRestored={() => {
        setSourceOverviewResumeAnchor(null)
      }}
      onTerminalReach={handleTerminalReach}
      onToggleSource={toggleSourceOverviewSection}
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
          sourceUrl: card.url,
          sourceAvatarUrl: card.sourceAvatar,
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
        />
      </FeedModeLayer> : <FeedModeLayer key="timeline" mode="timeline">
        <VirtualFeed
      topInset={feedContentInset}
      freshEdge={preference.order === 'newest' ? 'start' : 'end'}
      resetToTopKey={`${preference.sortBasis}:${preference.order}:${debouncedHistoryQuery}:${historySourceId}`}
      cards={cards}
      sourceItemIds={sourceItemIds}
      trackNewItems={kind !== 'history' && !globalSearchRequested}
      showTimelineBucket={globalSearchActive}
      feedWindowDays={feedWindowDays}
      footer={paginationFooter}
      terminal={terminalContent}
      terminalKey={terminalContextKey}
      expandedId={selectedId}
      navigationTargetId={deepLinkNotice ? undefined : initialNavigationTargetId}
      contextIds={agent.draft.items.map((item) => item.articleId)}
      detailLoading={detailQuery.isFetching}
      detailError={detailQuery.isError && selectedInSource}
      readonly={user.role === 'viewer'}
      onTerminalReach={handleTerminalReach}
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
          sourceUrl: card.url,
          sourceAvatarUrl: card.sourceAvatar,
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
        />
      </FeedModeLayer>}
    </LoadingReveal>
  </section>
}

function FilterSelect({ label, value, options, onChange }: { label: string; value: string; options: Array<{ id: string; label: string }>; onChange: (value: string) => void }) {
  return <Select aria-label={label} selectedKey={value} onSelectionChange={(key) => key !== null && onChange(String(key))}>
    <Select.Trigger><Select.Value /><Select.Indicator><Icons.ChevronDown size={15} /></Select.Indicator></Select.Trigger>
    <Select.Popover><ListBox items={options}>{(item) => <ListBox.Item id={item.id} textValue={item.label}>{item.label}</ListBox.Item>}</ListBox></Select.Popover>
  </Select>
}

function useDebouncedValue(value: string, delay: number) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [delay, value])
  return debounced
}

function EmptyFeedEndMessage({
  userId,
  label,
  messages,
}: {
  userId: string
  label: string
  messages: string[]
}) {
  const [message] = useState(() => selectEmptyFeedMessage(userId, messages))
  if (!message) return null
  return <FeedEndMessageLine data-testid="feed-empty-message" label={label} message={message} />
}

function FeedEndMessageLine({
  'data-testid': testId,
  label,
  message,
}: {
  'data-testid': string
  label?: string
  message: string
}) {
  return <p
    data-testid={testId}
    role={message ? 'status' : undefined}
    className="type-meta flex max-w-full min-w-0 items-center justify-center gap-2 px-3 py-2 text-center text-muted"
  >
    {label && <span className="sr-only">{label}</span>}
    <span aria-hidden="true" className="shrink-0">·</span>
    {message && <span className="min-w-0 truncate">{message}</span>}
  </p>
}
