import type { ReactNode } from 'react'

import { Card } from '../../design-system'

export function SettingsGroup({ children, className = '', ariaLabel, variant = 'surface' }: {
  children: ReactNode
  className?: string
  ariaLabel?: string
  variant?: 'surface' | 'inset'
}) {
  return <Card
    data-settings-group
    aria-label={ariaLabel}
    variant="secondary"
    className={`overflow-hidden border border-separator p-0 shadow-sm [&>[data-settings-item]+[data-settings-item]]:border-t [&>[data-settings-item]+[data-settings-item]]:border-separator ${variant === 'inset' ? 'bg-default' : 'bg-surface-secondary'} ${className}`}
  >{children}</Card>
}
