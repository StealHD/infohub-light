import { describe, expect, it, vi } from 'vitest'
import { createOpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { openOpenClawSession } from './openClawSessionNavigation'
import type { OpenClawClientPort } from '../openclawContracts'

function fixture({ mismatch = false, forbidden = false, historyFailure = false } = {}) {
  const refs = createOpenClawLifecycleRefs()
  refs.session.agentId = 'main'; refs.session.sessionKey = 'parent'
  const key = 'agent:research:dashboard:old'
  const request = vi.fn(async (method: string): Promise<unknown> => {
    if (method === 'sessions.preview') return { previews: [{ key, status: 'ok' }] }
    if (method === 'sessions.list') return { sessions: forbidden ? [] : [{ key, agentId: 'research' }] }
    if (method === 'sessions.describe') return { session: { key: mismatch ? 'wrong' : key, agentId: 'research' } }
    if (method === 'chat.history') { if (historyFailure) throw new Error('unavailable'); return { messages: [] } }
    if (method === 'models.list') return { models: [] }
    if (method === 'agents.list') return { agents: [{ id: 'research' }] }
    throw new Error('unexpected request')
  })
  refs.connection.client = { request, connect: vi.fn(), close: vi.fn() } as OpenClawClientPort
  const input = {
    refs, userId: 'user', state: { sending: false, runtimeUpdating: false }, dispatch: vi.fn(),
    vault: { updateSession: vi.fn() }, getGatewayUrl: () => 'ws://localhost:18789',
    transcript: { replace: vi.fn(), loadHistory: vi.fn() }, resetConversation: vi.fn(),
    bind: vi.fn(), applyRuntime: vi.fn(), loadContextUsage: vi.fn(),
  } as unknown as Parameters<typeof openOpenClawSession>[0]
  return { input, key, request }
}

describe('catalog session switching', () => {
  it('validates and opens the selected Agent on the existing connection', async () => {
    const { input, key, request } = fixture()
    expect(await openOpenClawSession(input, key, 'research')).toBe(true)
    expect(request).toHaveBeenCalledWith('sessions.describe', { key })
    expect(input.bind).toHaveBeenCalledWith('research', key)
    expect(input.refs.connection.client?.close).not.toHaveBeenCalled()
  })

  it.each([{ mismatch: true }, { forbidden: true }, { historyFailure: true }])('preserves current conversation when verification fails: %o', async (options) => {
    const { input, key } = fixture(options)
    expect(await openOpenClawSession(input, key, 'research')).toBe(false)
    expect(input.bind).not.toHaveBeenCalled()
    expect(input.vault.updateSession).not.toHaveBeenCalled()
    expect(input.transcript.replace).not.toHaveBeenCalled()
  })

  it('blocks rapid duplicate switching before pending state renders', async () => {
    const { input, key, request } = fixture()
    const first = openOpenClawSession(input, key, 'research')
    expect(await openOpenClawSession(input, key, 'research')).toBe(false)
    expect(await first).toBe(true)
    expect(request.mock.calls.filter(([method]) => method === 'sessions.preview')).toHaveLength(1)
  })
  it('ignores a verified response after the connection epoch changes', async () => {
    const { input, key, request } = fixture()
    let finish!: (value: unknown) => void
    const original = request.getMockImplementation()!
    request.mockImplementation((method) => method === 'sessions.describe'
      ? new Promise((resolve) => { finish = resolve }) : original(method))
    const pending = openOpenClawSession(input, key, 'research')
    await vi.waitFor(() => expect(finish).toBeTypeOf('function'))
    input.refs.session.navigationEpoch += 1
    finish({ session: { key, agentId: 'research' } })
    expect(await pending).toBe(false)
    expect(input.bind).not.toHaveBeenCalled()
    expect(input.vault.updateSession).not.toHaveBeenCalled()
    request.mockImplementation(original)
    expect(await openOpenClawSession(input, key, 'research')).toBe(true)
  })

})
