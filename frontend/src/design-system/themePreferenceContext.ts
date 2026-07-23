import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react'

import {
  applyThemePreferenceToRoot,
  readThemePreference,
  writeThemePreference,
  type ThemeColorMode,
  type ThemePreference,
} from './themePreference'

export type ThemePreferenceContextValue = ThemePreference & {
  setColorMode: (mode: ThemeColorMode) => void
  toggleColorMode: () => void
}

export const ThemePreferenceContext = createContext<ThemePreferenceContextValue | null>(null)

export function useThemePreference(): ThemePreferenceContextValue {
  const provided = useContext(ThemePreferenceContext)
  const [fallback, setFallback] = useState<ThemePreference>(readThemePreference)
  const setFallbackColorMode = useCallback((colorMode: ThemeColorMode) => {
    setFallback((current) => {
      const next = writeThemePreference({ ...current, colorMode })
      if (typeof document !== 'undefined') applyThemePreferenceToRoot(document.documentElement, next)
      return next
    })
  }, [])
  const toggleFallbackColorMode = useCallback(() => {
    setFallback((current) => {
      const next = writeThemePreference({
        ...current,
        colorMode: current.colorMode === 'dark' ? 'light' : 'dark',
      })
      if (typeof document !== 'undefined') applyThemePreferenceToRoot(document.documentElement, next)
      return next
    })
  }, [])
  const fallbackValue = useMemo<ThemePreferenceContextValue>(() => ({
    ...fallback,
    setColorMode: setFallbackColorMode,
    toggleColorMode: toggleFallbackColorMode,
  }), [fallback, setFallbackColorMode, toggleFallbackColorMode])
  return provided ?? fallbackValue
}
