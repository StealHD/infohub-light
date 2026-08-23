import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import type { WorkbenchAgentContextValue } from '../workbench-live/workbenchAgentContext'
import { OpenClawActivityTrace, OpenClawContextUsageIndicator, OpenClawConversation } from './OpenClawConversation'
import { gatewayOriginSetupCommands } from './openclawOriginSetup'

export function contextValue(overrides: Partial<WorkbenchAgentContextValue['draft']> = {}): WorkbenchAgentContextValue {
  return {
    draft: {
      userId: 'user-a',
      question: '',
      items: [],
      ...overrides,
    },
    toggleItem: vi.fn(),
    removeItem: vi.fn(),
    clearItems: vi.fn(),
    openComposer: vi.fn(),
    openWithSourceSnapshot: vi.fn(),
    setQuestion: vi.fn(),
    clearComposer: vi.fn(),
    restoreComposer: vi.fn(),
  }
}

export function chatController(overrides: Record<string, unknown> = {}) {
  return {
    gatewayUrl: 'ws://127.0.0.1:18789',
    setGatewayUrl: vi.fn(),
    status: 'idle',
    toolsStatus: 'unknown',
    messages: [],
    streamText: '',
    streamCreatedAt: null,
    runTrace: null,
    issue: null,
    runtimeIssue: null,
    modelSwitchFallback: null,
    contextUsage: null,
    imageInputAvailable: false,
    currentModelSupportsImages: false,
    sessionKey: null,
    isRunning: false,
    isStopping: false,
    reconnectAttempt: 0,
    runtimeLoading: false,
    runtimeUpdating: false,
    models: [],
    thinkingOptions: [],
    runtimeSelection: { modelId: null, thinkingLevel: null, defaultModelId: null, defaultThinkingLevel: null },
    connect: vi.fn().mockResolvedValue(true),
    retryConnection: vi.fn(),
    disconnect: vi.fn(),
    forget: vi.fn(),
    send: vi.fn().mockResolvedValue(true),
    retry: vi.fn().mockResolvedValue(true),
    takeFailedMessage: vi.fn(),
    stop: vi.fn(),
    setModel: vi.fn().mockResolvedValue(true),
    setThinking: vi.fn().mockResolvedValue(true),
    switchToBlankConversation: vi.fn().mockResolvedValue(true),
    newConversation: vi.fn(),
    refreshMedia: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  }
}

export { fireEvent, render, screen, waitFor, userEvent, OpenClawActivityTrace, OpenClawContextUsageIndicator, OpenClawConversation, gatewayOriginSetupCommands }