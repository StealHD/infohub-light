import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { DesignSystemProvider } from '../../design-system'
import { SettingsLayout } from './SettingsLayout'

const member = { id: 'member-1', username: 'member', role: 'member' as const, enabled: true }

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location-probe">{location.pathname}{location.search}{location.hash}</output>
}

function LayoutFixture({ state }: { state?: { settingsReturnTo: string } }) {
  return <MemoryRouter initialEntries={[{ pathname: '/settings/appearance', state }]}>
    <DesignSystemProvider>
      <Routes>
        <Route path="/settings/appearance" element={<SettingsLayout user={member}><p>外观内容</p></SettingsLayout>} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </DesignSystemProvider>
  </MemoryRouter>
}

describe('SettingsLayout', () => {
  it('returns to the sanitized originating application route', async () => {
    const browser = userEvent.setup()
    render(<LayoutFixture state={{ settingsReturnTo: '/saved?filter=unread#recent' }} />)

    expect(screen.getByRole('heading', { name: '外观', level: 1 })).toBeInTheDocument()
    await browser.click(screen.getAllByRole('button', { name: '返回应用' })[0])
    expect(screen.getByTestId('location-probe')).toHaveTextContent('/saved?filter=unread#recent')
  })

  it('falls back to Feed and reuses the role-scoped sidebar in the mobile drawer', async () => {
    const browser = userEvent.setup()
    render(<LayoutFixture />)

    expect(screen.queryByRole('link', { name: '高级' })).not.toBeInTheDocument()
    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
    await browser.click(screen.getAllByRole('button', { name: '打开设置导航' })[0])
    expect(await screen.findByRole('dialog', { name: '设置导航' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: '通知' }).length).toBeGreaterThanOrEqual(1)
  })
})
