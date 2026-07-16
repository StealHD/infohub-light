import { CssBaseline, ThemeProvider } from '@mui/material'
import type { ReactNode } from 'react'

import { inteliscopeNextTheme } from './theme'

export function NextUiProvider({ children }: { children: ReactNode }) {
  return <ThemeProvider theme={inteliscopeNextTheme}>
    <CssBaseline enableColorScheme />
    {children}
  </ThemeProvider>
}
