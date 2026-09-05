import { act, renderHook } from '@testing-library/react'
import { expect, it } from 'vitest'
import { chatController, contextValue } from '../OpenClawConversation.test.support'
import type { OpenClawChatController } from '../openclawContracts'
import { useComposerCommands } from './useComposerCommands'

it('isolates local command results by user, session, Gateway and connection generation', () => {
  const chat = chatController({ status: 'connected', sessionKey: 'session-a' }) as unknown as OpenClawChatController
  const value = contextValue()
  const { result, rerender } = renderHook(({ current, draft }) => useComposerCommands(current, draft), { initialProps: { current: chat, draft: value } })
  act(() => { result.current.command('status', '') })
  expect(result.current.commandEntries).toHaveLength(1)
  rerender({ current: { ...chat, sessionKey: 'session-b' }, draft: value })
  expect(result.current.commandEntries).toHaveLength(0)
  rerender({ current: { ...chat, gatewayUrl: 'ws://other.test' }, draft: value })
  expect(result.current.commandEntries).toHaveLength(0)
  rerender({ current: chat, draft: contextValue({ userId: 'other-user' }) })
  expect(result.current.commandEntries).toHaveLength(0)
  rerender({ current: { ...chat, workspace: { ...chat.workspace, skillScope: () => ({ agentId: 'main', generation: 2 }) } }, draft: value })
  expect(result.current.commandEntries).toHaveLength(0)
  expect(chat.send).not.toHaveBeenCalled()
})
