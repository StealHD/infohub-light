import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import type { CatalogSource, SourceTypeDefinition, Subscription } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { ActionFeedbackProvider } from '../../app/ActionFeedback'
import { DesignSystemProvider } from '../../design-system'
import { SourceForm, SubscriptionForm } from './HeroSubscriptionDialogs'

const source: CatalogSource = {
  id: 'source-1',
  type: 'rss',
  display_name: '测试来源',
  scope: 'private',
  owner_user_id: 'user-1',
  enabled: true,
}

const youtubeDefinition: SourceTypeDefinition = {
  type: 'youtube_channel',
  catalog_source_type: 'rss',
  label: 'YouTube 频道',
  credential_mode: undefined,
  fields: [
    {
      name: 'url',
      label: 'YouTube 频道地址或 @handle',
      input_type: 'text',
      required: true,
      default: null,
      help: '支持公开频道链接、@handle、频道 ID 或规范 Feed 地址。',
    },
    {
      name: 'keep_latest_item',
      label: '保留最新内容',
      input_type: 'boolean',
      required: false,
      default: true,
      help: '时间窗口为空时仅保留最近一条。',
    },
  ],
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => { resolve = next })
  return { promise, resolve }
}

function renderSubscriptionForm(subscription: Subscription, options: {
  api?: Partial<ServiceApi>
  onDone?: () => void
  onJob?: (kind: 'test' | 'fetch', sourceId: string, subscriptionId: string) => Promise<void>
  onPendingChange?: (pending: boolean) => void
} = {}) {
  const api = {
    updateSubscription: vi.fn().mockResolvedValue(subscription),
    updateSourceSchedule: vi.fn().mockResolvedValue({
      enabled: false,
      interval_minutes: 360,
      worker_status: 'ready',
    }),
    unsubscribe: vi.fn(),
    ...options.api,
  } as unknown as ServiceApi
  const token = { userId: 'user-1', generation: 0 }
  const context = {
    api,
    user: { id: 'user-1', username: 'member', role: 'member', enabled: true },
    query: '',
    setQuery: vi.fn(),
    activity: { state: 'idle', message: '' },
    refresh: vi.fn(),
    beginAction: () => token,
    isActionCurrent: () => true,
  } as unknown as AppOutletContext

  render(<MemoryRouter>
    <DesignSystemProvider>
      <Routes>
        <Route element={<Outlet context={context} />}>
          <Route index element={<SubscriptionForm
            subscription={subscription}
            source={source}
            readonly={false}
            taxonomy={{ channels: [], topics: [] }}
            onDone={options.onDone ?? vi.fn()}
            onJob={options.onJob ?? vi.fn()}
            onPendingChange={options.onPendingChange}
          />} />
        </Route>
      </Routes>
    </DesignSystemProvider>
  </MemoryRouter>)
  return api
}

function renderYouTubeSourceForm(
  onSubmit: (payload: Record<string, unknown>) => Promise<void>,
) {
  render(<MemoryRouter>
    <DesignSystemProvider>
      <ActionFeedbackProvider userId="user-1">
        <SourceForm
          definition={youtubeDefinition}
          secrets={[]}
          allowSecret={false}
          scopes={['private']}
          taxonomy={{ channels: [], topics: [] }}
          submitLabel="创建并订阅"
          onSubmit={onSubmit}
        />
      </ActionFeedbackProvider>
    </DesignSystemProvider>
  </MemoryRouter>)
}

describe('YouTube SourceForm', () => {
  it('submits the first-class setup type with the default latest-item policy', async () => {
    const browser = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    renderYouTubeSourceForm(onSubmit)

    expect(screen.getByRole('checkbox', { name: '保留最新内容' })).toBeChecked()
    await browser.type(screen.getByRole('textbox', { name: '来源名称' }), 'Google Developers')
    await browser.type(
      screen.getByRole('textbox', { name: 'YouTube 频道地址或 @handle' }),
      '@GoogleDevelopers',
    )
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'youtube_channel',
        scope: 'private',
        display_name: 'Google Developers',
        config: expect.objectContaining({
          url: '@GoogleDevelopers',
          keep_latest_item: true,
        }),
      }),
    ))
    expect(onSubmit.mock.calls[0]?.[0]).not.toHaveProperty('secret_env')
  })

  it('keeps a safe resolver error in the dialog and blocks replay while pending', async () => {
    const browser = userEvent.setup()
    const request = deferred<void>()
    const onSubmit = vi.fn().mockReturnValueOnce(request.promise).mockRejectedValueOnce(
      new ApiError(404, {
        code: 'youtube_channel_not_found',
        message: 'upstream detail',
      }),
    )
    renderYouTubeSourceForm(onSubmit)
    await browser.type(screen.getByRole('textbox', { name: '来源名称' }), 'Missing')
    await browser.type(
      screen.getByRole('textbox', { name: 'YouTube 频道地址或 @handle' }),
      '@Missing',
    )

    const submit = screen.getByRole('button', { name: '创建并订阅' })
    await browser.click(submit)
    expect(submit).toBeDisabled()
    await browser.click(submit)
    expect(onSubmit).toHaveBeenCalledTimes(1)
    request.resolve()
    await waitFor(() => expect(submit).toBeEnabled())

    await browser.click(submit)
    expect(await screen.findByText(
      '未找到这个 YouTube 频道，请检查链接或改用频道 ID。',
    )).toBeInTheDocument()
    expect(screen.queryByText('upstream detail')).not.toBeInTheDocument()
  })
})

describe('SubscriptionForm notification ownership', () => {
  it('does not render or submit notifications when analysis changes to personal only', async () => {
    const browser = userEvent.setup()
    const subscription: Subscription = {
      id: 'subscription-1',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      notify_on_new_items: true,
      schedule: { enabled: false, interval_minutes: 360 },
    }
    const api = renderSubscriptionForm(subscription)
    expect(screen.queryByRole('switch', { name: /新内容通知/ })).not.toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: /分析模式/ }))
    await browser.click(await screen.findByRole('option', { name: '仅收集' }))

    await browser.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(api.updateSubscription).toHaveBeenCalledWith(
      subscription.id,
      expect.objectContaining({
        analysis_mode: 'personal_only',
      }),
    ))
    expect(vi.mocked(api.updateSubscription).mock.calls[0]?.[1]).not.toHaveProperty('notify_on_new_items')
  })

  it('leaves an existing notification preference untouched for full analysis', async () => {
    const browser = userEvent.setup()
    const subscription: Subscription = {
      id: 'subscription-2',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      notify_on_new_items: false,
      schedule: { enabled: false, interval_minutes: 360 },
    }
    const api = renderSubscriptionForm(subscription)

    expect(screen.queryByRole('switch', { name: /新内容通知/ })).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(api.updateSubscription).toHaveBeenCalledWith(
      subscription.id,
      expect.objectContaining({
        analysis_mode: 'full',
      }),
    ))
    expect(vi.mocked(api.updateSubscription).mock.calls[0]?.[1]).not.toHaveProperty('notify_on_new_items')
  })

  it('does not submit notifications when the subscription is disabled', async () => {
    const browser = userEvent.setup()
    const subscription: Subscription = {
      id: 'subscription-3',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      notify_on_new_items: true,
      schedule: { enabled: false, interval_minutes: 360 },
    }
    const api = renderSubscriptionForm(subscription)

    await browser.click(screen.getByRole('checkbox', { name: '启用订阅' }))
    expect(screen.queryByRole('switch', { name: /新内容通知/ })).not.toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(api.updateSubscription).toHaveBeenCalledWith(
      subscription.id,
      expect.objectContaining({
        enabled: false,
      }),
    ))
    expect(vi.mocked(api.updateSubscription).mock.calls[0]?.[1]).not.toHaveProperty('notify_on_new_items')
  })

  it('requires an explicit second action before unsubscribing', async () => {
    const browser = userEvent.setup()
    const subscription: Subscription = {
      id: 'subscription-unsubscribe',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      schedule: { enabled: false, interval_minutes: 360 },
    }
    const api = renderSubscriptionForm(subscription)

    await browser.click(screen.getByRole('button', { name: '取消订阅…' }))
    expect(screen.getByText('确认取消这个订阅？')).toBeInTheDocument()
    expect(api.unsubscribe).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('button', { name: '确认取消订阅' }))
    await waitFor(() => expect(api.unsubscribe).toHaveBeenCalledWith(subscription.id))
  })

  it('locks every form exit while a save is pending', async () => {
    const browser = userEvent.setup()
    const updateRequest = deferred<Subscription>()
    const onPendingChange = vi.fn()
    const subscription: Subscription = {
      id: 'subscription-pending',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      schedule: { enabled: false, interval_minutes: 360 },
    }
    renderSubscriptionForm(subscription, {
      api: { updateSubscription: vi.fn().mockReturnValue(updateRequest.promise) },
      onPendingChange,
    })

    await browser.click(screen.getByRole('button', { name: '保存' }))
    await waitFor(() => expect(onPendingChange).toHaveBeenLastCalledWith(true))
    expect(screen.getByRole('button', { name: '保存' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '保存并获取' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '仅测试连接' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '取消订阅…' })).toBeDisabled()

    updateRequest.resolve(subscription)
    await waitFor(() => expect(onPendingChange).toHaveBeenLastCalledWith(false))
  })
})
