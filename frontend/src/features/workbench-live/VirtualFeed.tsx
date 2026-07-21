import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import {
  AvatarFallback,
  AvatarImage,
  AvatarRoot,
  Button,
  Card,
  Chip,
  Icons,
  Skeleton,
} from '../../design-system'
import { relativeTime, safeExternalUrl } from '../feed/feedModel'
import { workbenchSourceLabels, type WorkbenchCardModel } from './workbenchModel'
import { clampPendingNavigation, type PendingNavigation } from './workbenchNavigation'
import { workbenchRefreshRequestEvent } from './workbenchRefresh'

type ItemStateAction = 'is_read' | 'dismissed'

type VirtualFeedProps = {
  freshEdge?: 'start' | 'end'
  cards: WorkbenchCardModel[]
  sourceItemIds?: string[]
  expandedId?: string
  navigationTargetId?: string
  contextIds: string[]
  detailLoading?: boolean
  detailError?: boolean
  readonly?: boolean
  onToggleExpanded: (id: string) => void
  onToggleSaved: (id: string, saved: boolean) => void
  onToggleContext: (card: WorkbenchCardModel) => void
  onItemAction: (id: string, action: ItemStateAction, value: boolean) => void
}

const collapsedEstimate = 156
const expandedEstimate = 390

type ViewportAnchor = { id: string; offset: number }

function readViewportAnchor(scroll: HTMLDivElement): ViewportAnchor | null {
  const bounds = scroll.getBoundingClientRect()
  const topCard = Array.from(scroll.querySelectorAll<HTMLElement>('[data-testid="workbench-card"]'))
    .filter((card) => card.getBoundingClientRect().bottom > bounds.top)
    .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
  const topRow = topCard?.closest<HTMLElement>('[data-item-id]')
  if (!topCard || !topRow?.dataset.itemId) return null
  return { id: topRow.dataset.itemId, offset: topCard.getBoundingClientRect().top - bounds.top }
}

function useMeasuredClampOverflow(
  cardId: string,
  expanded: boolean,
): {
  overflow: boolean
  primaryRef: (node: HTMLElement | null) => void
  secondaryRef: (node: HTMLElement | null) => void
} {
  const primary = useRef<HTMLElement | null>(null)
  const secondary = useRef<HTMLElement | null>(null)
  const [overflow, setOverflow] = useState(false)

  useLayoutEffect(() => {
    if (expanded) return
    const elements = [primary.current, secondary.current].filter((value): value is HTMLElement => Boolean(value))
    const measure = () => setOverflow(elements.some((element) => element.scrollHeight > element.clientHeight + 1))
    measure()
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure)
      return () => window.removeEventListener('resize', measure)
    }
    const observer = new ResizeObserver(measure)
    elements.forEach((element) => observer.observe(element))
    return () => observer.disconnect()
  }, [cardId, expanded])

  return {
    overflow,
    primaryRef: (node) => { primary.current = node },
    secondaryRef: (node) => { secondary.current = node },
  }
}

function WorkbenchCard({
  card,
  expanded,
  inContext,
  contextFull,
  detailLoading,
  detailError,
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
  detailLoading?: boolean
  detailError?: boolean
  readonly?: boolean
  onToggleExpanded: () => void
  onToggleSaved: () => void
  onToggleContext: () => void
  onItemAction: (action: ItemStateAction, value: boolean) => void
}) {
  const externalUrl = safeExternalUrl(card.url)
  const social = card.displayKind === 'social'
  const socialText = expanded ? card.detailBody || card.primaryText : card.primaryText
  const cardLabel = social ? `${card.sourceLabel}: ${card.primaryText}` : card.title
  const sourceParts = workbenchSourceLabels(card)
  const [copyNotice, setCopyNotice] = useState('')
  const copyNoticeTimer = useRef<number | undefined>(undefined)
  const {
    overflow: measuredOverflow,
    primaryRef: measurePrimary,
    secondaryRef: measureSecondary,
  } = useMeasuredClampOverflow(card.id, expanded)
  const canExpand = measuredOverflow || card.hasDistinctDetail || card.mediaImages.length > 0
  const canToggleExpansion = canExpand || expanded
  const imageCountLabel = card.totalImageCount > 0
    ? card.mediaTruncated
      ? `${card.totalImageCount} 张图片 · 可查看 ${card.displayImageCount} 张`
      : `${card.totalImageCount} 张图片`
    : ''
  const incompleteMessage = card.bodyCompleteness === 'excerpt_only' || card.bodyTruncated || card.excerptTruncated
    ? '仅获取到内容片段，打开原文查看完整内容。'
    : ''

  useEffect(() => () => window.clearTimeout(copyNoticeTimer.current), [])

  async function copySummary() {
    window.clearTimeout(copyNoticeTimer.current)
    try {
      if (typeof navigator.clipboard?.writeText !== 'function') throw new Error('Clipboard API unavailable')
      await navigator.clipboard.writeText(social ? socialText : card.summary || card.title)
      setCopyNotice('摘要已复制')
    } catch {
      setCopyNotice('复制失败，请手动复制')
    }
    copyNoticeTimer.current = window.setTimeout(() => setCopyNotice(''), 2800)
  }

  return <Card
    data-testid="workbench-card"
    data-card-visual="quiet-studio"
    data-card-expanded={expanded ? 'true' : 'false'}
    role="article"
    aria-label={cardLabel}
    variant="secondary"
    className="group/card w-full gap-0 rounded-[var(--inteliscope-radius-feed-card)] border border-separator bg-surface-secondary p-0 shadow-none transition-[background-color,border-color,transform,box-shadow] duration-[var(--inteliscope-motion-standard)] hover:-translate-y-px hover:border-border hover:bg-surface-tertiary focus-within:border-border motion-reduce:transform-none"
  >
    {canToggleExpansion ? <button
      type="button"
      className="w-full cursor-pointer px-[19px] pt-[18px] text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
      aria-label={`${expanded ? '收起详情' : '打开详情'} ${cardLabel}`}
      aria-expanded={expanded}
      onClick={onToggleExpanded}
    >
      <span aria-label="来源信息" className="type-meta mb-2 flex items-center gap-2 text-muted">
        <AvatarRoot className="size-[25px] shrink-0">
          {card.sourceAvatar && <AvatarImage src={card.sourceAvatar} alt={card.source} />}
          <AvatarFallback>{card.source.slice(0, 1).toUpperCase()}</AvatarFallback>
        </AvatarRoot>
        {sourceParts.map((part, index) => <Fragment key={part}>
          {index > 0 && <span aria-hidden="true">·</span>}
          <span className="truncate">{part}</span>
        </Fragment>)}
        <span aria-hidden="true">·</span>
        <span>{relativeTime(card.publishedAt)}</span>
      </span>
      {social
        ? <Card.Description ref={measurePrimary} className={`type-body whitespace-pre-wrap text-foreground ${expanded ? '' : 'line-clamp-3'}`}>{socialText}</Card.Description>
        : <>
          <Card.Title ref={measurePrimary} className={`type-card-title ${expanded ? '' : 'line-clamp-2'}`}>{card.title}</Card.Title>
          {card.summary && <Card.Description ref={measureSecondary} className={`type-body mt-1.5 text-muted ${expanded ? '' : 'line-clamp-2'}`}>{card.summary}</Card.Description>}
        </>}
    </button> : <div className="w-full px-[19px] pt-[18px] text-left">
      <span aria-label="来源信息" className="type-meta mb-2 flex items-center gap-2 text-muted">
        <AvatarRoot className="size-[25px] shrink-0">
          {card.sourceAvatar && <AvatarImage src={card.sourceAvatar} alt={card.source} />}
          <AvatarFallback>{card.source.slice(0, 1).toUpperCase()}</AvatarFallback>
        </AvatarRoot>
        {sourceParts.map((part, index) => <Fragment key={part}>
          {index > 0 && <span aria-hidden="true">·</span>}
          <span className="truncate">{part}</span>
        </Fragment>)}
        <span aria-hidden="true">·</span>
        <span>{relativeTime(card.publishedAt)}</span>
      </span>
      {social
        ? <Card.Description ref={measurePrimary} className="type-body whitespace-pre-wrap text-foreground line-clamp-3">{socialText}</Card.Description>
        : <>
          <Card.Title ref={measurePrimary} className="type-card-title line-clamp-2">{card.title}</Card.Title>
          {card.summary && <Card.Description ref={measureSecondary} className="type-body mt-1.5 text-muted line-clamp-2">{card.summary}</Card.Description>}
        </>}
    </div>}

    <div
      data-testid={`card-details-${card.id}`}
      data-state={expanded ? 'expanded' : 'collapsed'}
      aria-hidden={!expanded}
      className={`grid px-[19px] transition-[grid-template-rows,opacity] duration-[var(--inteliscope-motion-deliberate)] ease-out ${expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}
    >
      <div className="min-h-0 overflow-hidden">
        {detailLoading && <div role="status" aria-label="正在读取详情" className="grid gap-2 border-t border-separator py-3"><Skeleton className="h-4 w-4/5 rounded-md" /><Skeleton className="h-4 w-3/5 rounded-md" /></div>}
        {detailError && <p role="status" className="type-meta border-t border-separator py-3 text-muted">暂时无法读取更多内容；当前卡片仍可继续使用。</p>}
        {!detailLoading && !social && card.detailBody && <div className="type-prose border-t border-separator pb-1 pt-3 text-foreground whitespace-pre-wrap">
          {card.detailBody}
        </div>}
        {!detailLoading && card.mediaImages.length > 0 && <div className={`mt-3 grid gap-2 ${card.mediaImages.length > 1 ? 'grid-cols-2' : 'grid-cols-1'}`} aria-label={`${card.displayImageCount} 张可查看图片`}>
          {card.mediaImages.map((image, index) => <img
            key={image.url}
            className={`w-full rounded-xl bg-default object-cover ${card.mediaImages.length > 1 ? 'aspect-[4/3]' : 'max-h-96 object-contain'}`}
            src={image.url}
            alt={image.alt || `${card.sourceLabel} 内容图片 ${index + 1}`}
            width={image.width}
            height={image.height}
            loading="lazy"
          />)}
        </div>}
        {!detailLoading && incompleteMessage && <p className="type-meta mt-2 text-muted">{incompleteMessage}</p>}
      </div>
    </div>

    <Card.Footer className="flex flex-wrap items-center justify-between gap-2 px-[19px] pb-[15px] pt-[10px]">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5" aria-label="内容分类、频道和主题">
        <Chip size="sm" variant="soft" className="type-micro"><Chip.Label>{card.formatLabel}</Chip.Label></Chip>
        {imageCountLabel && <Chip size="sm" variant="soft" className="type-micro"><Chip.Label>{imageCountLabel}</Chip.Label></Chip>}
        <Chip size="sm" color="accent" variant="soft" className="type-micro"><Chip.Label>{card.channel}</Chip.Label></Chip>
        {card.topics.slice(0, 3).map((topic) => <Chip key={topic} size="sm" variant="soft" className="type-micro"><Chip.Label>{topic}</Chip.Label></Chip>)}
      </div>
      {canToggleExpansion && <Button
        size="sm"
        variant="ghost"
        className="type-meta ml-auto min-h-8 gap-1 text-muted"
        aria-label={`${expanded ? '收起' : '展开'} ${cardLabel}`}
        aria-expanded={expanded}
        onPress={onToggleExpanded}
      >{expanded ? '收起' : '展开'}{expanded ? <Icons.ChevronUp size={14} aria-hidden="true" /> : <Icons.ChevronDown size={14} aria-hidden="true" />}</Button>}
      <div
        data-card-actions
        className={`${canToggleExpansion ? '' : 'ml-auto'} flex items-center gap-1 opacity-100 transition-opacity duration-[var(--inteliscope-motion-standard)] pointer-fine:opacity-60 pointer-fine:group-hover/card:opacity-100 pointer-fine:group-focus-within/card:opacity-100`}
      >
        {externalUrl && <a
          href={externalUrl}
          target="_blank"
          rel="noreferrer"
          aria-label={`打开 ${cardLabel} 原文`}
          className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus active:scale-95 pointer-coarse:size-11 motion-reduce:transform-none"
        ><Icons.ExternalLink size={15} aria-hidden="true" /></a>}
        <Button
          size="sm"
          variant={card.userState.is_saved ? 'secondary' : 'ghost'}
          className="size-8 active:scale-95 pointer-coarse:size-11 motion-reduce:transform-none"
          isDisabled={readonly}
          aria-label={`${card.userState.is_saved ? '取消收藏' : '收藏'} ${cardLabel}`}
          onPress={onToggleSaved}
          isIconOnly
        >{card.userState.is_saved ? <Icons.BookmarkCheck size={15} aria-hidden="true" /> : <Icons.Bookmark size={15} aria-hidden="true" />}</Button>
        <Button
          size="sm"
          variant={inContext ? 'secondary' : 'ghost'}
          data-context-state={inContext ? 'selected' : 'idle'}
          className="size-8 active:scale-95 pointer-coarse:size-11 data-[context-state=selected]:bg-accent/15 data-[context-state=selected]:text-accent motion-reduce:transform-none"
          isDisabled={contextFull && !inContext}
          aria-label={`将 ${cardLabel} ${inContext ? '移出' : '加入'} Agent 上下文`}
          onPress={onToggleContext}
          isIconOnly
        >{inContext ? <Icons.Check size={15} aria-hidden="true" /> : <Icons.Sparkles size={15} aria-hidden="true" />}</Button>
        <details className="relative">
          <summary
            role="button"
            aria-label={`更多操作 ${cardLabel}`}
            className="flex size-8 cursor-pointer list-none items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus active:scale-95 pointer-coarse:size-11 motion-reduce:transform-none"
          ><Icons.MoreHorizontal size={16} aria-hidden="true" /></summary>
          <div className="absolute bottom-10 right-0 z-20 grid min-w-32 gap-1 rounded-xl border border-separator bg-overlay p-1 shadow-lg">
            <button disabled={readonly} type="button" className="type-control flex items-center gap-2 rounded-lg px-3 py-2 text-left disabled:opacity-40" onClick={() => onItemAction('is_read', !card.userState.is_read)}>
              <Icons.Check size={14} aria-hidden="true" />{card.userState.is_read ? '标记未读' : '标记已读'}
            </button>
            <button type="button" className="type-control flex items-center gap-2 rounded-lg px-3 py-2 text-left" onClick={() => void copySummary()}>
              <Icons.Copy size={14} aria-hidden="true" />复制摘要
            </button>
            {copyNotice && <span role="status" aria-live="polite" className="type-meta px-3 py-1 text-muted">{copyNotice}</span>}
            <button disabled={readonly} type="button" className="type-control flex items-center gap-2 rounded-lg px-3 py-2 text-left disabled:opacity-40" onClick={() => onItemAction('dismissed', !card.userState.dismissed)}>
              <Icons.EyeOff size={14} aria-hidden="true" />{card.userState.dismissed ? '取消忽略' : '忽略'}
            </button>
          </div>
        </details>
      </div>
    </Card.Footer>
  </Card>
}

export function VirtualFeed(props: VirtualFeedProps) {
  const freshEdge = props.freshEdge ?? 'end'
  const sourceItemIds = props.sourceItemIds ?? props.cards.map((card) => card.id)
  const sourceSignature = sourceItemIds.join('\u0000')
  const cardsSignature = props.cards.map((card) => card.id).join('\u0000')
  const scrollRef = useRef<HTMLDivElement>(null)
  const wasNearFreshEdge = useRef(true)
  const previousFreshEdge = useRef(freshEdge)
  const previousSourceIds = useRef(new Set(sourceItemIds))
  const previousCardsSignature = useRef(cardsSignature)
  const viewportAnchor = useRef<ViewportAnchor | null>(null)
  const requestedRefreshAnchor = useRef<ViewportAnchor | null>(null)
  const restorationAnchor = useRef<ViewportAnchor | null>(null)
  const pendingNavigation = useRef<PendingNavigation | null>(null)
  const pendingNavigationFrame = useRef<number | undefined>(undefined)
  const inlineScrollAnchor = useRef<number | null>(null)
  const inlineAnchorTimer = useRef<number | undefined>(undefined)
  const inlineAnchorFrame = useRef<number | undefined>(undefined)
  const didInitialScroll = useRef(false)
  const [newItemCount, setNewItemCount] = useState(0)
  const initialTargetIndex = props.navigationTargetId
    ? props.cards.findIndex((card) => card.id === props.navigationTargetId)
    : freshEdge === 'start' ? 0 : props.cards.length - 1
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
    initialOffset: freshEdge === 'start'
      ? 0
      : Math.max(0, (Math.max(0, initialTargetIndex) + 1) * collapsedEstimate - 720),
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
    window.cancelAnimationFrame(pendingNavigationFrame.current ?? 0)
    pendingNavigationFrame.current = undefined
    window.clearTimeout(inlineAnchorTimer.current)
    window.cancelAnimationFrame(inlineAnchorFrame.current ?? 0)
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
        if (pendingNavigation.current !== navigation) return
        pendingNavigationFrame.current = undefined
        const target = clampPendingNavigation(navigation, cardsRef.current.length)
        pendingNavigation.current = target
        if (target.index === 0 && scrollRef.current) scrollRef.current.scrollTop = 0
        else virtualizerRef.current.scrollToIndex(target.index, { align: target.align })
      })
      pendingNavigationFrame.current = frame
      return () => {
        window.cancelAnimationFrame(frame)
        if (pendingNavigationFrame.current === frame) pendingNavigationFrame.current = undefined
      }
    }
    const anchor = requestedRefreshAnchor.current ?? restorationAnchor.current ?? viewportAnchor.current
    requestedRefreshAnchor.current = null
    const scroll = scrollRef.current
    if (!anchor || !scroll || wasNearFreshEdge.current) return
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
    const targetIndex = props.navigationTargetId
      ? props.cards.findIndex((card) => card.id === props.navigationTargetId)
      : freshEdge === 'start' ? 0 : props.cards.length - 1
    if (props.navigationTargetId && targetIndex < 0) return
    didInitialScroll.current = true
    const frame = window.requestAnimationFrame(() => {
      releaseNavigationOwnership()
      virtualizer.scrollToIndex(targetIndex, { align: props.navigationTargetId ? 'center' : freshEdge })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [freshEdge, props.cards, props.navigationTargetId, releaseNavigationOwnership, virtualizer])

  useEffect(() => {
    if (previousFreshEdge.current === freshEdge) return
    previousFreshEdge.current = freshEdge
    if (props.cards.length === 0) return
    const selectedIndex = props.expandedId ? props.cards.findIndex((card) => card.id === props.expandedId) : -1
    const targetIndex = selectedIndex >= 0 ? selectedIndex : freshEdge === 'start' ? 0 : props.cards.length - 1
    const align = selectedIndex >= 0 ? 'center' : freshEdge
    releaseNavigationOwnership()
    setNewItemCount(0)
    wasNearFreshEdge.current = selectedIndex < 0
    const frame = window.requestAnimationFrame(() => virtualizer.scrollToIndex(targetIndex, { align }))
    return () => window.cancelAnimationFrame(frame)
  }, [cardsSignature, freshEdge, props.cards, props.expandedId, releaseNavigationOwnership, virtualizer])

  useEffect(() => {
    const addedCount = sourceItemIds.filter((id) => !previousSourceIds.current.has(id)).length
    previousSourceIds.current = new Set(sourceItemIds)
    requestedRefreshAnchor.current = null
    if (addedCount <= 0) return
    if (wasNearFreshEdge.current) {
      releaseNavigationOwnership()
      const targetIndex = freshEdge === 'start' ? 0 : props.cards.length - 1
      virtualizer.scrollToIndex(targetIndex, { align: freshEdge })
    }
    else setNewItemCount((count) => count + addedCount)
  }, [freshEdge, props.cards.length, releaseNavigationOwnership, sourceItemIds, sourceSignature, virtualizer])

  const virtualItems = virtualizer.getVirtualItems()

  function updateScrollState() {
    const element = scrollRef.current
    if (!element) return
    wasNearFreshEdge.current = freshEdge === 'start'
      ? element.scrollTop <= 96
      : element.scrollHeight - element.scrollTop - element.clientHeight <= 96
    if (wasNearFreshEdge.current) setNewItemCount(0)
    const visible = virtualizer.getVirtualItems().filter((item) => item.end >= element.scrollTop && item.start <= element.scrollTop + element.clientHeight)
    if (visible.length) {
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
    <div
      ref={scrollRef}
      data-testid="workbench-feed-scroll"
      data-feed-visual="quiet-studio"
      data-fresh-edge={freshEdge}
      className="quiet-scroll-region min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-3 py-4 [overflow-anchor:none] sm:px-5"
      onScroll={updateScrollState}
      onWheel={cancelInlineAnchor}
      onTouchStart={cancelInlineAnchor}
      onPointerDown={cancelInlineAnchor}
      onKeyDown={cancelInlineAnchor}
    >
      <div className="relative mx-auto w-full max-w-[var(--inteliscope-width-reading)]" style={{ height: virtualizer.getTotalSize() }}>
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
              detailLoading={card.id === props.expandedId && props.detailLoading}
              detailError={card.id === props.expandedId && props.detailError}
              readonly={props.readonly}
              onToggleExpanded={() => toggleExpandedInline(card.id)}
              onToggleSaved={() => props.onToggleSaved(card.id, !card.userState.is_saved)}
              onToggleContext={() => props.onToggleContext(card)}
              onItemAction={(action, value) => props.onItemAction(card.id, action, value)}
            />
          </div>
        })}
      </div>
    </div>
    {newItemCount > 0 && <Button
      size="sm"
      className={`absolute left-1/2 z-10 -translate-x-1/2 ${freshEdge === 'start' ? 'top-4' : 'bottom-4'}`}
      aria-label={`查看 ${newItemCount} 条新内容`}
      onPress={() => {
        releaseNavigationOwnership()
        setNewItemCount(0)
        wasNearFreshEdge.current = true
        const targetIndex = freshEdge === 'start' ? 0 : props.cards.length - 1
        virtualizer.scrollToIndex(targetIndex, { align: freshEdge })
      }}
    >{newItemCount} 条新内容</Button>}
  </div>
}
