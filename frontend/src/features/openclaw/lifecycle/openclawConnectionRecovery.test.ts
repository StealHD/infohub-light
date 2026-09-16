import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { OpenClawClientPort } from '../openclawContracts'
import { createOpenClawLifecycleRefs, stopOpenClawRecovery } from './openclawLifecycleRefs'
import {
  markOpenClawConnectionStable,
  scheduleOpenClawReconnect,
} from './openclawConnectionRecovery'
import { startManagedRelayHeartbeat } from './openclawRelayHeartbeat'

describe('OpenClaw managed connection recovery', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('keeps one jittered reconnect timer and resets backoff only after stability', () => {
    const connection = createOpenClawLifecycleRefs().connection
    const dispatch = vi.fn()
    connection.reconnect = vi.fn()

    scheduleOpenClawReconnect(connection, dispatch, () => 0.5)
    scheduleOpenClawReconnect(connection, dispatch, () => 0.5)
    expect(connection.reconnectAttempt).toBe(1)
    expect(connection.reconnectDelay).toBe(1_700)
    vi.advanceTimersByTime(1_000)
    expect(connection.reconnect).toHaveBeenCalledOnce()

    markOpenClawConnectionStable(connection, dispatch, () => true)
    vi.advanceTimersByTime(59_999)
    expect(connection.reconnectDelay).toBe(1_700)
    vi.advanceTimersByTime(1)
    expect(connection.reconnectDelay).toBe(1_000)
    expect(connection.reconnectAttempt).toBe(0)
  })

  it('probes only while usable, limits requests, and reports a live timeout once', async () => {
    const originalHidden = Object.getOwnPropertyDescriptor(document, 'hidden')
    const originalOnline = Object.getOwnPropertyDescriptor(navigator, 'onLine')
    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: true })
    const request = vi.fn().mockResolvedValueOnce({ alive: true }).mockRejectedValueOnce(new Error('timeout'))
    const failure = vi.fn()
    const stop = startManagedRelayHeartbeat({
      client: { request, connect: vi.fn(), close: vi.fn() } as unknown as OpenClawClientPort,
      hello: { features: { methods: ['relay.ping'] } },
      isCurrent: () => true,
      onFailure: failure,
    })

    await vi.advanceTimersByTimeAsync(20_000)
    expect(request).not.toHaveBeenCalled()
    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    document.dispatchEvent(new Event('visibilitychange'))
    await Promise.resolve()
    expect(request).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(request).toHaveBeenCalledTimes(2)
    expect(failure).toHaveBeenCalledOnce()

    stop()
    if (originalHidden) Object.defineProperty(document, 'hidden', originalHidden)
    if (originalOnline) Object.defineProperty(navigator, 'onLine', originalOnline)
  })

  it('cancels heartbeat and reconnect timers together', () => {
    const connection = createOpenClawLifecycleRefs().connection
    connection.reconnect = vi.fn()
    connection.heartbeatStop = vi.fn()
    scheduleOpenClawReconnect(connection, vi.fn(), () => 0.5)
    stopOpenClawRecovery(connection)
    vi.runAllTimers()
    expect(connection.heartbeatStop).toBeNull()
    expect(connection.reconnect).not.toHaveBeenCalled()
  })
})
