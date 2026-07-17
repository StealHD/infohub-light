import { beforeEach, describe, expect, it } from 'vitest'

import {
  buildAgentHandoffPrompt,
  clearAgentContextDraft,
  readAgentContextDraft,
  updateAgentContextDraft,
  writeAgentContextDraft,
} from './agentContext'

describe('Agent context draft', () => {
  beforeEach(() => window.sessionStorage.clear())

  it('stores at most eight ordered IDs and a 1200-character question per user', () => {
    const ids = Array.from({ length: 10 }, (_, index) => `item-${index + 1}`)
    writeAgentContextDraft('user-a', { userId: 'other', question: '问'.repeat(1300), itemIds: [...ids, 'item-1'] })

    expect(readAgentContextDraft('user-a')).toEqual({
      userId: 'user-a',
      question: '问'.repeat(1200),
      itemIds: ids.slice(0, 8),
    })
    expect(readAgentContextDraft('user-b')).toEqual({ userId: 'user-b', question: '', itemIds: [] })
  })

  it('adds and removes context IDs without changing their order', () => {
    const initial = { userId: 'user-a', question: '比较差异', itemIds: ['a', 'b'] }
    expect(updateAgentContextDraft(initial, 'c').itemIds).toEqual(['a', 'b', 'c'])
    expect(updateAgentContextDraft(initial, 'a').itemIds).toEqual(['b'])
  })

  it('builds a deterministic OpenClaw handoff that explicitly calls get_item', () => {
    const prompt = buildAgentHandoffPrompt({ userId: 'user-a', question: '提炼机会', itemIds: ['a', 'b'] })

    expect(prompt).toContain('问题：提炼机会')
    expect(prompt).toContain('1. 调用 get_item，item_id="a"')
    expect(prompt).toContain('2. 调用 get_item，item_id="b"')
    expect(buildAgentHandoffPrompt({ userId: 'user-a', question: '提炼机会', itemIds: ['a', 'b'] })).toBe(prompt)
  })

  it('clears only the requested user draft', () => {
    writeAgentContextDraft('user-a', { userId: 'user-a', question: '', itemIds: ['a'] })
    writeAgentContextDraft('user-b', { userId: 'user-b', question: '', itemIds: ['b'] })
    clearAgentContextDraft('user-a')

    expect(readAgentContextDraft('user-a').itemIds).toEqual([])
    expect(readAgentContextDraft('user-b').itemIds).toEqual(['b'])
  })
})
