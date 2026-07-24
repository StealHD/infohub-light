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

describe('SubscriptionForm notifications', () => {
  it('clears and disables source notifications when analysis changes to personal only', async () => {
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
    const notification = screen.getByRole('switch', { name: '从现在开始接收新内容通知' })
    expect(notification).toBeChecked()

    await browser.click(screen.getByRole('button', { name: /分析模式/ }))
    await browser.click(await screen.findByRole('option', { name: '仅收集' }))

    expect(notification).not.toBeChecked()
    expect(notification).toBeDisabled()
    expect(screen.getByText(/“仅收集”内容不会推送/)).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '保存订阅' }))

    await waitFor(() => expect(api.updateSubscription).toHaveBeenCalledWith(
      subscription.id,
      expect.objectContaining({
        analysis_mode: 'personal_only',
        notify_on_new_items: false,
      }),
    ))
  })

  it('persists an enabled notification preference for full analysis', async () => {
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

    await browser.click(screen.getByRole('switch', { name: '从现在开始接收新内容通知' }))
    await browser.click(screen.getByRole('button', { name: '保存订阅' }))

    await waitFor(() => expect(api.updateSubscription).toHaveBeenCalledWith(
      subscription.id,
      expect.objectContaining({
        analysis_mode: 'full',
        notify_on_new_items: true,
      }),
    ))
  })

  it('clears the notification preference when the subscription is disabled', async () => {
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

    const notification = screen.getByRole('switch', { name: '从现在开始接收新内容通知' })
    expect(notification).not.toBeChecked()
    expect(notification).toBeDisabled()
    expect(screen.getByText(/停用订阅会同时关闭通知/)).toBeInTheDocument()

    await browser.click(screen.getByRole('button', { name: '保存订阅' }))

    await waitFor(() => expect(api.updateSubscription).toHaveBeenCalledWith(
      subscription.id,
      expect.objectContaining({
        enabled: false,
        notify_on_new_items: false,
      }),
    ))
  })
})
