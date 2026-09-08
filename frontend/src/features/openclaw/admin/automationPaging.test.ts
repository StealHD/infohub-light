import { describe, expect, it } from 'vitest'
import { parseAutomation, parseRunPage, nextOffset } from './automationPaging'
import { projectAutomationDraft } from '../../agent-workspace/agentAutomationDraft'
const job = { id: 'job', name: '长提示词', agentId: 'personal', enabled: false,
  schedule: { kind: 'every', everyMs: 60000 }, sessionTarget: 'isolated', delivery: { mode: 'none' } }

describe('legacy Cron compatibility', () => {
  it('preserves long prompts, newlines and explicit Agent when opening for edit', () => {
    const message = '  开头\n' + '完整判断要求\n'.repeat(2000) + '\n结尾  '
    const parsed = parseAutomation({ ...job, payload: { kind: 'agentTurn', message } })!
    expect(parsed.message).toBe(message)
    expect(parsed.agentId).toBe('personal')
    const result = projectAutomationDraft({ name: parsed.name, message: parsed.message, scheduleKind: 'every',
      everyMinutes: '1', at: '', cronExpr: '', timezone: 'UTC' })
    expect(result.draft?.message).toBe(message)
  })
  it('rejects invalid continuation and follows valid cursors beyond the first page', () => {
    expect(nextOffset({ hasMore: true, nextOffset: 200 }, 100, 100)).toBe(200)
    expect(() => nextOffset({ hasMore: true, nextOffset: 100 }, 100, 100)).toThrow()
    expect(() => nextOffset({ hasMore: true }, 0, 100)).toThrow()
    expect(parseRunPage({ entries: [{ jobId: 'other', ts: 1 }, { jobId: 'job', ts: 2 }], hasMore: true, nextOffset: 52 }, 'job', 50))
      .toMatchObject({ items: [{ jobId: 'job', ts: 2 }], nextOffset: 52 })
  })
  it('retains unbound legacy jobs for viewing and rejects oversized prompts instead of truncating', () => {
    expect(parseAutomation({ ...job, agentId: undefined, payload: { kind: 'agentTurn', message: 'legacy' } })?.agentId).toBeUndefined()
    expect(() => parseAutomation({ ...job, payload: { kind: 'agentTurn', message: 'x'.repeat(400001) } })).toThrow('截断')
  })
})
