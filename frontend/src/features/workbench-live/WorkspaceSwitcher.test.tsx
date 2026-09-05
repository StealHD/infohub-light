import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'

import { DesignSystemProvider } from '../../design-system'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'
import { readWorkspaceRoute } from './workspaceRoutePreference'

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="当前位置">{location.pathname}</output>
}

function renderSwitcher(path = '/saved') {
  render(<MemoryRouter initialEntries={[path]}><DesignSystemProvider><WorkspaceSwitcher userId="switcher-user" /><LocationProbe /></DesignSystemProvider></MemoryRouter>)
}

describe('WorkspaceSwitcher', () => {
  beforeEach(() => {
    window.localStorage.clear()
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1440 })
  })

  it('exposes both workspace meanings, selection and keyboard focus restoration', async () => {
    const browser = userEvent.setup()
    renderSwitcher()
    const trigger = screen.getByRole('button', { name: '切换工作区，当前为 Inscope' })
    trigger.focus()
    await browser.keyboard('{Enter}')
    expect(screen.getByRole('dialog', { name: '切换工作区' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Inscope.*订阅、阅读与追踪/ })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: /OpenClaw.*对话、执行与自动化/ })).toBeInTheDocument()
    await browser.keyboard('{Escape}')
    await waitFor(() => expect(trigger).toHaveFocus())
  })

  it('restores each user’s most recent allowlisted route without storing workspace data', async () => {
    const browser = userEvent.setup()
    renderSwitcher('/saved')
    await browser.click(screen.getByRole('button', { name: '切换工作区，当前为 Inscope' }))
    await browser.click(screen.getByRole('button', { name: /OpenClaw.*对话、执行与自动化/ }))
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('/agent')
    expect(readWorkspaceRoute('switcher-user', 'inscope')).toBe('/saved')

    const openClawTrigger = screen.getByRole('button', { name: '切换工作区，当前为 OpenClaw' })
    await waitFor(() => expect(openClawTrigger).toHaveFocus())
    await browser.click(openClawTrigger)
    await browser.click(await screen.findByRole('button', { name: /Inscope.*订阅、阅读与追踪/ }))
    expect(screen.getByLabelText('当前位置')).toHaveTextContent('/saved')
  })

  it('uses a bottom Sheet for the compact mobile switcher', async () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 })
    const browser = userEvent.setup()
    render(<MemoryRouter initialEntries={['/feed']}><DesignSystemProvider><WorkspaceSwitcher userId="mobile-switcher" compact /></DesignSystemProvider></MemoryRouter>)
    await browser.click(screen.getByRole('button', { name: '切换工作区，当前为 Inscope' }))
    expect(screen.getByRole('dialog', { name: '切换工作区' })).toHaveAttribute('data-placement', 'bottom')
  })
})
