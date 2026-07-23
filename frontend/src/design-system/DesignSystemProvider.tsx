import {
  createContext,
  useCallback,
  useContext,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { ToastProvider } from '@heroui/react'

import { DesignSystemRouterProvider } from './DesignSystemRouterProvider'
import {
  readThemePreference,
  writeThemePreference,
  type ThemeColorMode,
  type ThemePreference,
} from './themePreference'
import './theme.css'

type ThemeRootLease = {
  count: number
  hadClass: boolean
  inteliscopeTheme: string | null
  theme: string | null
}

const themeRootLeases = new WeakMap<HTMLElement, ThemeRootLease>()

function restoreAttribute(root: HTMLElement, name: string, value: string | null) {
  if (value === null) root.removeAttribute(name)
  else root.setAttribute(name, value)
}

function acquireThemeRoot(root: HTMLElement) {
  const current = themeRootLeases.get(root)
  if (current) current.count += 1
  else {
    themeRootLeases.set(root, {
      count: 1,
      hadClass: root.classList.contains('inteliscope-design-system'),
      inteliscopeTheme: root.getAttribute('data-inteliscope-theme'),
      theme: root.getAttribute('data-theme'),
    })
    root.classList.add('inteliscope-design-system')
    root.setAttribute('data-inteliscope-theme', 'graphite-purple')
  }

  return () => {
    const lease = themeRootLeases.get(root)
    if (!lease) return
    lease.count -= 1
    if (lease.count > 0) return
    restoreAttribute(root, 'data-theme', lease.theme)
    restoreAttribute(root, 'data-inteliscope-theme', lease.inteliscopeTheme)
    if (!lease.hadClass) root.classList.remove('inteliscope-design-system')
    themeRootLeases.delete(root)
  }
}

function applyThemeRoot(root: HTMLElement, preference: ThemePreference) {
  root.setAttribute('data-theme', preference.colorMode)
  root.setAttribute('data-inteliscope-theme', preference.themeName)
}

type ThemePreferenceContextValue = ThemePreference & {
  setColorMode: (mode: ThemeColorMode) => void
  toggleColorMode: () => void
}

const ThemePreferenceContext = createContext<ThemePreferenceContextValue | null>(null)

export function useThemePreference(): ThemePreferenceContextValue {
  const value = useContext(ThemePreferenceContext)
  if (!value) throw new Error('useThemePreference must be used inside DesignSystemProvider')
  return value
}

export function DesignSystemProvider({ children }: { children: ReactNode }) {
  const [preference, setPreference] = useState<ThemePreference>(readThemePreference)
  const setColorMode = useCallback((colorMode: ThemeColorMode) => {
    setPreference((current) => writeThemePreference({ ...current, colorMode }))
  }, [])
  const toggleColorMode = useCallback(() => {
    setPreference((current) => writeThemePreference({
      ...current,
      colorMode: current.colorMode === 'dark' ? 'light' : 'dark',
    }))
  }, [])
  const contextValue = useMemo<ThemePreferenceContextValue>(() => ({
    ...preference,
    setColorMode,
    toggleColorMode,
  }), [preference, setColorMode, toggleColorMode])

  useLayoutEffect(() => acquireThemeRoot(document.documentElement), [])
  useLayoutEffect(() => {
    const root = document.documentElement
    applyThemeRoot(root, preference)
  }, [preference])

  return <ThemePreferenceContext.Provider value={contextValue}>
    <DesignSystemRouterProvider>
      <div
        className="inteliscope-design-system"
        data-theme={preference.colorMode}
        data-inteliscope-theme={preference.themeName}
        data-ui-system="heroui"
      >
        {children}
        <ToastProvider placement="top" maxVisibleToasts={3} width="min(420px, calc(100vw - 24px))" />
      </div>
    </DesignSystemRouterProvider>
  </ThemePreferenceContext.Provider>
}
