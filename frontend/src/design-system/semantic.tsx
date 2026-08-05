import type { ReactNode } from 'react'

import { Tooltip } from './AnchoredTooltip'
import * as Icons from './icons'
import { topAnchoredTooltipProps } from './tooltip'

export type SemanticTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger'

const toneClasses: Record<SemanticTone, string> = {
  neutral: 'text-muted',
  accent: 'text-accent',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
}

const metaToneClasses: Record<Extract<SemanticTone, 'neutral' | 'accent'>, string> = {
  neutral: 'border-separator bg-default/70 text-muted',
  accent: 'border-accent/20 bg-accent/10 text-accent',
}

export function StatusIndicator({
  label,
  tone = 'neutral',
  icon,
  className = '',
  role,
  iconOnly = false,
  withTooltip = true,
}: {
  label: string
  tone?: SemanticTone
  icon?: ReactNode
  className?: string
  role?: 'status'
  iconOnly?: boolean
  withTooltip?: boolean
}) {
  const indicator = <span
    data-status-indicator
    data-tone={tone}
    data-icon-only={iconOnly ? 'true' : 'false'}
    role={role}
    className={`type-meta inline-flex min-h-[22px] min-w-0 items-center whitespace-nowrap font-medium ${iconOnly ? 'justify-center' : 'gap-1.5'} ${toneClasses[tone]} ${className}`}
  >
    {icon ?? <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-current" />}
    <span className={iconOnly ? 'sr-only' : 'min-w-0 truncate'}>{label}</span>
  </span>

  if (!iconOnly || !withTooltip) return indicator
  return <Tooltip delay={250}>
    <Tooltip.Trigger<'button'>
      aria-label={label}
      className="inline-flex shrink-0 rounded-md focus-visible:outline-2 focus-visible:outline-focus"
      render={(triggerProps) => <button {...triggerProps} type="button">{indicator}</button>}
    />
    <Tooltip.Content {...topAnchoredTooltipProps}>{label}</Tooltip.Content>
  </Tooltip>
}

export function MetaTag({
  children,
  tone = 'neutral',
  icon,
  className = '',
}: {
  children: ReactNode
  tone?: 'neutral' | 'accent'
  icon?: ReactNode
  className?: string
}) {
  return <span
    data-meta-tag
    data-tone={tone}
    className={`type-meta inline-flex min-h-[22px] min-w-0 items-center gap-1 rounded-lg border px-1.5 ${metaToneClasses[tone]} ${className}`}
  >
    {icon}
    <span className="min-w-0 truncate">{children}</span>
  </span>
}

export function CountBadge({ count, label, className = '' }: {
  count: number
  label?: string
  className?: string
}) {
  return <span
    data-count-badge
    aria-label={label ?? `${count} 项`}
    className={`type-micro inline-flex min-h-[18px] min-w-[18px] items-center justify-center rounded-md bg-accent/15 px-1.5 font-medium tabular-nums text-accent ${className}`}
  >{count}</span>
}

export function RemovableTag({
  label,
  onRemove,
  disabled = false,
  pending = false,
  transparent = false,
  className = '',
}: {
  label: string
  onRemove: () => void
  disabled?: boolean
  pending?: boolean
  transparent?: boolean
  className?: string
}) {
  return <span
    data-removable-tag
    aria-busy={pending || undefined}
    className={`type-meta inline-flex min-h-7 min-w-0 items-center rounded-lg border pl-2 text-foreground ${transparent ? 'border-separator/70 bg-transparent' : 'border-separator bg-default/70'} ${className}`}
  >
    <span className="min-w-0 truncate">{label}</span>
    <button
      type="button"
      aria-label={`移除 ${label}`}
      disabled={disabled || pending}
      className="ml-1 inline-flex size-7 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-surface-tertiary hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus disabled:opacity-40"
      onClick={onRemove}
    >
      {pending
        ? <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
        : <Icons.X size={13} aria-hidden="true" />}
    </button>
  </span>
}
