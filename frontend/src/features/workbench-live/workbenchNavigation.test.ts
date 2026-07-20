import { describe, expect, it } from 'vitest'

import { clampPendingNavigation } from './workbenchNavigation'

describe('workbench navigation ownership', () => {
  it('replaces a removed high-index rail target with the reached final index', () => {
    expect(clampPendingNavigation({ index: 181, align: 'center' }, 50)).toEqual({
      index: 49,
      align: 'center',
    })
  })
})
