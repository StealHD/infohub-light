import { describe, expect, it, vi } from 'vitest'
import type { OpenClawClientPort } from '../openclawContracts'
import { restoredSessionAgent } from './openclawSessionIdentity'

describe('restored session Agent', () => {
  it('restores the owning Agent instead of the default after refresh', async () => {
    const key = 'agent:research:dashboard:old'
    const request = vi.fn().mockResolvedValue({ session: { key, agentId: 'research' } })
    expect(await restoredSessionAgent({ request } as unknown as OpenClawClientPort, key, 'main')).toBe('research')
    expect(request).toHaveBeenCalledWith('sessions.describe', { key })
  })
  it.each([{ key: 'other' }, { key: 'agent:research:dashboard:old', agentId: 'main' }, null])('rejects a mismatched or missing saved session: %o', async (session) => {
    const request = vi.fn().mockResolvedValue({ session })
    await expect(restoredSessionAgent({ request } as unknown as OpenClawClientPort, 'agent:research:dashboard:old', 'main')).rejects.toThrow('不匹配')
  })
})
