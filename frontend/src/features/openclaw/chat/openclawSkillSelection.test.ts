import { describe, expect, it } from 'vitest'
import { buildAgentHandoffPrompt } from '../../workbench-live/agentHandoffPrompt'
import { projectOpenClawHandoffDisplay } from './openclawHandoffProtocol'
import { sanitizeSkillSelection, unwrapSkillHandoff } from './openclawSkillSelection'
import { escapeSkillReferences, wrapSkillHandoff } from './openclawSkillInvocation'

const selected = { key: 'weather', name: 'weather', gatewayUrl: 'ws://127.0.0.1:18789', agentId: 'main' }
describe('explicit Skill handoff', () => {
  it('projects original display text through native expansion without exposing internal instructions', () => {
    const prompt = buildAgentHandoffPrompt({ userId: 'a', question: '说明 $other 与 $weather', items: [] })
    const wrapped = wrapSkillHandoff(prompt, selected)
    expect(wrapped).toContain('\n$weather\n')
    expect(wrapped).not.toContain('\n/skill')
    const expanded = `Use the following explicitly referenced skills for this request. Read each skill's SKILL.md before acting:\n- weather\n\nUser request:\n${wrapped}`
    expect(projectOpenClawHandoffDisplay(expanded)?.displayText).toBe('说明 $other 与 $weather')
    expect(projectOpenClawHandoffDisplay(wrapped)?.displayText).toBe('说明 $other 与 $weather')
  })
  it('escapes incidental native references, including escaped refs and JSON metadata', () => {
    expect(escapeSkillReferences('$foo \\$bar \\\\$baz')).toBe('\\$foo \\$bar \\$baz')
    expect(JSON.parse(escapeSkillReferences('{"question":"$foo"}')).question).toBe('$foo')
  })
  it('hides malformed native expansion and private paths', () => {
    expect(unwrapSkillHandoff("Use the following explicitly referenced skills for this request. Read each skill's SKILL.md before acting:\n- weather (/private/secret/SKILL.md)\n\nUser request:\nhi")).toBe('')
    expect(unwrapSkillHandoff('[INTELISCOPE_SKILL_HANDOFF_V1]\n{"name":"bad"}\n$weather\n[INTELISCOPE_HANDOFF_V8]')).toBe('')
  })
  it('projects only bounded safe selection metadata', () => {
    expect(sanitizeSkillSelection({ ...selected, description: 'secret' })).toEqual(selected)
    for (const gatewayUrl of ['ws://user:secret@localhost', 'ws://localhost/?token=secret', 'https://localhost']) expect(sanitizeSkillSelection({ ...selected, gatewayUrl })).toBeUndefined()
    expect(sanitizeSkillSelection({ ...selected, name: 'a/b' })).toBeUndefined()
    expect(sanitizeSkillSelection({ ...selected, key: 'a\nsecret' })).toBeUndefined()
  })
})
