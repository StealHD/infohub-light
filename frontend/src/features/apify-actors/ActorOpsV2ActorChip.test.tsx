import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { ActorOpsV2ActorChip } from './ActorOpsV2ActorChip'

const candidate = {
  candidate_id: 'candidate-1', build_number: '1.0.10', lifecycle: 'certified', assignment: 'active', priority: 0, generation: 1,
  store_metadata: { actor_slug: 'instagram-scraper/instagram-profile-posts-scraper', display_name: 'Instagram Profile Posts Scraper', short_description: null, developer_name: 'instagram-scraper', maintained_by_apify: false, rating: 5, review_count: 1, bookmark_count: 2, total_users: 2100, monthly_active_users: null, pricing: [], last_modified_at: null, observed_at: '2026-08-24T00:00:00Z', generation: 1 },
  evidence_progress: { verified_bindings: 0, required_bindings: 1 },
}

describe('ActorOpsV2ActorChip', () => {
  it('keeps the preview open while moving from the chip to its interactive surface, then closes after leaving both', async () => {
    const browser = userEvent.setup()
    render(<ActorOpsV2ActorChip candidate={candidate} />)

    const trigger = screen.getByRole('button', { name: '查看Instagram Profile Posts Scraper商城信息' })
    await browser.hover(trigger)
    const dialog = await screen.findByRole('dialog', { name: 'Instagram Profile Posts Scraper 商城信息' })
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
})
