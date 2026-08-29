import { render, screen, waitFor, within } from '@testing-library/react'
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
      name: 'fetch_limit',
      label: '每次获取条数',
      input_type: 'number',
      required: false,
      default: 20,
      min: 1,
      max: 100,
      help: '每次最多保留的公开视频数量。',
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

const xProfileDefinition: SourceTypeDefinition = {
  type: 'x_profile',
  catalog_source_type: 'apify_social',
  label: 'X 账号',
  credential_mode: undefined,
  fields: [
    {
      name: 'target',
      label: 'X 用户名或主页链接',
      input_type: 'text',
      required: true,
      default: null,
      help: '输入公开 X 用户名、@handle 或主页链接。',
    },
    {
      name: 'fetch_limit',
      label: '每次获取条数',
      input_type: 'number',
      required: false,
      default: 20,
      min: 1,
      max: 100,
      help: '每次最多获取的公开动态数量。',
    },
    {
      name: 'analysis_mode',
      label: '分析模式',
      input_type: 'select',
      required: false,
      default: 'full',
      options: [{ value: 'full', label: '完整分析' }, { value: 'personal_only', label: '仅收集' }],
      help: '选择完整分析或仅收集到个人信息流。',
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

function renderXSourceForm(
  onSubmit: (payload: Record<string, unknown>) => Promise<void>,
  configLocked = false,
) {
  render(<MemoryRouter>
    <DesignSystemProvider>
      <ActionFeedbackProvider userId="user-1">
        <SourceForm
          definition={xProfileDefinition}
          source={{ ...source, type: 'apify_social', config: { target: 'openai', fetch_limit: 6, analysis_mode: 'full' } }}
          secrets={[]}
          allowSecret={false}
          scopes={['private']}
          taxonomy={{ channels: [], topics: [] }}
          submitLabel="保存来源"
          configLocked={configLocked}
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
    expect(screen.queryByText('高级配置')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('高级配置 JSON')).not.toBeInTheDocument()
    await browser.type(screen.getByRole('textbox', { name: '来源名称' }), 'Google Developers')
    await browser.type(
      screen.getByRole('textbox', { name: 'YouTube 频道地址或 @handle' }),
      '@GoogleDevelopers',
    )
    await browser.clear(screen.getByRole('spinbutton', { name: '每次获取条数' }))
    await browser.type(screen.getByRole('spinbutton', { name: '每次获取条数' }), '3')
    await browser.click(screen.getByRole('button', { name: '创建并订阅' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'youtube_channel',
        scope: 'private',
        display_name: 'Google Developers',
        config: expect.objectContaining({
          url: '@GoogleDevelopers',
          fetch_limit: 3,
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

describe('locked platform SourceForm', () => {
  it('does not disable a managed source when its hidden enable control is absent', async () => {
    const browser = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    renderXSourceForm(onSubmit)

    expect(screen.queryByRole('checkbox', { name: '启用来源' })).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '保存来源' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledOnce())
    expect(onSubmit.mock.calls[0]?.[0]).not.toHaveProperty('enabled')
  })

  it('keeps the platform target locked while saving a new fetch limit', async () => {
    const browser = userEvent.setup()
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    renderXSourceForm(onSubmit, true)

    expect(screen.getByRole('textbox', { name: 'X 用户名或主页链接' })).toBeDisabled()
    const fetchLimit = screen.getByRole('spinbutton', { name: '每次获取条数' })
    expect(fetchLimit).toBeEnabled()
    await browser.clear(fetchLimit)
    await browser.type(fetchLimit, '3')
    await browser.click(screen.getByRole('button', { name: '保存来源' }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({ target: 'openai', fetch_limit: 3, analysis_mode: 'full' }),
      }),
    ))
  })
})

describe('SubscriptionForm notification ownership', () => {
  it('defaults to global mode, reveals the source interval on demand, and preserves it when switching back', async () => {
    const browser = userEvent.setup()
    const subscription: Subscription = {
      id: 'subscription-global-mode',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      schedule: { enabled: false, interval_minutes: 180 },
    }
    const api = renderSubscriptionForm(subscription)
    const globalMode = screen.getByRole('radio', { name: '跟随全局（默认）' })
    const sourceMode = screen.getByRole('radio', { name: '单源独立周期' })

    expect(globalMode).toBeChecked()
    expect(sourceMode).not.toBeChecked()
    expect(screen.queryByRole('button', { name: /单源更新周期/ })).not.toBeInTheDocument()

    await browser.click(sourceMode)
    expect(sourceMode).toBeChecked()
    expect(screen.getByRole('button', { name: /单源更新周期/ })).toHaveTextContent('每 3 小时')

    await browser.click(globalMode)
    expect(screen.queryByRole('button', { name: /单源更新周期/ })).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(api.updateSourceSchedule).toHaveBeenCalledWith(
      subscription.id,
      { enabled: false, interval_minutes: 180 },
    ))
  })

  it('projects an enabled source schedule as the independent mode', async () => {
    const browser = userEvent.setup()
    const subscription: Subscription = {
      id: 'subscription-source-mode',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      schedule: { enabled: true, interval_minutes: 60 },
    }
    const api = renderSubscriptionForm(subscription)

    expect(screen.getByRole('radio', { name: '单源独立周期' })).toBeChecked()
    expect(screen.getByRole('button', { name: /单源更新周期/ })).toHaveTextContent('每 1 小时')
    await browser.click(screen.getByRole('button', { name: '保存' }))

    await waitFor(() => expect(api.updateSourceSchedule).toHaveBeenCalledWith(
      subscription.id,
      { enabled: true, interval_minutes: 60 },
    ))
  })

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
    const confirmation = await screen.findByRole('dialog', { name: '确认取消这个订阅？' })
    expect(within(confirmation).getByText('这只影响你的订阅，不会删除共享来源或其他成员的数据。')).toBeInTheDocument()
    expect(api.unsubscribe).not.toHaveBeenCalled()
    await browser.click(within(confirmation).getByRole('button', { name: '保留订阅' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '取消订阅…' })).toHaveFocus())
    await browser.click(screen.getByRole('button', { name: '取消订阅…' }))
    const secondConfirmation = await screen.findByRole('dialog', { name: '确认取消这个订阅？' })
    await browser.click(within(secondConfirmation).getByRole('button', { name: '确认取消订阅' }))
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
