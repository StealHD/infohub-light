import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { FeedHistory, FeedItem, FeedSnapshot } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { FeedFilters } from './FeedFilters'
import { FeedWorkspace } from './FeedWorkspace'
import { filterFeedItems, selectModeItems, type FeedMode } from './feedModel'
import { readLegacyFeedPreference, writeLegacyFeedPreference } from './feedPreference'
import { useOptimisticItemState } from './useOptimisticItemState'

type FeedPageProps = { kind: 'feed' | 'later' | 'saved' | 'history' }

const validMode = (value: string | null): FeedMode => value === 'all' || value === 'daily' ? value : 'featured'

function uniqueItems(values: FeedItem[]): FeedItem[] {
  const seen = new Set<string>()
  return values.filter((item) => !seen.has(item.id) && Boolean(seen.add(item.id)))
}

export function FeedPage({ kind }: FeedPageProps) {
  const { api, user, query, beginAction, isActionCurrent } = useAppContext()
  const location = useLocation()
  const [params, setParams] = useSearchParams()
  const [preference, setPreference] = useState(() => ({ userId: user.id, value: readLegacyFeedPreference(user.id) }))
  const activePreference = preference.userId === user.id ? preference.value : readLegacyFeedPreference(user.id)
  const unreadFirst = activePreference.unreadFirst
  const [sourceId, setSourceId] = useState('')
  const [channel, setChannel] = useState('')
  const [topic, setTopic] = useState('')
  const [minScore, setMinScore] = useState<number | undefined>()
  const mode = params.has('mode') ? validMode(params.get('mode')) : activePreference.mode
  const selectedId = params.get('item') ?? undefined
  const feedKey = queryKeys.feed(user.id, { hideDismissed: false, unreadFirst: false })
  const feedQuery = useQuery({ queryKey: feedKey, queryFn: ({ signal }) => api.latestFeed(signal), enabled: kind === 'feed' || kind === 'later' })
  const historyQuery = useQuery({
    queryKey: queryKeys.history(user.id),
    queryFn: ({ signal }) => api.historyFeed(signal),
    enabled: kind === 'later' || kind === 'history',
  })
  const savedQuery = useQuery({
    queryKey: queryKeys.saved(user.id),
    queryFn: ({ signal }) => api.savedFeed(200, 0, signal),
    enabled: kind === 'saved',
  })
  const detailQuery = useQuery({
    queryKey: queryKeys.feedItem(user.id, selectedId || ''),
    queryFn: ({ signal }) => api.feedItem(selectedId!, signal),
    enabled: Boolean(selectedId),
  })
  const healthQuery = useQuery({ queryKey: queryKeys.sourceHealth(user.id), queryFn: ({ signal }) => api.sourceHealth(signal) })

  const sourceItems = useMemo(() => {
    if (kind === 'history') return historyQuery.data?.items ?? []
    if (kind === 'saved') return (savedQuery.data?.items ?? []).filter((item) => item.user_state?.is_saved)
    if (kind === 'later') {
      return uniqueItems([...(feedQuery.data?.items ?? []), ...(historyQuery.data?.items ?? [])]).filter((item) => item.user_state?.is_later)
    }
    return selectModeItems(feedQuery.data, mode)
  }, [feedQuery.data, historyQuery.data, kind, mode, savedQuery.data])
  const items = useMemo(() => filterFeedItems(
    sourceItems.filter((item) => !item.user_state?.dismissed),
    { query, unreadFirst, sourceId: sourceId || undefined, channel: channel || undefined, topic: topic || undefined, minScore },
  ), [channel, minScore, query, sourceId, sourceItems, topic, unreadFirst])
  const sources = useMemo(() => Array.from(new Map(sourceItems.map((item) => {
    const value = item.source_id || item.source || ''
    return [value, item.source || item.source_type || value] as const
  }).filter(([value]) => Boolean(value))).entries()).sort((left, right) => left[1].localeCompare(right[1])), [sourceItems])
  const channels = useMemo(() => Array.from(new Set(sourceItems.map((item) => item.channel || item.category).filter(Boolean) as string[])).sort(), [sourceItems])
  const topics = useMemo(() => Array.from(new Set(sourceItems.flatMap((item) => item.topics ?? item.tags ?? []))).sort(), [sourceItems])

  const stateMutation = useOptimisticItemState({ api, user, beginAction, isActionCurrent })

  const selectItem = (id: string) => {
    const next = new URLSearchParams(params)
    next.set('item', id)
    setParams(next)
  }
  const clearSelection = () => {
    const next = new URLSearchParams(params)
    next.delete('item')
    setParams(next)
  }
  const setMode = (nextMode: FeedMode) => {
    const next = new URLSearchParams(params)
    next.set('mode', nextMode)
    next.delete('item')
    setParams(next)
    const value = { ...activePreference, mode: nextMode }
    setPreference({ userId: user.id, value })
    writeLegacyFeedPreference(user.id, value)
  }
  const setUnreadPreference = (value: boolean) => {
    const next = { ...activePreference, unreadFirst: value }
    setPreference({ userId: user.id, value: next })
    writeLegacyFeedPreference(user.id, next)
  }
  const clearFilters = () => {
    setUnreadPreference(false)
    setSourceId('')
    setChannel('')
    setTopic('')
    setMinScore(undefined)
  }
  const retry = () => {
    void feedQuery.refetch()
    if (kind === 'later' || kind === 'history') void historyQuery.refetch()
    if (kind === 'saved') void savedQuery.refetch()
  }
  const error = feedQuery.error || historyQuery.error || savedQuery.error || detailQuery.error
  const title = kind === 'later' ? '稍后读' : kind === 'saved' ? '收藏' : kind === 'history' ? '历史信息流' : '今日信息流'
  const description = kind === 'feed'
    ? `${items.length} 条${mode === 'featured' ? '高价值信号' : mode === 'daily' ? '日报内容' : '最新内容'}`
    : `${items.length} 条已留存内容`

  return <FeedWorkspace
    title={title}
    description={description}
    items={items}
    selectedId={selectedId}
    selectedItem={detailQuery.data}
    onSelect={selectItem}
    onBack={clearSelection}
    onStateAction={(id, action, value) => stateMutation.mutateItem(id, { [action]: value })}
    sourceHealth={healthQuery.data?.items ?? []}
    loading={feedQuery.isLoading || historyQuery.isLoading || savedQuery.isLoading}
    error={error ? (error instanceof ApiError ? error.message : '信息流加载失败，请稍后重试。') : undefined}
    onRetry={retry}
    onDismissActionError={() => stateMutation.reset()}
    onClearFilters={clearFilters}
    readonly={user.role === 'viewer'}
    isStateActionPending={(action) => Boolean(selectedId && stateMutation.isItemActionPending(action, selectedId))}
    toolbar={<FeedFilters
      showModes={kind === 'feed'}
      mode={mode}
      onModeChange={setMode}
      unreadFirst={unreadFirst}
      onUnreadFirstChange={setUnreadPreference}
      sourceId={sourceId}
      onSourceChange={setSourceId}
      channel={channel}
      onChannelChange={setChannel}
      topic={topic}
      onTopicChange={setTopic}
      minScore={minScore}
      onMinScoreChange={setMinScore}
      sources={sources}
      channels={channels}
      topics={topics}
      onClear={clearFilters}
      updatedLabel={feedQuery.data?.generated_at ? `更新于 ${new Date(feedQuery.data.generated_at).toLocaleString()}` : location.pathname === '/feed' ? '等待首次更新' : ''}
    />}
  />
}

export type { FeedSnapshot, FeedHistory }
