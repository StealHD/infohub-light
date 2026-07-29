import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { UserNotificationSettings } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { actionToast, DesignSystemProvider } from '../../design-system'
import { HeroNotificationSettings, NotificationSettingsForm } from './HeroNotificationSettings'

const settings = (overrides: Partial<UserNotificationSettings> = {}): UserNotificationSettings => ({
  schema_version: 1,
  enabled: true,
  channel: 'webhook',
  email_configured: false,
  email_transport_ready: true,
  webhook_configured: true,
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
    expect(screen.getByText(/飞书\/Lark V2 仅支持未启用签名校验/)).toBeVisible()
    expect(screen.getByText(/保存成功只表示配置已写入/)).toBeVisible()

    await browser.type(destination, 'https://example.invalid/hook')
    await browser.click(screen.getByRole('button', { name: '保存通知设置' }))

    expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      channel: 'webhook',
      webhook_url: 'https://example.invalid/hook',
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
