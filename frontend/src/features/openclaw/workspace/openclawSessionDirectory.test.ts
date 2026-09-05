import { describe, expect, it } from 'vitest'
import { projectSessionPage, sessionPageParams } from './openclawSessionDirectory'
import { openClawSessionTitle } from '../chat/openclawSessionTitle'

describe('session directory projection', () => {
  it('supports pages beyond 200, server search, and archived sessions', () => {
    expect(sessionPageParams({ offset: 250, search: ' 报告 ', archived: true })).toMatchObject({ offset: 250, limit: 50, search: '报告', archived: true, includeDerivedTitles: true })
    expect(projectSessionPage({ sessions: [{ key: 'old', agentId: 'research', label: '原名称', displayName: '报告摘要', updatedAt: 42, archived: true }], hasMore: true, nextOffset: 300, totalCount: 320 }, 250)).toMatchObject({ sessions: [{ key: 'old', agentId: 'research', updatedAt: 42, archived: true }], nextOffset: 300, totalCount: 320 })
  })

  it('rejects malformed paging and duplicate identities', () => {
    expect(() => sessionPageParams({ offset: -1 })).toThrow()
    expect(() => projectSessionPage({ sessions: [], hasMore: true, nextOffset: 200 }, 200)).toThrow()
    expect(() => projectSessionPage({ sessions: [{ key: 'same' }, { key: 'same' }] }, 0)).toThrow()
  })

  it('preserves authored titles and replaces machine labels without changing identity', () => {
    const session = { key: 'root', label: 'Inscope · localhost · 1234abcd', hasActiveRun: false }
    expect(openClawSessionTitle(session, '检查订阅来源失败的原因')).toBe('检查订阅来源失败的原因')
    expect(openClawSessionTitle({ ...session, displayName: '诊断订阅故障' }, 'first question')).toBe('诊断订阅故障')
    expect(openClawSessionTitle({ ...session, label: '人工命名', displayName: '生成标题' })).toBe('人工命名')
    expect(openClawSessionTitle(session)).toBe('新对话')
    expect(session.label).toContain('localhost')
  })
  it('keeps blank newly-created sessions readable before automatic naming', () => {
    expect(openClawSessionTitle({ key: 'agent:main:dashboard:new', label: 'agent:main:dashboard:new', hasActiveRun: false, createdAt: 1788600000000 })).toBe('新对话')
  })

})
