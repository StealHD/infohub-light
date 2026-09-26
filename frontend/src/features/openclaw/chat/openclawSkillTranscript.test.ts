import { beforeEach, describe, expect, it } from 'vitest'
import { buildAgentHandoffPrompt } from '../../workbench-live/agentHandoffPrompt'
import { projectChatHistory } from './openclawHistoryProjection'
import { wrapSkillHandoff } from './openclawSkillInvocation'
import { mergeOpenClawTranscript, readOpenClawTranscript, writeOpenClawTranscript } from '../storage/openclawTranscriptStore'
import type { OpenClawChatMessage } from '../openclawContracts'

const selection = { key: 'book-skill', name: 'book-skill', gatewayUrl: 'wss://gateway.test', agentId: 'main' }
const prompt = wrapSkillHandoff(buildAgentHandoffPrompt({ userId: 'a', question: '小王子', items: [] }), selection)
const expanded = (name: string) => `Use the following explicitly referenced skills for this request. Read each skill's SKILL.md before acting:\n- ${name}\n\nUser request:\n${prompt}`
const history = (text: string) => projectChatHistory({ messages: [{ id: 'remote', role: 'user', content: [{ type: 'text', text }] }] })
const local: OpenClawChatMessage = { id: 'local', role: 'user', text: '小王子', status: 'sent', origin: 'local', skillName: 'book-skill' }

beforeEach(() => sessionStorage.clear())
describe('selected Skill transcript metadata', () => {
  it.each([prompt, expanded('book-skill')])('restores only the selected name from a valid handoff', (text) => {
    const [message] = history(text)
    expect(message).toMatchObject({ text: '小王子', skillName: 'book-skill' })
    writeOpenClawTranscript('a', selection.gatewayUrl, 'session', [message])
    expect(readOpenClawTranscript('a', selection.gatewayUrl, 'session')[0]).toMatchObject({ text: '小王子', skillName: 'book-skill' })
    expect(JSON.stringify(readOpenClawTranscript('a', selection.gatewayUrl, 'session'))).not.toMatch(/HANDOFF|SKILL\.md|gatewayUrl|agentId/u)
  })
  it('keeps the label after delivery clears the retry snapshot and through old cached history', () => {
    const merged = mergeOpenClawTranscript([{ ...local, skillName: undefined }], history(prompt))
    expect(merged).toHaveLength(1)
    expect(merged[0]).toMatchObject({ id: 'local', text: '小王子', skillName: 'book-skill' })
    writeOpenClawTranscript('a', selection.gatewayUrl, 'session', merged)
    const restored = readOpenClawTranscript('a', selection.gatewayUrl, 'session')
    expect(mergeOpenClawTranscript(restored, [{ ...local, id: 'remote', skillName: undefined }])[0].skillName).toBe('book-skill')
    expect(restored[0].sendSnapshot).toBeUndefined()
  })
  it('does not conflate identical questions sent with different Skills', () => {
    const merged = mergeOpenClawTranscript([local], [{ ...local, id: 'other', skillName: 'weather' }])
    expect(merged.map((message) => message.skillName)).toEqual(['book-skill', 'weather'])
  })
  it('does not infer selection from ordinary text or mismatched native expansion', () => {
    expect(history('请解释 $book-skill')[0].skillName).toBeUndefined()
    const [message] = history(expanded('weather'))
    expect(message.text).toBe('Skill 请求记录暂不可读。')
    expect(message.skillName).toBeUndefined()
  })
  it('discards unsafe cached names and assistant metadata', () => {
    writeOpenClawTranscript('a', selection.gatewayUrl, 'session', [
      { ...local, skillName: '/private/book/SKILL.md' },
      { ...local, id: 'assistant', role: 'assistant' },
    ])
    expect(readOpenClawTranscript('a', selection.gatewayUrl, 'session').map((message) => message.skillName)).toEqual([undefined, undefined])
  })
})
