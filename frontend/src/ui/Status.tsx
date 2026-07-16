import type { ChipProps } from '@mui/material'

import { Chip } from '@mui/material'

type StatusTone = 'neutral' | 'positive' | 'warning' | 'critical' | 'accent'

type StatusProps = Omit<ChipProps, 'color'> & {
  tone?: StatusTone
}

const toneStyles: Record<StatusTone, object> = {
  neutral: { bgcolor: 'surfaceContainerHigh', color: 'text.secondary' },
  positive: { bgcolor: 'primaryContainer', color: 'onPrimaryContainer' },
  warning: { bgcolor: 'warningContainer', color: 'warning.main' },
  critical: { bgcolor: 'errorContainer', color: 'error.main' },
  accent: { bgcolor: 'primary.main', color: 'primary.contrastText' },
}

export function Status({ tone = 'neutral', size = 'small', sx, ...props }: StatusProps) {
  return <Chip {...props} size={size} sx={{ ...toneStyles[tone], ...sx }} />
}
