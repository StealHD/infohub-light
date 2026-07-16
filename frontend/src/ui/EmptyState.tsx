import type { ReactNode } from 'react'

import { Box, Button, Stack, Typography } from '@mui/material'

type EmptyStateProps = {
  title: string
  description?: string
  actionLabel?: string
  onAction?: () => void
  icon?: ReactNode
}

export function EmptyState({ title, description, actionLabel, onAction, icon }: EmptyStateProps) {
  return <Stack spacing={1.5} sx={{ minHeight: 220, alignItems: 'center', justifyContent: 'center', px: 3, py: 5, textAlign: 'center' }}>
    {icon && <Box sx={{ color: 'text.secondary' }}>{icon}</Box>}
    <Typography variant="h3">{title}</Typography>
    {description && <Typography color="text.secondary" sx={{ maxWidth: 360 }}>{description}</Typography>}
    {actionLabel && onAction && <Button variant="outlined" onClick={onAction}>{actionLabel}</Button>}
  </Stack>
}
