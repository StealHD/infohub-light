import { describe, expect, it } from 'vitest'

import { GatewayRequestError } from './openclawGateway'
import {
  createOpenClawSessionLabel,
  isOpenClawSessionLabelConflict,
} from './openclawSession'

describe('OpenClaw session identity', () => {
  it('creates readable origin-scoped labels with a 64-bit random suffix', () => {
    expect(createOpenClawSessionLabel(
      'RB.JIEFS.TOP',
      '9f6c1d2e-7a3b-4c5d-8e9f-0123456789ab',
    )).toBe('Inteliscope · rb.jiefs.top · 9f6c1d2e7a3b4c5d')
    expect(createOpenClawSessionLabel(
      'localhost:8080',
      '32e741ac-084f-6d19-8a2b-0123456789ab',
    )).toBe('Inteliscope · localhost:8080 · 32e741ac084f6d19')
  })

  it('falls back to browser and never exceeds the Gateway label limit', () => {
    expect(createOpenClawSessionLabel('', '12345678-90ab-cdef-0123-456789abcdef'))
      .toBe('Inteliscope · browser · 1234567890abcdef')
    expect(createOpenClawSessionLabel('x'.repeat(700), '12345678-90ab-cdef-0123-456789abcdef'))
      .toHaveLength(512)
  })

  it('recognizes only the exact Gateway label collision', () => {
    expect(isOpenClawSessionLabelConflict(new GatewayRequestError({
      code: 'INVALID_REQUEST', message: 'label already in use: Inteliscope',
    }))).toBe(true)
    expect(isOpenClawSessionLabelConflict(new GatewayRequestError({
      code: 'INVALID_REQUEST', message: 'invalid label: empty',
    }))).toBe(false)
    expect(isOpenClawSessionLabelConflict(new GatewayRequestError({
      code: 'PERMISSION_DENIED', message: 'missing scope: operator.write',
    }))).toBe(false)
    expect(isOpenClawSessionLabelConflict(new Error('label already in use: Inteliscope'))).toBe(false)
  })
})
