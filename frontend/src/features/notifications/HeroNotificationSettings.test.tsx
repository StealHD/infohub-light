import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type {
  NotificationChannelState,
  NotificationTarget,
  UserNotificationSettings,
} from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { actionToast, DesignSystemProvider } from '../../design-system'
import { HeroNotificationSettings } from './HeroNotificationSettings'

const state = (
  overrides: Partial<NotificationChannelState> = {},
): NotificationChannelState => ({
  enabled: false,
  configured: false,
  available: true,
  generation: 1,
  enabled_at: null,
  last_test_status: null,
  last_tested_at: null,
  last_test_error_code: null,
  ...overrides,
})

const providerOptions: UserNotificationSettings['webhook_provider_options'] = [{
  provider: 'generic_event',
  label: '通用事件 JSON',
  description: '发送 event/data，HTTP 2xx 仅表示接收端接受请求。',
  url_hint: 'https://example.com/webhook',
  signing: 'none',
  verification_mode: 'http_status',
}, {
  provider: 'feishu_lark_v2',
  label: '飞书 / Lark V2',
  description: '发送原生文本并校验平台业务响应，可选签名校验。',
  url_hint: 'https://open.feishu.cn/open-apis/bot/v2/hook/…',
  signing: 'optional',
  verification_mode: 'provider_response',
}]

const target = (overrides: Partial<NotificationTarget> = {}): NotificationTarget => ({
  id: 'target-private-email',
  name: '我的收件箱',
  scope: 'private',
  channel: 'email',
  configured: true,
  enabled: true,
  available: true,
  transport_ready: true,
  config_generation: 1,
  activation_generation: 1,
  enabled_at: '2026-07-30T00:00:00Z',
  last_test_status: 'sent',
  last_tested_at: '2026-07-30T00:00:00Z',
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
  updated_at: '2026-07-30T00:00:00Z',
  ...overrides,
})

const settings = (overrides: Partial<UserNotificationSettings> = {}): UserNotificationSettings => ({
  schema_version: 4,
  enabled: true,
  target_ids: [],
  selected_targets: [],
  channels: ['webhook'],
  channel: 'webhook',
  channel_states: {
    email: state({ configured: true }),
    webhook: {
      ...state({
        enabled: true,
        configured: true,
        enabled_at: '2026-07-24T00:00:00Z',
      }),
      provider: 'generic_event',
      provider_explicit: true,
      signing_secret_configured: false,
      verification_mode: 'http_status',
    },
    telegram: state(),
  },
  email_configured: true,
  email_transport_ready: true,
  webhook_configured: true,
  webhook_provider: 'generic_event',
  webhook_provider_explicit: true,
  webhook_signing_secret_configured: false,
  webhook_verification_mode: 'http_status',
  webhook_provider_options: providerOptions,
  telegram_configured: false,
  telegram_transport_ready: true,
  last_test_status: null,
  last_tested_at: null,
  last_test_error_code: null,
  updated_at: '2026-07-24T00:00:00Z',
  ...overrides,
})

describe('HeroNotificationSettings', () => {
  beforeEach(() => actionToast.clear())

  it('saves target selection without repeating target configuration or testing', async () => {
    const browser = userEvent.setup()
    const initial = settings()
    const selected = target()
    const notificationSettings = vi.fn().mockResolvedValue(initial)
    const updateNotificationSettings = vi.fn().mockResolvedValue(settings({
      target_ids: [selected.id],
      selected_targets: [selected],
    }))
    const api = {
      notificationSettings,
      notificationServices: vi.fn().mockResolvedValue({
        schema_version: 1,
        services: [{ ...selected, legacy_private: true, can_validate: true }],
        channel_credentials: {
          email: {
            configured: true,
            ready: true,
            generation: 1,
            provider: 'smtp',
            sender_name: 'Inteliscope',
            region: null,
            sender_email_configured: true,
            smtp_username_configured: true,
            providers: [],
          },
          telegram: { configured: false, ready: false, generation: 0 },
          webhook: { configured: true, ready: true, generation: 0 },
        },
        webhook_provider_options: providerOptions,
        can_manage: true,
      }),
      updateNotificationSettings,
    } as unknown as ServiceApi
    const token = { userId: 'owner-1', generation: 0 }
    const context = {
      api,
      user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true },
      query: '',
      setQuery: vi.fn(),
      activity: { state: 'idle', message: '' },
      refresh: vi.fn(),
      beginAction: () => token,
      isActionCurrent: () => true,
    } as unknown as AppOutletContext
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

    render(<QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <DesignSystemProvider>
          <Routes>
            <Route element={<Outlet context={context} />}>
              <Route index element={<HeroNotificationSettings />} />
            </Route>
          </Routes>
        </DesignSystemProvider>
      </MemoryRouter>
    </QueryClientProvider>)

    await browser.click(await screen.findByRole('checkbox', { name: selected.name }))
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    await waitFor(() => expect(updateNotificationSettings).toHaveBeenCalledWith({
      enabled: true,
      target_ids: [selected.id],
    }))
    expect(screen.queryByRole('button', { name: /发送.*测试/ })).not.toBeInTheDocument()
  })
})
