import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useOpenClawChat } from './useOpenClawChat'

const CONTROLLER_KEYS = [
  'clearTranscript',
  'connect',
  'contextUsage',
  'currentModelSupportsImages',
  'disconnect',
  'forget',
  'gatewayUrl',
  'imageInputAvailable',
  'isRunning',
  'isStopping',
  'messages',
  'modelSwitchFallback',
  'models',
  'newConversation',
  'reconnectAttempt',
  'refreshMedia',
  'retry',
  'retryConnection',
  'runTrace',
  'runtimeIssue',
  'runtimeLoading',
  'runtimeSelection',
  'runtimeUpdating',
  'send',
  'sessionKey',
  'setGatewayUrl',
  'setModel',
  'setThinking',
  'status',
  'stop',
  'streamCreatedAt',
  'streamText',
  'switchToBlankConversation',
  'takeFailedMessage',
  'thinkingOptions',
  'toolsStatus',
  'issue',
].sort()

describe('OpenClaw public behavior', () => {
  it('keeps the complete controller surface stable while chat is disabled', () => {
    const { result } = renderHook(() => useOpenClawChat({
      enabled: false,
      userId: 'characterization-user',
      defaultGatewayUrl: 'ws://127.0.0.1:18789',
    }))

    expect(Object.keys(result.current).sort()).toEqual(CONTROLLER_KEYS)
    expect(result.current.status).toBe('disabled')
    expect(result.current.toolsStatus).toBe('unknown')
    expect(result.current.isRunning).toBe(false)
  })
})
