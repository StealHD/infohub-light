import { beforeEach, describe, expect, it } from 'vitest'

import {
  INTELISCOPE_HANDOFF_MARKER,
  buildAgentHandoffPrompt,
  clearAgentContextDraft,
  projectAgentHandoffDisplay,
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
    writeAgentContextDraft('user-a', { userId: 'other', question: '问'.repeat(1300), items: [...items, items[0]] })

    expect(readAgentContextDraft('user-a')).toEqual({
      userId: 'user-a',
      question: '问'.repeat(1200),
      items: items.slice(0, 8),
    })
    expect(readAgentContextDraft('user-b')).toEqual({ userId: 'user-b', question: '', items: [] })
  })

  it('adds and removes context labels without changing their order', () => {
    const initial = { userId: 'user-a', question: '比较差异', items: [{ articleId: 'a', title: 'A' }, { articleId: 'b', title: 'B' }] }
    expect(updateAgentContextDraft(initial, { articleId: 'c', title: 'C' }).items.map((item) => item.articleId)).toEqual(['a', 'b', 'c'])
    expect(updateAgentContextDraft(initial, { articleId: 'a', title: 'A' }).items.map((item) => item.articleId)).toEqual(['b'])
  })

  it('builds a versioned deterministic handoff and projects only the visible question', () => {
    const draft = { userId: 'user-a', question: '提炼机会', items: [{ articleId: 'a', title: 'A' }, { articleId: 'b', title: 'B' }] }
    const prompt = buildAgentHandoffPrompt(draft)

    expect(prompt).toContain(INTELISCOPE_HANDOFF_MARKER)
    expect(prompt).toContain('问题：提炼机会')
    expect(prompt).toContain('1. 调用 get_item，article_id="a"')
    expect(prompt).toContain('2. 调用 get_item，article_id="b"')
    expect(prompt).not.toContain('模型偏好')
    expect(projectAgentHandoffDisplay(prompt)).toEqual({ displayText: '提炼机会', contextCount: 2 })
    expect(buildAgentHandoffPrompt(draft)).toBe(prompt)
  })

  it('migrates v1 and v2 drafts while ignoring their simulated model preference', () => {
    window.sessionStorage.setItem('inteliscope.agent-context.v1:user-a', JSON.stringify({ userId: 'user-a', question: '', itemIds: ['a'], modelPreference: 'deep' }))
    window.sessionStorage.setItem('inteliscope.agent-context.v2:user-b', JSON.stringify({ userId: 'user-b', question: '旧问题', items: [], modelPreference: 'fast' }))

    expect(readAgentContextDraft('user-a')).toEqual({ userId: 'user-a', question: '', items: [{ articleId: 'a', title: 'a' }] })
    expect(readAgentContextDraft('user-b')).toEqual({ userId: 'user-b', question: '旧问题', items: [] })
  })

  it('projects legacy handoffs without exposing their internal instructions', () => {
    const legacy = [
      '请使用 Inteliscope Remote MCP 完成以下任务。',
      '问题：比较变化',
      '模型偏好：深度分析',
      '必须按顺序读取上下文，不要把标题或摘要当作完整正文：',
      '1. 调用 get_item，article_id="internal-a"',
    ].join('\n')
    expect(projectAgentHandoffDisplay(legacy)).toEqual({ displayText: '比较变化', contextCount: 1 })
  })

  it('clears only the requested user draft', () => {
    writeAgentContextDraft('user-a', { userId: 'user-a', question: '', items: [{ articleId: 'a', title: 'A' }] })
    writeAgentContextDraft('user-b', { userId: 'user-b', question: '', items: [{ articleId: 'b', title: 'B' }] })
    clearAgentContextDraft('user-a')

    expect(readAgentContextDraft('user-a').items).toEqual([])
    expect(readAgentContextDraft('user-b').items.map((item) => item.articleId)).toEqual(['b'])
  })
})
