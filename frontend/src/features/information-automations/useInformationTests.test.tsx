import { act, renderHook } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { ApiError } from '../../api/client'
import { useInformationTests } from './useInformationTests'

const api = vi.hoisted(() => ({ testInformationRule: vi.fn(), informationTestPreview: vi.fn() }))
vi.mock('./useInformationContext', () => ({ useInformationContext: () => ({ api, userId: 'user' }) }))
beforeEach(() => vi.resetAllMocks())

it('shows an explicit Service rejection rather than submission unknown', async () => {
  api.testInformationRule.mockRejectedValue(new ApiError(409, { code: 'execution_disabled', message: '仅同步目录，请开启手动测试。' }))
  const { result } = renderHook(() => useInformationTests())
  act(() => result.current.select('rule', 1, [{ id: 'article', title: 'Article' }]))
  await act(async () => { await result.current.start('rule', 1) })
  expect(result.current.session('rule', 1).phase).toBe('failed')
  expect(result.current.session('rule', 1).error).toBe('仅同步目录，请开启手动测试。')
  expect(result.current.session('rule', 1).selection).toHaveLength(1)
})

it('reuses the same request identifier after an ambiguous network failure', async () => {
  api.testInformationRule.mockRejectedValueOnce(new TypeError('network'))
    .mockResolvedValue({ preview_id: 'same-preview', version: 1, status: 'pending', results: [] })
  const { result } = renderHook(() => useInformationTests())
  act(() => result.current.select('rule', 1, [{ id: 'article', title: 'Article' }]))
  await act(async () => { await result.current.start('rule', 1) })
  expect(result.current.session('rule', 1).phase).toBe('submission_unknown')
  await act(async () => { await result.current.start('rule', 1) })
  expect(api.testInformationRule.mock.calls[0][3]).toBe(api.testInformationRule.mock.calls[1][3])
  expect(result.current.session('rule', 1).data?.preview_id).toBe('same-preview')
})

it('a late restored preview cannot replace a newly submitted test', async () => {
  let restore!: (value: unknown) => void
  api.informationTestPreview.mockReturnValue(new Promise((resolve) => { restore = resolve }))
  api.testInformationRule.mockResolvedValue({ preview_id: 'new', version: 1, status: 'pending', results: [] })
  const { result } = renderHook(() => useInformationTests())
  let pending: Promise<void>
  act(() => { pending = result.current.restore('rule', 1) })
  act(() => result.current.select('rule', 1, [{ id: 'article', title: 'Article' }]))
  await act(async () => { await result.current.start('rule', 1) })
  await act(async () => { restore({ preview_id: 'old', version: 1, status: 'completed', results: [] }); await pending })
  expect(result.current.session('rule', 1).data?.preview_id).toBe('new')
})
