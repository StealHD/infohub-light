import { describe, expect, it } from 'vitest'

import { actorOpsV2CandidateHasPublicIdentity, actorOpsV2CandidateLabel, compareActorOpsV2ReplacementCandidates, type ActorOpsV2CandidateView } from './actorOpsV2RouteModel'

const candidate: ActorOpsV2CandidateView = {
  candidate_id: 'candidate-1', build_number: null, lifecycle: 'static_valid', assignment: 'inactive', priority: null, generation: 1,
  store_metadata: {
    actor_slug: 'apify/tweet-scraper', display_name: 'Tweet Scraper', short_description: null, developer_name: null, maintained_by_apify: false,
    rating: null, review_count: null, bookmark_count: null, total_users: null, monthly_active_users: null, pricing: [], last_modified_at: null, observed_at: '2026-08-24T00:00:00+00:00', generation: 1,
  },
  evidence_progress: { verified_bindings: 0, required_bindings: 2 },
}

describe('actorOpsV2RouteModel', () => {
  it('keeps opaque marketplace IDs out of the selectable Actor identity', () => {
    const opaque = { ...candidate, store_metadata: { ...candidate.store_metadata!, actor_slug: '4wL6Wm4CWnpgaDALa', display_name: '4wL6Wm4CWnpgaDALa' } }

    expect(actorOpsV2CandidateLabel(opaque)).toBe('商城信息待更新')
    expect(actorOpsV2CandidateHasPublicIdentity(opaque)).toBe(false)
    expect(actorOpsV2CandidateHasPublicIdentity(candidate)).toBe(true)
  })

  it('orders replacement choices by public total users before verification state', () => {
    const popular = { ...candidate, candidate_id: 'popular', store_metadata: { ...candidate.store_metadata!, total_users: 135000 }, evidence_progress: { verified_bindings: 0, required_bindings: 2 } }
    const verified = { ...candidate, candidate_id: 'verified', store_metadata: { ...candidate.store_metadata!, total_users: 10000 }, evidence_progress: { verified_bindings: 2, required_bindings: 2 } }

    expect([verified, popular].sort(compareActorOpsV2ReplacementCandidates).map((item) => item.candidate_id)).toEqual(['popular', 'verified'])
  })
})
