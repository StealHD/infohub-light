import { describe, expect, it, vi } from 'vitest'

import { createApiClient } from './client'

describe('api client', () => {
  it('unwraps a successful service envelope and forwards the abort signal', async () => {
    const fetcher = vi.fn(async (_path: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.credentials).toBe('same-origin')
      expect(init?.signal).toBeInstanceOf(AbortSignal)
      return new Response(JSON.stringify({ ok: true, data: { count: 3 } }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    const controller = new AbortController()
    const api = createApiClient({ fetcher })

    await expect(api.get<{ count: number }>('/api/example', controller.signal)).resolves.toEqual({ count: 3 })
    expect(fetcher).toHaveBeenCalledOnce()
  })

  it('throws a typed error and notifies once when the session is unauthorized', async () => {
    const unauthorized = vi.fn()
    const api = createApiClient({
      onUnauthorized: unauthorized,
      fetcher: async () => new Response(
        JSON.stringify({
          ok: false,
          error: { code: 'unauthorized', message: '请先登录', retryable: false },
        }),
        { status: 401, headers: { 'Content-Type': 'application/json' } },
      ),
    })

    await expect(api.get('/api/private')).rejects.toMatchObject({
      name: 'ApiError',
      status: 401,
      code: 'unauthorized',
      message: '请先登录',
      retryable: false,
    })
    expect(unauthorized).toHaveBeenCalledOnce()
  })

  it.each([
    [403, 'forbidden'],
    [404, 'not_found'],
    [409, 'source_key_conflict'],
    [429, 'daily_quota_exceeded'],
    [503, 'worker_stale'],
  ])('preserves service diagnostics for HTTP %s', async (status, code) => {
    const api = createApiClient({
      fetcher: async () => new Response(JSON.stringify({
        ok: false,
        error: { code, message: `diagnostic:${code}`, retryable: status >= 429, action: 'retry_later' },
      }), { status, headers: { 'Content-Type': 'application/json' } }),
    })

    await expect(api.get('/api/example')).rejects.toMatchObject({
      status,
      code,
      message: `diagnostic:${code}`,
      retryable: status >= 429,
      action: 'retry_later',
    })
  })

  it('surfaces a network failure unchanged so Query can apply its retry policy', async () => {
    const failure = new TypeError('network offline')
    const api = createApiClient({ fetcher: async () => { throw failure } })

    await expect(api.get('/api/example')).rejects.toBe(failure)
  })
})
