import '@fontsource-variable/noto-sans-sc/wght.css'

import { CssBaseline, ThemeProvider } from '@mui/material'
import type { ReactNode } from 'react'

import { inteliscopeTheme } from './theme'

export function UiProvider({ children }: { children: ReactNode }) {
  return <ThemeProvider theme={inteliscopeTheme}>
    <CssBaseline />
    {children}
  </ThemeProvider>
}
