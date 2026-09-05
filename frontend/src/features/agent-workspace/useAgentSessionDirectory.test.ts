import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { OpenClawChatController } from '../openclaw'
import { recentSessionRows, useAgentSessionDirectory } from './useAgentSessionDirectory'

function row(key: string, updatedAt = 0) { return { key, label: key, updatedAt, hasActiveRun: false } }

function fixture() {
  let notify = (event: string) => { void event }
  const listSessionPage = vi.fn(async () => ({ sessions: [row('other-root')], hasMore: false }))
  const chat = { status: 'connected', gatewayUrl: 'ws://localhost:18789', sessionKey: 'current', workspace: {
    capabilities: () => ({ 'sessions.list': true }), listSessionPage,
    subscribe: (listener: (event: string) => void) => { notify = listener; return () => {} },
  } } as unknown as OpenClawChatController
  return { chat, listSessionPage, notify: (event: string) => notify(event) }
}

describe('Agent session directory', () => {
  it('keeps current plus two recent sessions from independent roots', () => {
    expect(recentSessionRows([row('a', 1), row('b', 3), row('c', 2), row('d', 4)], row('current')).map((item) => item.key)).toEqual(['d', 'b', 'current'])
    expect(recentSessionRows([row('a'), row('a2')])).toHaveLength(2)
  })

  it('does not reorder visible rows just because selection changes', () => {
    const rows = [row('a', 30), row('b', 20), row('c', 10), row('d', 5)]
    for (const current of rows.slice(0, 3)) expect(recentSessionRows(rows, current).map((item) => item.key)).toEqual(['a', 'b', 'c'])
    expect(recentSessionRows(rows, rows[3]).map((item) => item.key)).toEqual(['a', 'b', 'd'])
  })

  it('refreshes the catalog on title events without widening resource scope', async () => {
    const { chat, listSessionPage, notify } = fixture()
    const { result } = renderHook(() => useAgentSessionDirectory(chat, 'user'))
    await waitFor(() => expect(result.current.page?.sessions[0].key).toBe('other-root'))
    listSessionPage.mockResolvedValue({ sessions: [{ ...row('other-root'), label: '自动总结' }], hasMore: false })
    act(() => notify('sessions.changed'))
    await waitFor(() => expect(result.current.page?.sessions[0].label).toBe('自动总结'))
  })

  it('hides old-user and old-Gateway data immediately and ignores late results', async () => {
    const { chat, listSessionPage } = fixture()
    const { result, rerender } = renderHook(({ user, gateway }) => useAgentSessionDirectory({ ...chat, gatewayUrl: gateway }, user), { initialProps: { user: 'one', gateway: 'ws://one' } })
    await waitFor(() => expect(result.current.page).toBeDefined())
    let finish!: (value: { sessions: ReturnType<typeof row>[]; hasMore: boolean }) => void
    listSessionPage.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    rerender({ user: 'two', gateway: 'ws://two' })
    expect(result.current.page).toBeUndefined()
    await waitFor(() => expect(finish).toBeDefined())
    rerender({ user: 'three', gateway: 'ws://three' })
    await waitFor(() => expect(result.current.page?.sessions[0].key).toBe('other-root'))
    await act(async () => finish({ sessions: [row('private-old-user')], hasMore: false }))
    expect(result.current.page?.sessions[0].key).toBe('other-root')
  })
})
