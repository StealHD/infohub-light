import { describe, expect, it } from 'vitest'

import { actorOpsV2CandidateHasPublicIdentity, actorOpsV2CandidateLabel, actorOpsV2MappingIssueLabel, compareActorOpsV2ReplacementCandidates, orderedActorOpsV2StandbyCandidates, type ActorOpsV2CandidateView } from './actorOpsV2RouteModel'

const candidate: ActorOpsV2CandidateView = {
  candidate_id: 'candidate-1', build_number: null, lifecycle: 'static_valid', assignment: 'inactive', priority: null, generation: 1,
  operational_status: 'normal', issue_code: null, last_success_at: null, last_failure_at: null, retry_at: null, avatar_mapping_status: 'ready',
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

  it('orders standby slots by their persisted priority', () => {
    const standbyTwo = { ...candidate, candidate_id: 'a-standby', assignment: 'standby', priority: 2 }
    const standbyOne = { ...candidate, candidate_id: 'z-standby', assignment: 'standby', priority: 1 }

    expect(orderedActorOpsV2StandbyCandidates([standbyTwo, standbyOne]).map((item) => item.priority)).toEqual([1, 2])
  })

  it('explains the exact post mapping gap', () => {
    expect(actorOpsV2MappingIssueLabel({
      ...candidate,
      lifecycle: 'mapping_pending',
      mapping_issue_code: 'missing_post_author_handle',
    })).toBe('缺少帖子作者用户名字段')
  })

  it('keeps adaptable and wrong-route Actors distinct from broken Actors', () => {
    expect(actorOpsV2MappingIssueLabel({
      ...candidate,
      lifecycle: 'mapping_pending',
      mapping_issue_code: 'nested_content_items',
    })).toBe('发布内容位于嵌套列表，等待系统展开适配')
    expect(actorOpsV2MappingIssueLabel({
      ...candidate,
      lifecycle: 'mapping_pending',
      mapping_issue_code: 'wrong_actor_type',
    })).toBe('Actor 可用，但用途不是此来源的新发布内容')
  })
})
