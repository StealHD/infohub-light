import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { CatalogSource } from '../../api/types'
import { DesignSystemProvider } from '../../design-system'
import { SubscriptionRows } from './HeroSubscriptionChannelViews'

function renderSource(status: string, reason: string | null = null, canEdit = true, canManageActors = true) {
  const source: CatalogSource = {
    id: 'bili', type: 'rss', setup_type: 'bilibili', display_name: '测试 UP 主',
    scope: 'private', enabled: status === 'ready' && !reason,
    acquisition: { provider: 'apify', status, allowed: status === 'ready' && !reason, reason },
  }
  const onFetch = vi.fn()
  render(<MemoryRouter><DesignSystemProvider><SubscriptionRows
    items={[{ source, subscription: { id: 'sub', source_id: 'bili', user_id: 'owner', enabled: true },
      fetchLabel: '立即获取', notificationPending: false, canEdit, canShare: false }]}
    editable actorOpsEditable={canManageActors} onFetch={onFetch} onToggleNotification={vi.fn()} onEditSubscription={vi.fn()}
    onEditSource={vi.fn()} onShare={vi.fn()}
  /></DesignSystemProvider></MemoryRouter>)
  return onFetch
}

describe('Bilibili subscription acquisition state', () => {
  it('shows pending actor verification and blocks fetch while retaining setup entry', async () => {
    const onFetch = renderSource('pending', 'actorops_v2_binding_pending')
    expect(screen.getByText('Bilibili UP 主 · 私人订阅')).toBeInTheDocument()
    expect(screen.getByText('更新：等待 Actor 验证')).toBeInTheDocument()
    expect(screen.queryByText('更新：订阅已停用')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '配置 Bilibili 主备' })).toHaveAttribute('href', '/settings/actorops')
    const fetch = screen.getByRole('button', { name: /立即获取 测试 UP 主/ })
    expect(fetch).toBeDisabled()
    await userEvent.click(fetch)
    expect(onFetch).not.toHaveBeenCalled()
  })

  it('distinguishes an explicitly disabled binding', () => {
    renderSource('disabled', 'actorops_v2_binding_disabled')
    expect(screen.getByText('更新：来源已停用')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /立即获取 测试 UP 主/ })).toBeDisabled()
  })

  it('does not offer settings access to members without source management', () => {
    renderSource('pending', 'actorops_v2_binding_pending', true, false)
    expect(screen.queryByRole('link', { name: '配置 Bilibili 主备' })).not.toBeInTheDocument()
    expect(screen.getByText('请联系管理员配置主备')).toBeInTheDocument()
  })

  it('allows a ready source to fetch', async () => {
    const onFetch = renderSource('ready')
    const fetch = screen.getByRole('button', { name: /立即获取 测试 UP 主/ })
    expect(fetch).toBeEnabled()
    await userEvent.click(fetch)
    expect(onFetch).toHaveBeenCalledOnce()
  })
})
