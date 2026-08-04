import type { ReactNode } from 'react'

export type StatusBadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger'

const toneClasses: Record<StatusBadgeTone, string> = {
  neutral: 'border-separator bg-default text-foreground',
  accent: 'border-accent/30 bg-accent/15 text-foreground',
  success: 'border-success/30 bg-success/15 text-foreground',
  warning: 'border-warning/35 bg-warning/15 text-foreground',
  danger: 'border-danger/35 bg-danger/15 text-foreground',
}

export function StatusBadge({ children, tone = 'neutral', icon, className = '' }: {
  children: ReactNode
  tone?: StatusBadgeTone
  icon?: ReactNode
  className?: string
}) {
  return <span
    data-settings-status-badge={tone}
    className={`type-micro inline-flex min-h-5 shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 ${toneClasses[tone]} ${className}`}
  >{icon}{children}</span>
}
