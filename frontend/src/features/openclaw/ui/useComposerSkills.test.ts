import { act, renderHook, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { OpenClawChatController } from '../openclawContracts'
import { useComposerSkills } from './useComposerSkills'

function setup() {
  const scope = { agentId: 'main', generation: 1 }
  let event!: (name: string) => void
  const workspace = {
    skillScope: () => ({ ...scope }), capabilities: () => ({ 'skills.status': true }),
    skillsStatus: vi.fn().mockResolvedValue({ skills: [{ key: 'one' }] }),
    subscribe: (listener: (name: string) => void) => { event = listener; return () => {} },
  }
  const chat = { workspace, status: 'connected', gatewayUrl: 'ws://localhost', sessionKey: 'root' } as unknown as OpenClawChatController
  return { scope, workspace, chat, emit: (name: string) => event(name) }
}
describe('scoped Skill directory', () => {
  it('loads only on demand and deduplicates same-scope requests', async () => {
    const { chat, workspace } = setup()
    const { result, rerender } = renderHook(({ open }) => useComposerSkills(chat, open), { initialProps: { open: false } })
    expect(workspace.skillsStatus).not.toHaveBeenCalled()
    rerender({ open: true }); await waitFor(() => expect(result.current.items).toHaveLength(1))
    rerender({ open: false }); rerender({ open: true })
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(workspace.skillsStatus).toHaveBeenCalledTimes(1)
  })
  it('ignores old responses and reloads after an Agent/generation change and skills.changed', async () => {
    const { chat, workspace, scope, emit } = setup()
    let finish!: (value: unknown) => void
    workspace.skillsStatus.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const { result, rerender } = renderHook(() => useComposerSkills(chat, true))
    await waitFor(() => expect(workspace.skillsStatus).toHaveBeenCalledTimes(1))
    scope.agentId = 'other'; scope.generation++
    rerender(); await waitFor(() => expect(result.current.items).toEqual([{ key: 'one' }]))
    await act(async () => finish({ skills: [{ key: 'OLD_SECRET' }] }))
    expect(result.current.items).toEqual([{ key: 'one' }])
    act(() => emit('skills.changed'))
    await waitFor(() => expect(workspace.skillsStatus).toHaveBeenCalledTimes(3))
  })
  it('offers safe failure retry and keeps unrelated context usable', async () => {
    const { chat, workspace } = setup()
    workspace.skillsStatus.mockRejectedValueOnce(new Error('SECRET_SENTINEL'))
    const { result } = renderHook(() => useComposerSkills(chat, true))
    await waitFor(() => expect(result.current.error).toContain('重试'))
    expect(result.current.error).not.toContain('SECRET_SENTINEL')
    await act(() => result.current.retry())
    await waitFor(() => expect(result.current.items).toHaveLength(1))
  })
})
