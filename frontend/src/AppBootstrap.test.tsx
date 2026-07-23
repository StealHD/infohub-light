import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AppBootstrap } from './AppBootstrap'

describe('AppBootstrap', () => {
  it('keeps pending authentication accessible without replacing the boot shell with a full-page loader', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))

    render(<AppBootstrap />)

    expect(screen.getByRole('status')).toHaveTextContent('正在连接 Inteliscope')
    expect(screen.getByRole('status')).toHaveClass('sr-only')
    expect(document.querySelector('.app-loading')).not.toBeInTheDocument()
    expect(document.querySelector('[data-ui-system="heroui"]')).toBeInTheDocument()
  })

  it('ships a route-aware noninteractive shell in the initial HTML', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')
    const css = readFileSync(resolve(process.cwd(), 'src/design-system/bootstrap.css'), 'utf8')

    expect(html).toContain('id="inteliscope-bootstrap-shell"')
    expect(html).toContain('data-bootstrap-region="navigation"')
    expect(html).toContain('data-bootstrap-region="header"')
    expect(html).toContain('data-bootstrap-region="feed"')
    expect(html).toContain('data-bootstrap-region="agent"')
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain('/src/design-system/bootstrap.css')
    expect(html).toContain("'inteliscope.ui.theme.v1'")
    expect(html).toContain("colorMode === 'light' || colorMode === 'dark'")
    expect(html).not.toContain("matchMedia('(prefers-color-scheme: dark)')")
    expect(html).toContain("dataset.theme")
    expect(html).toContain("dataset.inteliscopeTheme")
    expect(css).toContain(':root[data-theme="light"]')
    expect(css).toContain('min(var(--inteliscope-bootstrap-right-rail-width), calc(100vw - 72px - 650px))')
    expect(css).toContain('min(var(--inteliscope-bootstrap-right-rail-width), calc(100vw - 232px - 650px))')
  })
})
