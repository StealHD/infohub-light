import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { User } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { DesignSystemProvider } from '../../design-system'
import { SettingsSystemPage } from './SettingsSystemPage'

const owner: User = {
  id: 'owner-1', username: 'owner', display_name: 'Owner', role: 'owner', enabled: true,
}

const response = {
  generation: 3,
  settings: [{
    key: 'limits.max_workspace_fetch_attempts_per_day',
    env_name: 'INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY',
    kind: 'integer' as const,
    default: 100,
    category: 'capacity' as const,
    minimum: 0,
    maximum: 10_000,
    risk: 'medium' as const,
    effect_timing: 'next_operation',
    description: '工作区每日上游抓取尝试总上限。',
    value: 100,
    fallback_value: 100,
    source: 'default' as const,
    override: null,
  }],
}

function renderPage(user: User = owner) {
  const api = {
    systemSettings: vi.fn().mockResolvedValue(response),
    prepareSystemSettings: vi.fn().mockResolvedValue({
      proposal_id: 'ssp_12345678', base_generation: 3,
      changes: [{
        key: response.settings[0].key,
        env_name: response.settings[0].env_name,
        before: 100, after: 500, reset: false,
        risk: 'medium', effect_timing: 'next_operation',
      }],
      warnings: ['workspace fetch capacity exceeds the per-provider capacity'],
      confirmation: '确认执行 12345678',
      expires_at: '2026-08-24T12:00:00Z',
    }),
    applySystemSettings: vi.fn().mockResolvedValue({
      proposal_id: 'ssp_12345678', generation: 4,
      changed_keys: [response.settings[0].key],
    }),
  } as unknown as ServiceApi
  const context: AppOutletContext = {
    api, user, query: '', setQuery: vi.fn(),
    activity: { state: 'idle', retryable: false, terminal: true },
    refresh: vi.fn(), cancelRefresh: vi.fn(), canCancelRefresh: false,
    isCancellingRefresh: false, reloadFeed: vi.fn(),
    beginAction: () => ({ userId: user.id, generation: 0 }),
    isActionCurrent: () => true,
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const Layout = () => <Outlet context={context} />
  const rendered = render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={['/settings/system']}><DesignSystemProvider><Routes>
      <Route element={<Layout />}>
        <Route path="/settings" element={<div>设置首页</div>} />
        <Route path="/settings/system" element={<SettingsSystemPage />} />
      </Route>
    </Routes></DesignSystemProvider></MemoryRouter>
  </QueryClientProvider>)
  return { api, ...rendered }
}

describe('SettingsSystemPage', () => {
  it('previews a typed change and applies only after exact confirmation', async () => {
    const browser = userEvent.setup()
    const { api } = renderPage()

    const input = await screen.findByRole('spinbutton', { name: response.settings[0].key })
    await browser.clear(input)
    await browser.type(input, '500')
    await browser.click(screen.getByRole('button', { name: '预演 1 项变更' }))

    expect(api.prepareSystemSettings).toHaveBeenCalledWith(3, [{ key: response.settings[0].key, value: 500 }])
    const dialog = await screen.findByRole('dialog', { name: '确认系统参数变更' })
    expect(within(dialog).getByText(/workspace fetch capacity/)).toBeInTheDocument()
    const apply = within(dialog).getByRole('button', { name: '应用变更' })
    expect(apply).toBeDisabled()
    await browser.type(within(dialog).getByRole('textbox', { name: '精确确认短语' }), '确认执行 12345678')
    await browser.click(apply)

    await waitFor(() => expect(api.applySystemSettings).toHaveBeenCalledWith('ssp_12345678', '确认执行 12345678'))
  })

  it('redirects a member before requesting admin settings', async () => {
    const { api } = renderPage({ ...owner, id: 'member-1', role: 'member' })
    expect(await screen.findByText('设置首页')).toBeInTheDocument()
    expect(api.systemSettings).not.toHaveBeenCalled()
  })

  it('does not preview an empty or out-of-range integer draft', async () => {
    const browser = userEvent.setup()
    renderPage()
    const input = await screen.findByRole('spinbutton', { name: response.settings[0].key })

    await browser.clear(input)
    expect(screen.getByRole('button', { name: /预演.*项变更/ })).toBeDisabled()
    await browser.type(input, '10001')
    expect(screen.getByRole('button', { name: /预演.*项变更/ })).toBeDisabled()
  })
})
