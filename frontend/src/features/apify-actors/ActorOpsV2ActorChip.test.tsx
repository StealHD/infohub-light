import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { ActorOpsV2ActorChip } from './ActorOpsV2ActorChip'

const candidate = {
  candidate_id: 'candidate-1', build_number: '1.0.10', lifecycle: 'certified', assignment: 'active', priority: 0, generation: 1,
  operational_status: 'normal' as const, issue_code: null, last_success_at: null, last_failure_at: null, retry_at: null, avatar_mapping_status: 'ready' as const,
  store_metadata: { actor_slug: 'instagram-scraper/instagram-profile-posts-scraper', display_name: 'Instagram Profile Posts Scraper', short_description: null, developer_name: 'instagram-scraper', maintained_by_apify: false, rating: 5, review_count: 1, bookmark_count: 2, total_users: 2100, monthly_active_users: null, pricing: [], last_modified_at: null, observed_at: '2026-08-24T00:00:00Z', generation: 1 },
  evidence_progress: { verified_bindings: 0, required_bindings: 1 },
}

describe('ActorOpsV2ActorChip', () => {
  it('keeps one pointer cursor on the full Popover trigger instead of switching at the Chip boundary', () => {
    render(<ActorOpsV2ActorChip candidate={candidate} />)

    const trigger = screen.getByRole('button', { name: '查看Instagram Profile Posts Scraper商城信息' })
    expect(trigger).toHaveClass('cursor-pointer')
    expect(trigger).toHaveClass('inline-flex')
    expect(trigger.querySelector('[data-slot="chip"]')).not.toHaveClass('cursor-pointer')
  })

  it('keeps the preview open while moving from the chip to its interactive surface, then closes after leaving both', async () => {
    const browser = userEvent.setup()
    render(<ActorOpsV2ActorChip candidate={candidate} />)

    const trigger = screen.getByRole('button', { name: '查看Instagram Profile Posts Scraper商城信息' })
    await browser.hover(trigger)
    const dialog = await screen.findByRole('dialog', { name: 'Instagram Profile Posts Scraper 商城信息' })
    expect(screen.queryByTestId('underlay')).not.toBeInTheDocument()
    expect(trigger).not.toHaveAttribute('aria-hidden')
    await browser.unhover(trigger)
    await browser.hover(dialog)
    expect(screen.getByRole('link', { name: '打开 Apify' })).toBeInTheDocument()

    await browser.unhover(dialog)
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Instagram Profile Posts Scraper 商城信息' })).not.toBeInTheDocument())
  })

  it('opens from keyboard focus, supports Escape, and keeps touch-style clicks available', async () => {
    const browser = userEvent.setup()
    render(<ActorOpsV2ActorChip candidate={candidate} />)

    const trigger = screen.getByRole('button', { name: '查看Instagram Profile Posts Scraper商城信息' })
    trigger.focus()
    expect(await screen.findByRole('dialog', { name: 'Instagram Profile Posts Scraper 商城信息' })).toBeInTheDocument()
    await browser.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Instagram Profile Posts Scraper 商城信息' })).not.toBeInTheDocument()
    await waitFor(() => expect(trigger).toHaveFocus())

    await browser.click(trigger)
    expect(await screen.findByRole('link', { name: '打开 Apify' })).toBeInTheDocument()
  })

  it('shows two-level operational labels and safe failure details', async () => {
    const browser = userEvent.setup()
    const { rerender } = render(<ActorOpsV2ActorChip candidate={{ ...candidate, operational_status: 'recent_failure', issue_code: 'stale_regression', last_failure_at: '2026-08-27T05:00:00Z' }} />)

    expect(screen.getByText('最近失败')).toBeInTheDocument()
    await browser.hover(screen.getByRole('button', { name: '查看Instagram Profile Posts Scraper商城信息' }))
    expect(await screen.findByText(/返回内容早于来源水位/)).toBeInTheDocument()
    expect(screen.getByText('头像映射')).toBeInTheDocument()
    expect(screen.getByText('已就绪')).toBeInTheDocument()

    rerender(<ActorOpsV2ActorChip candidate={{ ...candidate, operational_status: 'confirmed_failure', issue_code: 'build_unavailable', last_failure_at: '2026-08-27T05:00:00Z' }} />)
    expect(screen.getAllByText('已确认故障')).toHaveLength(2)
    expect(await screen.findByText(/系统已停止调度这个 Actor/)).toBeInTheDocument()
  })
})
