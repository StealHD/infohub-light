import type { ReactNode } from 'react'

export type StatusBadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger'

const toneClasses: Record<StatusBadgeTone, string> = {
  neutral: 'bg-default text-foreground',
  accent: 'bg-accent/15 text-foreground',
  success: 'bg-success/15 text-foreground',
  warning: 'bg-warning/15 text-foreground',
  danger: 'bg-danger/15 text-foreground',
}

export function StatusBadge({ children, tone = 'neutral', className = '' }: {
  children: ReactNode
  tone?: StatusBadgeTone
  className?: string
}) {
  return <span
    data-settings-status-badge={tone}
    className={`type-micro inline-flex min-h-5 shrink-0 items-center rounded-full px-2 py-0.5 ${toneClasses[tone]} ${className}`}
  >{children}</span>
}
