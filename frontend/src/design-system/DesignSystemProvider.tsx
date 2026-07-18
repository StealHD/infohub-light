import { useLayoutEffect, type ReactNode } from 'react'

import { DesignSystemRouterProvider } from './DesignSystemRouterProvider'
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
    root.setAttribute('data-theme', 'dark')
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

export function DesignSystemProvider({ children }: { children: ReactNode }) {
  useLayoutEffect(() => acquireThemeRoot(document.documentElement), [])

  return <DesignSystemRouterProvider>
    <div
      className="inteliscope-design-system"
      data-theme="dark"
      data-inteliscope-theme="graphite-purple"
      data-ui-system="heroui"
    >
      {children}
    </div>
  </DesignSystemRouterProvider>
}
