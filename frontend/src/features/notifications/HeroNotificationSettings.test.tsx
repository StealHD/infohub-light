import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import type { UserNotificationSettings } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { actionToast, DesignSystemProvider } from '../../design-system'
import { HeroNotificationSettings, NotificationSettingsForm } from './HeroNotificationSettings'

const settings = (overrides: Partial<UserNotificationSettings> = {}): UserNotificationSettings => ({
  schema_version: 2,
  enabled: true,
  channel: 'webhook',
  email_configured: false,
  email_transport_ready: true,
  webhook_configured: true,
  webhook_provider: 'generic_event',
  webhook_provider_explicit: true,
  webhook_signing_secret_configured: false,
  webhook_verification_mode: 'http_status',
  webhook_provider_options: [
    {
      provider: 'generic_event',
      label: '通用事件 JSON',
      description: '发送 event/data，HTTP 2xx 仅表示接收端接受请求。',
      url_hint: 'https://example.com/webhook',
      signing: 'none',
      verification_mode: 'http_status',
    },
    {
      provider: 'generic_text',
      label: '通用文本 JSON',
      description: '发送 text，HTTP 2xx 仅表示接收端接受请求。',
      url_hint: 'https://example.com/webhook',
      signing: 'none',
      verification_mode: 'http_status',
    },
    {
      provider: 'feishu_lark_v2',
      label: '飞书 / Lark V2',
      description: '发送原生文本并校验平台业务响应，可选签名校验。',
      url_hint: 'https://open.feishu.cn/open-apis/bot/v2/hook/…',
      signing: 'optional',
      verification_mode: 'provider_response',
    },
    {
      provider: 'wecom',
      label: '企业微信群机器人',
      description: '发送原生文本并校验 errcode。',
      url_hint: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…',
      signing: 'none',
      verification_mode: 'provider_response',
    },
    {
      provider: 'dingtalk',
      label: '钉钉自定义机器人',
      description: '发送原生文本并校验 errcode，可选签名校验。',
      url_hint: 'https://oapi.dingtalk.com/robot/send?access_token=…',
      signing: 'optional',
      verification_mode: 'provider_response',
    },
    {
      provider: 'slack',
      label: 'Slack / GovSlack',
      description: '发送 Incoming Webhook 文本并校验 ok 响应。',
      url_hint: 'https://hooks.slack.com/services/…/…/…',
      signing: 'none',
      verification_mode: 'provider_response',
    },
    {
      provider: 'discord',
      label: 'Discord Incoming Webhook',
      description: '发送禁用 mentions 的文本并校验返回消息 ID。',
      url_hint: 'https://discord.com/api/webhooks/…/…',
      signing: 'none',
      verification_mode: 'provider_response',
    },
  ],
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
  onTest = vi.fn().mockResolvedValue({ sent: true, channel: value.channel }),
) {
  render(<MemoryRouter><DesignSystemProvider>
    <NotificationSettingsForm settings={value} onSave={onSave} onTest={onTest} />
  </DesignSystemProvider></MemoryRouter>)
  return { onSave, onTest }
}

describe('NotificationSettingsForm', () => {
  beforeEach(() => actionToast.clear())

  it('keeps a Webhook destination write-only and clears it as soon as saving starts', async () => {
    const browser = userEvent.setup()
    const request = deferred<UserNotificationSettings>()
    const onSave = vi.fn().mockReturnValue(request.promise)
    renderForm(settings(), onSave)

    const destination = screen.getByLabelText('Webhook 地址')
    expect(destination).toHaveAttribute('type', 'password')
    expect(destination).toHaveValue('')
    expect(screen.queryByDisplayValue(/Webhook 已配置/)).not.toBeInTheDocument()
    expect(screen.getByText(/平台预设会校验业务响应/)).toBeVisible()
    expect(screen.getByText(/保存成功仅表示配置已写入/)).toBeVisible()

    await browser.type(destination, 'https://example.invalid/hook')
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      channel: 'webhook',
      webhook_url: 'https://example.invalid/hook',
      webhook_provider: 'generic_event',
    })
    expect(destination).toHaveValue('')
    expect(screen.queryByDisplayValue('https://example.invalid/hook')).not.toBeInTheDocument()

    await act(async () => request.resolve(settings()))
    await waitFor(() => expect(screen.getByRole('button', { name: '保存通知设置' })).toBeDisabled())
  })

  it('tests only persisted configuration and leaves invalid raw destinations out of the page', async () => {
    const browser = userEvent.setup()
    const ready = settings({ enabled: false })
    const { onSave, onTest } = renderForm(ready)

    await browser.click(screen.getByRole('button', { name: '发送测试通知' }))
    await waitFor(() => expect(onTest).toHaveBeenCalledOnce())

    const destination = screen.getByLabelText('Webhook 地址')
    await browser.type(destination, 'http://example.invalid/hook')
    expect(screen.getByRole('button', { name: '发送测试通知' })).toBeDisabled()
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).not.toHaveBeenCalled()
    expect(await screen.findByText('Webhook 地址必须使用 HTTPS。')).toBeInTheDocument()
    expect(destination).toHaveValue('')
    expect(screen.queryByDisplayValue('http://example.invalid/hook')).not.toBeInTheDocument()
  })

  it('saves a provider preset and write-only signing Secret together', async () => {
    const browser = userEvent.setup()
    const request = deferred<UserNotificationSettings>()
    const onSave = vi.fn().mockReturnValue(request.promise)
    renderForm(settings(), onSave)

    await browser.click(screen.getByRole('button', { name: /Webhook 类型/ }))
    await browser.click(await screen.findByRole('option', { name: '飞书 / Lark V2' }))
    const destination = screen.getByLabelText('Webhook 地址')
    await browser.type(
      destination,
      'https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000000',
    )
    const signingSwitch = screen.getByRole('switch', { name: '启用机器人签名校验' })
    expect(signingSwitch).toHaveAccessibleDescription(/仅在接收端机器人已启用签名校验/)
    await browser.click(signingSwitch)
    const signingSecret = screen.getByLabelText('签名 Secret')
    await browser.type(signingSecret, 'write-only-signing-secret')
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      channel: 'webhook',
      webhook_provider: 'feishu_lark_v2',
      webhook_url: 'https://open.feishu.cn/open-apis/bot/v2/hook/00000000-0000-0000-0000-000000000000',
      webhook_signing_secret: 'write-only-signing-secret',
    })
    expect(destination).toHaveValue('')
    expect(signingSecret).toHaveValue('')
    expect(document.body.textContent).not.toContain('write-only-signing-secret')

    await act(async () => request.resolve(settings({
      webhook_provider: 'feishu_lark_v2',
      webhook_signing_secret_configured: true,
      webhook_verification_mode: 'provider_response',
    })))
  })

  it('requires legacy Feishu settings to be made explicit before adding signing', async () => {
    const browser = userEvent.setup()
    const onSave = vi.fn()
    renderForm(settings({
      webhook_provider: 'feishu_lark_v2',
      webhook_provider_explicit: false,
      webhook_verification_mode: 'provider_response',
    }), onSave)

    await browser.click(screen.getByRole('switch', { name: '启用机器人签名校验' }))
    const signingSecret = screen.getByLabelText('签名 Secret')
    await browser.type(signingSecret, 'legacy-secret-draft')
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).not.toHaveBeenCalled()
    expect(await screen.findByText('升级旧 Webhook 配置时，请选择类型并重新输入对应地址。')).toBeVisible()
    expect(signingSecret).toHaveValue('')
    expect(document.body.textContent).not.toContain('legacy-secret-draft')
  })

  it('requires an active legacy Webhook to be upgraded before any settings edit', async () => {
    const browser = userEvent.setup()
    const onSave = vi.fn().mockResolvedValue(settings({
      enabled: false,
      webhook_provider_explicit: true,
    }))
    renderForm(settings({
      webhook_provider_explicit: false,
    }), onSave)

    await browser.click(screen.getByRole('switch', { name: '启用新内容通知' }))
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).not.toHaveBeenCalled()
    expect(await screen.findByText('升级旧 Webhook 配置时，请选择类型并重新输入对应地址。')).toBeVisible()

    await browser.type(
      screen.getByLabelText('Webhook 地址'),
      'https://hooks.example.com/upgraded',
    )
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    await waitFor(() => expect(onSave).toHaveBeenCalledWith({
      enabled: false,
      channel: 'webhook',
      webhook_url: 'https://hooks.example.com/upgraded',
      webhook_provider: 'generic_event',
    }))
  })

  it('uses email wording for an email test result', async () => {
    const browser = userEvent.setup()
    const value = settings({
      channel: 'email',
      email_configured: true,
      webhook_configured: false,
    })
    renderForm(
      value,
      vi.fn().mockResolvedValue(value),
      vi.fn().mockResolvedValue({ sent: true, channel: 'email' }),
    )

    await browser.click(screen.getByRole('button', { name: '发送测试通知' }))

    expect(await screen.findByText('测试邮件已发送')).toBeVisible()
    expect(screen.getByText('请检查当前收件邮箱。')).toBeVisible()
    expect(screen.queryByText(/HTTP 成功状态/)).not.toBeInTheDocument()
  })

  it('shows paused email delivery without discarding the existing opt-in', async () => {
    const browser = userEvent.setup()
    const paused = settings({
      enabled: true,
      channel: 'email',
      email_configured: true,
      email_transport_ready: false,
      webhook_configured: false,
    })
    const { onSave, onTest } = renderForm(paused)

    expect(screen.getByText('邮箱通知已暂停')).toBeInTheDocument()
    expect(screen.getByText(/暂停期间不会产生邮件投递/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发送测试通知' })).toBeDisabled()
    expect(screen.getByRole('switch', { name: '启用新内容通知' })).toBeEnabled()

    await browser.click(screen.getByRole('switch', { name: '启用新内容通知' }))
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith({
      enabled: false,
      channel: 'email',
    }))
    expect(onTest).not.toHaveBeenCalled()
  })

  it('refreshes and shows persisted unknown status after an ambiguous test', async () => {
    const browser = userEvent.setup()
    const value = settings()
    const unknown = settings({
      last_test_status: 'unknown',
      last_tested_at: '2026-07-30T08:00:00Z',
      last_test_error_code: 'notification_webhook_response_invalid',
    })
    const notificationSettings = vi.fn()
      .mockResolvedValueOnce(value)
      .mockResolvedValue(unknown)
    const testNotificationSettings = vi.fn().mockRejectedValue(new ApiError(502, {
      code: 'notification_test_outcome_unknown',
      message: 'raw upstream response must stay private',
      retryable: false,
    }))
    const api = {
      notificationSettings,
      updateNotificationSettings: vi.fn().mockResolvedValue(value),
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

    expect(await screen.findByText('尚未发送测试通知')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '发送测试通知' }))

    await waitFor(() => expect(notificationSettings).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/最近一次测试结果未知，不会自动重发/)).toBeVisible()
    expect(screen.getByText('测试通知结果未知，请勿重复发送；请先确认接收端。')).toBeVisible()
    expect(testNotificationSettings).toHaveBeenCalledOnce()
    expect(document.body.textContent).not.toContain('raw upstream')
  })

  it('derives viewer access as read-only and blocks notification writes and tests', async () => {
    const browser = userEvent.setup()
    const value = settings()
    const updateNotificationSettings = vi.fn().mockResolvedValue(value)
    const testNotificationSettings = vi.fn().mockResolvedValue({ sent: true, channel: value.channel })
    const api = {
      notificationSettings: vi.fn().mockResolvedValue(value),
      updateNotificationSettings,
      testNotificationSettings,
    } as unknown as ServiceApi
    const token = { userId: 'viewer-1', generation: 0 }
    const context = {
      api,
      user: { id: 'viewer-1', username: 'viewer', role: 'viewer', enabled: true },
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

    expect(await screen.findByText('当前账户为只读权限')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: '启用新内容通知' })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Webhook.*通知方式/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Webhook 类型/ })).toBeDisabled()
    expect(screen.getByLabelText('Webhook 地址')).toBeDisabled()
    const save = screen.getByRole('button', { name: '保存通知设置' })
    const test = screen.getByRole('button', { name: '发送测试通知' })
    expect(save).toBeDisabled()
    expect(test).toBeDisabled()

    await browser.click(save)
    await browser.click(test)
    expect(updateNotificationSettings).not.toHaveBeenCalled()
    expect(testNotificationSettings).not.toHaveBeenCalled()
  })
})
