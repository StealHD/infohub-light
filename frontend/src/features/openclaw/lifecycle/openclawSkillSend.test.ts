import { renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { createOpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { createOpenClawChatState } from './openclawChatReducer'
import { useOpenClawSendActions } from './openclawSendActions'
import type { OpenClawChatMessage } from '../openclawContracts'
import { models, agents, session } from '../useOpenClawChat.test.support'

const skill = { key: 'weather', name: 'weather', gatewayUrl: 'ws://localhost:18789', agentId: 'main' }
const requestInput = { displayText: '查天气', gatewayPrompt: 'private-prompt', contextItems: [], selectedSkill: skill }
function setup() {
  const refs = createOpenClawLifecycleRefs()
  const request = vi.fn(async (method: string, params?: Record<string, unknown>) => {
    void params
    return method === 'skills.status'
      ? { skills: [{ skillKey: 'weather', name: 'weather', disabled: false, eligible: true, userInvocable: true, commandVisible: true, modelVisible: true }] }
      : { runId: 'run' }
  })
  refs.connection.client = { request: async (method: string, params?: Record<string, unknown>) => {
    if (method === 'models.list') return models
    if (method === 'agents.list') return agents
    if (method === 'sessions.describe') return { session: { ...session.session, key: 'root' } }
    return request(method, params)
  } } as never
  refs.connection.hello = { features: { methods: ['skills.status'] } } as never
  refs.session.agentId = 'main'; refs.session.sessionKey = 'root'
  const persist = (update: OpenClawChatMessage[] | ((current: OpenClawChatMessage[]) => OpenClawChatMessage[])) => {
    refs.transcript.messages = typeof update === 'function' ? update(refs.transcript.messages) : update
    return refs.transcript.messages
  }
  const dispatch = vi.fn()
  const { result } = renderHook(() => useOpenClawSendActions({
    refs, dispatch, state: { ...createOpenClawChatState(skill.gatewayUrl, 'connected'),
      runtimeSelection: { modelId: 'openai/gpt-5.4', thinkingLevel: null, defaultModelId: 'openai/gpt-5.4', defaultThinkingLevel: 'low' } },
    transcript: { persist, resolveMedia: vi.fn() }, beginRunTrace: vi.fn(), finishRunTrace: vi.fn(), updateRunTrace: vi.fn(), setModel: vi.fn(),
  }))
  return { result, refs, request, dispatch }
}
describe('Skill send snapshots', () => {
  it('gates concurrent sends while fresh validation is pending', async () => {
    const { result, refs, request } = setup()
    let finish!: (value: unknown) => void
    request.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }) as never)
    const sending = result.current.send(requestInput)
    expect(await result.current.send(requestInput)).toBe(false)
    expect(refs.transcript.messages).toHaveLength(1)
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    finish({ skills: [{ skillKey: 'weather', name: 'weather', disabled: false, eligible: true, userInvocable: true, commandVisible: true, modelVisible: true }] })
    expect(await sending).toBe(true)
    expect(request.mock.calls.filter(([method]) => method === 'chat.send')).toHaveLength(1)
  })
  it('retains exact Skill and stable idempotency key after a failed send and on retry', async () => {
    const { result, refs, request } = setup()
    request.mockResolvedValueOnce({ skills: [{ skillKey: 'weather', name: 'weather', disabled: false, eligible: true, userInvocable: true, commandVisible: true, modelVisible: true }] } as never)
      .mockRejectedValueOnce(new Error('send failed'))
    const input = { ...requestInput, selectedSkill: { ...skill } }
    expect(await result.current.send(input)).toBe(false)
    input.selectedSkill.name = 'later-choice'
    const failed = refs.transcript.messages[0]
    expect(failed.sendSnapshot?.selectedSkill?.name).toBe('weather')
    expect(await result.current.retry(failed.id)).toBe(true)
    const sends = request.mock.calls.filter(([method]) => method === 'chat.send') as unknown as Array<[string, { idempotencyKey: string }]>
    expect(sends).toHaveLength(2)
    expect(sends[0][1].idempotencyKey).toBe(sends[1][1].idempotencyKey)
  })
  it('restores the original Skill when editing a failed message', async () => {
    const { result, refs, request } = setup()
    request.mockRejectedValueOnce(new Error('SECRET_SENTINEL'))
    expect(await result.current.send(requestInput)).toBe(false)
    expect(result.current.takeFailedMessage(refs.transcript.messages[0].id)?.selectedSkill).toEqual(skill)
    expect(refs.transcript.messages).toHaveLength(0)
  })
  it('does not send or dispatch late errors into a replacement connection', async () => {
    const { result, refs, request, dispatch } = setup()
    let fail!: (error: Error) => void
    request.mockReturnValueOnce(new Promise((_, reject) => { fail = reject }) as never)
    const pending = result.current.send(requestInput)
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
    refs.connection.generation++; refs.connection.client = null
    dispatch.mockClear()
    fail(new Error('SECRET_SENTINEL'))
    expect(await pending).toBe(false)
    expect(dispatch).not.toHaveBeenCalled()
    expect(request).toHaveBeenCalledTimes(1)
  })
})
