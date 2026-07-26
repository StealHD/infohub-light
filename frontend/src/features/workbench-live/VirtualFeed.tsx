import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import {
  AvatarFallback,
  AvatarImage,
  AvatarRoot,
  Button,
  Card,
  Icons,
  MetaTag,
  Modal,
  Popover,
  Skeleton,
  Tooltip,
  TooltipTriggerButton,
  topAnchoredTooltipProps,
} from '../../design-system'
import { relativeTime, safeExternalUrl } from '../feed/feedModel'
import { workbenchSourceLabels, type WorkbenchCardModel } from './workbenchModel'
import { clampPendingNavigation, type PendingNavigation } from './workbenchNavigation'
import { workbenchRefreshRequestEvent } from './workbenchRefresh'
import { WORKBENCH_COLLAPSED_ROW_PX, WORKBENCH_EXPANDED_ROW_PX } from './workbenchLayout'

type VirtualFeedProps = {
  freshEdge?: 'start' | 'end'
  resetToTopKey?: string
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
  onItemAction: (id: string, dismissed: boolean) => void
}

const collapsedEstimate = WORKBENCH_COLLAPSED_ROW_PX
const expandedEstimate = WORKBENCH_EXPANDED_ROW_PX

type ViewportAnchor = { id: string; offset: number }

type MediaViewerState = {
  cardLabel: string
  images: WorkbenchCardModel['mediaImages']
  index: number
}

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
    window.addEventListener('resize', measure)
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    elements.forEach((element) => observer?.observe(element))
    return () => {
      window.removeEventListener('resize', measure)
      observer?.disconnect()
    }
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
  contextCount,
  actionMenuOpen,
  detailLoading,
  detailError,
  readonly,
  onToggleExpanded,
  onToggleSaved,
  onToggleContext,
  onActionMenuOpenChange,
  onItemAction,
  onOpenMedia,
}: {
  card: WorkbenchCardModel
  expanded: boolean
  inContext: boolean
  contextFull: boolean
  contextCount: number
  actionMenuOpen: boolean
  detailLoading?: boolean
  detailError?: boolean
  readonly?: boolean
  onToggleExpanded: () => void
  onToggleSaved: () => void
  onToggleContext: () => void
  onActionMenuOpenChange: (open: boolean) => void
  onItemAction: (dismissed: boolean) => void
  onOpenMedia: (index: number, trigger: HTMLButtonElement) => void
}) {
  const externalUrl = safeExternalUrl(card.url)
  const social = card.displayKind === 'social'
  const socialText = expanded ? card.detailBody || card.primaryText : card.primaryText
  const cardLabel = social ? `${card.sourceLabel}: ${card.primaryText}` : card.title
  const sourceParts = workbenchSourceLabels(card)
  const [copyNotice, setCopyNotice] = useState('')
  const copyNoticeTimer = useRef<number | undefined>(undefined)
  const actionMenuTriggerRef = useRef<HTMLDivElement>(null)
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
  const detailsId = `card-details-${card.id}`

  useEffect(() => () => window.clearTimeout(copyNoticeTimer.current), [])

  function setActionMenuOpen(open: boolean) {
    onActionMenuOpenChange(open)
    if (!open) {
      window.requestAnimationFrame(() => {
        if (actionMenuTriggerRef.current?.isConnected) actionMenuTriggerRef.current.focus()
      })
    }
  }

  async function copySummary() {
    window.clearTimeout(copyNoticeTimer.current)
    try {
      if (typeof navigator.clipboard?.writeText !== 'function') throw new Error('Clipboard API unavailable')
      await navigator.clipboard.writeText(social ? socialText : card.summary || card.title)
      setCopyNotice('摘要已复制')
    } catch {
      setCopyNotice('复制失败，请手动复制')
    }
    setActionMenuOpen(false)
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
      aria-controls={detailsId}
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
      id={detailsId}
      data-testid={detailsId}
      data-state={expanded ? 'expanded' : 'collapsed'}
      aria-hidden={!expanded}
      inert={!expanded}
      className={`grid px-[19px] transition-[grid-template-rows,opacity] duration-[var(--inteliscope-motion-deliberate)] ease-out ${expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}
    >
      <div className="min-h-0 overflow-hidden">
        {detailLoading && <div role="status" aria-label="正在读取详情" className="grid gap-2 border-t border-separator py-3"><Skeleton className="h-4 w-4/5 rounded-md" /><Skeleton className="h-4 w-3/5 rounded-md" /></div>}
        {detailError && <p role="status" className="type-meta border-t border-separator py-3 text-muted">暂时无法读取更多内容；当前卡片仍可继续使用。</p>}
        {!detailLoading && !social && card.detailBody && <div className="type-prose border-t border-separator pb-1 pt-3 text-foreground whitespace-pre-wrap">
          {card.detailBody}
        </div>}
        {!detailLoading && card.mediaImages.length > 0 && <div className={`mt-3 grid gap-2 ${card.mediaImages.length > 1 ? 'grid-cols-2' : 'grid-cols-1'}`} aria-label={`${card.displayImageCount} 张可查看图片`}>
          {card.mediaImages.map((image, index) => <button
            key={image.url}
            type="button"
            aria-label={`查看第 ${index + 1} 张图片，共 ${card.mediaImages.length} 张`}
            className={`flex w-full items-center justify-center overflow-hidden rounded-xl bg-default focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${card.mediaImages.length > 1 ? 'aspect-[4/3]' : 'max-h-96'}`}
            onClick={(event) => onOpenMedia(index, event.currentTarget)}
          >
            <img
              className={`w-full object-contain ${card.mediaImages.length > 1 ? 'h-full' : 'max-h-96'}`}
              src={image.url}
              alt={image.alt || `${card.sourceLabel} 内容图片 ${index + 1}`}
              width={image.width}
              height={image.height}
              loading="lazy"
            />
          </button>)}
        </div>}
        {!detailLoading && incompleteMessage && <p className="type-meta mt-2 text-muted">{incompleteMessage}</p>}
      </div>
    </div>

    <Card.Footer className="flex items-center gap-2 px-[19px] pb-[15px] pt-[10px]">
      <div
        data-card-expand-zone={canToggleExpansion ? 'true' : 'false'}
        className="type-meta flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5 gap-y-1 self-stretch py-1 text-left text-muted"
        aria-label="内容分类、频道和主题"
      >
        <span>{card.formatLabel}</span>
        {imageCountLabel && <>
          <span aria-hidden="true">·</span>
          <span>{card.mediaTruncated ? `图片 ${card.displayImageCount}/${card.totalImageCount}` : `图片 ${card.totalImageCount}`}</span>
        </>}
        <MetaTag tone="accent">{card.channel}</MetaTag>
        {card.topics.slice(0, 2).map((topic) => <span key={topic}>#{topic.replace(/^#/, '')}</span>)}
        {card.topics.length > 2 && <span aria-label={`另有 ${card.topics.length - 2} 个主题`}>+{card.topics.length - 2}</span>}
      </div>
      {canToggleExpansion && <Tooltip delay={600}>
        <TooltipTriggerButton
          data-expand-trigger
          className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground active:scale-95 pointer-coarse:size-11 motion-reduce:transform-none"
          aria-label={`${expanded ? '收起' : '展开'} ${cardLabel}`}
          aria-controls={detailsId}
          aria-expanded={expanded}
          onClick={onToggleExpanded}
        >{expanded ? <Icons.FoldVertical size={15} aria-hidden="true" /> : <Icons.UnfoldVertical size={15} aria-hidden="true" />}</TooltipTriggerButton>
        <Tooltip.Content {...topAnchoredTooltipProps}>{expanded ? '收起内容' : '展开内容'}</Tooltip.Content>
      </Tooltip>}
      <div
        data-card-actions
        className="flex shrink-0 items-center gap-1 opacity-100 transition-opacity duration-[var(--inteliscope-motion-standard)] pointer-fine:opacity-60 pointer-fine:group-hover/card:opacity-100 pointer-fine:group-focus-within/card:opacity-100"
      >
        {externalUrl && <Tooltip delay={600}>
          <Tooltip.Trigger<'a'> render={(triggerProps) => <a
            {...triggerProps}
            href={externalUrl}
            target="_blank"
            rel="noreferrer"
            role={undefined}
            aria-label={`打开 ${cardLabel} 原文`}
            className={`${triggerProps.className ?? ''} inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus active:scale-95 pointer-coarse:size-11 motion-reduce:transform-none`}
          ><Icons.ExternalLink size={15} aria-hidden="true" /></a>} />
          <Tooltip.Content {...topAnchoredTooltipProps}>在新窗口打开原文</Tooltip.Content>
        </Tooltip>}
        <Tooltip delay={600}>
          <TooltipTriggerButton
            className={`size-8 rounded-lg active:scale-95 pointer-coarse:size-11 motion-reduce:transform-none ${card.userState.is_saved ? 'bg-default text-accent' : 'text-muted hover:bg-default hover:text-foreground'}`}
            disabled={readonly}
            aria-label={`${card.userState.is_saved ? '取消收藏' : '收藏'} ${cardLabel}`}
            onClick={onToggleSaved}
          >{card.userState.is_saved ? <Icons.BookmarkCheck size={15} aria-hidden="true" /> : <Icons.Bookmark size={15} aria-hidden="true" />}</TooltipTriggerButton>
          <Tooltip.Content {...topAnchoredTooltipProps}>{card.userState.is_saved ? '从收藏中移除' : '加入收藏'}</Tooltip.Content>
        </Tooltip>
        <button
          type="button"
          data-context-state={inContext ? 'selected' : 'idle'}
          className="type-control inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-lg bg-transparent px-2 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus active:scale-95 pointer-coarse:min-h-11 data-[context-state=selected]:bg-accent/15 data-[context-state=selected]:text-accent data-[context-state=selected]:ring-1 data-[context-state=selected]:ring-accent/45 motion-reduce:transform-none"
          disabled={contextFull && !inContext}
          aria-pressed={inContext}
          aria-label={`将 ${cardLabel} ${inContext ? '移出' : '加入'} Agent 上下文`}
          onClick={onToggleContext}
        >
          <Icons.Sparkles size={15} fill="currentColor" aria-hidden="true" />
          <span>{inContext ? `已加入 ${contextCount}/8` : '问 Agent'}</span>
        </button>
        <Popover isOpen={actionMenuOpen} onOpenChange={setActionMenuOpen}>
          <Popover.Trigger
            ref={actionMenuTriggerRef}
            aria-label={`更多操作 ${cardLabel}`}
            title="复制摘要或忽略这条内容"
            className="flex size-8 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus active:scale-95 pointer-coarse:size-11 motion-reduce:transform-none"
          ><Icons.MoreHorizontal size={16} aria-hidden="true" /></Popover.Trigger>
          <Popover.Content placement="top end" offset={6} className="z-40 min-w-36 p-0">
            <Popover.Dialog aria-label={`${cardLabel} 更多操作`} className="grid gap-1 p-1">
              <button type="button" className="type-control flex items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus" onClick={() => void copySummary()}>
                <Icons.Copy size={14} aria-hidden="true" />复制摘要
              </button>
              <button
                disabled={readonly}
                type="button"
                className="type-control flex items-center gap-2 rounded-lg px-3 py-2 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus disabled:opacity-40"
                onClick={() => {
                  setActionMenuOpen(false)
                  onItemAction(!card.userState.dismissed)
                }}
              >
                <Icons.EyeOff size={14} aria-hidden="true" />{card.userState.dismissed ? '取消忽略' : '忽略'}
              </button>
            </Popover.Dialog>
          </Popover.Content>
        </Popover>
        {copyNotice && <span role="status" aria-live="polite" className="sr-only">{copyNotice}</span>}
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
  const previousResetToTopKey = useRef(props.resetToTopKey)
  const previousSourceIds = useRef(new Set(sourceItemIds))
  const previousCardsSignature = useRef(cardsSignature)
  const viewportAnchor = useRef<ViewportAnchor | null>(null)
  const requestedRefreshAnchor = useRef<ViewportAnchor | null>(null)
  const restorationAnchor = useRef<ViewportAnchor | null>(null)
  const pendingNavigation = useRef<PendingNavigation | null>(null)
  const pendingNavigationFrame = useRef<number | undefined>(undefined)
  const resetToTopRequest = useRef<object | null>(null)
  const resetToTopFrame = useRef<number | undefined>(undefined)
  const inlineScrollAnchor = useRef<number | null>(null)
  const inlineAnchorTimer = useRef<number | undefined>(undefined)
  const inlineAnchorFrame = useRef<number | undefined>(undefined)
  const didInitialScroll = useRef(false)
  const [newItemCount, setNewItemCount] = useState(0)
  const [openActionCardId, setOpenActionCardId] = useState<string | null>(null)
  const [mediaViewer, setMediaViewer] = useState<MediaViewerState | null>(null)
  const [mediaLoading, setMediaLoading] = useState(false)
  const [mediaError, setMediaError] = useState(false)
  const [mediaRetryKey, setMediaRetryKey] = useState(0)
  const mediaTriggerRef = useRef<HTMLButtonElement | null>(null)
  const mediaSwipeStart = useRef<number | null>(null)
  const mediaViewerOpen = mediaViewer !== null
  const activeMediaUrl = mediaViewer?.images[mediaViewer.index]?.url
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
    initialOffset: props.navigationTargetId && initialTargetIndex >= 0
      ? Math.max(0, (initialTargetIndex + 1) * collapsedEstimate - 720)
      : 0,
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

  useEffect(() => {
    if (!mediaViewerOpen) return
    const navigateWithArrowKey = (event: KeyboardEvent) => {
      const delta = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0
      if (!delta) return
      event.preventDefault()
      setMediaViewer((current) => {
        if (!current || current.images.length < 2) return current
        return {
          ...current,
          index: (current.index + delta + current.images.length) % current.images.length,
        }
      })
    }
    window.addEventListener('keydown', navigateWithArrowKey)
    return () => window.removeEventListener('keydown', navigateWithArrowKey)
  }, [mediaViewerOpen])

  useEffect(() => {
    if (!activeMediaUrl) return
    setMediaLoading(true)
    setMediaError(false)
    if (!mediaViewer || mediaViewer.images.length < 2 || typeof Image === 'undefined') return
    const neighborIndexes = [
      (mediaViewer.index - 1 + mediaViewer.images.length) % mediaViewer.images.length,
      (mediaViewer.index + 1) % mediaViewer.images.length,
    ]
    neighborIndexes.forEach((index) => {
      const image = new Image()
      image.src = mediaViewer.images[index]?.url ?? ''
    })
  }, [activeMediaUrl, mediaRetryKey, mediaViewer])

  const releaseNavigationOwnership = useCallback(() => {
    requestedRefreshAnchor.current = null
    restorationAnchor.current = null
    inlineScrollAnchor.current = null
    viewportAnchor.current = null
    pendingNavigation.current = null
    window.cancelAnimationFrame(pendingNavigationFrame.current ?? 0)
    pendingNavigationFrame.current = undefined
    resetToTopRequest.current = null
    window.cancelAnimationFrame(resetToTopFrame.current ?? 0)
    resetToTopFrame.current = undefined
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
    const explicitAnchor = requestedRefreshAnchor.current
    const anchor = explicitAnchor ?? restorationAnchor.current ?? viewportAnchor.current
    requestedRefreshAnchor.current = null
    const scroll = scrollRef.current
    if (!anchor || !scroll || (!explicitAnchor && wasNearFreshEdge.current)) return
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
    if (!props.navigationTargetId) {
      didInitialScroll.current = true
      wasNearFreshEdge.current = freshEdge === 'start'
      return
    }
    const targetIndex = props.cards.findIndex((card) => card.id === props.navigationTargetId)
    if (targetIndex < 0) return
    didInitialScroll.current = true
    wasNearFreshEdge.current = false
    const frame = window.requestAnimationFrame(() => {
      releaseNavigationOwnership()
      virtualizer.scrollToIndex(targetIndex, { align: 'center' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [freshEdge, props.cards, props.navigationTargetId, releaseNavigationOwnership, virtualizer])

  useLayoutEffect(() => {
    if (props.resetToTopKey === undefined || previousResetToTopKey.current === props.resetToTopKey) return
    previousResetToTopKey.current = props.resetToTopKey
    releaseNavigationOwnership()
    setNewItemCount(0)
    wasNearFreshEdge.current = freshEdge === 'start'
    const request = {}
    resetToTopRequest.current = request
    let remainingFrames = 120
    let stableFrames = 0
    const reset = () => {
      if (resetToTopRequest.current !== request) return
      const scroll = scrollRef.current
      if (!scroll) {
        resetToTopRequest.current = null
        resetToTopFrame.current = undefined
        return
      }
      stableFrames = scroll.scrollTop <= 0.5 ? stableFrames + 1 : 0
      scroll.scrollTop = 0
      if (props.cards.length > 0) virtualizerRef.current.scrollToIndex(0, { align: 'start' })
      viewportAnchor.current = readViewportAnchor(scroll)
      remainingFrames -= 1
      if (stableFrames >= 6 || remainingFrames <= 0) {
        resetToTopRequest.current = null
        resetToTopFrame.current = undefined
        return
      }
      resetToTopFrame.current = window.requestAnimationFrame(reset)
    }
    resetToTopFrame.current = window.requestAnimationFrame(reset)
    return () => {
      if (resetToTopRequest.current === request) resetToTopRequest.current = null
      window.cancelAnimationFrame(resetToTopFrame.current ?? 0)
      resetToTopFrame.current = undefined
    }
  }, [freshEdge, props.cards.length, props.resetToTopKey, releaseNavigationOwnership])

  useEffect(() => {
    if (previousFreshEdge.current === freshEdge) return
    previousFreshEdge.current = freshEdge
    setNewItemCount(0)
  }, [freshEdge])

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

  function openMediaViewer(card: WorkbenchCardModel, index: number, trigger: HTMLButtonElement) {
    const requestedImage = card.mediaImages[index]
    if (!requestedImage?.url.startsWith('/api/media/')) return
    const images = card.mediaImages.filter((image) => image.url.startsWith('/api/media/')).slice(0, 6)
    const safeIndex = images.findIndex((image) => image.url === requestedImage.url)
    if (safeIndex < 0) return
    mediaTriggerRef.current = trigger
    setMediaViewer({ cardLabel: cardLabelForViewer(card), images, index: safeIndex })
  }

  function moveMediaViewer(delta: number) {
    setMediaViewer((current) => {
      if (!current || current.images.length < 2) return current
      return {
        ...current,
        index: (current.index + delta + current.images.length) % current.images.length,
      }
    })
  }

  function closeMediaViewer() {
    const trigger = mediaTriggerRef.current
    mediaTriggerRef.current = null
    setMediaViewer(null)
    window.requestAnimationFrame(() => {
      if (trigger?.isConnected) trigger.focus()
    })
  }

  const activeMedia = mediaViewer?.images[mediaViewer.index]

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
      <div data-feed-reading-frame className="relative mx-auto w-full max-w-[var(--inteliscope-width-reading)]" style={{ height: virtualizer.getTotalSize() }}>
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
              contextCount={props.contextIds.length}
              actionMenuOpen={openActionCardId === card.id}
              detailLoading={card.id === props.expandedId && props.detailLoading}
              detailError={card.id === props.expandedId && props.detailError}
              readonly={props.readonly}
              onToggleExpanded={() => toggleExpandedInline(card.id)}
              onToggleSaved={() => props.onToggleSaved(card.id, !card.userState.is_saved)}
              onToggleContext={() => props.onToggleContext(card)}
              onActionMenuOpenChange={(open) => setOpenActionCardId(open ? card.id : null)}
              onItemAction={(dismissed) => props.onItemAction(card.id, dismissed)}
              onOpenMedia={(index, trigger) => openMediaViewer(card, index, trigger)}
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
    <Modal isOpen={Boolean(mediaViewer && activeMedia)} onOpenChange={(open) => !open && closeMediaViewer()}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开图片预览</Modal.Trigger>
      <Modal.Backdrop variant="opaque" isDismissable>
        <Modal.Container size="cover" placement="center" className="p-3 sm:w-full sm:p-6">
          <Modal.Dialog className="h-full max-w-none overflow-hidden rounded-2xl bg-overlay p-0 text-foreground">
            <div className="relative flex h-full min-h-0 flex-col">
              <Modal.Header className="sr-only">
                <Modal.Heading>{mediaViewer ? `${mediaViewer.cardLabel} 图片预览` : '图片预览'}</Modal.Heading>
              </Modal.Header>
              <Modal.CloseTrigger
                aria-label="关闭图片预览"
                className="z-20 size-11 rounded-full bg-background/80 text-foreground hover:bg-default"
              />
              <Modal.Body
                className="relative m-0 grid min-h-0 touch-pan-y place-items-center overflow-hidden bg-default/40 p-0 pb-20 text-foreground"
                onPointerDown={(event) => {
                  if (event.pointerType === 'mouse') return
                  mediaSwipeStart.current = event.clientX
                  event.currentTarget.setPointerCapture?.(event.pointerId)
                }}
                onPointerUp={(event) => {
                  const start = mediaSwipeStart.current
                  mediaSwipeStart.current = null
                  if (start === null || mediaViewer?.images.length === 1) return
                  const distance = event.clientX - start
                  if (Math.abs(distance) >= 48) moveMediaViewer(distance > 0 ? -1 : 1)
                }}
                onPointerCancel={() => { mediaSwipeStart.current = null }}
              >
                {mediaLoading && !mediaError && <Skeleton aria-label="正在加载图片" className="absolute inset-[10%] rounded-2xl" />}
                {activeMedia && <img
                  key={`${activeMedia.url}:${mediaRetryKey}`}
                  src={activeMedia.url}
                  alt={activeMedia.alt || `${mediaViewer?.cardLabel || '内容'} 图片 ${(mediaViewer?.index ?? 0) + 1}`}
                  className={`z-[1] max-h-full max-w-full object-contain transition-opacity motion-reduce:transition-none ${mediaLoading || mediaError ? 'opacity-0' : 'opacity-100'}`}
                  width={activeMedia.width}
                  height={activeMedia.height}
                  onLoad={() => {
                    setMediaLoading(false)
                    setMediaError(false)
                  }}
                  onError={() => {
                    setMediaLoading(false)
                    setMediaError(true)
                  }}
                />}
                {mediaError && <div role="alert" className="z-[2] grid justify-items-center gap-3 rounded-2xl bg-background/90 p-5 text-center">
                  <Icons.ImageOff size={28} className="text-muted" aria-hidden="true" />
                  <p className="type-control">图片加载失败</p>
                  <Button size="sm" variant="secondary" onPress={() => {
                    setMediaError(false)
                    setMediaLoading(true)
                    setMediaRetryKey((value) => value + 1)
                  }}>重试这张图片</Button>
                </div>}
                {mediaViewer && <p
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                  className="type-control absolute left-1/2 top-4 z-10 -translate-x-1/2 rounded-full bg-background/80 px-3 py-1.5 text-foreground"
                >{mediaViewer.index + 1} / {mediaViewer.images.length}</p>}
                {mediaViewer && mediaViewer.images.length > 1 && <>
                  <Button
                    isIconOnly
                    variant="secondary"
                    className="absolute left-3 z-10 size-11 rounded-full bg-background/80 text-foreground hover:bg-default sm:left-5"
                    aria-label="上一张图片"
                    onPress={() => moveMediaViewer(-1)}
                  ><Icons.ChevronLeft size={22} aria-hidden="true" /></Button>
                  <Button
                    isIconOnly
                    variant="secondary"
                    className="absolute right-3 z-10 size-11 rounded-full bg-background/80 text-foreground hover:bg-default sm:right-5"
                    aria-label="下一张图片"
                    onPress={() => moveMediaViewer(1)}
                  ><Icons.ChevronRight size={22} aria-hidden="true" /></Button>
                  <div aria-label="图片缩略图" className="quiet-scroll-region absolute inset-x-14 bottom-3 z-10 flex justify-center gap-2 overflow-x-auto">
                    {mediaViewer.images.map((image, index) => <button
                      key={image.url}
                      type="button"
                      aria-label={`切换到第 ${index + 1} 张图片`}
                      aria-current={index === mediaViewer.index ? 'true' : undefined}
                      className={`size-12 shrink-0 overflow-hidden rounded-lg border-2 bg-background/80 focus-visible:outline-2 focus-visible:outline-focus ${index === mediaViewer.index ? 'border-accent' : 'border-transparent opacity-70 hover:opacity-100'}`}
                      onClick={() => setMediaViewer((current) => current ? { ...current, index } : current)}
                    >
                      <img src={image.url} alt="" className="size-full object-cover" loading="eager" />
                    </button>)}
                  </div>
                </>}
              </Modal.Body>
            </div>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  </div>
}

function cardLabelForViewer(card: WorkbenchCardModel): string {
  return card.displayKind === 'social' ? `${card.sourceLabel}: ${card.primaryText}` : card.title
}
