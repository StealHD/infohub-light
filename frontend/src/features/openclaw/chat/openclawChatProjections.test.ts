import { describe, expect, it } from 'vitest'

import { projectOpenClawAgentEvent } from './openclawEventProjection'
import {
  INTELISCOPE_HANDOFF_MARKER,
  projectOpenClawHandoffDisplay,
  sanitizeOpenClawSourceUrl,
} from './openclawHandoffProtocol'
import { projectChatHistory } from './openclawHistoryProjection'
import {
  projectOpenClawContextUsage,
  projectOpenClawRuntime,
} from './openclawRuntimeProjection'

describe('OpenClaw pure chat projections', () => {
  it('projects versioned handoffs without exposing sensitive URL parameters', () => {
    const prompt = [
      INTELISCOPE_HANDOFF_MARKER,
      JSON.stringify({
        displayText: '比较变化',
        contextCount: 2,
        imageCount: 1,
        sources: [{ title: 'Source', url: 'https://example.com/a?utm_source=x&token=secret&keep=yes#fragment' }],
      }),
      'untrusted payload',
    ].join('\n')

    expect(projectOpenClawHandoffDisplay(prompt)).toEqual({
      displayText: '比较变化',
      contextCount: 2,
      imageCount: 1,
      sources: [{ title: 'Source', url: 'https://example.com/a?keep=yes' }],
    })
    expect(sanitizeOpenClawSourceUrl('javascript:alert(1)')).toBe('')
  })

  it('projects history handoffs and keeps media references inert', () => {
    const handoff = `${INTELISCOPE_HANDOFF_MARKER}\n${JSON.stringify({ displayText: '问题', contextCount: 1 })}`
    expect(projectChatHistory({
      messages: [{
        id: 'message-1',
        role: 'user',
        text: handoff,
        content: [{ type: 'image', mediaRef: { messageId: 'message-1', partIndex: 1 } }],
      }],
    })).toMatchObject([{
      id: 'message-1',
      text: '问题',
      contextCount: 1,
      images: [{ reference: { messageId: 'message-1', partIndex: 1 } }],
    }])
  })

  it('filters agent events to the exact session and sanitizes tool labels', () => {
    const projected = projectOpenClawAgentEvent({
      type: 'event',
      event: 'agent',
      payload: {
        sessionKey: 'session-1',
        runId: 'run-1',
        stream: 'tool',
        seq: 3,
        data: { name: 'mcp__inteliscope__get_item', phase: 'start' },
      },
    }, 'session-1')

    expect(projected).toMatchObject({ runId: 'run-1', seq: 3, toolKey: 'get_item', toolLabel: '读取文章详情' })
    expect(projectOpenClawAgentEvent({
      type: 'event',
      event: 'agent',
      payload: { sessionKey: 'other', runId: 'run-1', stream: 'tool', seq: 3 },
    }, 'session-1')).toBeNull()
  })

  it('projects only fresh exact-session usage and available runtime models', () => {
    expect(projectOpenClawContextUsage({
      sessions: [{ key: 'session-1', totalTokens: 250, contextTokens: 1_000, model: 'model', provider: 'provider' }],
    }, 'session-1')).toEqual({
      sessionKey: 'session-1',
      usedTokens: 250,
      contextTokens: 1_000,
      percent: 25,
      modelId: 'provider/model',
    })

    expect(projectOpenClawRuntime(
      { models: [{ id: 'model', name: 'Model', provider: 'provider', available: true, input: ['text', 'image'] }] },
      { defaultId: 'main', agents: [{ id: 'main', model: { primary: 'provider/model' } }] },
      { session: { model: 'model', modelProvider: 'provider' } },
      'main',
    )).toMatchObject({
      models: [{ id: 'provider/model', supportsImages: true }],
      selection: { modelId: 'provider/model', defaultModelId: 'provider/model' },
      invalidSessionModel: false,
    })
  })
})
