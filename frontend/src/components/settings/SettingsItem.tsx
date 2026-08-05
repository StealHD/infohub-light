import type { ReactNode } from 'react'
import { Link, type To } from 'react-router-dom'

export function SettingsItem({ label, description, icon, trailing, children, className = '', density = 'comfortable', to, state, href }: {
  label: string
  description?: string
  icon?: ReactNode
  trailing?: ReactNode
  children?: ReactNode
  className?: string
  density?: 'comfortable' | 'compact'
  to?: To
  state?: unknown
  href?: string
}) {
  const baseClass = `flex min-w-0 flex-col gap-3 px-4 min-[640px]:flex-row min-[640px]:items-center ${density === 'compact' ? 'py-3' : 'py-3.5'} ${className}`
  const interactiveClass = 'transition-colors duration-[var(--inteliscope-motion-standard)] hover:bg-default/70 active:bg-default focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-focus motion-reduce:transition-none'
  const body = <>
    <div className="flex min-w-0 flex-1 items-start gap-3">
      {icon && <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-default text-muted">{icon}</span>}
      <div className="min-w-0 flex-1">
        <p className="type-control text-foreground">{label}</p>
        {description && <p className="type-body mt-0.5 text-muted">{description}</p>}
        {children && <div className="mt-3">{children}</div>}
      </div>
    </div>
    {trailing && <div className="flex shrink-0 items-center gap-2 pl-11 min-[640px]:pl-0">{trailing}</div>}
  </>

  if (to) {
    return <Link data-settings-item to={to} state={state} className={`${baseClass} ${interactiveClass}`}>{body}</Link>
  }
  if (href) {
    return <a data-settings-item href={href} target="_blank" rel="noopener noreferrer" className={`${baseClass} ${interactiveClass}`}>{body}</a>
  }
  return <div data-settings-item className={baseClass}>{body}</div>
}
