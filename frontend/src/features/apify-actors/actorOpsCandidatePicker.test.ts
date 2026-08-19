import { describe, expect, it } from 'vitest'

import type { ApifyActorPoolCandidate } from '../../api/types'
import { actorPickerCandidates } from './actorOpsCandidatePicker'

function candidate(id: string, overrides: Partial<ApifyActorPoolCandidate> = {}): ApifyActorPoolCandidate {
  return {
    candidate_id: id,
    actor_public_name: `${id} Actor`,
    publisher: id,
    pricing: {
      model: null,
      billing_unit: 'unknown',
      unit_price_min_usd: null,
      unit_price_max_usd: null,
      minimum_charge_usd: null,
      minimum_run_cap_usd: null,
    },
    max_validation_charge_usd: 0.02,
    selectable: true,
    unavailable_reason: null,
    ...overrides,
  }
}

describe('actorPickerCandidates', () => {
  it('only exposes explicitly verified selectable candidates', () => {
    const result = actorPickerCandidates([
      candidate('verified', { already_validated: true }),
      candidate('pending', { already_validated: false }),
      candidate('unknown'),
      candidate('rejected', { already_validated: false, selectable: false }),
    ], 'add_slot')

    expect(result.visibleCandidates.map((item) => item.candidate_id)).toEqual(['verified'])
  })
})
