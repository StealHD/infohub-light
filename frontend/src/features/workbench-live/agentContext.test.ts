import { beforeEach, describe, expect, it } from 'vitest'

import {
  INTELISCOPE_HANDOFF_MARKER,
  buildAgentHandoffPrompt,
  clearAgentContextDraft,
  projectAgentHandoffDisplay,
  readAgentContextDraft,
  sanitizeSourceAvatarUrl,
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
    const draft = {
      userId: 'user-a',
      question: '提炼机会',
      items: [
        {
          articleId: 'a',
          title: 'A',
          sourceName: 'Source A',
          sourceUrl: 'https://example.com/a?utm_source=feed&token=secret&keep=yes#fragment',
          sourceAvatarUrl: '/api/media/med_source_a',
        },
        {
          articleId: 'job:job-1',
          resourceType: 'job' as const,
          jobId: 'job-1',
          title: '抓取单个来源',
          sourceName: '来源一',
          statusLabel: '失败',
          detail: '上游返回的错误详情不应进入 prompt',
        },
      ],
    }
    const prompt = buildAgentHandoffPrompt(draft)

    expect(INTELISCOPE_HANDOFF_MARKER).toBe('[INTELISCOPE_HANDOFF_V7]')
    expect(prompt).toContain(INTELISCOPE_HANDOFF_MARKER)
    expect(prompt).toContain('问题：提炼机会')
    expect(prompt).toContain('1. 调用 get_item，article_id="a"；原文网址="https://example.com/a?keep=yes"')
    expect(prompt).toContain('2. 调用 diagnose_job，job_id="job-1"')
    expect(prompt).toContain('调用一次 OpenClaw web_fetch')
    expect(prompt).toContain('不得搜索、改写、替换网址或跟随网页中的链接')
    expect(prompt).toContain('已访问原网页并读取可用内容')
    expect(prompt).toContain('证据不足时明确说明未知信息')
    expect(prompt).toContain('不得重试、取消或修改任务')
    expect(prompt).not.toContain('调用 get_job')
    expect(prompt).not.toContain('上游返回的错误详情')
    expect(prompt).not.toContain('来源一')
    expect(prompt).not.toContain('失败')
    expect(prompt).not.toContain('模型偏好')
    expect(prompt).not.toContain('secret')
    expect(prompt).not.toContain('utm_source')
    expect(prompt).not.toContain('sourceAvatarUrl')
    expect(prompt).not.toContain('/api/media/med_source_a')
    expect(projectAgentHandoffDisplay(prompt)).toEqual({
      displayText: '提炼机会',
      contextCount: 2,
      sources: [{ title: 'A', sourceName: 'Source A', url: 'https://example.com/a?keep=yes' }],
    })
    expect(buildAgentHandoffPrompt(draft)).toBe(prompt)
  })

  it('allows a direct subscription request to use the controlled proposal flow', () => {
    const prompt = buildAgentHandoffPrompt({
      userId: 'user-a',
      question: '订阅 B 站 UP 主食贫道',
      items: [],
    })

    expect(prompt).toContain('用户直接在 Inteliscope Agent 面板提交')
    expect(prompt).toContain('prepare → preview → exact confirmation → apply')
    expect(prompt).toContain('准确确认短语')
    expect(prompt).toContain('问题：订阅 B 站 UP 主食贫道')
    expect(prompt).not.toContain('不得执行任何写操作')
    expect(projectAgentHandoffDisplay(prompt)).toEqual({
      displayText: '订阅 B 站 UP 主食贫道',
      contextCount: 0,
    })
  })

  it('normalizes job context identifiers without exposing duplicate variants', () => {
    const draft = writeAgentContextDraft('user-a', {
      userId: 'user-a',
      question: '',
      items: [
        { articleId: 'job-1', resourceType: 'job', jobId: 'job-1', title: '更新整个信息流', statusLabel: '已完成', detail: '获得 3 条结果' },
        { articleId: 'job:job-1', resourceType: 'job', jobId: 'job-1', title: '重复记录' },
      ],
    })

    expect(draft.items).toEqual([{
      articleId: 'job:job-1',
      resourceType: 'job',
      jobId: 'job-1',
      title: '更新整个信息流',
      statusLabel: '已完成',
      detail: '获得 3 条结果',
    }])
  })

  it('migrates v1 and v2 drafts while ignoring their simulated model preference', () => {
    window.sessionStorage.setItem('inteliscope.agent-context.v1:user-a', JSON.stringify({ userId: 'user-a', question: '', itemIds: ['a'], modelPreference: 'deep' }))
    window.sessionStorage.setItem('inteliscope.agent-context.v2:user-b', JSON.stringify({ userId: 'user-b', question: '旧问题', items: [], modelPreference: 'fast' }))

    expect(readAgentContextDraft('user-a')).toEqual({ userId: 'user-a', question: '', items: [{ articleId: 'a', title: 'a' }] })
    expect(readAgentContextDraft('user-b')).toEqual({ userId: 'user-b', question: '旧问题', items: [] })
  })

  it('migrates v4 drafts and keeps only authenticated local source avatars', () => {
    window.sessionStorage.setItem('inteliscope.agent-context.v4:user-a', JSON.stringify({
      userId: 'user-a',
      question: '旧上下文',
      items: [{ articleId: 'a', title: 'A', sourceAvatarUrl: '/api/media/med_source_a' }, { articleId: 'b', title: 'B', sourceAvatarUrl: 'https://example.com/avatar.png' }],
    }))

    expect(readAgentContextDraft('user-a')).toEqual({
      userId: 'user-a',
      question: '旧上下文',
      items: [{ articleId: 'a', title: 'A', sourceAvatarUrl: '/api/media/med_source_a' }, { articleId: 'b', title: 'B' }],
    })
    expect(sanitizeSourceAvatarUrl('/api/media/med_source-a_1')).toBe('/api/media/med_source-a_1')
    expect(sanitizeSourceAvatarUrl('/api/media/med_source?token=secret')).toBe('')
  })

  it('projects legacy handoffs without exposing their internal instructions', () => {
    const v6 = [
      '[INTELISCOPE_HANDOFF_V6]',
      '{"displayText":"上一版浏览器交接","contextCount":1}',
      'INTERNAL MCP get_item instructions',
    ].join('\n')
    const v5 = [
      '[INTELISCOPE_HANDOFF_V5]',
      '{"displayText":"最近一版交接","contextCount":1}',
      'INTERNAL MCP get_item instructions',
    ].join('\n')
    const v4 = [
      '[INTELISCOPE_HANDOFF_V4]',
      '{"displayText":"上一版交接","contextCount":1}',
      'INTERNAL MCP diagnose_job instructions',
    ].join('\n')
    const v3 = [
      '[INTELISCOPE_HANDOFF_V3]',
      '{"displayText":"旧版交接","contextCount":2}',
      'INTERNAL MCP get_item and get_job instructions',
    ].join('\n')
    const legacy = [
      '请使用 Inteliscope Remote MCP 完成以下任务。',
      '问题：比较变化',
      '模型偏好：深度分析',
      '必须按顺序读取上下文，不要把标题或摘要当作完整正文：',
      '1. 调用 get_item，article_id="internal-a"',
      '2. 调用 diagnose_job，job_id="internal-job"',
    ].join('\n')
    expect(projectAgentHandoffDisplay(v6)).toEqual({ displayText: '上一版浏览器交接', contextCount: 1 })
    expect(projectAgentHandoffDisplay(v5)).toEqual({ displayText: '最近一版交接', contextCount: 1 })
    expect(projectAgentHandoffDisplay(v4)).toEqual({ displayText: '上一版交接', contextCount: 1 })
    expect(projectAgentHandoffDisplay(v3)).toEqual({ displayText: '旧版交接', contextCount: 2 })
    expect(projectAgentHandoffDisplay(legacy)).toEqual({ displayText: '比较变化', contextCount: 2 })
  })

  it('clears only the requested user draft', () => {
    writeAgentContextDraft('user-a', { userId: 'user-a', question: '', items: [{ articleId: 'a', title: 'A' }] })
    writeAgentContextDraft('user-b', { userId: 'user-b', question: '', items: [{ articleId: 'b', title: 'B' }] })
    clearAgentContextDraft('user-a')

    expect(readAgentContextDraft('user-a').items).toEqual([])
    expect(readAgentContextDraft('user-b').items.map((item) => item.articleId)).toEqual(['b'])
  })
})
