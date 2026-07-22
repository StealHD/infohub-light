export type SystemTheme = 'light' | 'dark'

export const systemDarkModeQuery = '(prefers-color-scheme: dark)'

export function readSystemTheme(): SystemTheme {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'light'
  return window.matchMedia(systemDarkModeQuery).matches ? 'dark' : 'light'
}
