import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import { DesignSystemProvider, ThemeModeToggle } from '.'
import { THEME_PREFERENCE_STORAGE_KEY } from './themePreference'

describe('ThemeModeToggle', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('toggles from the default night mode to day mode and persists it', async () => {
    const browser = userEvent.setup()
    render(<MemoryRouter><DesignSystemProvider><ThemeModeToggle /></DesignSystemProvider></MemoryRouter>)

    await browser.click(screen.getByRole('button', { name: '切换到白天模式' }))

    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
    expect(JSON.parse(window.localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY) || 'null')).toEqual({
      themeName: 'graphite-purple',
      colorMode: 'light',
    })
    expect(screen.getByRole('button', { name: '切换到黑夜模式' })).toBeInTheDocument()
  })

  it('uses a moon action in day mode and returns to night mode', async () => {
    window.localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, JSON.stringify({
      themeName: 'graphite-purple',
      colorMode: 'light',
    }))
    const browser = userEvent.setup()
    render(<MemoryRouter><DesignSystemProvider><ThemeModeToggle /></DesignSystemProvider></MemoryRouter>)

    const toggle = screen.getByRole('button', { name: '切换到黑夜模式' })
    expect(toggle.querySelector('.lucide-moon')).not.toBeNull()
    await browser.click(toggle)

    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    expect(screen.getByRole('button', { name: '切换到白天模式' }).querySelector('.lucide-sun')).not.toBeNull()
  })
})
