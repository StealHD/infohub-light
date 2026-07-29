import { beforeEach, describe, expect, it } from 'vitest'

import {
  clearFeedEndMessageSession,
  selectEmptyFeedMessage,
  selectTerminalFeedMessage,
} from './feedEndMessageSession'

const scenes = {
  empty: ['空白甲', '空白乙', '空白丙'],
  first_end: ['首次甲', '首次乙', '首次丙'],
  repeat_end: ['再次甲', '再次乙', '再次丙'],
}

describe('feed end message tab session', () => {
  beforeEach(() => window.sessionStorage.clear())

  it('uses first_end once, preserves the count across reload-like calls, and then uses repeat_end', () => {
    const first = selectTerminalFeedMessage('user-a', scenes, () => 0)
    const second = selectTerminalFeedMessage('user-a', scenes, () => 0)

    expect(first).toEqual({ scene: 'first_end', message: '首次甲' })
    expect(second).toEqual({ scene: 'repeat_end', message: '再次甲' })
  })

  it('avoids the immediately previous phrase when the terminal is left and entered again', () => {
    selectTerminalFeedMessage('user-a', scenes, () => 0)
    const firstRepeat = selectTerminalFeedMessage('user-a', scenes, () => 0)
    const nextRepeat = selectTerminalFeedMessage('user-a', scenes, () => 0)

    expect(firstRepeat.message).toBe('再次甲')
    expect(nextRepeat.message).toBe('再次乙')
  })

  it('isolates users and clears only the departing user session on logout', () => {
    selectTerminalFeedMessage('user-a', scenes, () => 0)
    selectTerminalFeedMessage('user-b', scenes, () => 0)
    clearFeedEndMessageSession('user-a')

    expect(selectTerminalFeedMessage('user-a', scenes, () => 0).scene).toBe('first_end')
    expect(selectTerminalFeedMessage('user-b', scenes, () => 0).scene).toBe('repeat_end')
  })

  it('keeps empty copy separate and avoids a neighboring repeat', () => {
    expect(selectEmptyFeedMessage('user-a', scenes.empty, () => 0)).toBe('空白甲')
    expect(selectEmptyFeedMessage('user-a', scenes.empty, () => 0)).toBe('空白乙')
    expect(selectTerminalFeedMessage('user-a', scenes, () => 0).scene).toBe('first_end')
  })
})
