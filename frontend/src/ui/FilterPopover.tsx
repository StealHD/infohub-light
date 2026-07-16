import type { ReactNode } from 'react'
import { useState } from 'react'

import { Badge, Box, Button, Popover } from '@mui/material'

import { TuneRounded } from './icons'
import { uiRadii } from './theme'

type FilterPopoverProps = {
  label?: string
  dialogLabel: string
  activeCount?: number
  children: ReactNode
}

export function FilterPopover({ label = '更多筛选', dialogLabel, activeCount = 0, children }: FilterPopoverProps) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const open = Boolean(anchor)

  return <>
    <Badge color="primary" badgeContent={activeCount} invisible={!activeCount}>
      <Button
        variant="outlined"
        startIcon={<TuneRounded />}
        aria-haspopup="dialog"
        aria-expanded={open}
        onClick={(event) => setAnchor(event.currentTarget)}
      >{label}</Button>
    </Badge>
    <Popover
      open={open}
      anchorEl={anchor}
      onClose={() => setAnchor(null)}
      anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
      transformOrigin={{ vertical: 'top', horizontal: 'right' }}
      slotProps={{ paper: { sx: { mt: 1, borderRadius: `${uiRadii.card}px` } } }}
    >
      <Box role="dialog" aria-label={dialogLabel} sx={{ width: { xs: 300, sm: 360 }, p: 2.5 }}>{children}</Box>
    </Popover>
  </>
}
