import { describe, expect, it, vi } from 'vitest'

import type { OpenClawClientPort } from '../openclawContracts'
import type { OpenClawGatewayClientOptions } from '../openclawGateway'
import { OPENCLAW_ADMIN_METHODS } from '../workspace/openclawWorkspaceContracts'
import { OpenClawAdminSessionController } from './OpenClawAdminSessionController'

function adminClient(responder: (method: string, params: Record<string, unknown>) => unknown) {
  const request = vi.fn(async (method: string, params: Record<string, unknown>) => responder(method, params)) as OpenClawClientPort['request']
  const close = vi.fn()
  const destroy = vi.fn(() => close())
  let options: OpenClawGatewayClientOptions | null = null
  const clientFactory = vi.fn((value: OpenClawGatewayClientOptions): OpenClawClientPort => {
    options = value
    return { connect: vi.fn(async () => ({ features: { methods: [...OPENCLAW_ADMIN_METHODS] } })), request, close, destroy }
  })
  return { request, close, destroy, clientFactory, options: () => options }
}

describe('OpenClaw ephemeral admin controller', () => {
  it('uses an isolated exact-scope credential without an event route', async () => {
    const fake = adminClient(() => ({}))
    const session = await OpenClawAdminSessionController.connect({ gatewayUrl: 'ws://127.0.0.1:18789', token: 'temporary-admin', clientFactory: fake.clientFactory })
    expect(fake.options()).toMatchObject({ bootstrapToken: 'temporary-admin', credentialClass: 'ephemeral-admin', requestedScopes: ['operator.admin'], deviceFamily: 'browser-temporary-admin' })
    expect(fake.options()?.onEvent).toBeUndefined()
    session.close(); expect(fake.close).toHaveBeenCalledOnce()
  })

  it('uploads ZIP bytes in ordered 512 KiB chunks before commit and install', async () => {
    const calls: Array<[string, Record<string, unknown>]> = []
    const fake = adminClient((method, params) => {
      calls.push([method, params])
      if (method === 'skills.upload.begin') return { uploadId: 'upload-1' }
      if (method === 'skills.upload.chunk') return { nextOffset: Number(params.offset) + atob(String(params.dataBase64)).length }
      return { ok: true }
    })
    const session = await OpenClawAdminSessionController.connect({ gatewayUrl: 'ws://127.0.0.1:18789', token: 'temporary-admin', clientFactory: fake.clientFactory })
    const bytes = new Uint8Array(600 * 1024); bytes.fill(7)
    const file = { name: 'private.zip', size: bytes.byteLength, arrayBuffer: async () => bytes.buffer } as File
    const progress = vi.fn()
    await session.uploadAndInstallSkill({ file, slug: 'private-skill', force: false, onProgress: progress })
    expect(calls.map(([method]) => method)).toEqual(['skills.upload.begin', 'skills.upload.chunk', 'skills.upload.chunk', 'skills.upload.commit', 'skills.install'])
    expect(calls.filter(([method]) => method === 'skills.upload.chunk').map(([, params]) => params.offset)).toEqual([0, 512 * 1024])
    expect(calls[0][1]).toMatchObject({ slug: 'private-skill', sizeBytes: bytes.byteLength, force: false })
    expect(String(calls[0][1].sha256)).toMatch(/^[a-f0-9]{64}$/u)
    expect(progress).toHaveBeenLastCalledWith(bytes.byteLength)
    session.close()
  })

  it('rejects a discontinuous upload offset without committing', async () => {
    const fake = adminClient((method) => method === 'skills.upload.begin' ? { uploadId: 'upload-1' } : method === 'skills.upload.chunk' ? { nextOffset: 1 } : {})
    const session = await OpenClawAdminSessionController.connect({ gatewayUrl: 'ws://127.0.0.1:18789', token: 'temporary-admin', clientFactory: fake.clientFactory })
    const bytes = new Uint8Array(32)
    await expect(session.uploadAndInstallSkill({ file: { name: 'bad.zip', size: bytes.byteLength, arrayBuffer: async () => bytes.buffer } as File, slug: 'bad', force: false })).rejects.toThrow('offset')
    expect(fake.request).not.toHaveBeenCalledWith('skills.upload.commit', expect.anything())
    expect(fake.request).not.toHaveBeenCalledWith('skills.install', expect.anything())
    session.close()
  })

  it('requires every chunk and install step to return a strict receipt', async () => {
    const missingOffset = adminClient((method) => method === 'skills.upload.begin' ? { uploadId: 'upload-1' } : {})
    const first = await OpenClawAdminSessionController.connect({ gatewayUrl: 'ws://127.0.0.1:18789', token: 'temporary-admin', clientFactory: missingOffset.clientFactory })
    const bytes = new Uint8Array(8)
    await expect(first.uploadAndInstallSkill({ file: { name: 'bad.zip', size: 8, arrayBuffer: async () => bytes.buffer } as File, slug: 'bad', force: false })).rejects.toThrow('offset')
    first.close()

    const missingCommit = adminClient((method, params) => method === 'skills.upload.begin' ? { uploadId: 'upload-2' } : method === 'skills.upload.chunk' ? { nextOffset: Number(params.offset) + 8 } : {})
    const second = await OpenClawAdminSessionController.connect({ gatewayUrl: 'ws://127.0.0.1:18789', token: 'temporary-admin', clientFactory: missingCommit.clientFactory })
    await expect(second.uploadAndInstallSkill({ file: { name: 'bad.zip', size: 8, arrayBuffer: async () => bytes.buffer } as File, slug: 'bad', force: false })).rejects.toThrow('有效回执')
    expect(missingCommit.request).not.toHaveBeenCalledWith('skills.install', expect.anything())
    second.close()
  })

  it('expires after ten idle minutes and publishes remote disconnects', async () => {
    vi.useFakeTimers()
    try {
      const fake = adminClient(() => ({ ok: true }))
      const session = await OpenClawAdminSessionController.connect({ gatewayUrl: 'ws://127.0.0.1:18789', token: 'temporary-admin', clientFactory: fake.clientFactory })
      const states: string[] = []
      session.subscribe((state) => states.push(state))
      vi.advanceTimersByTime(10 * 60 * 1000)
      expect(states).toContain('expired')
      expect(fake.destroy).toHaveBeenCalledOnce()

      const remote = adminClient(() => ({ ok: true }))
      const second = await OpenClawAdminSessionController.connect({ gatewayUrl: 'ws://127.0.0.1:18789', token: 'temporary-admin', clientFactory: remote.clientFactory })
      const remoteStates: string[] = []
      second.subscribe((state) => remoteStates.push(state))
      remote.options()?.onClose?.({ code: 1006 })
      expect(remoteStates).toContain('disconnected')
      expect(remote.destroy).toHaveBeenCalledOnce()
    } finally { vi.useRealTimers() }
  })

  it('creates only disabled isolated agentTurn automations with no delivery', async () => {
    const fake = adminClient((method, params) => method === 'cron.add' ? { job: { id: 'cron-1', ...params } } : method === 'cron.get' ? { job: { id: 'cron-1', name: 'Daily review', enabled: false, schedule: { kind: 'cron', expr: '0 9 * * *', tz: 'Asia/Shanghai' }, sessionTarget: 'isolated', payload: { kind: 'agentTurn', message: 'Review tasks' }, delivery: { mode: 'none' } } } : {})
    const session = await OpenClawAdminSessionController.connect({ gatewayUrl: 'ws://127.0.0.1:18789', token: 'temporary-admin', clientFactory: fake.clientFactory })
    await expect(session.createAutomation({ name: 'Daily review', message: 'Review tasks', schedule: { kind: 'cron', expr: '0 9 * * *', tz: 'Asia/Shanghai' } })).resolves.toMatchObject({ id: 'cron-1', enabled: false })
    expect(fake.request).toHaveBeenCalledWith('cron.add', expect.objectContaining({ enabled: false, sessionTarget: 'isolated', payload: { kind: 'agentTurn', message: 'Review tasks' }, delivery: { mode: 'none' } }))
    await expect(session.getAutomation('cron-1')).resolves.toMatchObject({ id: 'cron-1', message: 'Review tasks' })
    expect(fake.request).toHaveBeenCalledWith('cron.get', { id: 'cron-1' })
    session.close()
  })
})
