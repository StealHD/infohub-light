import type { ReactNode } from 'react'

import { Button, Icons, Tooltip, TooltipTriggerButton } from '../../../design-system'
import type { OpenClawContextUsage } from '../openclawContracts'
import type { OpenClawMessageImage } from '../openclawMedia'

type FormattedMessageTime = {
  label: string
  title: string
  dateTime: string
}

const CONTEXT_RING_CIRCUMFERENCE = 2 * Math.PI * 7

function formatTokenK(value: number): string {
  return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value / 1000)}k`
}

export function OpenClawContextUsageIndicator({ usage }: {
  usage: OpenClawContextUsage | null
}) {
  const progressValue = usage ? Math.min(100, usage.percent) : 0
  const label = usage
    ? `上下文占用 ${formatTokenK(usage.usedTokens)} / ${formatTokenK(usage.contextTokens)}，${usage.percent}%`
    : '上下文占用暂无可信用量'
  return <Tooltip delay={250}>
    <TooltipTriggerButton
      aria-label={label}
      className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground"
    >
      <svg
        role="progressbar"
        aria-label="上下文占用"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={usage ? progressValue : undefined}
        aria-valuetext={usage ? `${usage.percent}%` : '暂无可信用量'}
        viewBox="0 0 20 20"
        className="size-5"
      >
        <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="2" className="text-border" />
        {usage && <circle
          cx="10"
          cy="10"
          r="7"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray={CONTEXT_RING_CIRCUMFERENCE}
          strokeDashoffset={CONTEXT_RING_CIRCUMFERENCE * (1 - progressValue / 100)}
          transform="rotate(-90 10 10)"
          className="text-accent"
        />}
      </svg>
    </TooltipTriggerButton>
    <Tooltip.Content placement="top" offset={8}>
      {usage
        ? `${formatTokenK(usage.usedTokens)} / ${formatTokenK(usage.contextTokens)} · ${usage.percent}%`
        : '暂无可信用量'}
    </Tooltip.Content>
  </Tooltip>
}

function padTimePart(value: number): string {
  return String(value).padStart(2, '0')
}

function formatOpenClawMessageTime(
  value: number | undefined | null,
  now = Date.now(),
): FormattedMessageTime | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const date = new Date(value)
  const current = new Date(now)
  if (!Number.isFinite(date.getTime()) || !Number.isFinite(current.getTime())) return null
  const clock = `${padTimePart(date.getHours())}:${padTimePart(date.getMinutes())}`
  const today = date.getFullYear() === current.getFullYear()
    && date.getMonth() === current.getMonth()
    && date.getDate() === current.getDate()
  const fullDate = `${date.getFullYear()}-${padTimePart(date.getMonth() + 1)}-${padTimePart(date.getDate())}`
  return {
    label: today ? clock : `${padTimePart(date.getMonth() + 1)}-${padTimePart(date.getDate())} ${clock}`,
    title: `${fullDate} ${clock}:${padTimePart(date.getSeconds())}`,
    dateTime: date.toISOString(),
  }
}

const OPENCLAW_LINK_PATTERN = /\[([^\]\r\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<]+)/giu
const BARE_LINK_TRAILING_PUNCTUATION = /[.,!?;:，。！？；：、)\]}"']$/u

function safeHttpUrl(value: string): string | null {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? value : null
  } catch {
    return null
  }
}

function trimBareLink(value: string): { href: string; trailing: string } {
  let href = value
  let trailing = ''
  while (href && BARE_LINK_TRAILING_PUNCTUATION.test(href.at(-1) ?? '')) {
    trailing = `${href.at(-1)}${trailing}`
    href = href.slice(0, -1)
  }
  return { href, trailing }
}

function OpenClawMessageText({ text }: { text: string }) {
  const nodes: ReactNode[] = []
  let cursor = 0
  for (const match of text.matchAll(OPENCLAW_LINK_PATTERN)) {
    const index = match.index ?? 0
    if (index > cursor) nodes.push(text.slice(cursor, index))
    const markdownLabel = match[1]
    const markdownUrl = match[2]
    const bareCandidate = match[3]
    const bare = bareCandidate ? trimBareLink(bareCandidate) : null
    const href = safeHttpUrl(markdownUrl ?? bare?.href ?? '')
    if (!href) {
      nodes.push(match[0])
    } else {
      nodes.push(<a
        key={`${index}-${href}`}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-accent underline decoration-accent/50 underline-offset-[3px]"
      >{markdownLabel ?? bare?.href}</a>)
      if (bare?.trailing) nodes.push(bare.trailing)
    }
    cursor = index + match[0].length
  }
  if (cursor < text.length) nodes.push(text.slice(cursor))
  return <>{nodes}</>
}

function MessageTimestamp({ value }: { value?: number | null }) {
  const formatted = formatOpenClawMessageTime(value)
  if (!formatted) return null
  return <time
    className="type-label text-muted"
    dateTime={formatted.dateTime}
    title={formatted.title}
    aria-label={formatted.title}
  >{formatted.label}</time>
}

export function ConversationTurn({
  role,
  text,
  createdAt,
  status,
  hasNext,
  children,
}: {
  role: 'user' | 'assistant'
  text: string
  createdAt?: number | null
  status?: string
  hasNext: boolean
  children?: ReactNode
}) {
  return <>
    <div data-chat-marker className="flex min-h-full flex-col items-center self-stretch" aria-hidden="true">
      <span className={`mt-1.5 size-[5px] shrink-0 rounded-full ${role === 'assistant' ? 'bg-accent' : 'bg-muted'}`} />
      {hasNext && <span className="mt-[5px] min-h-8 w-px flex-1 bg-separator" />}
    </div>
    <article
      className={`min-w-0 max-w-full ${hasNext ? 'pb-4' : ''}`}
      data-chat-role={role}
      data-chat-status={status}
    >
      <div className="mb-[5px] flex min-w-0 items-baseline gap-1.5">
        <span className={`type-label ${role === 'assistant' ? 'text-accent' : 'text-muted'}`}>
          {role === 'assistant' ? 'OpenClaw' : '你'}
        </span>
        <MessageTimestamp value={createdAt} />
      </div>
      {text && <div
          data-chat-message-body
          className="type-chat min-w-0 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
        >
          <OpenClawMessageText text={text} />
        </div>}
      {children}
    </article>
  </>
}

export type OpenClawImageViewerState = {
  label: string
  images: OpenClawMessageImage[]
  index: number
  messageId?: string
}

export function OpenClawImageGrid({
  images,
  role,
  messageId,
  onOpen,
  onRefresh,
}: {
  images: OpenClawMessageImage[]
  role: 'user' | 'assistant'
  messageId?: string
  onOpen: (index: number) => void
  onRefresh?: (imageId: string) => void
}) {
  if (!images.length) return null
  const label = role === 'assistant' ? 'OpenClaw 返回的图片' : '你发送的图片'
  return <div className="mt-2 grid max-w-[520px] grid-cols-2 gap-2" role="group" aria-label={label}>
    {images.slice(0, 4).map((image, index) => image.url ? <button
      key={image.id}
      type="button"
      className={`relative min-w-0 overflow-hidden rounded-xl border border-separator bg-default/60 text-left outline-none focus-visible:outline-2 focus-visible:outline-focus ${images.length === 1 ? 'col-span-2 max-h-[320px]' : 'aspect-[4/3]'}`}
      aria-label={`查看${label}第 ${index + 1} 张`}
      onClick={() => onOpen(index)}
    >
      <img
        src={image.url}
        alt={image.alt || `${label}第 ${index + 1} 张`}
        width={image.width}
        height={image.height}
        referrerPolicy="no-referrer"
        className="size-full object-cover"
        onError={() => messageId && onRefresh?.(image.id)}
      />
      {index === 3 && images.length > 4 && <span className="type-control absolute inset-0 grid place-items-center bg-background/70 text-foreground">+{images.length - 4}</span>}
    </button> : <div
      key={image.id}
      className={`grid min-w-0 place-items-center rounded-xl border border-separator bg-default/60 p-3 text-center ${images.length === 1 ? 'col-span-2 min-h-32' : 'aspect-[4/3]'}`}
    >
      <div>
        <Icons.ImageOff size={18} className="mx-auto text-muted" aria-hidden="true" />
        <p className="type-label mt-1 text-muted">图片暂不可用</p>
        {messageId && onRefresh && <Button size="sm" variant="ghost" className="mt-1" onPress={() => onRefresh(image.id)}>重试</Button>}
      </div>
    </div>)}
  </div>
}
