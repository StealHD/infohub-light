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

  it('stores at most eight safe item labels and a 1200-character question per user', () => {
    const items = Array.from({ length: 10 }, (_, index) => ({
      articleId: `item-${index + 1}`,
      title: `标题 ${index + 1}`,
      sourceName: `来源 ${index + 1}`,
      publishedAt: '2026-07-19T00:00:00Z',
    }))
    writeAgentContextDraft('user-a', { userId: 'other', question: '问'.repeat(1300), items: [...items, items[0]], modelPreference: 'deep' })

    expect(readAgentContextDraft('user-a')).toEqual({
      userId: 'user-a',
      question: '问'.repeat(1200),
      items: items.slice(0, 8),
      modelPreference: 'deep',
    })
    expect(readAgentContextDraft('user-b')).toEqual({ userId: 'user-b', question: '', items: [], modelPreference: 'auto' })
  })

  it('adds and removes context labels without changing their order', () => {
    const initial = { userId: 'user-a', question: '比较差异', items: [{ articleId: 'a', title: 'A' }, { articleId: 'b', title: 'B' }], modelPreference: 'auto' as const }
    expect(updateAgentContextDraft(initial, { articleId: 'c', title: 'C' }).items.map((item) => item.articleId)).toEqual(['a', 'b', 'c'])
    expect(updateAgentContextDraft(initial, { articleId: 'a', title: 'A' }).items.map((item) => item.articleId)).toEqual(['b'])
  })

  it('builds a deterministic OpenClaw handoff that explicitly calls get_item', () => {
    const draft = { userId: 'user-a', question: '提炼机会', items: [{ articleId: 'a', title: 'A' }, { articleId: 'b', title: 'B' }], modelPreference: 'deep' as const }
    const prompt = buildAgentHandoffPrompt(draft)

    expect(prompt).toContain('问题：提炼机会')
    expect(prompt).toContain('模型偏好：深度分析')
    expect(prompt).toContain('1. 调用 get_item，article_id="a"')
    expect(prompt).toContain('2. 调用 get_item，article_id="b"')
    expect(buildAgentHandoffPrompt(draft)).toBe(prompt)
  })

  it('migrates v1 IDs to safe labels and sanitizes invalid model preferences', () => {
    window.sessionStorage.setItem('inteliscope.agent-context.v1:user-a', JSON.stringify({ userId: 'user-a', question: '', itemIds: ['a'] }))
    window.sessionStorage.setItem('inteliscope.agent-context.v2:user-b', JSON.stringify({ userId: 'user-b', question: '', items: [], modelPreference: 'unknown' }))

    expect(readAgentContextDraft('user-a').modelPreference).toBe('auto')
    expect(readAgentContextDraft('user-a').items).toEqual([{ articleId: 'a', title: 'a' }])
    expect(readAgentContextDraft('user-b').modelPreference).toBe('auto')
    expect(buildAgentHandoffPrompt(readAgentContextDraft('user-a'))).toContain('模型偏好：自动，由 OpenClaw 决定')
  })

  it('clears only the requested user draft', () => {
    writeAgentContextDraft('user-a', { userId: 'user-a', question: '', items: [{ articleId: 'a', title: 'A' }], modelPreference: 'auto' })
    writeAgentContextDraft('user-b', { userId: 'user-b', question: '', items: [{ articleId: 'b', title: 'B' }], modelPreference: 'fast' })
    clearAgentContextDraft('user-a')

    expect(readAgentContextDraft('user-a').items).toEqual([])
    expect(readAgentContextDraft('user-b').items.map((item) => item.articleId)).toEqual(['b'])
  })
})
