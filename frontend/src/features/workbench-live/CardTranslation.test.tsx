import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { AppOutletContext } from '../../app/AppContext'
import type { FeedTranslation } from '../../api/feedTranslationService'
import { ApiError } from '../../api/client'
import { CardTranslation } from './CardTranslation'
import { toWorkbenchCardModel } from './workbenchModel'

const idle: FeedTranslation = {
  status: 'idle', translation: null, job_id: null, cached: false, expires_at: null,
  scope: 'body', source_truncated: false, error: null,
}
const success: FeedTranslation = { ...idle, status: 'succeeded', translation: '完整译文', cached: true }
const card = toWorkbenchCardModel({
  id: 'post-1', title: 'Title', url: 'https://example.test',
  presentation: { content: { excerpt: 'Original body' } } as never,
})

function setup({ read = vi.fn().mockResolvedValue(idle), write = vi.fn().mockResolvedValue(success), readonly = false } = {}) {
  let active = true
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  const onExpand = vi.fn()
  const context = {
    api: { feedTranslation: read, translateFeedItem: write }, user: { id: 'owner', role: 'owner' },
    beginAction: () => ({ userId: 'owner', generation: 0 }), isActionCurrent: () => active,
  } as unknown as AppOutletContext
  const view = render(<QueryClientProvider client={queryClient}><MemoryRouter><Routes>
    <Route element={<Outlet context={context} />}><Route path="/" element={
      <CardTranslation card={card} readonly={readonly} onExpand={onExpand}>{({ button, body }) => <article><p>Original body</p>{button}{body}</article>}</CardTranslation>
    } /></Route>
  </Routes></MemoryRouter></QueryClientProvider>)
  return { ...view, read, write, onExpand, queryClient, logout: () => { active = false; queryClient.clear() } }
}

describe('CardTranslation', () => {
  it('translates once below original text and toggles cached output', async () => {
    const read = vi.fn().mockResolvedValueOnce(idle).mockResolvedValue(success)
    const state = setup({ read })
    expect(state.read).not.toHaveBeenCalled()
    fireEvent.click(await screen.findByRole('button', { name: '翻译正文' }))
    expect(await screen.findByText('完整译文')).toBeVisible()
    expect(screen.getByText('Original body')).toBeVisible()
    expect(state.write).toHaveBeenCalledTimes(1)
    expect(state.onExpand).toHaveBeenCalledTimes(1)
    read.mockResolvedValue(success)
    await waitFor(() => expect(screen.getByRole('button', { name: '翻译正文' })).toBeEnabled())
    fireEvent.click(await screen.findByRole('button', { name: '翻译正文' }))
    await waitFor(() => expect(screen.queryByText('完整译文')).not.toBeInTheDocument())
    fireEvent.click(await screen.findByRole('button', { name: '翻译正文' }))
    expect(await screen.findByText('完整译文')).toBeVisible()
    expect(state.write).toHaveBeenCalledTimes(1)
  })

  it('prevents duplicate submissions and resumes a running task without a POST', async () => {
    let resolve!: (data: FeedTranslation) => void
    const read = vi.fn().mockImplementationOnce(() => new Promise<FeedTranslation>((done) => { resolve = done }))
      .mockResolvedValue({ ...idle, status: 'running', job_id: 'job-1' })
    const state = setup({ read })
    fireEvent.click(await screen.findByRole('button', { name: '翻译正文' }))
    fireEvent.click(await screen.findByRole('button', { name: '翻译正文' }))
    await waitFor(() => expect(read).toHaveBeenCalledTimes(1))
    await act(async () => resolve({ ...idle, status: 'running', job_id: 'job-1' }))
    expect(await screen.findByText('正在翻译…')).toBeVisible()
    expect(state.write).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '翻译正文' })).toBeDisabled()
  })

  it('restores a cached excerpt without calling the model', async () => {
    const state = setup({ read: vi.fn().mockResolvedValue({ ...success, scope: 'excerpt' }) })
    fireEvent.click(await screen.findByRole('button', { name: '翻译正文' }))
    expect(await screen.findByText('仅翻译已抓取摘录')).toBeVisible()
    expect(state.write).not.toHaveBeenCalled()
  })

  it('preserves original and provides model setup recovery', async () => {
    setup({ read: vi.fn().mockRejectedValue(new ApiError(409, { code: 'translation_model_unavailable', message: '请配置模型' })) })
    fireEvent.click(await screen.findByRole('button', { name: '翻译正文' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('请配置模型')
    expect(screen.getByText('Original body')).toBeVisible()
    expect(screen.getByRole('link', { name: '前往 AI 设置' })).toHaveAttribute('href', '/settings/ai')
  })

  it('does not refill user caches after logout while a request is in flight', async () => {
    let resolve!: (data: FeedTranslation) => void
    const state = setup({ write: vi.fn().mockImplementation(() => new Promise<FeedTranslation>((done) => { resolve = done })) })
    fireEvent.click(await screen.findByRole('button', { name: '翻译正文' }))
    await waitFor(() => expect(state.write).toHaveBeenCalledTimes(1))
    state.unmount()
    state.logout()
    await act(async () => resolve(success))
    expect(state.queryClient.getQueriesData({ queryKey: ['user', 'owner'] })).toEqual([])
  })

  it('recovers an unknown POST outcome by reading the accepted task', async () => {
    const state = setup({ read: vi.fn().mockResolvedValueOnce(idle).mockResolvedValue(success),
      write: vi.fn().mockRejectedValue(new Error('network interrupted')) })
    fireEvent.click(await screen.findByRole('button', { name: '翻译正文' }))
    expect(await screen.findByText('完整译文')).toBeVisible()
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(state.write).toHaveBeenCalledTimes(1)
  })

  it('disables paid actions for viewers', async () => {
    const state = setup({ readonly: true })
    expect(await screen.findByRole('button', { name: '只读账户不可发起翻译' })).toBeDisabled()
    expect(state.read).not.toHaveBeenCalled()
  })
})
