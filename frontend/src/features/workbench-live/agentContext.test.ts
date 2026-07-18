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
    writeAgentContextDraft('user-a', { userId: 'other', question: '问'.repeat(1300), itemIds: [...ids, 'item-1'], modelPreference: 'deep' })

    expect(readAgentContextDraft('user-a')).toEqual({
      userId: 'user-a',
      question: '问'.repeat(1200),
      itemIds: ids.slice(0, 8),
      modelPreference: 'deep',
    })
    expect(readAgentContextDraft('user-b')).toEqual({ userId: 'user-b', question: '', itemIds: [], modelPreference: 'auto' })
  })

  it('adds and removes context IDs without changing their order', () => {
    const initial = { userId: 'user-a', question: '比较差异', itemIds: ['a', 'b'], modelPreference: 'auto' as const }
    expect(updateAgentContextDraft(initial, 'c').itemIds).toEqual(['a', 'b', 'c'])
    expect(updateAgentContextDraft(initial, 'a').itemIds).toEqual(['b'])
  })

  it('builds a deterministic OpenClaw handoff that explicitly calls get_item', () => {
    const prompt = buildAgentHandoffPrompt({ userId: 'user-a', question: '提炼机会', itemIds: ['a', 'b'], modelPreference: 'deep' })

    expect(prompt).toContain('问题：提炼机会')
    expect(prompt).toContain('模型偏好：深度分析')
    expect(prompt).toContain('1. 调用 get_item，item_id="a"')
    expect(prompt).toContain('2. 调用 get_item，item_id="b"')
    expect(buildAgentHandoffPrompt({ userId: 'user-a', question: '提炼机会', itemIds: ['a', 'b'], modelPreference: 'deep' })).toBe(prompt)
  })

  it('sanitizes legacy and invalid model preferences to auto', () => {
    window.sessionStorage.setItem('inteliscope.agent-context.v1:user-a', JSON.stringify({ userId: 'user-a', question: '', itemIds: ['a'] }))
    window.sessionStorage.setItem('inteliscope.agent-context.v1:user-b', JSON.stringify({ userId: 'user-b', question: '', itemIds: [], modelPreference: 'unknown' }))

    expect(readAgentContextDraft('user-a').modelPreference).toBe('auto')
    expect(readAgentContextDraft('user-b').modelPreference).toBe('auto')
    expect(buildAgentHandoffPrompt(readAgentContextDraft('user-a'))).toContain('模型偏好：自动，由 OpenClaw 决定')
  })

  it('clears only the requested user draft', () => {
    writeAgentContextDraft('user-a', { userId: 'user-a', question: '', itemIds: ['a'], modelPreference: 'auto' })
    writeAgentContextDraft('user-b', { userId: 'user-b', question: '', itemIds: ['b'], modelPreference: 'fast' })
    clearAgentContextDraft('user-a')

    expect(readAgentContextDraft('user-a').itemIds).toEqual([])
    expect(readAgentContextDraft('user-b').itemIds).toEqual(['b'])
  })
})
