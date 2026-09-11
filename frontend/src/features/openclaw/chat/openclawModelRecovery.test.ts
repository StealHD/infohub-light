import { describe, expect, it } from 'vitest'
import { projectOpenClawRuntime } from './openclawRuntimeProjection'
import { validateSendSelection } from '../lifecycle/openclawRuntimeGuard'
import { projectChatHistory } from './openclawHistoryProjection'

describe('OpenClaw 2026.9.2 production regression', () => {
  it('does not trust describe(default) on a fork with no direct override', () => {
    const projection = projectOpenClawRuntime({ models: [{ id: 'flash', provider: 'deepseek' }] },
      { agents: [{ id: 'personal', model: { primary: 'deepseek/flash' } }] },
      { session: { key: 'child', agentId: 'personal', parentSessionKey: 'gemini-parent', modelProvider: 'deepseek', model: 'flash' } }, 'personal', 'child')
    expect(() => validateSendSelection({ displayText: 'question', gatewayPrompt: 'question', contextItems: [],
      idempotencyKey: 'turn', modelId: 'deepseek/flash', thinkingLevel: null }, projection)).toThrow('模型继承异常')
  })

  it('projects a sanitized historical error as failed, not as a successful English reply', () => {
    const [message] = projectChatHistory({ messages: [{ id: 'failed', role: 'assistant', stopReason: 'error',
      content: [{ type: 'text', text: 'The agent run failed before producing a reply.' }] }] })
    expect(message.status).toBe('failed')
    expect(message.text).toContain('具体原因不可用')
  })
})
