import type {} from '@mui/material/themeCssVarsAugmentation'
import { createTheme } from '@mui/material/styles'

declare module '@mui/material/styles' {
  interface Palette {
    surfaceContainer: string
    surfaceContainerHigh: string
    primaryContainer: string
    onPrimaryContainer: string
    outline: string
    outlineVariant: string
    warningContainer: string
    errorContainer: string
  }

  interface PaletteOptions {
    surfaceContainer?: string
    surfaceContainerHigh?: string
    primaryContainer?: string
    onPrimaryContainer?: string
    outline?: string
    outlineVariant?: string
    warningContainer?: string
    errorContainer?: string
  }
}

export const uiLayout = {
  appBarHeight: 64,
  collapsedDrawerWidth: 72,
  expandedDrawerWidth: 240,
  mobileNavHeight: 68,
  feedListMinWidth: 420,
  feedListMaxWidth: 440,
} as const

export const uiRadii = {
  panel: 24,
  card: 16,
  control: 20,
  small: 10,
} as const

export const inteliscopeTheme = createTheme({
  cssVariables: { cssVarPrefix: 'inteliscope' },
  palette: {
    mode: 'light',
    primary: { main: '#386A4A', contrastText: '#FFFFFF' },
    background: { default: '#F8FAF3', paper: '#FFFFFF' },
    text: { primary: '#1B1C19', secondary: '#566258' },
    divider: '#DCE2D9',
    warning: { main: '#765A00' },
    error: { main: '#BA1A1A' },
    surfaceContainer: '#F0F4EC',
    surfaceContainerHigh: '#E9EEE5',
    primaryContainer: '#CCE8D2',
    onPrimaryContainer: '#173824',
    outline: '#768477',
    outlineVariant: '#DCE2D9',
    warningContainer: '#FFDF99',
    errorContainer: '#FFDAD6',
  },
  typography: {
    fontFamily: '"Noto Sans SC Variable", "PingFang SC", "Microsoft YaHei", sans-serif',
    h1: { fontSize: '2.5rem', fontWeight: 650, lineHeight: 1.18, letterSpacing: '-0.025em' },
    h2: { fontSize: '1.75rem', fontWeight: 650, lineHeight: 1.25, letterSpacing: '-0.02em' },
    h3: { fontSize: '1.25rem', fontWeight: 650, lineHeight: 1.35 },
    button: { fontWeight: 650, textTransform: 'none' },
  },
  shape: { borderRadius: uiRadii.small },
  components: {
    MuiButtonBase: { defaultProps: { disableRipple: true } },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { minHeight: 40, borderRadius: uiRadii.control, textTransform: 'none' } },
    },
    MuiIconButton: {
      styleOverrides: { root: { borderRadius: uiRadii.control } },
    },
    MuiChip: {
      styleOverrides: { root: { borderRadius: uiRadii.control, fontWeight: 600 } },
    },
    MuiListItemButton: {
      styleOverrides: { root: { borderRadius: uiRadii.card } },
    },
    MuiPaper: {
      defaultProps: { elevation: 0 },
    },
    MuiOutlinedInput: {
      styleOverrides: { root: { borderRadius: uiRadii.control } },
    },
    MuiTooltip: {
      defaultProps: { arrow: true, enterDelay: 400 },
    },
  },
})

export const nextUiLayout = {
  desktopSidebarWidth: 232,
  compactSidebarWidth: 72,
  agentPanelWidth: 360,
  collapsedAgentWidth: 52,
  headerHeight: 52,
  mobileNavHeight: 64,
} as const

export const nextUiRadii = {
  panel: 16,
  card: 14,
  control: 10,
  small: 8,
} as const

export const inteliscopeNextTheme = createTheme({
  cssVariables: { cssVarPrefix: 'inteliscope-next' },
  palette: {
    mode: 'dark',
    primary: { main: '#A99AF7', contrastText: '#17151F' },
    background: { default: '#151516', paper: '#1B1B1D' },
    text: { primary: '#F2F2F4', secondary: '#A3A3AA' },
    divider: 'rgba(255, 255, 255, 0.08)',
    warning: { main: '#E9B872' },
    error: { main: '#F48B8B' },
    surfaceContainer: '#19191C',
    surfaceContainerHigh: '#242429',
    primaryContainer: '#312C47',
    onPrimaryContainer: '#E7E0FF',
    outline: '#686472',
    outlineVariant: '#333338',
    warningContainer: '#3C3020',
    errorContainer: '#422326',
  },
  typography: {
    fontFamily: '"Noto Sans SC Variable", "PingFang SC", "Microsoft YaHei", sans-serif',
    h1: { fontSize: '1.5rem', fontWeight: 680, lineHeight: 1.3, letterSpacing: '-0.025em' },
    h2: { fontSize: '1.125rem', fontWeight: 650, lineHeight: 1.38, letterSpacing: '-0.015em' },
    h3: { fontSize: '1rem', fontWeight: 650, lineHeight: 1.45 },
    body1: { fontSize: '0.875rem', lineHeight: 1.65 },
    body2: { fontSize: '0.8125rem', lineHeight: 1.6 },
    caption: { fontSize: '0.75rem', lineHeight: 1.5 },
    button: { fontSize: '0.8125rem', fontWeight: 620, textTransform: 'none' },
  },
  shape: { borderRadius: nextUiRadii.control },
  transitions: {
    duration: { shortest: 120, shorter: 150, short: 180, standard: 220 },
  },
  components: {
    MuiButtonBase: { defaultProps: { disableRipple: true } },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: { root: { minHeight: 32, borderRadius: nextUiRadii.control, textTransform: 'none' } },
    },
    MuiIconButton: { styleOverrides: { root: { borderRadius: nextUiRadii.control } } },
    MuiChip: { styleOverrides: { root: { height: 26, borderRadius: nextUiRadii.small, fontWeight: 560 } } },
    MuiOutlinedInput: { styleOverrides: { root: { borderRadius: nextUiRadii.control } } },
    MuiPaper: { defaultProps: { elevation: 0 } },
    MuiTooltip: { defaultProps: { arrow: true, enterDelay: 350 } },
  },
})
