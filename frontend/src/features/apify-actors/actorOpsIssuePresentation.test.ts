import { describe, expect, it } from 'vitest'

import { presentActorOpsIncidentIssue, presentActorOpsJobIssue } from './actorOpsIssuePresentation'

describe('ActorOps issue presentation', () => {
  it.each([
    ['actor_switched', 'route'],
    ['route_exhausted', 'route'],
    ['quota_low', 'secrets'],
    ['budget_blocked', 'route-cost'],
    ['start_outcome_unknown', 'apify-runs'],
    ['recovered', undefined],
  ] as const)('explains %s with a bounded safe next step', (event, target) => {
    const presentation = presentActorOpsIncidentIssue(event)
    expect(presentation.reason).not.toBe('')
    expect(presentation.impact).not.toBe('')
    expect(presentation.next).not.toBe('')
    expect(presentation.action?.target).toBe(target)
  })

  it('locks an unknown start to Apify reconciliation without offering a retry', () => {
    const presentation = presentActorOpsJobIssue({ error_code: 'apify_start_outcome_unknown' })
    expect(presentation).toMatchObject({
      reason: '无法确认 Actor 是否已启动。',
      action: { label: '打开 Apify 运行记录', target: 'apify-runs' },
    })
    expect(presentation.next).toContain('不要重试')
    expect(JSON.stringify(presentation)).not.toContain('重试此任务')
  })
})
