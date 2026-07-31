import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { NotificationTarget } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { actionToast, DesignSystemProvider } from '../../design-system'
import { HeroNotificationTargets } from './HeroNotificationTargets'

const target = (overrides: Partial<NotificationTarget> = {}): NotificationTarget => ({
  id: 'target-shared-telegram',
  name: '值班 Telegram',
  scope: 'shared',
  channel: 'telegram',
  configured: true,
  enabled: false,
  available: false,
  transport_ready: true,
  config_generation: 2,
  activation_generation: 1,
  enabled_at: null,
  last_test_status: 'sent',
  last_tested_at: '2026-07-31T00:00:00Z',
  last_test_error_code: null,
  can_edit: true,
  can_test: true,
  can_enable: true,
  usage: {
    user_binding_count: 0,
    alert_binding_count: 0,
    preferred_active_delivery_count: 0,
    alert_active_delivery_count: 0,
  },
  updated_at: '2026-07-31T00:00:00Z',
  ...overrides,
})

function renderTargets(apiOverrides: Partial<ServiceApi> = {}) {
  const api = {
    notificationTargets: vi.fn().mockResolvedValue({
      schema_version: 1,
      targets: [],
      webhook_provider_options: [],
    }),
    createNotificationTarget: vi.fn().mockResolvedValue(target()),
    updateNotificationTarget: vi.fn().mockResolvedValue(target()),
    testNotificationTarget: vi.fn().mockResolvedValue({
      sent: true,
      target_id: 'target-shared-telegram',
      channel: 'telegram',
    }),
    archiveNotificationTarget: vi.fn().mockResolvedValue({
      target_id: 'target-shared-telegram',
      archived: true,
    }),
    ...apiOverrides,
  } as unknown as ServiceApi
  const context = {
    api,
    user: {
      id: 'owner-targets',
      username: 'owner',
      role: 'owner',
      enabled: true,
    },
    query: '',
    setQuery: vi.fn(),
    activity: { state: 'idle', message: '' },
    refresh: vi.fn(),
    beginAction: () => ({ userId: 'owner-targets', generation: 0 }),
    isActionCurrent: () => true,
  } as unknown as AppOutletContext
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  render(<QueryClientProvider client={queryClient}>
    <MemoryRouter>
      <DesignSystemProvider>
        <Routes>
          <Route element={<Outlet context={context} />}>
            <Route index element={<HeroNotificationTargets />} />
          </Route>
        </Routes>
      </DesignSystemProvider>
    </MemoryRouter>
  </QueryClientProvider>)
  return api
}

describe('HeroNotificationTargets', () => {
  beforeEach(() => actionToast.clear())

  it('creates one write-only destination and clears it before the request resolves', async () => {
    const browser = userEvent.setup()
    const api = renderTargets()
    await screen.findByRole('heading', { name: '通知目标' })

    await browser.type(screen.getByRole('textbox', { name: '目标名称' }), '我的 Telegram')
    await browser.selectOptions(screen.getByRole('combobox', { name: '渠道' }), 'telegram')
    const destination = screen.getByLabelText('Chat ID')
    expect(destination).toHaveAttribute('type', 'password')
    await browser.type(destination, '@private_delivery_target')
    await browser.click(screen.getByRole('button', { name: '创建通知目标' }))

    await waitFor(() => expect(api.createNotificationTarget).toHaveBeenCalledWith({
      name: '我的 Telegram',
      scope: 'private',
      channel: 'telegram',
      telegram_chat_id: '@private_delivery_target',
    }))
    expect(destination).toHaveValue('')
    expect(document.body.textContent).not.toContain('@private_delivery_target')
  })

  it('tests and enables an existing target only from the target manager', async () => {
    const browser = userEvent.setup()
    const existing = target()
    const api = renderTargets({
      notificationTargets: vi.fn().mockResolvedValue({
        schema_version: 1,
        targets: [existing],
        webhook_provider_options: [],
      }),
    })

    await browser.click(await screen.findByRole('button', { name: '发送测试' }))
    await waitFor(() => expect(api.testNotificationTarget).toHaveBeenCalledWith(existing.id))
    await browser.click(screen.getByRole('button', { name: '启用' }))
    await waitFor(() => expect(api.updateNotificationTarget).toHaveBeenCalledWith(
      existing.id,
      { enabled: true },
    ))
  })
})
