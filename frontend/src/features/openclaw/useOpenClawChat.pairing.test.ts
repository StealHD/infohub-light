import { act, renderHook } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { OpenClawCredentialVault } from './openclawCredentialVault'
import { MemoryAdapter } from './useOpenClawChat.test.support'
import { useOpenClawChat } from './useOpenClawChat'

it('explains first pairing without contacting the Gateway when this origin has no credential', async () => {
  const clientFactory = vi.fn()
  const vault = new OpenClawCredentialVault(new MemoryAdapter())
  const { result } = renderHook(() => useOpenClawChat({
    enabled: true, userId: 'unpaired-user', defaultGatewayUrl: 'ws://127.0.0.1:13789', vault, clientFactory,
  }))
  await act(async () => { expect(await result.current.connect()).toBe(false) })
  expect(result.current.issue).toEqual({
    kind: 'auth', message: '当前地址尚未配对。请填写 OpenClaw Gateway token，完成首次连接。',
  })
  expect(clientFactory).not.toHaveBeenCalled()
})
