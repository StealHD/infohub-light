import { describe, expect, it } from 'vitest'

import { ActionGeneration } from './actionGeneration'

describe('action generation', () => {
  it('invalidates slow actions when the user changes or the layout logs out', () => {
    const guard = new ActionGeneration('user-a')
    const actionA = guard.capture()
    expect(guard.isCurrent(actionA)).toBe(true)

    guard.update('user-b')
    expect(guard.isCurrent(actionA)).toBe(false)
    const actionB = guard.capture()
    guard.invalidate()
    expect(guard.isCurrent(actionB)).toBe(false)
  })
})
