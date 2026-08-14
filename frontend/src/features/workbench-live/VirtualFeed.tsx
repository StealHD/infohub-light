import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import {
  Button,
  Card,
  ImageGalleryModal,
  Icons,
  MetaTag,
  Popover,
  Skeleton,
  Tooltip,
  TooltipTriggerButton,
  topAnchoredTooltipProps,
} from '../../design-system'
import { relativeTime, safeExternalUrl } from '../feed/feedModel'
import { SourceAvatar } from '../source-avatar/SourceAvatar'
import { cardLabelForViewer, workbenchSourceLabels, type WorkbenchCardModel } from './workbenchModel'
import { clampPendingNavigation, type PendingNavigation } from './workbenchNavigation'
import { workbenchRefreshRequestEvent } from './workbenchRefresh'
import { WORKBENCH_COLLAPSED_ROW_PX, WORKBENCH_EXPANDED_ROW_PX } from './workbenchLayout'
import { workbenchMediaLabels, workbenchTimelineLabel } from './workbenchCardPresentation'
import { useMeasuredClampOverflow } from './useMeasuredClampOverflow'

type VirtualFeedProps = {
  topInset?: number
  freshEdge?: 'start' | 'end'
  resetToTopKey?: string
  cards: WorkbenchCardModel[]
  sourceItemIds?: string[]
  trackNewItems?: boolean
  showTimelineBucket?: boolean
  feedWindowDays?: number
  footer?: ReactNode
  terminal?: ReactNode
  terminalKey?: string
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
  onTerminalReach?: () => void
}

const collapsedEstimate = WORKBENCH_COLLAPSED_ROW_PX
const expandedEstimate = WORKBENCH_EXPANDED_ROW_PX

type ViewportAnchor = { id: string; offset: number }

export type MediaViewerState = {
  cardLabel: string
  images: WorkbenchCardModel['mediaImages']
  index: number
}

function readViewportAnchor(scroll: HTMLDivElement, topInset: number): ViewportAnchor | null {
  const bounds = scroll.getBoundingClientRect()
  const effectiveTop = bounds.top + topInset
  const topCard = Array.from(scroll.querySelectorAll<HTMLElement>('[data-testid="workbench-card"]'))
    .filter((card) => card.getBoundingClientRect().bottom > effectiveTop)
    .sort((left, right) => left.getBoundingClientRect().top - right.getBoundingClientRect().top)[0]
  const topRow = topCard?.closest<HTMLElement>('[data-item-id]')
  if (!topCard || !topRow?.dataset.itemId) return null
  return { id: topRow.dataset.itemId, offset: topCard.getBoundingClientRect().top - effectiveTop }
}

export function WorkbenchCard({
  card,
  expanded,
  inContext,
  contextFull,
  contextCount,
  actionMenuOpen,
  detailLoading,
  detailError,
  readonly,
  showTimelineBucket,
  feedWindowDays,
  onToggleExpanded,
  onToggleSaved,
  onToggleContext,
  onActionMenuOpenChange,
  onItemAction,
  onOpenMedia,
  variant = 'timeline',
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
  showTimelineBucket?: boolean
  feedWindowDays?: number
  onToggleExpanded: () => void
  onToggleSaved: () => void
  onToggleContext: () => void
  onActionMenuOpenChange: (open: boolean) => void
  onItemAction: (dismissed: boolean) => void
  onOpenMedia: (index: number, trigger: HTMLButtonElement) => void
  variant?: 'timeline' | 'source-overview'
}) {
  const sourceOverview = variant === 'source-overview'
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
  } = useMeasuredClampOverflow(card.id, expanded, `${card.primaryText}\u0000${card.title}\u0000${card.summary ?? ''}`)
  const canExpand = measuredOverflow || card.hasDistinctDetail || card.mediaImages.length > 0
  const canToggleExpansion = canExpand || expanded
  const { imageCountLabel, mediaPreviewActionLabel, mediaPreviewBadge } = workbenchMediaLabels(card)
  const mediaPreview = card.mediaImages[0]
  const mediaStackDepth = Math.min(Math.max(card.totalImageCount, card.displayImageCount) - 1, 2)
  const showCompactMedia = !expanded && Boolean(mediaPreview)
  const incompleteMessage = card.bodyCompleteness === 'excerpt_only' || card.bodyTruncated || card.excerptTruncated
    ? '仅获取到内容片段，打开原文查看完整内容。'
    : ''
  const detailsId = `card-details-${card.id}`
  const timelineLabel = workbenchTimelineLabel(card, feedWindowDays)
  const classificationMetadata = <>
      <span>{card.formatLabel}</span>
      {imageCountLabel && <>
        <span aria-hidden="true">·</span>
        <span>{card.mediaTruncated ? `图片 ${card.displayImageCount}/${card.totalImageCount}` : `图片 ${card.totalImageCount}`}</span>
      </>}
      <MetaTag tone="accent">{card.channel}</MetaTag>
      {card.topics.slice(0, 2).map((topic) => <span key={topic}>#{topic.replace(/^#/, '')}</span>)}
      {card.topics.length > 2 && <span aria-label={`另有 ${card.topics.length - 2} 个主题`}>+{card.topics.length - 2}</span>}
    </>
  const summaryContent = <>
    {!sourceOverview && <span aria-label="来源信息" className="type-meta mb-2 flex min-w-0 items-center gap-2 text-muted">
      <SourceAvatar
        name={card.source}
        avatarUrl={card.sourceAvatar}
        platform={card.platformLabel}
        className="size-[25px] shrink-0"
      />
      {sourceParts.map((part, index) => <Fragment key={part}>
        {index > 0 && <span aria-hidden="true">·</span>}
        <span className="truncate">{part}</span>
      </Fragment>)}
      <span aria-hidden="true">·</span>
      <span className="shrink-0">{relativeTime(card.publishedAt)}</span>
      {showTimelineBucket && timelineLabel && <span aria-label={`时间归属：${timelineLabel}`} className="shrink-0 rounded-full bg-default px-2 py-0.5 text-foreground">{timelineLabel}</span>}
    </span>}
    {social
      ? <Card.Description ref={measurePrimary} className={`type-body whitespace-pre-wrap text-foreground ${expanded ? '' : sourceOverview ? 'line-clamp-2' : 'line-clamp-3'}`}>{socialText}</Card.Description>
      : <>
        <Card.Title ref={measurePrimary} className={`type-card-title ${expanded ? '' : 'line-clamp-2'}`}>{card.title}</Card.Title>
        {card.summary && <Card.Description ref={measureSecondary} className={`type-body mt-1.5 text-muted ${expanded ? '' : sourceOverview ? 'line-clamp-1' : 'line-clamp-2'}`}>{card.summary}</Card.Description>}
      </>}
  </>

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

  function handleCardClick(event: ReactMouseEvent<HTMLElement>) {
    if (!canToggleExpansion || !(event.target instanceof Element)) return
    if (event.target.closest('a, button, input, select, textarea, [role="button"], [data-card-actions]')) return
    onToggleExpanded()
  }

  return <Card
    data-testid="workbench-card"
    data-card-visual="quiet-studio"
    data-card-variant={variant}
    data-card-expanded={expanded ? 'true' : 'false'}
    role="article"
    aria-label={cardLabel}
    variant="secondary"
    className={sourceOverview
      ? 'group/card w-full gap-0 rounded-none border-0 bg-transparent p-0 shadow-none'
      : 'group/card w-full gap-0 rounded-[var(--inteliscope-radius-feed-card)] border border-separator bg-surface-secondary p-0 shadow-none transition-[background-color,border-color,transform,box-shadow] duration-[var(--inteliscope-motion-standard)] hover:-translate-y-px hover:border-border hover:bg-surface-tertiary focus-within:border-border motion-reduce:transform-none'}
    onClick={handleCardClick}
  >
    {canToggleExpansion
      ? showCompactMedia && mediaPreview
        ? <div
          data-card-media-layout="compact"
          className={`grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 ${sourceOverview ? 'px-0 pt-2' : 'px-[19px] pt-[18px]'}`}
        >
          <button
            type="button"
            className="min-w-0 cursor-pointer text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            aria-label={`打开详情 ${cardLabel}`}
            aria-controls={detailsId}
            aria-expanded={false}
            onClick={onToggleExpanded}
          >{summaryContent}</button>
          <button
            type="button"
            data-testid="card-media-stack"
            data-stack-depth={mediaStackDepth}
            aria-label={mediaPreviewActionLabel}
            className="group/media relative block min-h-11 min-w-11 shrink-0 pb-[6px] pr-[6px] text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus active:scale-95 motion-reduce:transform-none"
            onClick={(event) => onOpenMedia(0, event.currentTarget)}
          >
            {mediaStackDepth >= 2 && <span
              aria-hidden="true"
              data-card-media-stack-layer="back"
              className="pointer-events-none absolute bottom-0 left-[6px] right-0 top-[6px] rounded-[var(--inteliscope-radius-control)] border border-separator bg-default/55"
            />}
            {mediaStackDepth >= 1 && <span
              aria-hidden="true"
              data-card-media-stack-layer="middle"
              className="pointer-events-none absolute bottom-[3px] left-[3px] right-[3px] top-[3px] rounded-[var(--inteliscope-radius-control)] border border-separator bg-surface-tertiary"
            />}
            <span
              aria-hidden="true"
              data-card-media-stack-front
              className="relative z-10 block aspect-[4/3] w-[clamp(72px,15vw,88px)] overflow-hidden rounded-[var(--inteliscope-radius-control)] border border-separator bg-default transition-colors duration-[var(--inteliscope-motion-standard)] group-hover/media:border-border motion-reduce:transition-none"
            >
              <img
                className="size-full object-contain"
                src={mediaPreview.url}
                alt=""
                width={mediaPreview.width}
                height={mediaPreview.height}
                loading="lazy"
              />
            </span>
          </button>
        </div>
        : <button
          type="button"
          className={`w-full cursor-pointer text-left focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus ${sourceOverview ? 'px-0 pt-2' : 'px-[19px] pt-[18px]'}`}
          aria-label={`${expanded ? '收起详情' : '打开详情'} ${cardLabel}`}
          aria-controls={detailsId}
          aria-expanded={expanded}
          onClick={onToggleExpanded}
        >{summaryContent}</button>
      : <div className={`w-full text-left ${sourceOverview ? 'px-0 pt-2' : 'px-[19px] pt-[18px]'}`}>{summaryContent}</div>}

    <div
      id={detailsId}
      data-testid={detailsId}
      data-state={expanded ? 'expanded' : 'collapsed'}
      aria-hidden={!expanded}
      inert={!expanded}
      className={`grid ${sourceOverview ? 'px-0' : 'px-[19px]'} transition-[grid-template-rows,opacity] duration-[var(--inteliscope-motion-deliberate)] ease-out ${expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}
    >
      <div className="min-h-0 overflow-hidden">
        {detailLoading && <div role="status" aria-label="正在读取详情" className="grid gap-2 border-t border-separator py-3"><Skeleton className="h-4 w-4/5 rounded-md" /><Skeleton className="h-4 w-3/5 rounded-md" /></div>}
        {detailError && <p role="status" className="type-meta border-t border-separator py-3 text-muted">暂时无法读取更多内容；当前卡片仍可继续使用。</p>}
        {!detailLoading && !social && card.detailBody && <div className="type-prose border-t border-separator pb-1 pt-3 text-foreground whitespace-pre-wrap">
          {card.detailBody}
        </div>}
        {expanded && !detailLoading && mediaPreview && <div className="mt-3 flex justify-center" aria-label={`图片预览，共 ${card.displayImageCount} 张可查看图片`}>
          <button
            type="button"
            data-testid="card-media-preview"
            aria-label={mediaPreviewActionLabel}
            className="group/media relative flex aspect-[4/3] w-full max-w-lg items-center justify-center overflow-hidden rounded-xl bg-default focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            onClick={(event) => onOpenMedia(0, event.currentTarget)}
          >
            <img
              className="size-full object-contain"
              src={mediaPreview.url}
              alt={mediaPreview.alt || `${card.sourceLabel} 内容图片 1`}
              width={mediaPreview.width}
              height={mediaPreview.height}
              loading="lazy"
            />
            {(card.displayImageCount > 1 || card.mediaTruncated) && <span
              aria-hidden="true"
              className="type-control pointer-events-none absolute bottom-3 right-3 rounded-full bg-background/80 px-3 py-1.5 text-foreground shadow-sm"
            >{mediaPreviewBadge}</span>}
          </button>
        </div>}
        {!detailLoading && incompleteMessage && <p className="type-meta mt-2 text-muted">{incompleteMessage}</p>}
      </div>
    </div>

    {sourceOverview ? <Card.Footer className="flex items-center gap-1 px-0 pb-2 pt-1.5">
      <span className="type-meta min-w-0 flex-1 text-muted">{relativeTime(card.publishedAt)}</span>
      {canToggleExpansion && <Tooltip delay={600}>
        <TooltipTriggerButton
          data-expand-trigger
          className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground active:scale-95 pointer-coarse:size-11 motion-reduce:transform-none"
          aria-label={`${expanded ? '收起' : '展开'} ${cardLabel}`}
          aria-controls={detailsId}
          aria-expanded={expanded}
          onClick={onToggleExpanded}
        >{expanded ? <Icons.FoldVertical size={15} aria-hidden="true" /> : <Icons.UnfoldVertical size={15} aria-hidden="true" />}</TooltipTriggerButton>
        <Tooltip.Content {...topAnchoredTooltipProps}>{expanded ? '收起完整内容' : '展开完整内容'}</Tooltip.Content>
      </Tooltip>}
    </Card.Footer> : <Card.Footer className="flex items-center gap-2 px-[19px] pb-[15px] pt-[10px]">
      <div
        data-card-expand-zone={canToggleExpansion ? 'true' : 'false'}
        className={`type-meta flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5 gap-y-1 self-stretch py-1 text-left text-muted ${canToggleExpansion ? 'cursor-pointer' : ''}`}
        aria-label="内容分类、频道和主题"
      >{classificationMetadata}</div>
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
          ><Icons.Star size={15} fill={card.userState.is_saved ? 'currentColor' : 'none'} aria-hidden="true" /></TooltipTriggerButton>
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
    </Card.Footer>}
  </Card>
}

export function VirtualFeed(props: VirtualFeedProps) {
  const topInset = props.topInset ?? 64
  const freshEdge = props.freshEdge ?? 'end'
  const sourceItemIds = props.sourceItemIds ?? props.cards.map((card) => card.id)
  const sourceSignature = sourceItemIds.join('\u0000')
  const cardsSignature = props.cards.map((card) => card.id).join('\u0000')
  const layoutSignature = `${cardsSignature}\u0000${topInset}`
  const scrollRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<HTMLDivElement>(null)
  const terminalVisible = useRef(false)
  const onTerminalReachRef = useRef(props.onTerminalReach)
  const wasNearFreshEdge = useRef(true)
  const previousFreshEdge = useRef(freshEdge)
  const previousResetToTopKey = useRef(props.resetToTopKey)
  const previousSourceIds = useRef(new Set(sourceItemIds))
  const previousLayoutSignature = useRef(layoutSignature)
  const viewportAnchor = useRef<ViewportAnchor | null>(null)
  const requestedRefreshAnchor = useRef<ViewportAnchor | null>(null)
  const restorationAnchor = useRef<ViewportAnchor | null>(null)
  const pendingNavigation = useRef<PendingNavigation | null>(null)
  const pendingNavigationFrame = useRef<number | undefined>(undefined)
  const resetToTopRequest = useRef<object | null>(null)
  const resetToTopFrame = useRef<number | undefined>(undefined)
  const inlineScrollAnchor = useRef<ViewportAnchor | null>(null)
  const inlineAnchorFrame = useRef<number | undefined>(undefined)
  const didInitialScroll = useRef(false)
  const [newItemCount, setNewItemCount] = useState(0)
  const [openActionCardId, setOpenActionCardId] = useState<string | null>(null)
  const [mediaViewer, setMediaViewer] = useState<MediaViewerState | null>(null)
  const mediaTriggerRef = useRef<HTMLButtonElement | null>(null)
  const terminalEnabled = Boolean(props.terminal)
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
  onTerminalReachRef.current = props.onTerminalReach

  useEffect(() => {
    terminalVisible.current = false
    const terminal = terminalRef.current
    const scroll = scrollRef.current
    if (!terminalEnabled || !terminal || !scroll) return
    const setVisibility = (visible: boolean) => {
      if (visible && !terminalVisible.current) onTerminalReachRef.current?.()
      terminalVisible.current = visible
    }
    if (typeof IntersectionObserver !== 'undefined') {
      const observer = new IntersectionObserver(
        (entries) => setVisibility(Boolean(entries[0]?.isIntersecting)),
        { root: scroll, threshold: 0.01 },
      )
      observer.observe(terminal)
      return () => observer.disconnect()
    }
    const frame = window.requestAnimationFrame(() => {
      const rootBounds = scroll.getBoundingClientRect()
      const terminalBounds = terminal.getBoundingClientRect()
      setVisibility(
        terminalBounds.bottom >= rootBounds.top
        && terminalBounds.top <= rootBounds.bottom,
      )
    })
    return () => window.cancelAnimationFrame(frame)
  }, [props.terminalKey, terminalEnabled])

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
    window.cancelAnimationFrame(inlineAnchorFrame.current ?? 0)
  }, [])

  useEffect(() => {
    const capture = () => {
      const liveAnchor = scrollRef.current ? readViewportAnchor(scrollRef.current, topInset) : null
      const storedAnchor = viewportAnchor.current
      const anchor = liveAnchor ?? storedAnchor
      releaseNavigationOwnership()
      requestedRefreshAnchor.current = anchor
    }
    window.addEventListener(workbenchRefreshRequestEvent, capture)
    return () => window.removeEventListener(workbenchRefreshRequestEvent, capture)
  }, [releaseNavigationOwnership, topInset])

  useLayoutEffect(() => {
    if (previousLayoutSignature.current === layoutSignature) return
    previousLayoutSignature.current = layoutSignature
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
      const currentOffset = card.getBoundingClientRect().top - scroll.getBoundingClientRect().top - topInset
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
  }, [layoutSignature, topInset])

  useLayoutEffect(() => {
    const anchor = inlineScrollAnchor.current
    const scroll = scrollRef.current
    if (!anchor || !scroll) return

    let remainingFrames = 120
    let stableFrames = 0
    const restore = () => {
      if (inlineScrollAnchor.current !== anchor || remainingFrames <= 0) return
      remainingFrames -= 1
      const row = Array.from(scroll.querySelectorAll<HTMLElement>('[data-item-id]'))
        .find((element) => element.dataset.itemId === anchor.id)
      const card = row?.querySelector<HTMLElement>('[data-testid="workbench-card"]')
      if (!card) {
        inlineAnchorFrame.current = window.requestAnimationFrame(restore)
        return
      }
      const currentOffset = card.getBoundingClientRect().top - scroll.getBoundingClientRect().top - topInset
      const correction = currentOffset - anchor.offset
      if (Math.abs(correction) > 0.5) {
        stableFrames = 0
        scroll.scrollTop += correction
      } else stableFrames += 1
      // Keep correcting through the card's reveal/measurement window. A few
      // apparently stable frames are not enough when the production build
      // commits detail content or media geometry just after the first paint.
      if (stableFrames < 30) {
        inlineAnchorFrame.current = window.requestAnimationFrame(restore)
      } else {
        inlineScrollAnchor.current = null
        inlineAnchorFrame.current = undefined
      }
    }
    restore()
    return () => window.cancelAnimationFrame(inlineAnchorFrame.current ?? 0)
  }, [props.cards, props.expandedId, topInset])

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
      viewportAnchor.current = readViewportAnchor(scroll, topInset)
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
  }, [freshEdge, props.cards.length, props.resetToTopKey, releaseNavigationOwnership, topInset])

  useEffect(() => {
    if (previousFreshEdge.current === freshEdge) return
    previousFreshEdge.current = freshEdge
    setNewItemCount(0)
  }, [freshEdge])

  useEffect(() => {
    const addedCount = sourceItemIds.filter((id) => !previousSourceIds.current.has(id)).length
    previousSourceIds.current = new Set(sourceItemIds)
    requestedRefreshAnchor.current = null
    if (props.trackNewItems === false) {
      setNewItemCount(0)
      return
    }
    if (addedCount <= 0) return
    if (wasNearFreshEdge.current) {
      releaseNavigationOwnership()
      const targetIndex = freshEdge === 'start' ? 0 : props.cards.length - 1
      virtualizer.scrollToIndex(targetIndex, { align: freshEdge })
    }
    else setNewItemCount((count) => count + addedCount)
  }, [freshEdge, props.cards.length, props.trackNewItems, releaseNavigationOwnership, sourceItemIds, sourceSignature, virtualizer])

  const virtualItems = virtualizer.getVirtualItems()

  function updateScrollState() {
    const element = scrollRef.current
    if (!element) return
    wasNearFreshEdge.current = freshEdge === 'start'
      ? element.scrollTop <= 96
      : element.scrollHeight - element.scrollTop - element.clientHeight <= 96
    if (wasNearFreshEdge.current) setNewItemCount(0)
    const visibleStart = element.scrollTop + topInset
    const visible = virtualizer.getVirtualItems().filter((item) => item.end >= visibleStart && item.start <= element.scrollTop + element.clientHeight)
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
        const correction = card.getBoundingClientRect().top - element.getBoundingClientRect().top - topInset - activeRestoration.offset
        if (Math.abs(correction) > 0.5) element.scrollTop += correction
      }
    }
    viewportAnchor.current = readViewportAnchor(element, topInset)
    if (typeof IntersectionObserver === 'undefined' && terminalRef.current) {
      const rootBounds = element.getBoundingClientRect()
      const terminalBounds = terminalRef.current.getBoundingClientRect()
      const visible = terminalBounds.bottom >= rootBounds.top
        && terminalBounds.top <= rootBounds.bottom
      if (visible && !terminalVisible.current) onTerminalReachRef.current?.()
      terminalVisible.current = visible
    }
  }

  function toggleExpandedInline(id: string) {
    releaseNavigationOwnership()
    inlineScrollAnchor.current = scrollRef.current ? readViewportAnchor(scrollRef.current, topInset) : null
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

  function closeMediaViewer() {
    const trigger = mediaTriggerRef.current
    mediaTriggerRef.current = null
    setMediaViewer(null)
    window.requestAnimationFrame(() => {
      if (trigger?.isConnected) trigger.focus()
    })
  }

  return <div className="relative flex min-h-0 flex-1 overflow-hidden">
    <div
      ref={scrollRef}
      data-testid="workbench-feed-scroll"
      data-feed-visual="quiet-studio"
      data-fresh-edge={freshEdge}
      data-top-inset={topInset}
      className="quiet-scroll-region min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-3 pb-4 [overflow-anchor:none] sm:px-5"
      style={{ paddingTop: topInset }}
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
              showTimelineBucket={props.showTimelineBucket}
              feedWindowDays={props.feedWindowDays}
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
      {props.footer && <div className="mx-auto w-full max-w-[var(--inteliscope-width-reading)] pb-4">{props.footer}</div>}
      {props.terminal && <div
        ref={terminalRef}
        data-testid="feed-end-sentinel"
        className="mx-auto w-full max-w-[var(--inteliscope-width-reading)] pb-5"
      >{props.terminal}</div>}
    </div>
    {newItemCount > 0 && <Button
      size="sm"
      className={`absolute left-1/2 z-10 -translate-x-1/2 ${freshEdge === 'start' ? '' : 'bottom-4'}`}
      style={freshEdge === 'start' ? { top: topInset + 16 } : undefined}
      aria-label={`查看 ${newItemCount} 条新内容`}
      onPress={() => {
        releaseNavigationOwnership()
        setNewItemCount(0)
        wasNearFreshEdge.current = true
        const targetIndex = freshEdge === 'start' ? 0 : props.cards.length - 1
        virtualizer.scrollToIndex(targetIndex, { align: freshEdge })
      }}
    >{newItemCount} 条新内容</Button>}
    <ImageGalleryModal
      isOpen={Boolean(mediaViewer)}
      heading={mediaViewer ? `${mediaViewer.cardLabel} 图片预览` : '图片预览'}
      images={mediaViewer?.images ?? []}
      index={mediaViewer?.index ?? 0}
      onIndexChange={(index) => setMediaViewer((current) => current ? { ...current, index } : current)}
      onOpenChange={(open) => { if (!open) closeMediaViewer() }}
    />
  </div>
}
