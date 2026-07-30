import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import type { NotificationChannelState, UserNotificationSettings } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { actionToast, DesignSystemProvider } from '../../design-system'
import { HeroNotificationSettings, NotificationSettingsForm } from './HeroNotificationSettings'

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

const settings = (overrides: Partial<UserNotificationSettings> = {}): UserNotificationSettings => ({
  schema_version: 3,
  enabled: true,
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

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => {
    resolve = next
  })
  return { promise, resolve }
}

function renderForm(
  value: UserNotificationSettings,
  onSave = vi.fn().mockResolvedValue(value),
  onTest = vi.fn().mockImplementation((channel) => Promise.resolve({ sent: true, channel })),
  readOnly = false,
) {
  render(<MemoryRouter><DesignSystemProvider>
    <NotificationSettingsForm settings={value} onSave={onSave} onTest={onTest} readOnly={readOnly} />
  </DesignSystemProvider></MemoryRouter>)
  return { onSave, onTest }
}

function channelCard(channel: 'email' | 'webhook' | 'telegram') {
  const card = document.querySelector<HTMLElement>(`[data-notification-channel="${channel}"]`)
  expect(card).not.toBeNull()
  return within(card!)
}

describe('NotificationSettingsForm', () => {
  beforeEach(() => actionToast.clear())

  it('always shows all channels and preserves configured channels while saving a multi-select change', async () => {
    const browser = userEvent.setup()
    const request = deferred<UserNotificationSettings>()
    const onSave = vi.fn().mockReturnValue(request.promise)
    renderForm(settings(), onSave)

    expect(screen.getByRole('heading', { name: '邮箱' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Webhook' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Telegram' })).toBeVisible()
    expect(channelCard('email').getByText(/已配置；接收目标不会回显/)).toBeVisible()
    expect(screen.getByRole('checkbox', { name: '启用邮箱渠道' })).not.toBeChecked()

    await browser.click(screen.getByRole('checkbox', { name: '启用邮箱渠道' }))
    await browser.click(screen.getByRole('checkbox', { name: '启用Telegram渠道' }))
    const chatId = screen.getByLabelText('Telegram Chat ID')
    expect(chatId).toHaveAttribute('type', 'password')
    await browser.type(chatId, '-1001234567890')
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      channels: ['webhook', 'email', 'telegram'],
      telegram_chat_id: '-1001234567890',
    })
    expect(chatId).toHaveValue('')
    expect(document.body.textContent).not.toContain('-1001234567890')

    await act(async () => request.resolve(settings({
      channels: ['webhook', 'email', 'telegram'],
    })))
  })

  it('submits only non-empty write-only destinations and clears every secret draft when saving starts', async () => {
    const browser = userEvent.setup()
    const request = deferred<UserNotificationSettings>()
    const onSave = vi.fn().mockReturnValue(request.promise)
    renderForm(settings({
      channels: ['email', 'webhook', 'telegram'],
      channel_states: {
        ...settings().channel_states,
        email: state({ enabled: true, configured: false }),
        telegram: state({ enabled: true, configured: false }),
      },
    }), onSave)

    const email = screen.getByLabelText('收件邮箱')
    const chatId = screen.getByLabelText('Telegram Chat ID')
    await browser.type(email, 'reader@example.com')
    await browser.type(chatId, '@inteliscope_alerts')
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      channels: ['email', 'webhook', 'telegram'],
      email_address: 'reader@example.com',
      telegram_chat_id: '@inteliscope_alerts',
    })
    expect(email).toHaveValue('')
    expect(chatId).toHaveValue('')
    expect(document.body.textContent).not.toContain('@inteliscope_alerts')
    await act(async () => request.resolve(settings()))
  })

  it('validates Telegram Chat ID without sending or retaining the invalid draft', async () => {
    const browser = userEvent.setup()
    const { onSave } = renderForm(settings({
      channels: ['webhook', 'telegram'],
      channel_states: {
        ...settings().channel_states,
        telegram: state({ enabled: true }),
      },
    }))

    const chatId = screen.getByLabelText('Telegram Chat ID')
    await browser.type(chatId, 'not a chat id')
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).not.toHaveBeenCalled()
    expect(await screen.findByText('请输入有效的 Chat ID（有符号整数或 @channel）。')).toBeVisible()
    expect(chatId).toHaveValue('')
    expect(document.body.textContent).not.toContain('not a chat id')
  })

  it('tests each persisted channel independently and leaves a paused transport isolated', async () => {
    const browser = userEvent.setup()
    const value = settings({
      channels: ['email', 'webhook', 'telegram'],
      channel_states: {
        email: state({ enabled: true, configured: true, available: false }),
        webhook: settings().channel_states.webhook,
        telegram: state({ enabled: true, configured: true }),
      },
      telegram_configured: true,
    })
    const { onTest } = renderForm(value)

    expect(channelCard('email').getByText('服务暂停')).toBeVisible()
    expect(screen.getByRole('button', { name: '发送邮箱测试' })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: '发送Webhook测试' }))
    await browser.click(screen.getByRole('button', { name: '发送Telegram测试' }))

    await waitFor(() => expect(onTest).toHaveBeenNthCalledWith(1, 'webhook'))
    await waitFor(() => expect(onTest).toHaveBeenNthCalledWith(2, 'telegram'))
  })

  it('keeps provider and signing secrets write-only when changing Webhook type', async () => {
    const browser = userEvent.setup()
    const request = deferred<UserNotificationSettings>()
    const onSave = vi.fn().mockReturnValue(request.promise)
    renderForm(settings(), onSave)

    await browser.click(screen.getByRole('button', { name: /Webhook 类型/ }))
    await browser.click(await screen.findByRole('option', { name: '飞书 / Lark V2' }))
    await browser.type(
      screen.getByLabelText('Webhook 地址'),
      'https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000000',
    )
    await browser.click(screen.getByRole('switch', { name: '启用机器人签名校验' }))
    const signingSecret = screen.getByLabelText('签名 Secret')
    await browser.type(signingSecret, 'write-only-signing-secret')
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      channels: ['webhook'],
      webhook_provider: 'feishu_lark_v2',
      webhook_url: 'https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000000',
      webhook_signing_secret: 'write-only-signing-secret',
    })
    expect(signingSecret).toHaveValue('')
    expect(document.body.textContent).not.toContain('write-only-signing-secret')
    await act(async () => request.resolve(settings()))
  })

  it('derives viewer access as read-only and blocks every write and test', async () => {
    const browser = userEvent.setup()
    const { onSave, onTest } = renderForm(settings(), undefined, undefined, true)

    expect(screen.getByText('当前账户为只读权限')).toBeVisible()
    expect(screen.getByRole('switch', { name: '启用新内容通知' })).toBeDisabled()
    for (const channel of ['邮箱', 'Webhook', 'Telegram']) {
      expect(screen.getByRole('checkbox', { name: `启用${channel}渠道` })).toBeDisabled()
    }
    expect(screen.getByRole('button', { name: /Webhook 类型/ })).toBeDisabled()
    expect(screen.getByLabelText('Telegram Chat ID')).toBeDisabled()
    expect(screen.getByRole('button', { name: '保存通知设置' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '发送Webhook测试' })).toBeDisabled()

    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))
    await browser.click(screen.getByRole('button', { name: '发送Webhook测试' }))
    expect(onSave).not.toHaveBeenCalled()
    expect(onTest).not.toHaveBeenCalled()
  })

  it('refreshes the tested channel state after an outcome-unknown response', async () => {
    const browser = userEvent.setup()
    const initial = settings()
    const unknown = settings({
      channel_states: {
        ...initial.channel_states,
        webhook: {
          ...initial.channel_states.webhook,
          last_test_status: 'unknown',
          last_tested_at: '2026-07-30T08:00:00Z',
          last_test_error_code: 'notification_webhook_response_invalid',
        },
      },
    })
    const notificationSettings = vi.fn()
      .mockResolvedValueOnce(initial)
      .mockResolvedValue(unknown)
    const testNotificationSettings = vi.fn().mockRejectedValue(new ApiError(502, {
      code: 'notification_test_outcome_unknown',
      message: 'raw upstream response must stay private',
      retryable: false,
    }))
    const api = {
      notificationSettings,
      updateNotificationSettings: vi.fn().mockResolvedValue(initial),
      testNotificationSettings,
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

    await screen.findByRole('heading', { name: 'Webhook' })
    expect(await channelCard('webhook').findByText('尚未发送测试通知')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '发送Webhook测试' }))

    await waitFor(() => expect(notificationSettings).toHaveBeenCalledTimes(2))
    expect(await channelCard('webhook').findByText(/最近一次测试结果未知，不会自动重发/)).toBeVisible()
    expect(screen.getByText('测试通知结果未知，请勿重复发送；请先确认接收端。')).toBeVisible()
    expect(testNotificationSettings).toHaveBeenCalledWith('webhook')
    expect(document.body.textContent).not.toContain('raw upstream')
  })
})
