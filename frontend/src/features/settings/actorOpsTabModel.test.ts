import { describe, expect, it } from 'vitest'

import { actorOpsCanonicalSearchParams, actorOpsTabFromSearchParams, safeActorOpsEventJobId } from './actorOpsTabModel'

describe('ActorOps tab navigation', () => {
  it.each([
    ['', 'routes'],
    ['routes', 'routes'],
    ['logs', 'logs'],
    ['pool', 'routes'],
    ['sources', 'routes'],
    ['operations', 'logs'],
    ['unexpected', 'routes'],
  ] as const)('maps %s to %s', (requested, expected) => {
    expect(actorOpsTabFromSearchParams(new URLSearchParams(requested ? { tab: requested } : undefined))).toBe(expected)
  })

  it('canonicalizes a legacy tab and keeps a valid log job only on logs', () => {
    expect(actorOpsCanonicalSearchParams(new URLSearchParams('tab=operations&job=job-1'), 'logs').toString()).toBe('tab=logs&job=job-1')
    expect(actorOpsCanonicalSearchParams(new URLSearchParams('tab=pool&job=job-1'), 'routes').toString()).toBe('tab=routes')
  })

  it('only permits opaque job identifiers', () => {
    expect(safeActorOpsEventJobId('job-safe_1:trace')).toBe('job-safe_1:trace')
    expect(safeActorOpsEventJobId('../not-safe')).toBeUndefined()
    expect(actorOpsCanonicalSearchParams(new URLSearchParams('tab=logs&job=../not-safe'), 'logs').toString()).toBe('tab=logs')
  })
})
