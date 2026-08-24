import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { NotificationService, NotificationServices } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { actionToast, DesignSystemProvider } from '../../design-system'
import { HeroNotificationTargets } from './HeroNotificationTargets'

const service = (overrides: Partial<NotificationService> = {}): NotificationService => ({
  id: 'service-shared-telegram',
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
  can_validate: true,
  legacy_private: false,
  usage: {
    user_binding_count: 0,
    alert_binding_count: 0,
    preferred_active_delivery_count: 0,
    alert_active_delivery_count: 0,
  },
  updated_at: '2026-07-31T00:00:00Z',
  ...overrides,
})

const response = (services: NotificationService[] = []): NotificationServices => ({
  schema_version: 1,
  services,
  channel_credentials: {
    email: {
      configured: false,
      ready: false,
      generation: 0,
      provider: null,
      sender_name: 'Inteliscope',
      region: null,
      sender_email_configured: false,
      smtp_username_configured: false,
      providers: [],
    },
    telegram: {
      configured: false,
      ready: false,
      generation: 0,
    },
    webhook: {
      configured: true,
      ready: true,
      generation: 0,
    },
  },
  webhook_provider_options: [],
  can_manage: true,
})

function renderServices(apiOverrides: Partial<ServiceApi> = {}) {
  const created = service()
  const api = {
    notificationServices: vi.fn().mockResolvedValue(response()),
    createNotificationService: vi.fn().mockResolvedValue(created),
    updateNotificationService: vi.fn().mockResolvedValue(created),
    testAndEnableNotificationService: vi.fn().mockResolvedValue({
      sent: true,
      enabled: true,
      target_id: created.id,
      channel: 'telegram',
    }),
    archiveNotificationService: vi.fn().mockResolvedValue({
      service_id: created.id,
      archived: true,
    }),
    updateNotificationTarget: vi.fn(),
    archiveNotificationTarget: vi.fn(),
    ...apiOverrides,
  } as unknown as ServiceApi
  const context = {
    api,
    user: {
      id: 'owner-services',
      username: 'owner',
      role: 'owner',
      enabled: true,
    },
    query: '',
    setQuery: vi.fn(),
    activity: { state: 'idle', message: '' },
    refresh: vi.fn(),
    beginAction: () => ({ userId: 'owner-services', generation: 0 }),
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

  it('configures, tests, and enables Telegram from one write-only form', async () => {
    const browser = userEvent.setup()
    const api = renderServices()
    await screen.findByRole('heading', { name: '通知服务' })
    await browser.click(screen.getByRole('button', { name: '新增通知服务' }))
    const dialog = screen.getByRole('dialog', { name: '新增通知服务' })
    expect(within(dialog).getAllByRole('heading', { name: '新增通知服务' })).toHaveLength(1)
    expect(within(dialog).getByRole('button', { name: '取消' })).toBeInTheDocument()
    expect(dialog.querySelector('[data-notification-service-dialog-footer]')).toContainElement(within(dialog).getByRole('button', { name: '保存并测试' }))

    await browser.type(within(dialog).getByRole('textbox', { name: '服务名称' }), '群组 Telegram')
    expect(within(dialog).getByRole('button', { name: /邮件服务商/ })).toHaveClass('select__trigger')
    await browser.click(within(dialog).getByRole('button', { name: /发送方式/ }))
    await browser.click(await screen.findByRole('option', { name: 'Webhook' }))
    expect(within(dialog).getByRole('button', { name: /Webhook 类型/ })).toHaveClass('select__trigger')
    await browser.click(within(dialog).getByRole('button', { name: /发送方式/ }))
    await browser.click(await screen.findByRole('option', { name: 'Telegram' }))
    const destination = within(dialog).getByLabelText('群组或会话 Chat ID')
    const token = within(dialog).getByLabelText('Bot Token')
    expect(destination).toHaveAttribute('type', 'password')
    expect(token).toHaveAttribute('type', 'password')
    await browser.type(destination, '-1001234567890')
    await browser.type(token, '123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')
    await browser.click(screen.getByRole('button', { name: '保存并测试' }))

    await waitFor(() => expect(api.createNotificationService).toHaveBeenCalledWith({
      name: '群组 Telegram',
      scope: 'shared',
      channel: 'telegram',
      telegram_chat_id: '-1001234567890',
      telegram_bot_token: '123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA',
    }))
    await waitFor(() => expect(api.testAndEnableNotificationService).toHaveBeenCalledWith(
      'service-shared-telegram',
    ))
    expect(destination).toHaveValue('')
    expect(token).toHaveValue('')
    expect(document.body.textContent).not.toContain('-1001234567890')
    expect(document.body.textContent).not.toContain('123456789:AAAAAAAA')
  })

  it('resumes a previously verified service without sending another test', async () => {
    const browser = userEvent.setup()
    const existing = service()
    const api = renderServices({
      notificationServices: vi.fn().mockResolvedValue(response([existing])),
    })

    await browser.click(await screen.findByRole('button', { name: '更多操作：值班 Telegram' }))
    await browser.click(await screen.findByRole('button', { name: '启用' }))
    await waitFor(() => expect(api.updateNotificationService).toHaveBeenCalledWith(
      existing.id,
      { enabled: true },
    ))
    expect(api.testAndEnableNotificationService).not.toHaveBeenCalled()
  })

  it('tests and enables a service whose current generation is not verified', async () => {
    const browser = userEvent.setup()
    const existing = service({
      last_test_status: null,
      last_tested_at: null,
      can_enable: false,
    })
    const api = renderServices({
      notificationServices: vi.fn().mockResolvedValue(response([existing])),
    })

    await browser.click(await screen.findByRole('button', { name: '更多操作：值班 Telegram' }))
    await browser.click(await screen.findByRole('button', { name: '测试并启用' }))
    await waitFor(() => expect(api.testAndEnableNotificationService).toHaveBeenCalledWith(existing.id))
    expect(api.updateNotificationService).not.toHaveBeenCalled()
  })

  it('keeps services in a compact table and confirms archive in a modal', async () => {
    const browser = userEvent.setup()
    const existing = service({ enabled: true, available: true })
    const api = renderServices({
      notificationServices: vi.fn().mockResolvedValue(response([existing])),
    })

    expect(await screen.findByRole('grid', { name: '通知服务列表' })).toBeInTheDocument()
    expect(screen.getByText('generation 2 · 尚未被业务选择')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '更多操作：值班 Telegram' }))
    await browser.click(screen.getByRole('button', { name: '归档' }))
    const dialog = await screen.findByRole('dialog', { name: '归档通知服务' })
    await browser.click(within(dialog).getByRole('button', { name: '确认归档' }))

    await waitFor(() => expect(api.archiveNotificationService).toHaveBeenCalledWith(existing.id))
  })
})
