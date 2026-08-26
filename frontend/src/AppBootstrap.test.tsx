import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AppBootstrap } from './AppBootstrap'

describe('AppBootstrap', () => {
  it('keeps pending authentication accessible without replacing the boot shell with a full-page loader', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))

    render(<AppBootstrap />)

    expect(screen.getByRole('status')).toHaveTextContent('正在连接 Inscope')
    expect(screen.getByRole('status')).toHaveClass('sr-only')
    expect(document.querySelector('.app-loading')).not.toBeInTheDocument()
    expect(document.querySelector('[data-ui-system="heroui"]')).toBeInTheDocument()
  })

  it('ships a route-aware noninteractive shell in the initial HTML', () => {
    const html = readFileSync(resolve(process.cwd(), 'index.html'), 'utf8')
    const css = readFileSync(resolve(process.cwd(), 'src/design-system/bootstrap.css'), 'utf8')
    const favicon = readFileSync(resolve(process.cwd(), 'public/favicon.svg'), 'utf8')

    expect(html).toContain('id="inteliscope-bootstrap-shell"')
    expect(html).toContain('data-bootstrap-region="navigation"')
    expect(html).toContain('data-bootstrap-region="header"')
    expect(html).toContain('data-bootstrap-region="feed"')
    expect(html).toContain('data-bootstrap-region="agent"')
    expect(html.match(/bootstrap-shell-card-meta/g)).toHaveLength(5)
    expect(html.match(/bootstrap-shell-card-footer/g)).toHaveLength(5)
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain('/src/design-system/bootstrap.css')
    expect(html).toContain('href="/favicon.svg"')
    expect(html).toContain('<title>Inscope | Private &amp; Insights</title>')
    expect(html).toContain('content="Inscope 私人 AI 信息雷达"')
    expect(html).toContain("'inteliscope.ui.theme.v1'")
    expect(html).toContain("colorMode === 'light' || colorMode === 'dark'")
    expect(html).not.toContain("matchMedia('(prefers-color-scheme: dark)')")
    expect(html).toContain("dataset.theme")
    expect(html).toContain("dataset.inteliscopeTheme")
    expect(css).toContain(':root[data-theme="light"]')
    expect(css).toContain('--inteliscope-bootstrap-page-header-size: 52px')
    expect(css).toContain('--inteliscope-bootstrap-page-header-surface-size: 44px')
    expect(css).toContain('--inteliscope-bootstrap-page-header-inline-inset: 8px')
    expect(css).toContain('--inteliscope-bootstrap-page-header-block-inset: 4px')
    expect(css).toContain('--inteliscope-bootstrap-page-header-radius: 999px')
    expect(css).toContain('height: var(--inteliscope-bootstrap-page-header-surface-size)')
    expect(css).toContain('margin: var(--inteliscope-bootstrap-page-header-block-inset) var(--inteliscope-bootstrap-page-header-inline-inset)')
    expect(css).toContain('background: color-mix(in oklab, var(--inteliscope-bootstrap-surface) 75%, transparent)')
    expect(css).toContain('border-radius: var(--inteliscope-bootstrap-page-header-radius)')
    expect(css).toContain('grid-row: 1 / span 2')
    expect(css).toContain('margin: calc(var(--inteliscope-bootstrap-page-header-size) + 8px) auto 0')
    expect(css).not.toContain('padding-top: var(--inteliscope-bootstrap-page-header-size)')
    expect(css).not.toContain('box-shadow: 0 0 0 var(--inteliscope-bootstrap-page-header-inline-inset)')
    expect(css).not.toContain('data-bootstrap-route')
    expect(css).toContain('min(var(--inteliscope-bootstrap-right-rail-width), calc(100vw - 72px - 650px))')
    expect(css).toContain('min(var(--inteliscope-bootstrap-right-rail-width), calc(100vw - 232px - 650px))')
    expect(css).toContain('grid-template-rows: 25px 16px 12px 12px 1fr')
    expect(favicon).toContain('fill="currentColor"')
    expect(favicon).toContain('aria-label="Inscope"')
    expect(favicon).toContain('@media (prefers-color-scheme: dark)')
    expect(favicon.match(/<path /gu)).toHaveLength(2)
  })
})
