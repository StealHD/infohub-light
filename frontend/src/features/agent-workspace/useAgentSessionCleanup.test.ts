import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { OpenClawChatController } from '../openclaw'
import { useAgentSessionCleanup } from './useAgentSessionCleanup'
import { cleanupPreferenceScope, writeCleanupEnabled } from './sessionCleanupPreference'

beforeEach(() => {
  vi.useFakeTimers(); localStorage.clear()
  Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: vi.fn(async (_scope, _options, callback) => callback({})) } })
})
afterEach(() => { vi.useRealTimers(); Reflect.deleteProperty(navigator, 'locks'); localStorage.clear() })

function chat() {
  return { gatewayUrl: '/api/me/openclaw/socket', status: 'connected', sessionKey: 'agent:own:current',
    workspace: { cleanupSessions: vi.fn().mockResolvedValue(2) } } as unknown as OpenClawChatController
}
it('schedules bounded cleanup, records current use and respects the persistent switch', async () => {
  const current = chat(), { result, unmount } = renderHook(() => useAgentSessionCleanup(current, 'alice'))
  await act(() => vi.advanceTimersByTimeAsync(3000))
  expect(current.workspace.cleanupSessions).toHaveBeenCalledTimes(1)
  const options = vi.mocked(current.workspace.cleanupSessions!).mock.calls[0][0]
  expect(options.lastUsedAt(current.sessionKey!)).toBe(Date.now())
  expect(result.current.status).toContain('2 个')
  act(() => result.current.setEnabled(false))
  await act(() => vi.advanceTimersByTimeAsync(60_000))
  expect(current.workspace.cleanupSessions).toHaveBeenCalledTimes(1)
  expect(options.isEnabled()).toBe(false)
  unmount()
})

it('isolates preferences by user and stops a pending pass after unmount', async () => {
  const current = chat()
  writeCleanupEnabled(cleanupPreferenceScope('alice', current.gatewayUrl), false)
  const { result, rerender, unmount } = renderHook(({ user }) => useAgentSessionCleanup(current, user), { initialProps: { user: 'alice' } })
  await act(() => vi.advanceTimersByTimeAsync(3000))
  expect(current.workspace.cleanupSessions).not.toHaveBeenCalled()
  rerender({ user: 'bob' })
  expect(result.current.enabled).toBe(true)
  await act(() => vi.advanceTimersByTimeAsync(3000))
  const options = vi.mocked(current.workspace.cleanupSessions!).mock.calls[0][0]
  expect(options.isEnabled()).toBe(true)
  unmount()
  expect(options.isEnabled()).toBe(false)
})
