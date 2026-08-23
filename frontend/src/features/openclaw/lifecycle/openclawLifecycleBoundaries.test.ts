import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { createOpenClawChatState, openClawChatReducer } from './openclawChatReducer'

const sourceFile = (name: string) => readFileSync(
  fileURLToPath(new URL(name, import.meta.url)),
  'utf8',
)

describe('OpenClaw lifecycle boundaries', () => {
  it('keeps the root Hook bounded and reducer-owned state serializable', () => {
    const root = sourceFile('../useOpenClawChat.ts')
    expect(root.split('\n').length).toBeLessThanOrEqual(300)
    expect(root).not.toContain('useState')
    const state = openClawChatReducer(
      createOpenClawChatState('ws://127.0.0.1:18789', 'idle'),
      { type: 'patch', value: { sessionKey: 'session-1', sending: true } },
    )
    expect(JSON.parse(JSON.stringify(state))).toMatchObject({ sessionKey: 'session-1', sending: true })
  })

  it('keeps controllers independent and raw Gateway frames in the root router', () => {
    const controllers = [
      'openclawSendActions.ts',
      'openclawSessionActions.ts',
      'useOpenClawConnection.ts',
      'useOpenClawConversationRun.ts',
      'useOpenClawSessionRuntime.ts',
      'useOpenClawTranscriptController.ts',
    ]
    for (const controller of controllers) {
      expect(sourceFile(controller)).not.toMatch(/from ['"]\.\/useOpenClaw/u)
    }
    expect(sourceFile('useOpenClawConversationRun.ts')).not.toContain('GatewayEvent')
    expect(sourceFile('useOpenClawSessionRuntime.ts')).not.toContain('GatewayEvent')
    const root = sourceFile('../useOpenClawChat.ts')
    expect(root).toContain('generation !== refs.connection.generation')
    expect(root).toContain('payload.sessionKey !== sessionKey')
    expect(root).toContain('conversation.acceptsRun(payload.runId)')
  })
})
