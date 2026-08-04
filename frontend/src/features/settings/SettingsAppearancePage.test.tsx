import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import {
  DesignSystemProvider,
  THEME_PREFERENCE_STORAGE_KEY,
  ThemeModeToggle,
} from '../../design-system'
import { SettingsAppearancePage } from './SettingsAppearancePage'

describe('SettingsAppearancePage', () => {
  beforeEach(() => window.localStorage.clear())

  it('uses the shared theme preference and keeps the header toggle synchronized', async () => {
    const browser = userEvent.setup()
    render(<MemoryRouter><DesignSystemProvider>
      <ThemeModeToggle />
      <SettingsAppearancePage />
    </DesignSystemProvider></MemoryRouter>)

    expect(screen.getByRole('radio', { name: '深色' })).toBeChecked()
    await browser.click(screen.getByRole('radio', { name: '浅色' }))
    expect(screen.getByRole('radio', { name: '浅色' })).toBeChecked()
    expect(screen.getByRole('button', { name: '切换到黑夜模式' })).toBeInTheDocument()
    expect(JSON.parse(window.localStorage.getItem(THEME_PREFERENCE_STORAGE_KEY) || '{}')).toMatchObject({ colorMode: 'light' })
  })
})
