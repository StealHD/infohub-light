import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { beforeEach, expect, it, vi } from 'vitest'
import { useModelRefresh } from './useModelRefresh'

const api = vi.hoisted(() => ({ informationModels: vi.fn(), refreshInformationModels: vi.fn() }))
vi.mock('./useInformationContext', () => ({ useInformationContext: () => ({ api, userId: 'user' }) }))
const catalog = { status: 'ready', models: [{ id: 'openai/gpt-5.6-terra', name: 'GPT-5.6 Terra', thinking_levels: [] }], refresh: null }
function setup() {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return { cache, ...renderHook(() => useModelRefresh(), { wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={cache}>{children}</QueryClientProvider> }) }
}
beforeEach(() => { vi.clearAllMocks(); api.informationModels.mockResolvedValue(catalog); api.refreshInformationModels.mockResolvedValue(catalog) })

it('replaces the catalog with the direct OpenClaw response without waiting for an executor receipt', async () => {
  const { result } = setup()
  await waitFor(() => expect(result.current.models.data).toEqual(catalog))
  await act(async () => { await result.current.refresh() })
  expect(result.current.models.data).toEqual(catalog)
  expect(result.current.refreshing).toBe(false)
  expect(result.current.message).toBe('')
  expect(api.refreshInformationModels).toHaveBeenCalledOnce()
})

it('keeps one in-flight direct read and reports its local error', async () => {
  let reject!: (error: Error) => void
  api.refreshInformationModels.mockReturnValue(new Promise((_, fail) => { reject = fail }))
  const { result } = setup()
  await waitFor(() => expect(result.current.models.data).toEqual(catalog))
  act(() => { void result.current.refresh() })
  await waitFor(() => expect(api.refreshInformationModels).toHaveBeenCalledOnce())
  act(() => { void result.current.refresh() })
  expect(api.refreshInformationModels).toHaveBeenCalledOnce()
  await act(async () => { reject(new Error('Gateway 不可用')); await Promise.resolve() })
  await waitFor(() => expect(result.current.error).toBe('Gateway 不可用'))
})
