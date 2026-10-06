import type { ReactNode } from 'react'
import { Icons, Tooltip, TooltipTriggerButton, topAnchoredTooltipProps } from '../../design-system'
import { safeExternalUrl } from '../feed/feedModel'
import { cardLabelForViewer, type WorkbenchCardModel } from './workbenchModel'

type Props = {
  card: WorkbenchCardModel; readonly?: boolean; savedPending?: boolean
  inContext: boolean; contextFull: boolean; contextCount: number
  onToggleSaved: () => unknown; onToggleContext: () => void; translationButton: ReactNode
}

export function CardFooterActions({ card, readonly, savedPending, inContext, contextFull, contextCount, onToggleSaved, onToggleContext, translationButton }: Props) {
  const externalUrl = safeExternalUrl(card.url)
  const cardLabel = cardLabelForViewer(card)
  return (
      <div
        data-card-actions
        data-card-footer-actions
        className="flex shrink-0 items-center gap-1 opacity-100 transition-opacity duration-[var(--inteliscope-motion-standard)] pointer-fine:opacity-60 pointer-fine:group-hover/card:opacity-100 pointer-fine:group-focus-within/card:opacity-100"
      >
        {translationButton}
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
            disabled={readonly} pending={savedPending}
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
      </div>
  )
}
