export type ThemeColorMode = 'dark' | 'light'
export type ThemeName = 'graphite-purple'

export type ThemePreference = {
  themeName: ThemeName
  colorMode: ThemeColorMode
}

export const THEME_PREFERENCE_STORAGE_KEY = 'inteliscope.ui.theme.v1'

export const DEFAULT_THEME_PREFERENCE: ThemePreference = {
  themeName: 'graphite-purple',
  colorMode: 'dark',
}

function browserStorage(): Storage | undefined {
  if (typeof window === 'undefined') return undefined
  try {
    return window.localStorage
  } catch {
    return undefined
  }
}

function sanitizeThemePreference(value: Partial<ThemePreference> | null): ThemePreference {
  if (
    value?.themeName !== 'graphite-purple'
    || (value.colorMode !== 'dark' && value.colorMode !== 'light')
  ) return { ...DEFAULT_THEME_PREFERENCE }
  return { themeName: value.themeName, colorMode: value.colorMode }
}

export function readThemePreference(storage: Storage | undefined = browserStorage()): ThemePreference {
  if (!storage) return { ...DEFAULT_THEME_PREFERENCE }
  try {
    const value = JSON.parse(storage.getItem(THEME_PREFERENCE_STORAGE_KEY) || 'null') as Partial<ThemePreference> | null
    return sanitizeThemePreference(value)
  } catch {
    return { ...DEFAULT_THEME_PREFERENCE }
  }
}

export function writeThemePreference(
  preference: ThemePreference,
  storage: Storage | undefined = browserStorage(),
): ThemePreference {
  const value = sanitizeThemePreference(preference)
  try {
    storage?.setItem(THEME_PREFERENCE_STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Preference persistence is best-effort; the in-memory mode still changes.
  }
  return value
}
