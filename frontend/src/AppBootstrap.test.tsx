import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { AppBootstrap } from './AppBootstrap'

describe('AppBootstrap', () => {
  it('mounts the HeroUI provider inside the application router', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => undefined)))

    render(<AppBootstrap />)

    expect(screen.getByRole('status')).toHaveTextContent('正在连接 Inteliscope')
    expect(document.querySelector('[data-ui-system="heroui"]')).toBeInTheDocument()
  })
})
