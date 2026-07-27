import { beforeEach, describe, expect, it } from 'vitest'

import {
  canDockRightRail,
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

  it('docks only when the current sidebar still leaves a 640px Feed and 320px rail', () => {
    expect(canDockRightRail(1280, 72)).toBe(true)
    expect(canDockRightRail(1042, 72)).toBe(true)
    expect(canDockRightRail(1041, 72)).toBe(false)
    expect(canDockRightRail(1202, 232)).toBe(true)
    expect(canDockRightRail(1201, 232)).toBe(false)
  })

  it('persists independent account widths and rejects invalid values', () => {
    writeRightRailWidth('alpha', 480)
    expect(readRightRailWidth('alpha')).toBe(480)
    expect(readRightRailWidth('beta')).toBe(400)
    window.localStorage.setItem(rightRailWidthPreferenceKey('beta'), '{bad')
    expect(readRightRailWidth('beta')).toBe(400)
  })
})
