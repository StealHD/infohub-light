import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { CatalogSource, Subscription } from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { DesignSystemProvider } from '../../design-system'
import { SubscriptionForm } from './HeroSubscriptionDialogs'

const source: CatalogSource = {
  id: 'source-1',
  type: 'rss',
  display_name: '测试来源',
  scope: 'private',
  owner_user_id: 'user-1',
  enabled: true,
}

function renderSubscriptionForm(subscription: Subscription) {
  const api = {
    updateSubscription: vi.fn().mockResolvedValue(subscription),
    updateSourceSchedule: vi.fn().mockResolvedValue({
      enabled: false,
      interval_minutes: 360,
      worker_status: 'ready',
    }),
    unsubscribe: vi.fn(),
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
            onDone={vi.fn()}
            onJob={vi.fn()}
          />} />
        </Route>
      </Routes>
    </DesignSystemProvider>
  </MemoryRouter>)
  return api
}

describe('SubscriptionForm notification ownership', () => {
  it('does not submit notification state when analysis changes to personal only', async () => {
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

    await browser.click(screen.getByRole('button', { name: '保存订阅' }))

    await waitFor(() => expect(api.updateSubscription).toHaveBeenCalled())
    const [, payload] = vi.mocked(api.updateSubscription).mock.calls[0]
    expect(payload).toEqual(expect.objectContaining({ analysis_mode: 'personal_only' }))
    expect(payload).not.toHaveProperty('notify_on_new_items')
  })

  it('does not overwrite a disabled card notification preference on save', async () => {
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
    await browser.click(screen.getByRole('button', { name: '保存订阅' }))

    await waitFor(() => expect(api.updateSubscription).toHaveBeenCalled())
    const [, payload] = vi.mocked(api.updateSubscription).mock.calls[0]
    expect(payload).toEqual(expect.objectContaining({ analysis_mode: 'full' }))
    expect(payload).not.toHaveProperty('notify_on_new_items')
  })

  it('does not overwrite an enabled card notification preference when disabling the subscription', async () => {
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

    await browser.click(screen.getByRole('button', { name: '保存订阅' }))

    await waitFor(() => expect(api.updateSubscription).toHaveBeenCalled())
    const [, payload] = vi.mocked(api.updateSubscription).mock.calls[0]
    expect(payload).toEqual(expect.objectContaining({ enabled: false }))
    expect(payload).not.toHaveProperty('notify_on_new_items')
  })
})
