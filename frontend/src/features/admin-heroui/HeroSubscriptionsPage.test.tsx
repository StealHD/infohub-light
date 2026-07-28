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
  const onEditSource = vi.fn()
  const onShare = vi.fn()
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
    onEditSource={onEditSource}
    onShare={onShare}
  /></DesignSystemProvider></MemoryRouter>)
  return { onToggleNotification, onEditSource, onShare }
}

describe('subscription source card notifications', () => {
  it('labels a projected YouTube RSS row by its setup type', () => {
    renderCard({
      id: 'subscription-youtube',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
    }, {
      source: {
        ...source,
        type: 'rss',
        setup_type: 'youtube_channel',
      },
    })

    expect(screen.getByText(/YouTube 频道/)).toBeInTheDocument()
  })

  it('shows the effective notification state as a card switch', async () => {
    const browser = userEvent.setup()
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
    notification.focus()
    await browser.keyboard('[Space]')
    expect(onToggleNotification).toHaveBeenCalledWith(
      expect.objectContaining({ subscription }),
      false,
    )
  })

  it('keeps a focusable explanation while blocking personal-only notifications', async () => {
    const { onToggleNotification } = renderCard({
      id: 'subscription-2',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'personal_only',
      notify_on_new_items: true,
    })
    const notification = screen.getByRole('switch', { name: '新内容通知：通知来源' })
    expect(notification).not.toBeChecked()
    expect(notification).toHaveAttribute('aria-disabled', 'true')
    await userEvent.click(notification)
    expect(onToggleNotification).not.toHaveBeenCalled()
  })

  it('blocks notifications for a disabled subscription', async () => {
    const { onToggleNotification } = renderCard({
      id: 'subscription-3',
      user_id: 'user-1',
      source_id: source.id,
      enabled: false,
      analysis_mode: 'full',
      notify_on_new_items: true,
    })
    const notification = screen.getByRole('switch', { name: '新内容通知：通知来源' })
    expect(notification).not.toBeChecked()
    expect(notification).toHaveAttribute('aria-disabled', 'true')
    await userEvent.click(notification)
    expect(onToggleNotification).not.toHaveBeenCalled()
  })

  it('blocks notifications for a disabled source', async () => {
    const { onToggleNotification } = renderCard({
      id: 'subscription-disabled-source',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      notify_on_new_items: true,
    }, { source: { ...source, enabled: false } })
    const notification = screen.getByRole('switch', { name: '新内容通知：通知来源' })
    expect(notification).not.toBeChecked()
    expect(notification).toHaveAttribute('aria-disabled', 'true')
    await userEvent.click(notification)
    expect(onToggleNotification).not.toHaveBeenCalled()
  })

  it('keeps the fetch button label and geometry class stable while busy', () => {
    renderCard({
      id: 'subscription-4',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
    }, { fetchLabel: '获取中' })

    const fetchButton = screen.getByRole('button', { name: /^获取中 通知来源；上次抓取 0 条；/ })
    expect(fetchButton).toHaveTextContent('立即获取')
    expect(fetchButton).toHaveClass('min-w-[104px]')
    expect(fetchButton.parentElement).toHaveAttribute('aria-busy', 'true')
    expect(fetchButton).toBeDisabled()
    expect(fetchButton.querySelector('svg')).toHaveClass('animate-spin', 'motion-reduce:animate-none')
  })

  it('keeps edit and share directly visible in the lower control row', async () => {
    const browser = userEvent.setup()
    const { onEditSource, onShare } = renderCard({
      id: 'subscription-5',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
    }, { canEdit: true, canShare: true })

    const editSource = screen.getByRole('button', { name: '编辑来源：通知来源' })
    expect(editSource.closest('[data-source-card-header]')).toBeNull()
    expect(editSource.closest('[data-source-card-controls]')).not.toBeNull()
    await browser.click(editSource)
    expect(onEditSource).toHaveBeenCalledWith(source, expect.any(HTMLElement))

    expect(screen.queryByRole('button', { name: '更多操作：通知来源' })).not.toBeInTheDocument()
    const share = screen.getByRole('button', { name: '分享来源：通知来源' })
    expect(share.closest('[data-source-card-controls]')).not.toBeNull()
    await browser.click(share)
    expect(onShare).toHaveBeenCalledWith(source, expect.any(HTMLElement))
  })

  it('shows today, feed-window and historical counts while keeping fetched count in metadata', () => {
    renderCard({
      id: 'subscription-counts',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
    }, {
      health: {
        subscription_id: 'subscription-counts',
        source_id: source.id,
        status: 'healthy',
        consecutive_failures: 0,
        last_fetched_count: 2,
        today_item_count: 1,
        feed_item_count: 4,
        current_item_count: 4,
        history_item_count: 2,
      },
    })

    expect(document.querySelector('[data-source-counts]')).toHaveTextContent('今日1近7天4历史2')
    expect(screen.getByLabelText('最近更新 尚未完成，上次抓取 2 条')).toBeInTheDocument()
    expect(screen.queryByText('上次抓取 2 条')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看 通知来源 的 2 条历史内容' })).toHaveAttribute(
      'href',
      '/history?source_id=source-1',
    )
  })
})
