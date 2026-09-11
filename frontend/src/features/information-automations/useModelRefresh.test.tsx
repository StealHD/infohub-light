import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useModelRefresh } from './useModelRefresh'

const api = vi.hoisted(() => ({ informationModels: vi.fn(), refreshInformationModels: vi.fn() }))
vi.mock('./useInformationContext', () => ({ useInformationContext: () => ({ api, userId: 'user' }) }))
const receipt = { id: 'request', status: 'pending', requested_at: '', completed_at: null, changed: false }
const catalog = { status: 'ready', models: [{ id: 'old', name: 'Old', thinking_levels: [] }], refresh: null }
function setup() {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return { cache, ...renderHook(() => useModelRefresh(), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider> }) }
}
beforeEach(() => { vi.clearAllMocks(); api.informationModels.mockResolvedValue(catalog); api.refreshInformationModels.mockResolvedValue({ ...catalog, requested: true, refresh: receipt }) })
afterEach(() => vi.useRealTimers())

it('acceptance keeps the old catalog until the matching receipt; no-change is explicit', async () => {
  const { result, cache } = setup()
  await waitFor(() => expect(result.current.models.data).toEqual(catalog))
  await act(async () => { await result.current.refresh() })
  expect(result.current.refreshing).toBe(true)
  expect(result.current.models.data?.models[0].id).toBe('old')
  await act(async () => cache.setQueryData(['information-models', 'user'], { ...catalog, refresh: { ...receipt, id: 'stale', status: 'completed' } }))
  expect(result.current.refreshing).toBe(true)
  await act(async () => cache.setQueryData(['information-models', 'user'], { ...catalog, refresh: { ...receipt, status: 'completed' } }))
  await waitFor(() => expect(result.current.message).toBe('已刷新，无变化。'))
  expect(result.current.refreshing).toBe(false)
  expect(api.refreshInformationModels).toHaveBeenCalledOnce()
})

it('stops after 120 seconds without submitting another refresh', async () => {
  const { result } = setup()
  await waitFor(() => expect(result.current.models.data).toEqual(catalog))
  vi.useFakeTimers()
  await act(async () => { await result.current.refresh() })
  await act(async () => { await vi.advanceTimersByTimeAsync(120001) })
  expect(result.current.refreshing).toBe(false)
  expect(result.current.error).toContain('模型刷新超时')
  expect(api.refreshInformationModels).toHaveBeenCalledOnce()
})
