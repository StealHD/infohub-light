import { describe, expect, it } from 'vitest'
import { findComposerTrigger, replaceComposerTrigger } from './openclawShortcuts'
import { skillInvocationIssue } from '../chat/openclawSkillInvocation'

describe('composer shortcuts', () => {
  it('finds a token at the caret without swallowing following text', () => {
    expect(findComposerTrigger('请用 @天气 总结', 6)).toEqual({ start: 3, end: 6, prefix: '@', query: '天气' })
    expect(replaceComposerTrigger('请用 @天气 总结', { start: 3, end: 6 }, '「材料」')).toEqual({ text: '请用 「材料」 总结', caret: 7 })
  })
  it.each(['a@example.com', 'https://example.com/x', '/tmp/file', 'C:/code', 'test/@skill'])('ignores addresses and paths: %s', (text) => {
    expect(findComposerTrigger(text, text.length)).toBeNull()
  })
  it('does not truncate remaining text when insertion exceeds the limit', () => {
    expect(replaceComposerTrigger('@a' + 'x'.repeat(1198), { start: 0, end: 2 }, 'long title')).toBeNull()
  })
  it('requires explicit callable flags and unique safe names', () => {
    const skill = { key: 'a', name: 'weather', enabled: true, eligible: true, userInvocable: true, commandVisible: true, modelVisible: true, missingBins: [], missingEnv: [], installOptions: [] }
    expect(skillInvocationIssue(skill, [skill])).toBeNull()
    expect(skillInvocationIssue({ ...skill, commandVisible: undefined }, [skill])).toBeTruthy()
    expect(skillInvocationIssue(skill, [skill, { ...skill, key: 'b' }])).toBeTruthy()
    expect(skillInvocationIssue({ ...skill, name: 'a/b' }, [])).toBeTruthy()
  })
})
