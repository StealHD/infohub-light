import type { ReactNode } from 'react'

import { Card } from '../../design-system'

export function SettingsGroup({ children, className = '', ariaLabel }: {
  children: ReactNode
  className?: string
  ariaLabel?: string
}) {
  return <Card
    data-settings-group
    aria-label={ariaLabel}
    variant="secondary"
    className={`overflow-hidden border border-separator bg-surface-secondary p-0 shadow-none [&>[data-settings-item]+[data-settings-item]]:border-t [&>[data-settings-item]+[data-settings-item]]:border-separator ${className}`}
  >{children}</Card>
}
