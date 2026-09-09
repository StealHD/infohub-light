import { act, renderHook } from '@testing-library/react'
import { expect, it } from 'vitest'
import { chatController, contextValue } from '../OpenClawConversation.test.support'
import type { OpenClawChatController } from '../openclawContracts'
import { useComposerCommands } from './useComposerCommands'

it('isolates the temporary command panel by user, session, Gateway and connection generation', () => {
  const chat = chatController({ status: 'connected', sessionKey: 'session-a' }) as unknown as OpenClawChatController
  const value = contextValue()
  const { result, rerender } = renderHook(({ current, draft }) => useComposerCommands(current, draft), { initialProps: { current: chat, draft: value } })
  act(() => { result.current.command('status', '') })
  expect(result.current.commandPanel).not.toBeNull()
  rerender({ current: { ...chat, sessionKey: 'session-b' }, draft: value })
  expect(result.current.commandPanel).toBeNull()
  rerender({ current: { ...chat, gatewayUrl: 'ws://other.test' }, draft: value })
  expect(result.current.commandPanel).toBeNull()
  rerender({ current: chat, draft: contextValue({ userId: 'other-user' }) })
  expect(result.current.commandPanel).toBeNull()
  rerender({ current: { ...chat, workspace: { ...chat.workspace, skillScope: () => ({ agentId: 'main', generation: 2 }) } }, draft: value })
  expect(result.current.commandPanel).toBeNull()
  expect(chat.send).not.toHaveBeenCalled()
})

it('replaces and dismisses commands without adding transcript entries or changing drafts', () => {
  const chat = chatController({ status: 'connected', sessionKey: 'session-a' }) as unknown as OpenClawChatController
  const value = contextValue()
  const { result } = renderHook(() => useComposerCommands(chat, value))
  act(() => { result.current.command('status', '') })
  const first = result.current.commandPanel
  act(() => { result.current.command('help', '') })
  expect(result.current.commandPanel).not.toBe(first)
  expect(result.current).not.toHaveProperty('commandEntries')
  act(() => { result.current.closeCommand() })
  expect(result.current.commandPanel).toBeNull()
  expect(value.setQuestion).not.toHaveBeenCalled()
  expect(chat.send).not.toHaveBeenCalled()
})
