import type { ReactNode } from 'react'

export function SettingsSection({ id, title, description, actions, children, className = '' }: {
  id?: string
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  className?: string
}) {
  return <section id={id} data-settings-section tabIndex={id ? -1 : undefined} className={`grid gap-3 ${className}`}>
    <header className="flex min-w-0 flex-col gap-2 px-1 min-[640px]:flex-row min-[640px]:items-end min-[640px]:justify-between">
      <div className="min-w-0">
        <h2 className="type-title text-foreground">{title}</h2>
        {description && <p className="type-body mt-1 max-w-3xl text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </header>
    {children}
  </section>
}
