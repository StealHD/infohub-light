import { describe, expect, it } from 'vitest'

import type { ApifyActorCanaryPlan, ApifyActorRouteDetail } from '../../api/types'
import {
  toActivationConfirmationView,
  toBatchConfirmationView,
} from './actorOpsWorkflowDialogModel'

describe('ActorOps workflow dialog model', () => {
  it('projects a paid plan without exposing approval or internal revision identifiers', () => {
    const plan = {
      platform: 'instagram',
      target_type: 'profile',
      capability: 'items',
      goal: 'compatibility_single',
      max_total_charge_usd: 0.02,
      source_count: 2,
      source_validation_count: 1,
      ready: true,
      items: [{
        ordinal: 1,
        revision_id: 'private-revision',
        actor_public_name: 'Public Actor',
        publisher: 'publisher-a',
        authorized_cap_usd: 0.02,
        already_validated: false,
        validation_profile: null,
      }],
    } as unknown as ApifyActorCanaryPlan

    const view = toBatchConfirmationView(plan)

    expect(view).toMatchObject({
      compatibility: true,
      routeLabel: 'Instagram 主页内容',
      maxTotalChargeUsd: 0.02,
    })
    expect(JSON.stringify(view)).not.toContain('private-revision')
  })

  it('bounds the activation minimum while preserving the current slot count', () => {
    const route = {
      min_runtime_healthy: 2,
      actual_min_runtime_healthy: 9,
      slots: [{ revision_id: 'one' }, { revision_id: null }],
      workflow: { goal: 'complete_third' },
    } as unknown as ApifyActorRouteDetail

    expect(toActivationConfirmationView(route)).toEqual({
      goal: 'complete_third',
      minimumActors: 3,
      currentSlotCount: 1,
    })
  })
})
