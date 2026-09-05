import { beforeEach, describe, expect, it } from 'vitest'
import { readAgentContextDraft, writeAgentContextDraft } from './agentContext'
import { createWorkbenchAgentValue } from './createWorkbenchAgentValue'

const selectedSkill = { key: 'weather', name: 'weather', gatewayUrl: 'ws://localhost:18789', agentId: 'main' }
describe('user-scoped Skill drafts', () => {
  beforeEach(() => sessionStorage.clear())
  it('persists bounded selection without directories and isolates users', () => {
    writeAgentContextDraft('one', { userId: 'one', question: '保留', items: [], selectedSkill: { ...selectedSkill, description: 'SECRET_DESCRIPTION' } as never })
    expect(readAgentContextDraft('one').selectedSkill).toEqual(selectedSkill)
    expect(readAgentContextDraft('two').selectedSkill).toBeUndefined()
    expect(JSON.stringify(sessionStorage)).not.toContain('SECRET_DESCRIPTION')
  })
  it('keeps a selected Skill when editing or clearing context, and clears it on successful send', () => {
    let draft = { userId: 'one', question: '保留', items: [], selectedSkill } as ReturnType<typeof readAgentContextDraft>
    const value = () => createWorkbenchAgentValue(draft, (next) => { draft = next })
    value().setQuestion('新的问题'); expect(draft.selectedSkill).toEqual(selectedSkill)
    value().toggleItem({ articleId: 'one', title: '材料', sourceName: '测试' }); expect(draft.selectedSkill).toEqual(selectedSkill)
    value().clearItems(); expect(draft.selectedSkill).toEqual(selectedSkill)
    value().clearComposer(); expect(draft.selectedSkill).toBeUndefined()
    value().restoreComposer('旧问题', [], undefined, selectedSkill); expect(draft.selectedSkill).toEqual(selectedSkill)
  })
  it('accepts legacy drafts without Skill metadata', () => {
    writeAgentContextDraft('one', { userId: 'one', question: '旧问题', items: [] })
    expect(readAgentContextDraft('one')).toMatchObject({ question: '旧问题' })
    expect(readAgentContextDraft('one').selectedSkill).toBeUndefined()
  })
})
