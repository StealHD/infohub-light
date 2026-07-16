import type { PaperProps } from '@mui/material'
import type { SystemStyleObject, Theme } from '@mui/system'

import { Paper } from '@mui/material'

import { uiRadii } from './theme'

type SurfaceProps = Omit<PaperProps, 'sx'> & {
  radius?: keyof typeof uiRadii
  sx?: SystemStyleObject<Theme>
}

export function Surface({ radius = 'panel', sx, ...props }: SurfaceProps) {
  return <Paper {...props} sx={{ borderRadius: `${uiRadii[radius]}px`, ...sx }} />
}
