import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { CatalogSource, Subscription } from '../../api/types'
import { DesignSystemProvider } from '../../design-system'
import { SubscriptionRows } from './HeroSubscriptionChannelViews'

const source: CatalogSource = {
  id: 'source-1',
  type: 'rss',
  display_name: '通知来源',
  scope: 'private',
  enabled: true,
}

function renderCard(subscription: Subscription, overrides: Partial<Parameters<typeof SubscriptionRows>[0]['items'][number]> = {}) {
  const onToggleNotification = vi.fn()
  render(<MemoryRouter><DesignSystemProvider><SubscriptionRows
    items={[{
      source,
      subscription,
      channel: '其他',
      fetchLabel: '立即获取',
      notificationPending: false,
      canEdit: false,
      canShare: false,
      ...overrides,
    }]}
    editable
    onFetch={vi.fn()}
    onToggleNotification={onToggleNotification}
    onEditSubscription={vi.fn()}
    onEditSource={vi.fn()}
    onShare={vi.fn()}
  /></DesignSystemProvider></MemoryRouter>)
  return { onToggleNotification }
}

describe('subscription source card notifications', () => {
  it('shows the effective notification state as a card switch', async () => {
    const subscription = {
      id: 'subscription-1',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      notify_on_new_items: true,
    } satisfies Subscription
    const { onToggleNotification } = renderCard(subscription)
    const notification = screen.getByRole('switch', { name: '新内容通知：通知来源' })

    expect(notification).toBeChecked()
    expect(notification).toBeEnabled()
    await userEvent.click(notification)
    expect(onToggleNotification).toHaveBeenCalledWith(
      expect.objectContaining({ subscription }),
      false,
    )
  })

  it('disables and clears the effective switch for personal-only content', () => {
    renderCard({
      id: 'subscription-2',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'personal_only',
      notify_on_new_items: true,
    })
    const notification = screen.getByRole('switch', { name: '新内容通知：通知来源' })
    expect(notification).not.toBeChecked()
    expect(notification).toBeDisabled()
  })

  it('disables and clears the effective switch for a disabled subscription', () => {
    renderCard({
      id: 'subscription-3',
      user_id: 'user-1',
      source_id: source.id,
      enabled: false,
      analysis_mode: 'full',
      notify_on_new_items: true,
    })
    const notification = screen.getByRole('switch', { name: '新内容通知：通知来源' })
    expect(notification).not.toBeChecked()
    expect(notification).toBeDisabled()
  })

  it('disables and clears the effective switch for a disabled source', () => {
    renderCard({
      id: 'subscription-source-disabled',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      notify_on_new_items: true,
    }, { source: { ...source, enabled: false } })
    const notification = screen.getByRole('switch', { name: '新内容通知：通知来源' })
    expect(notification).not.toBeChecked()
    expect(notification).toBeDisabled()
  })

  it('keeps the fetch button label and geometry class stable while busy', () => {
    renderCard({
      id: 'subscription-4',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
    }, { fetchLabel: '获取中' })

    const fetchButton = screen.getByRole('button', { name: '获取中 通知来源' })
    expect(fetchButton).toHaveTextContent('立即获取')
    expect(fetchButton).toHaveClass('min-w-[104px]')
    expect(fetchButton.parentElement).toHaveAttribute('aria-busy', 'true')
    expect(fetchButton).toBeDisabled()
    expect(fetchButton.querySelector('svg')).toHaveClass('animate-spin', 'motion-reduce:animate-none')
  })

  it('places share and edit actions directly on the card', () => {
    renderCard({
      id: 'subscription-5',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
    }, { canEdit: true, canShare: true })

    expect(screen.getByRole('button', { name: '分享 通知来源' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '编辑 通知来源 来源' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /更多操作/ })).not.toBeInTheDocument()
  })
})
