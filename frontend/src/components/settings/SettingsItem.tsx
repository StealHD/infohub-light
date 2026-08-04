import type { ReactNode } from 'react'

export function SettingsItem({ label, description, icon, trailing, children, className = '', density = 'comfortable' }: {
  label: string
  description?: string
  icon?: ReactNode
  trailing?: ReactNode
  children?: ReactNode
  className?: string
  density?: 'comfortable' | 'compact'
}) {
  return <div data-settings-item className={`flex min-w-0 flex-col gap-3 px-4 min-[640px]:flex-row min-[640px]:items-center ${density === 'compact' ? 'py-3' : 'py-3.5'} ${className}`}>
    <div className="flex min-w-0 flex-1 items-start gap-3">
      {icon && <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-lg bg-default text-muted">{icon}</span>}
      <div className="min-w-0 flex-1">
        <p className="type-control text-foreground">{label}</p>
        {description && <p className="type-body mt-0.5 text-muted">{description}</p>}
        {children && <div className="mt-3">{children}</div>}
      </div>
    </div>
    {trailing && <div className="flex shrink-0 items-center gap-2 pl-11 min-[640px]:pl-0">{trailing}</div>}
  </div>
}
