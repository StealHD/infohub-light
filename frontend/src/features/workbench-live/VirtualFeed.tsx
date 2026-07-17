import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import {
  AvatarFallback,
  AvatarImage,
  AvatarRoot,
  Button,
  Card,
  Chip,
  Icons,
} from '../../design-system'
import { relativeTime, safeExternalUrl } from '../feed/feedModel'
import { sampleTickIndexes, type WorkbenchCardModel } from './workbenchModel'
import { workbenchRefreshRequestEvent } from './workbenchRefresh'

type ItemStateAction = 'is_read' | 'dismissed'

type VirtualFeedProps = {
  cards: WorkbenchCardModel[]
  sourceItemIds?: string[]
  expandedId?: string
  navigationTargetId?: string
  contextIds: string[]
  readonly?: boolean
  onToggleExpanded: (id: string) => void
  onToggleSaved: (id: string, saved: boolean) => void
  onToggleContext: (id: string) => void
  onItemAction: (id: string, action: ItemStateAction, value: boolean) => void
}

const collapsedEstimate = 156
const expandedEstimate = 390

type ViewportAnchor = { id: string; offset: number }
type PendingNavigation = { index: number; align: 'start' | 'center' | 'end' }

function readViewportAnchor(scroll: HTMLDivElement): ViewportAnchor | null {
  const bounds = scroll.getBoundingClientRect()
  const topCard = Array.from(scroll.querySelectorAll<HTMLElement>('[data-testid="workbench-card"]'))
    .filter((card) => card.getBoundingClientRect().bottom > bounds.top)
    .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
  const topRow = topCard?.closest<HTMLElement>('[data-item-id]')
  if (!topCard || !topRow?.dataset.itemId) return null
  return { id: topRow.dataset.itemId, offset: topCard.getBoundingClientRect().top - bounds.top }
}

function WorkbenchCard({
  card,
  expanded,
  inContext,
  contextFull,
  readonly,
  onToggleExpanded,
  onToggleSaved,
  onToggleContext,
  onItemAction,
}: {
  card: WorkbenchCardModel
  expanded: boolean
  inContext: boolean
  contextFull: boolean
  readonly?: boolean
  onToggleExpanded: () => void
  onToggleSaved: () => void
  onToggleContext: () => void
  onItemAction: (action: ItemStateAction, value: boolean) => void
}) {
  const externalUrl = safeExternalUrl(card.url)
  const copySummary = () => void navigator.clipboard?.writeText(card.summary || card.title)

  return <Card
    data-testid="workbench-card"
    role="article"
    aria-label={card.title}
    variant="secondary"
    className="w-full gap-0 rounded-2xl border border-separator bg-surface-secondary p-0 shadow-none"
  >
    <button
      type="button"
      className="w-full cursor-pointer px-4 pt-4 text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      aria-label={`${expanded ? '收起' : '展开'} ${card.title}`}
      aria-expanded={expanded}
      onClick={onToggleExpanded}
    >
      <span className="mb-2 flex items-center gap-2 text-xs text-muted">
        <AvatarRoot className="size-7 shrink-0">
          {card.sourceAvatar && <AvatarImage src={card.sourceAvatar} alt={card.source} />}
          <AvatarFallback>{card.source.slice(0, 1).toUpperCase()}</AvatarFallback>
        </AvatarRoot>
        <span className="truncate">{card.source}</span>
        <span aria-hidden="true">·</span>
        <span>{relativeTime(card.publishedAt)}</span>
      </span>
      <Card.Title className="line-clamp-2 text-base leading-6">{card.title}</Card.Title>
      <Card.Description className="mt-1 line-clamp-2 leading-5">{card.summary}</Card.Description>
    </button>

    {expanded && <Card.Content className="px-4 pt-3">
      <div className="border-t border-separator pt-3 text-sm leading-7 text-foreground whitespace-pre-wrap">
        {card.body || '该条内容未保存正文片段；重新获取来源后可显示。'}
      </div>
      {card.bodyTruncated && <p className="mt-2 text-xs text-muted">内容已截断，打开原文查看完整内容。</p>}
      {card.imageUrl && <img className="mt-3 max-h-80 w-full rounded-xl object-contain" src={card.imageUrl} alt={`${card.title} 内容图片`} loading="lazy" />}
    </Card.Content>}

    <Card.Footer className="flex flex-wrap items-center justify-between gap-2 px-4 pb-4 pt-3">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5" aria-label="频道和主题">
        <Chip size="sm" color="accent" variant="soft"><Chip.Label>{card.channel}</Chip.Label></Chip>
        {card.topics.slice(0, 3).map((topic) => <Chip key={topic} size="sm" variant="soft"><Chip.Label>{topic}</Chip.Label></Chip>)}
      </div>
      <div className="flex items-center gap-1">
        {externalUrl && <a
          href={externalUrl}
          target="_blank"
          rel="noreferrer"
          aria-label={`打开 ${card.title} 原文`}
          className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
        ><Icons.ExternalLink size={15} aria-hidden="true" /></a>}
        <Button
          size="sm"
          variant={card.userState.is_saved ? 'secondary' : 'ghost'}
          isDisabled={readonly}
          aria-label={`${card.userState.is_saved ? '取消收藏' : '收藏'} ${card.title}`}
          onPress={onToggleSaved}
          isIconOnly
        >{card.userState.is_saved ? <Icons.BookmarkCheck size={15} aria-hidden="true" /> : <Icons.Bookmark size={15} aria-hidden="true" />}</Button>
        <Button
          size="sm"
          variant={inContext ? 'secondary' : 'ghost'}
          isDisabled={contextFull && !inContext}
          aria-label={`将 ${card.title} ${inContext ? '移出' : '加入'} Agent 上下文`}
          onPress={onToggleContext}
          isIconOnly
        >{inContext ? <Icons.X size={15} aria-hidden="true" /> : <Icons.Sparkles size={15} aria-hidden="true" />}</Button>
        <details className="relative">
          <summary
            role="button"
            aria-label={`更多操作 ${card.title}`}
            className="flex size-8 cursor-pointer list-none items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
          ><Icons.MoreHorizontal size={16} aria-hidden="true" /></summary>
          <div className="absolute bottom-10 right-0 z-20 grid min-w-32 gap-1 rounded-xl border border-separator bg-overlay p-1 shadow-lg">
            <button disabled={readonly} type="button" className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm disabled:opacity-40" onClick={() => onItemAction('is_read', !card.userState.is_read)}>
              <Icons.Check size={14} aria-hidden="true" />{card.userState.is_read ? '标记未读' : '标记已读'}
            </button>
            <button type="button" className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm" onClick={copySummary}>
              <Icons.Copy size={14} aria-hidden="true" />复制摘要
            </button>
            <button disabled={readonly} type="button" className="flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm disabled:opacity-40" onClick={() => onItemAction('dismissed', !card.userState.dismissed)}>
              <Icons.EyeOff size={14} aria-hidden="true" />{card.userState.dismissed ? '取消忽略' : '忽略'}
            </button>
          </div>
        </details>
      </div>
    </Card.Footer>
  </Card>
}

export function VirtualFeed(props: VirtualFeedProps) {
  const sourceItemIds = props.sourceItemIds ?? props.cards.map((card) => card.id)
  const sourceSignature = sourceItemIds.join('\u0000')
  const cardsSignature = props.cards.map((card) => card.id).join('\u0000')
  const scrollRef = useRef<HTMLDivElement>(null)
  const wasNearBottom = useRef(true)
  const previousSourceIds = useRef(new Set(sourceItemIds))
  const previousCardsSignature = useRef(cardsSignature)
  const viewportAnchor = useRef<ViewportAnchor | null>(null)
  const requestedRefreshAnchor = useRef<ViewportAnchor | null>(null)
  const restorationAnchor = useRef<ViewportAnchor | null>(null)
  const pendingNavigation = useRef<PendingNavigation | null>(null)
  const navigationBoundary = useRef<'start' | 'end' | null>(null)
  const navigationBoundaryTimer = useRef<number | undefined>(undefined)
  const navigationBoundaryFrame = useRef<number | undefined>(undefined)
  const inlineScrollAnchor = useRef<number | null>(null)
  const inlineAnchorTimer = useRef<number | undefined>(undefined)
  const inlineAnchorFrame = useRef<number | undefined>(undefined)
  const didInitialScroll = useRef(false)
  const [activeIndex, setActiveIndex] = useState(Math.max(0, props.cards.length - 1))
  const [newItemCount, setNewItemCount] = useState(0)
  const ticks = useMemo(() => sampleTickIndexes(props.cards.length), [props.cards.length])
  const initialTargetIndex = props.navigationTargetId ? props.cards.findIndex((card) => card.id === props.navigationTargetId) : props.cards.length - 1
  // TanStack Virtual intentionally returns mutable imperative methods; React Compiler skips this component safely.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: props.cards.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => props.cards[index]?.id === props.expandedId ? expandedEstimate : collapsedEstimate,
    overscan: 5,
    measureElement: (element) => {
      const height = element.getBoundingClientRect().height
      if (height > 0) return height
      const index = Number(element.getAttribute('data-index'))
      return props.cards[index]?.id === props.expandedId ? expandedEstimate : collapsedEstimate
    },
    getItemKey: (index) => props.cards[index]?.id ?? index,
    initialRect: { width: 760, height: 720 },
    initialOffset: Math.max(0, (Math.max(0, initialTargetIndex) + 1) * collapsedEstimate - 720),
    observeElementRect: (instance, callback) => {
      const element = instance.scrollElement
      if (!(element instanceof HTMLElement)) return undefined
      const update = () => {
        const rect = element.getBoundingClientRect()
        callback({ width: rect.width || 760, height: rect.height || 720 })
      }
      update()
      if (typeof ResizeObserver === 'undefined') return undefined
      const observer = new ResizeObserver(update)
      observer.observe(element)
      return () => observer.disconnect()
    },
  })
  const cardsRef = useRef(props.cards)
  const virtualizerRef = useRef(virtualizer)
  cardsRef.current = props.cards
  virtualizerRef.current = virtualizer

  const releaseNavigationOwnership = useCallback(() => {
    requestedRefreshAnchor.current = null
    restorationAnchor.current = null
    inlineScrollAnchor.current = null
    viewportAnchor.current = null
    pendingNavigation.current = null
    navigationBoundary.current = null
    window.clearTimeout(inlineAnchorTimer.current)
    window.cancelAnimationFrame(inlineAnchorFrame.current ?? 0)
    window.clearTimeout(navigationBoundaryTimer.current)
    window.cancelAnimationFrame(navigationBoundaryFrame.current ?? 0)
  }, [])

  useEffect(() => {
    const capture = () => {
      const liveAnchor = scrollRef.current ? readViewportAnchor(scrollRef.current) : null
      const storedAnchor = viewportAnchor.current
      const anchor = liveAnchor ?? storedAnchor
      releaseNavigationOwnership()
      requestedRefreshAnchor.current = anchor
    }
    window.addEventListener(workbenchRefreshRequestEvent, capture)
    return () => window.removeEventListener(workbenchRefreshRequestEvent, capture)
  }, [releaseNavigationOwnership])

  useLayoutEffect(() => {
    if (previousCardsSignature.current === cardsSignature) return
    previousCardsSignature.current = cardsSignature
    const navigation = pendingNavigation.current
    if (navigation) {
      requestedRefreshAnchor.current = null
      const frame = window.requestAnimationFrame(() => {
        const index = Math.max(0, Math.min(navigation.index, cardsRef.current.length - 1))
        if (index === 0 && scrollRef.current) scrollRef.current.scrollTop = 0
        else virtualizerRef.current.scrollToIndex(index, { align: navigation.align })
      })
      return () => window.cancelAnimationFrame(frame)
    }
    const anchor = requestedRefreshAnchor.current ?? restorationAnchor.current ?? viewportAnchor.current
    requestedRefreshAnchor.current = null
    const scroll = scrollRef.current
    if (!anchor || !scroll || wasNearBottom.current) return
    restorationAnchor.current = anchor

    let frame = 0
    let remainingMeasurementFrames = 120
    let stableMeasurementFrames = 0
    const restore = () => {
      if (restorationAnchor.current !== anchor) return
      if (remainingMeasurementFrames <= 0) return
      remainingMeasurementFrames -= 1
      const row = Array.from(scroll.querySelectorAll<HTMLElement>('[data-item-id]'))
        .find((element) => element.dataset.itemId === anchor.id)
      if (!row) {
        const index = cardsRef.current.findIndex((card) => card.id === anchor.id)
        if (index < 0) {
          restorationAnchor.current = null
          return
        }
        virtualizerRef.current.scrollToIndex(index, { align: 'start' })
        frame = window.requestAnimationFrame(restore)
        return
      }
      const card = row.querySelector<HTMLElement>('[data-testid="workbench-card"]')
      if (!card) return
      const currentOffset = card.getBoundingClientRect().top - scroll.getBoundingClientRect().top
      const correction = currentOffset - anchor.offset
      if (Math.abs(correction) > 0.5) {
        stableMeasurementFrames = 0
        scroll.scrollTop += correction
      } else stableMeasurementFrames += 1
      if (stableMeasurementFrames < 6) {
        frame = window.requestAnimationFrame(restore)
      }
    }

    restore()
    const observer = new MutationObserver(() => {
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(restore)
    })
    const virtualSurface = scroll.firstElementChild
    if (virtualSurface) observer.observe(virtualSurface, { attributes: true, subtree: true, attributeFilter: ['style'] })
    return () => {
      observer.disconnect()
      window.cancelAnimationFrame(frame)
    }
  }, [cardsSignature])

  useLayoutEffect(() => {
    if (inlineScrollAnchor.current === null || !scrollRef.current) return
    const scroll = scrollRef.current
    const restore = () => {
      if (inlineScrollAnchor.current !== null) scroll.scrollTop = inlineScrollAnchor.current
    }
    restore()
    const frame = window.requestAnimationFrame(restore)
    return () => window.cancelAnimationFrame(frame)
  }, [props.cards, props.expandedId])

  useEffect(() => () => releaseNavigationOwnership(), [releaseNavigationOwnership])

  useEffect(() => {
    if (didInitialScroll.current || props.cards.length === 0) return
    const targetIndex = props.navigationTargetId ? props.cards.findIndex((card) => card.id === props.navigationTargetId) : props.cards.length - 1
    if (props.navigationTargetId && targetIndex < 0) return
    didInitialScroll.current = true
    const frame = window.requestAnimationFrame(() => {
      releaseNavigationOwnership()
      virtualizer.scrollToIndex(targetIndex, { align: props.navigationTargetId ? 'center' : 'end' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [props.cards, props.navigationTargetId, releaseNavigationOwnership, virtualizer])

  useEffect(() => {
    const addedCount = sourceItemIds.filter((id) => !previousSourceIds.current.has(id)).length
    previousSourceIds.current = new Set(sourceItemIds)
    requestedRefreshAnchor.current = null
    if (addedCount <= 0) return
    if (wasNearBottom.current) {
      releaseNavigationOwnership()
      virtualizer.scrollToIndex(props.cards.length - 1, { align: 'end' })
    }
    else setNewItemCount((count) => count + addedCount)
  }, [props.cards.length, releaseNavigationOwnership, sourceItemIds, sourceSignature, virtualizer])

  const virtualItems = virtualizer.getVirtualItems()

  function updateScrollState() {
    const element = scrollRef.current
    if (!element) return
    wasNearBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight <= 96
    if (wasNearBottom.current) setNewItemCount(0)
    const visible = virtualizer.getVirtualItems().filter((item) => item.end >= element.scrollTop && item.start <= element.scrollTop + element.clientHeight)
    if (visible.length) {
      setActiveIndex(visible[Math.floor((visible.length - 1) / 2)].index)
      if (pendingNavigation.current && visible.some((item) => item.index === pendingNavigation.current?.index)) {
        pendingNavigation.current = null
      }
    }
    const activeRestoration = restorationAnchor.current
    if (activeRestoration) {
      const row = Array.from(element.querySelectorAll<HTMLElement>('[data-item-id]'))
        .find((candidate) => candidate.dataset.itemId === activeRestoration.id)
      const card = row?.querySelector<HTMLElement>('[data-testid="workbench-card"]')
      if (card) {
        const correction = card.getBoundingClientRect().top - element.getBoundingClientRect().top - activeRestoration.offset
        if (Math.abs(correction) > 0.5) element.scrollTop += correction
      }
    }
    viewportAnchor.current = readViewportAnchor(element)
  }

  function jumpTo(index: number) {
    const refreshInFlight = requestedRefreshAnchor.current !== null
    const align = index <= 0 ? 'start' : index >= props.cards.length - 1 ? 'end' : 'center'
    const navigation = { index, align } satisfies PendingNavigation
    releaseNavigationOwnership()
    if (refreshInFlight) pendingNavigation.current = navigation
    setActiveIndex(index)
    if (index === 0 && scrollRef.current) {
      scrollRef.current.scrollTop = 0
      holdNavigationBoundary('start')
    }
    else virtualizerRef.current.scrollToIndex(index, { align })
  }

  function holdNavigationBoundary(boundary: 'start' | 'end') {
    navigationBoundary.current = boundary
    const hold = () => {
      const scroll = scrollRef.current
      if (!scroll || navigationBoundary.current !== boundary) return
      scroll.scrollTop = boundary === 'start' ? 0 : scroll.scrollHeight - scroll.clientHeight
      navigationBoundaryFrame.current = window.requestAnimationFrame(hold)
    }
    navigationBoundaryFrame.current = window.requestAnimationFrame(hold)
    navigationBoundaryTimer.current = window.setTimeout(() => {
      if (navigationBoundary.current === boundary) navigationBoundary.current = null
      window.cancelAnimationFrame(navigationBoundaryFrame.current ?? 0)
    }, 3000)
  }

  function toggleExpandedInline(id: string) {
    releaseNavigationOwnership()
    inlineScrollAnchor.current = scrollRef.current?.scrollTop ?? null
    const holdAnchor = () => {
      const element = scrollRef.current
      if (!element || inlineScrollAnchor.current === null) return
      element.scrollTop = inlineScrollAnchor.current
      inlineAnchorFrame.current = window.requestAnimationFrame(holdAnchor)
    }
    inlineAnchorFrame.current = window.requestAnimationFrame(holdAnchor)
    inlineAnchorTimer.current = window.setTimeout(() => {
      inlineScrollAnchor.current = null
      window.cancelAnimationFrame(inlineAnchorFrame.current ?? 0)
    }, 1000)
    props.onToggleExpanded(id)
  }

  function cancelInlineAnchor() {
    releaseNavigationOwnership()
  }

  return <div className="relative flex min-h-0 flex-1 overflow-hidden">
    <nav aria-label="信息流进度" className="absolute right-2 top-1/2 z-10 flex h-28 -translate-y-1/2 flex-col justify-around rounded-lg bg-surface/80 px-1.5 py-2 backdrop-blur">
      {ticks.map((index) => <button
        key={index}
        type="button"
        aria-label={`跳转到第 ${index + 1} 条信息`}
        aria-current={Math.abs(activeIndex - index) <= Math.max(1, Math.ceil(props.cards.length / Math.max(1, ticks.length)) / 2) ? 'true' : undefined}
        className="h-0.5 w-3 rounded-lg bg-muted aria-current:w-5 aria-current:bg-accent"
        onClick={() => jumpTo(index)}
      />)}
    </nav>
    <div
      ref={scrollRef}
      data-testid="workbench-feed-scroll"
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-3 py-4 pr-10 [overflow-anchor:none] sm:px-5 sm:pr-12"
      onScroll={updateScrollState}
      onWheel={cancelInlineAnchor}
      onTouchStart={cancelInlineAnchor}
      onPointerDown={cancelInlineAnchor}
      onKeyDown={cancelInlineAnchor}
    >
      <div className="relative mx-auto w-full max-w-3xl" style={{ height: virtualizer.getTotalSize() }}>
        {virtualItems.map((virtualItem) => {
          const card = props.cards[virtualItem.index]
          if (!card) return null
          return <div
            key={virtualItem.key}
            data-index={virtualItem.index}
            data-item-id={card.id}
            ref={virtualizer.measureElement}
            className="absolute left-0 top-0 w-full pb-3"
            style={{ transform: `translateY(${virtualItem.start}px)` }}
          >
            <WorkbenchCard
              card={card}
              expanded={card.id === props.expandedId}
              inContext={props.contextIds.includes(card.id)}
              contextFull={props.contextIds.length >= 8}
              readonly={props.readonly}
              onToggleExpanded={() => toggleExpandedInline(card.id)}
              onToggleSaved={() => props.onToggleSaved(card.id, !card.userState.is_saved)}
              onToggleContext={() => props.onToggleContext(card.id)}
              onItemAction={(action, value) => props.onItemAction(card.id, action, value)}
            />
          </div>
        })}
      </div>
    </div>
    {newItemCount > 0 && <Button
      size="sm"
      className="absolute bottom-4 left-1/2 z-10 -translate-x-1/2"
      aria-label={`查看 ${newItemCount} 条新内容`}
      onPress={() => {
        releaseNavigationOwnership()
        setNewItemCount(0)
        wasNearBottom.current = true
        virtualizer.scrollToIndex(props.cards.length - 1, { align: 'end' })
      }}
    >{newItemCount} 条新内容</Button>}
  </div>
}
