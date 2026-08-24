import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ActorOpsV2CandidateView } from './actorOpsV2RouteModel'
import { ActorOpsV2CandidateCard } from './ActorOpsV2CandidateCard'

const readableCandidate: ActorOpsV2CandidateView = {
  candidate_id: 'candidate-1', build_number: '1.2.3', lifecycle: 'static_valid', assignment: 'inactive', priority: null, generation: 2,
  store_metadata: {
    actor_slug: 'apidojo/tweet-scraper', display_name: 'Tweet Scraper V2', short_description: null, developer_name: 'apidojo', maintained_by_apify: true,
    rating: 3.9, review_count: 181, bookmark_count: 1415, total_users: 74413, monthly_active_users: null, pricing: [{ minimumChargeUsd: 0.02 }], last_modified_at: null, observed_at: '2026-08-24T00:00:00+00:00', generation: 1,
  },
  evidence_progress: { verified_bindings: 1, required_bindings: 2 },
}

describe('ActorOpsV2CandidateCard', () => {
  it('shows public Actor basics before a replacement is authorized', async () => {
    const onSelect = vi.fn()
    render(<ActorOpsV2CandidateCard candidate={readableCandidate} selected={false} onSelect={onSelect} />)

    expect(screen.getByText('Tweet Scraper V2')).toBeInTheDocument()
    expect(screen.getByText('apidojo/tweet-scraper')).toBeInTheDocument()
    expect(screen.getByText('评分 3.9（181）')).toBeInTheDocument()
    expect(screen.getByText('收藏 1.4K')).toBeInTheDocument()
    expect(screen.getByText('用户 74.4K')).toBeInTheDocument()
    expect(screen.getByText('开发者：apidojo')).toBeInTheDocument()
    expect(screen.getByText('Maintained by Apify')).toBeInTheDocument()
    expect(screen.getByText('$0.02 · 已核验 1/2')).toBeInTheDocument()

    await userEvent.setup().click(screen.getByRole('button', { name: '选择 Tweet Scraper V2' }))
    expect(onSelect).toHaveBeenCalledWith(readableCandidate)
  })

  it('does not expose an opaque actor identifier as its public name', () => {
    const candidate: ActorOpsV2CandidateView = {
      ...readableCandidate,
      store_metadata: { ...readableCandidate.store_metadata!, actor_slug: '4wL6Wm4CWnpgaDALa', display_name: '4wL6Wm4CWnpgaDALa' },
    }
    render(<ActorOpsV2CandidateCard candidate={candidate} selected={false} onSelect={vi.fn()} />)

    expect(screen.getByText('商城信息待更新')).toBeInTheDocument()
    expect(screen.queryByText('4wL6Wm4CWnpgaDALa')).not.toBeInTheDocument()
  })
})
