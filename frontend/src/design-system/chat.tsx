import type { ComponentProps, HTMLAttributes, ReactNode } from 'react'
import { Button } from '@heroui/react'
import { Globe2, X } from 'lucide-react'

import { Tooltip } from './AnchoredTooltip'

export type ChatSourceData = {
  title: string
  url: string
  sourceName?: string
  sourceAvatarUrl?: string
}

const LOCAL_AVATAR_URL = /^\/api\/media\/[A-Za-z0-9_-]{1,128}$/u

function sourceHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./u, '')
  } catch {
    return ''
  }
}

export function PromptInput({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div
    {...props}
    data-prompt-input className={`min-w-0 rounded-2xl border border-separator bg-surface-secondary shadow-sm transition-colors focus-within:border-focus ${className}`}
  />
}

export function PromptInputBody({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={`min-w-0 ${className}`} />
}

export function PromptInputToolbar({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={`min-w-0 ${className}`} />
}

function PromptSuggestionRoot({ className = '', ...props }: HTMLAttributes<HTMLElement>) {
  return <section
    {...props}
    className={`prompt-suggestion min-w-0 ${className}`}
  />
}

function PromptSuggestionHeader({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={`prompt-suggestion__header min-w-0 ${className}`} />
}

function PromptSuggestionTitle({ className = '', prominent = false, ...props }: HTMLAttributes<HTMLHeadingElement> & { prominent?: boolean }) {
  return <h2 {...props} className={`prompt-suggestion__title ${prominent ? 'type-section-title' : 'type-page-title'} ${className}`} />
}

function PromptSuggestionDescription({ className = '', ...props }: HTMLAttributes<HTMLParagraphElement>) {
  return <p {...props} className={`prompt-suggestion__description type-body text-muted ${className}`} />
}

function PromptSuggestionItems({ className = '', layout = 'list', ...props }: HTMLAttributes<HTMLDivElement> & { layout?: 'list' | 'tiles' }) {
  return <div {...props} className={`prompt-suggestion__items grid min-w-0 ${layout === 'tiles' ? 'gap-3 min-[768px]:grid-cols-3' : 'gap-2'} ${className}`} />
}

function PromptSuggestionItem({ className = '', layout = 'row', ...props }: ComponentProps<typeof Button> & { layout?: 'row' | 'tile' }) {
  return <Button
    {...props}
    variant="secondary"
    className={`prompt-suggestion__item relative flex w-full min-w-0 gap-3 border border-separator bg-surface-secondary text-left shadow-none transition-[background-color,border-color] duration-[var(--inteliscope-motion-standard)] hover:border-accent/40 hover:bg-default focus-visible:outline-2 focus-visible:outline-focus motion-reduce:transition-none ${layout === 'tile'
      ? 'min-h-24 items-center rounded-2xl p-3 pr-9 min-[768px]:min-h-40 min-[768px]:flex-col min-[768px]:items-start min-[768px]:justify-between min-[768px]:p-4'
      : 'min-h-14 items-center rounded-xl px-3 py-2'} ${className}`}
  />
}

function PromptSuggestionItemTitle({ className = '', prominent = false, ...props }: HTMLAttributes<HTMLSpanElement> & { prominent?: boolean }) {
  return <span {...props} className={`prompt-suggestion__item-title ${prominent ? 'type-card-title' : 'type-control'} block ${className}`} />
}

function PromptSuggestionItemDescription({ className = '', prominent = false, ...props }: HTMLAttributes<HTMLSpanElement> & { prominent?: boolean }) {
  return <span {...props} className={`prompt-suggestion__item-description ${prominent ? 'type-body' : 'type-meta'} block text-muted ${className}`} />
}

// This namespace-like export is intentional: it keeps the prompt-starter anatomy discoverable at call sites.
// eslint-disable-next-line react-refresh/only-export-components
export const PromptSuggestion = Object.assign(PromptSuggestionRoot, {
  Header: PromptSuggestionHeader,
  Title: PromptSuggestionTitle,
  Description: PromptSuggestionDescription,
  Items: PromptSuggestionItems,
  Item: PromptSuggestionItem,
  ItemTitle: PromptSuggestionItemTitle,
  ItemDescription: PromptSuggestionItemDescription,
})

export function ChatSources({
  children,
  className = '',
  label = '引用来源',
}: {
  children: ReactNode
  className?: string
  label?: string
}) {
  return <div className={`flex min-w-0 flex-wrap gap-1.5 ${className}`} aria-label={label}>{children}</div>
}

export function ChatSource({
  source,
  onRemove,
  compact = false,
  fullWidth = false,
}: {
  source: ChatSourceData
  onRemove?: () => void
  compact?: boolean
  fullWidth?: boolean
}) {
  const host = sourceHost(source.url)
  const metadata = [source.sourceName, host].filter(Boolean).join(' · ')
  const tooltip = metadata ? `${source.title} · ${metadata}` : source.title
  const sourceAvatarUrl = source.sourceAvatarUrl && LOCAL_AVATAR_URL.test(source.sourceAvatarUrl)
    ? source.sourceAvatarUrl
    : ''
  return <span
    data-chat-source
    className={`${fullWidth ? 'flex w-full' : 'inline-flex'} min-w-0 max-w-full items-center overflow-hidden rounded-lg border border-separator bg-default/75 text-foreground ${compact ? 'h-7' : 'h-8'}`}
  >
    <Tooltip delay={250}>
      <Tooltip.Trigger<'a'> render={(triggerProps) => <a
        {...triggerProps}
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
        className={`${triggerProps.className ?? ''} flex h-full min-w-0 flex-1 items-center gap-1.5 px-2 outline-none hover:bg-surface-secondary focus-visible:outline-2 focus-visible:outline-focus`}
        aria-label={`打开来源：${source.title}`}
      >
        {sourceAvatarUrl
          ? <img src={sourceAvatarUrl} alt="" className={`${compact ? 'size-3.5' : 'size-4'} shrink-0 rounded-full object-cover`} />
          : <Globe2 size={compact ? 12 : 13} className="shrink-0 text-muted" aria-hidden="true" />}
        <span className="type-label min-w-0 flex-1 truncate">{source.title}</span>
      </a>} />
      <Tooltip.Content placement="top" offset={8} className="max-w-[320px]">
        <span className="block break-words">{tooltip}</span>
      </Tooltip.Content>
    </Tooltip>
    {onRemove && <button
      type="button"
      aria-label={`移除来源：${source.title}`}
      onClick={onRemove}
      className="inline-flex h-full w-7 shrink-0 items-center justify-center border-l border-separator text-muted outline-none hover:bg-surface-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
    >
      <X size={12} aria-hidden="true" />
    </button>}
  </span>
}
