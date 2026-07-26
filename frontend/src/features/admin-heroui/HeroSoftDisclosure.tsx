import { useId, useState, type ReactNode } from 'react'

import { Icons } from '../../design-system'

export function HeroSoftDisclosure({
  label,
  children,
  className = '',
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const contentId = useId()

  return <div
    data-soft-disclosure={label}
    data-disclosure-state={open ? 'open' : 'closed'}
    className={`${open ? 'w-full basis-full' : 'w-auto'} min-w-0 rounded-lg transition-colors duration-200 ${className}`}
  >
    <button
      type="button"
      aria-expanded={open}
      aria-controls={contentId}
      className={`type-meta inline-flex min-h-7 items-center gap-1.5 rounded-lg px-2 transition-colors duration-200 hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus ${open ? 'bg-default text-foreground' : 'text-muted'}`}
      onClick={() => setOpen((current) => !current)}
    >
      <Icons.ChevronRight
        size={14}
        aria-hidden="true"
        className={`shrink-0 transition-transform duration-200 motion-reduce:transition-none ${open ? 'rotate-90' : ''}`}
      />
      {label}
    </button>
    <div
      id={contentId}
      aria-hidden={!open}
      className={`grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
    >
      <div className="min-h-0 overflow-hidden">
        <div className="px-2 pb-2 pt-1">{children}</div>
      </div>
    </div>
  </div>
}
