import type { ReactNode } from 'react'
import { Link, type To } from 'react-router-dom'

import { Card, Icons } from '../../design-system'

export function SettingsCard({ title, description, icon, status, to, state, className = '' }: {
  title: string
  description: string
  icon: ReactNode
  status?: ReactNode
  to?: To
  state?: unknown
  className?: string
}) {
  const card = <Card
    data-settings-card
    variant="secondary"
    className={`group h-full gap-0 border border-separator bg-surface-secondary p-4 shadow-none transition-[border-color,transform] duration-[var(--inteliscope-motion-standard)] hover:border-accent/35 hover:bg-default/80 motion-reduce:transform-none ${className}`}
  >
    <Card.Content className="flex h-full min-w-0 items-start gap-3 p-0">
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-default text-muted transition-colors group-hover:text-foreground">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <strong className="type-control min-w-0 flex-1 text-foreground">{title}</strong>
          {status}
          {to && <Icons.ChevronRight className="shrink-0 text-muted" size={15} aria-hidden="true" />}
        </span>
        <span className="type-body mt-1 block text-muted">{description}</span>
      </span>
    </Card.Content>
  </Card>

  if (!to) return card
  return <Link
    to={to}
    state={state}
    className="rounded-[var(--inteliscope-radius-card)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
  >{card}</Link>
}
