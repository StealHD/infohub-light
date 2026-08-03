import { useId, useState, type ReactNode } from 'react'

import { Icons } from '../../design-system'

export function SettingsDisclosure({ title, description, children, defaultOpen = false, className = '' }: {
  title: string
  description?: string
  children: ReactNode
  defaultOpen?: boolean
  className?: string
}) {
  const [open, setOpen] = useState(defaultOpen)
  const contentId = useId()

  return <div
    data-settings-disclosure={title}
    data-disclosure-state={open ? 'open' : 'closed'}
    className={`rounded-xl border border-separator bg-default/40 ${className}`}
  >
    <button
      type="button"
      aria-expanded={open}
      aria-controls={contentId}
      className="flex min-h-12 w-full items-center gap-3 px-3 text-left hover:bg-default/60 focus-visible:outline-2 focus-visible:outline-focus"
      onClick={() => setOpen((current) => !current)}
    >
      <Icons.ChevronRight
        size={16}
        aria-hidden="true"
        className={`shrink-0 text-muted transition-transform duration-[var(--inteliscope-motion-fast)] motion-reduce:transition-none ${open ? 'rotate-90' : ''}`}
      />
      <span className="min-w-0 flex-1">
        <span className="type-control block text-foreground">{title}</span>
        {description && <span className="type-meta mt-0.5 block text-muted">{description}</span>}
      </span>
    </button>
    <div
      id={contentId}
      hidden={!open}
      className="border-t border-separator"
    >
      <div className="px-3 py-4">{children}</div>
    </div>
  </div>
}
