import { describe, expect, it, vi } from 'vitest'
import { createOpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { OpenClawSkillValidationError, validateOpenClawSkill } from './validateOpenClawSkill'
import type { OpenClawSendSnapshot } from '../openclawContracts'

const selectedSkill = { key: 'weather', name: 'weather', gatewayUrl: 'ws://localhost:18789', agentId: 'main' }
const snapshot = { selectedSkill } as OpenClawSendSnapshot
const skill = { skillKey: 'weather', name: 'weather', disabled: false, eligible: true, userInvocable: true, commandVisible: true, modelVisible: true, missing: {}, install: [] }
function fixture() {
  const refs = createOpenClawLifecycleRefs()
  const request = vi.fn().mockResolvedValue({ skills: [skill] })
  refs.connection.client = { request } as never
  refs.connection.hello = { features: { methods: ['skills.status'] } } as never
  refs.session.agentId = 'main'; refs.session.sessionKey = 'root'
  return { refs, request }
}
describe('send-time Skill validation', () => {
  it('uses a fresh scoped read and never calls a skill execution RPC', async () => {
    const { refs, request } = fixture()
    await validateOpenClawSkill(refs, snapshot, selectedSkill.gatewayUrl)
    expect(request.mock.calls).toEqual([['skills.status', { agentId: 'main' }]])
  })
  it.each([{ disabled: true }, { eligible: false }, { commandVisible: undefined }, { modelVisible: false }, { userInvocable: false }, { skillKey: 'other' }])('fails closed for changed metadata %j', async (patch) => {
    const { refs, request } = fixture(); request.mockResolvedValue({ skills: [{ ...skill, ...patch }] })
    await expect(validateOpenClawSkill(refs, snapshot, selectedSkill.gatewayUrl)).rejects.toBeInstanceOf(OpenClawSkillValidationError)
  })
  it('rejects snapshots, mismatched Gateway and unproven methods without RPC', async () => {
    const { refs, request } = fixture()
    await expect(validateOpenClawSkill(refs, { ...snapshot, sourceSnapshot: {} } as never, selectedSkill.gatewayUrl)).rejects.toThrow()
    await expect(validateOpenClawSkill(refs, snapshot, 'ws://other')).rejects.toThrow()
    refs.connection.hello = { methods: ['skills.status'] } as never
    await expect(validateOpenClawSkill(refs, snapshot, selectedSkill.gatewayUrl)).rejects.toThrow()
    expect(request).not.toHaveBeenCalled()
  })
  it.each(['generation', 'agent', 'session', 'client'])('rejects a deferred response after %s changes', async (change) => {
    const { refs, request } = fixture()
    let finish!: (value: unknown) => void
    request.mockReturnValue(new Promise((resolve) => { finish = resolve }))
    const validation = validateOpenClawSkill(refs, snapshot, selectedSkill.gatewayUrl)
    if (change === 'generation') refs.connection.generation++
    if (change === 'agent') refs.session.agentId = 'other'
    if (change === 'session') refs.session.sessionKey = 'child'
    if (change === 'client') refs.connection.client = null
    finish({ skills: [skill] })
    await expect(validation).rejects.toThrow()
  })
  it('does not leak Gateway errors', async () => {
    const { refs, request } = fixture(); request.mockRejectedValue(new Error('SECRET_SENTINEL'))
    await expect(validateOpenClawSkill(refs, snapshot, selectedSkill.gatewayUrl)).rejects.not.toThrow('SECRET_SENTINEL')
  })
})
