import { act, renderHook } from '@testing-library/react'
import { createElement, StrictMode, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { OpenClawAdminSessionController } from '../openclaw/admin/OpenClawAdminSessionController'
import { useOpenClawAdminSession } from './useOpenClawAdminSession'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('useOpenClawAdminSession lifecycle', () => {
  it('accepts a connection after StrictMode effect cleanup and setup', async () => {
    const close = vi.fn()
    const controller = { close, subscribe: vi.fn(() => () => undefined) } as unknown as OpenClawAdminSessionController
    vi.spyOn(OpenClawAdminSessionController, 'connect').mockResolvedValueOnce(controller)
    const hook = renderHook(() => useOpenClawAdminSession('ws://127.0.0.1:18789'), {
      wrapper: ({ children }: { children: ReactNode }) => createElement(StrictMode, null, children),
    })
    await act(async () => { expect(await hook.result.current.connect('temporary-token')).toBe(true) })
    expect(hook.result.current.admin).toBe(controller)
    expect(hook.result.current.connecting).toBe(false)
    hook.unmount()
    expect(close).toHaveBeenCalledOnce()
  })
  it('destroys a pending connection that completes after unmount', async () => {
    const pending = deferred<OpenClawAdminSessionController>()
    const close = vi.fn()
    const controller = { close, subscribe: vi.fn(() => () => undefined) } as unknown as OpenClawAdminSessionController
    vi.spyOn(OpenClawAdminSessionController, 'connect').mockReturnValueOnce(pending.promise)
    const hook = renderHook(() => useOpenClawAdminSession('ws://127.0.0.1:18789'))
    let connecting!: Promise<boolean>
    act(() => { connecting = hook.result.current.connect('temporary-token') })
    hook.unmount()
    pending.resolve(controller)
    await expect(connecting).resolves.toBe(false)
    expect(close).toHaveBeenCalledOnce()
  })
})
