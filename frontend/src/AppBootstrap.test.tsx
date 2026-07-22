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

    expect(html).toContain('id="inteliscope-bootstrap-shell"')
    expect(html).toContain('data-bootstrap-region="navigation"')
    expect(html).toContain('data-bootstrap-region="header"')
    expect(html).toContain('data-bootstrap-region="feed"')
    expect(html).toContain('data-bootstrap-region="agent"')
    expect(html).toContain('aria-hidden="true"')
    expect(html).toContain('/src/design-system/bootstrap.css')
  })
})
