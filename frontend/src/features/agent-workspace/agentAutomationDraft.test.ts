import { describe, expect, it } from 'vitest'

import { projectAutomationDraft } from './agentAutomationDraft'

const base = { name: 'Review', message: 'Review tasks', scheduleKind: 'every' as const, at: '', everyMinutes: '60', cronExpr: '', timezone: 'UTC' }

describe('Automation form projection', () => {
  it('rejects past one-time schedules and unsafe intervals', () => {
    expect(projectAutomationDraft({ ...base, scheduleKind: 'at', at: '2026-01-01T00:00' }, Date.parse('2026-02-01T00:00Z')).errors.at).toBeTruthy()
    expect(projectAutomationDraft({ ...base, everyMinutes: String(Number.MAX_SAFE_INTEGER) }).errors.everyMinutes).toBeTruthy()
  })

  it('rejects malformed cron expressions and unknown timezones', () => {
    const result = projectAutomationDraft({ ...base, scheduleKind: 'cron', cronExpr: '* *', timezone: 'Mars/Olympus' })
    expect(result.draft).toBeNull()
    expect(result.errors).toMatchObject({ cronExpr: expect.any(String), timezone: expect.any(String) })
  })
})
