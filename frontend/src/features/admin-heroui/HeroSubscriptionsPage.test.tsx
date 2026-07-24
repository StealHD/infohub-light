import { render, screen } from '@testing-library/react'
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

function renderCard(subscription: Subscription) {
  render(<MemoryRouter><DesignSystemProvider><SubscriptionRows
    items={[{
      source,
      subscription,
      channel: '其他',
      fetchLabel: '立即获取',
      canEdit: false,
      canShare: false,
    }]}
    editable
    onFetch={vi.fn()}
    onEditSubscription={vi.fn()}
    onEditSource={vi.fn()}
    onShare={vi.fn()}
  /></DesignSystemProvider></MemoryRouter>)
}

describe('subscription source card notifications', () => {
  it('shows the notification chip only when delivery is effective', () => {
    renderCard({
      id: 'subscription-1',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'full',
      notify_on_new_items: true,
    })
    expect(screen.getByText('新内容通知')).toBeInTheDocument()
  })

  it('does not claim notification delivery for personal-only content', () => {
    renderCard({
      id: 'subscription-2',
      user_id: 'user-1',
      source_id: source.id,
      enabled: true,
      analysis_mode: 'personal_only',
      notify_on_new_items: true,
    })
    expect(screen.queryByText('新内容通知')).not.toBeInTheDocument()
  })

  it('does not show the notification chip for a disabled subscription', () => {
    renderCard({
      id: 'subscription-3',
      user_id: 'user-1',
      source_id: source.id,
      enabled: false,
      analysis_mode: 'full',
      notify_on_new_items: true,
    })
    expect(screen.queryByText('新内容通知')).not.toBeInTheDocument()
  })
})
