import { beforeEach, describe, expect, it } from 'vitest'

import {
  clampRightRailWidth,
  maximumRightRailWidth,
  readRightRailWidth,
  rightRailWidthPreferenceKey,
  writeRightRailWidth,
} from './rightRailPreference'

describe('right rail width preference', () => {
  beforeEach(() => window.localStorage.clear())

  it('clamps against both the fixed rail range and the 640px Feed minimum', () => {
    expect(maximumRightRailWidth(1440, 72)).toBe(718)
    expect(maximumRightRailWidth(1440, 232)).toBe(558)
    expect(clampRightRailWidth(900, 1440, 72)).toBe(718)
    expect(clampRightRailWidth(100, 1440, 72)).toBe(320)
  })

  it('persists independent account widths and rejects invalid values', () => {
    writeRightRailWidth('alpha', 480)
    expect(readRightRailWidth('alpha')).toBe(480)
    expect(readRightRailWidth('beta')).toBe(360)
    window.localStorage.setItem(rightRailWidthPreferenceKey('beta'), '{bad')
    expect(readRightRailWidth('beta')).toBe(360)
  })
})
