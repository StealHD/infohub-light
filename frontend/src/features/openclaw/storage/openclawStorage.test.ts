import { beforeEach, describe, expect, it } from 'vitest'

import type { OpenClawChatMessage } from '../openclawContracts'
import {
  readSavedGatewayUrl,
  saveGatewayUrl,
} from './openclawGatewayPreferences'
import {
  OPENCLAW_MAX_HISTORY_CHARS,
  OPENCLAW_MAX_MESSAGES,
  clearOpenClawTranscript,
  readOpenClawTranscript,
  writeOpenClawTranscript,
} from './openclawTranscriptStore'

const gatewayA = 'ws://127.0.0.1:18789'
const gatewayB = 'wss://agent.example.com/openclaw'

function message(id: string, text = id): OpenClawChatMessage {
  return { id, role: 'user', text, status: 'sent', createdAt: Number(id.replace(/\D/gu, '')) || 1 }
}

describe('OpenClaw browser storage boundaries', () => {
  beforeEach(() => {
    window.localStorage.clear()
    window.sessionStorage.clear()
  })

  it('isolates Gateway preferences by user and validates persisted values on read', () => {
    saveGatewayUrl('user-a', gatewayA)
    saveGatewayUrl('user-b', gatewayB)

    expect(readSavedGatewayUrl('user-a', gatewayB)).toBe(gatewayA)
    expect(readSavedGatewayUrl('user-b', gatewayA)).toBe(gatewayB)
    saveGatewayUrl('user-a', 'ws://remote.example.com')
    expect(readSavedGatewayUrl('user-a', gatewayA)).toBe(gatewayA)
  })

  it('isolates transcripts by user, Gateway and session', () => {
    writeOpenClawTranscript('user-a', gatewayA, 'session-a', [message('a1')])
    writeOpenClawTranscript('user-a', gatewayA, 'session-b', [message('a2')])
    writeOpenClawTranscript('user-a', gatewayB, 'session-a', [message('a3')])
    writeOpenClawTranscript('user-b', gatewayA, 'session-a', [message('b1')])

    expect(readOpenClawTranscript('user-a', gatewayA, 'session-a').map(({ id }) => id)).toEqual(['a1'])
    expect(readOpenClawTranscript('user-a', gatewayA, 'session-b').map(({ id }) => id)).toEqual(['a2'])
    expect(readOpenClawTranscript('user-a', gatewayB, 'session-a').map(({ id }) => id)).toEqual(['a3'])
    expect(readOpenClawTranscript('user-b', gatewayA, 'session-a').map(({ id }) => id)).toEqual(['b1'])
  })

  it('bounds persisted transcripts and clears only the selected isolation scope', () => {
    const messages = Array.from({ length: OPENCLAW_MAX_MESSAGES + 5 }, (_, index) => (
      message(`m${index + 1}`, 'x'.repeat(Math.ceil(OPENCLAW_MAX_HISTORY_CHARS / OPENCLAW_MAX_MESSAGES) + 10))
    ))
    writeOpenClawTranscript('user-a', gatewayA, 'session-a', messages)
    writeOpenClawTranscript('user-a', gatewayA, 'session-b', [message('keep-1')])
    writeOpenClawTranscript('user-a', gatewayB, 'session-a', [message('keep-2')])

    const persisted = readOpenClawTranscript('user-a', gatewayA, 'session-a')
    expect(persisted.length).toBeLessThanOrEqual(OPENCLAW_MAX_MESSAGES)
    expect(persisted.reduce((total, item) => total + item.text.length, 0)).toBeLessThanOrEqual(OPENCLAW_MAX_HISTORY_CHARS)

    clearOpenClawTranscript('user-a', gatewayA, 'session-a')
    expect(readOpenClawTranscript('user-a', gatewayA, 'session-a')).toEqual([])
    expect(readOpenClawTranscript('user-a', gatewayA, 'session-b')).toHaveLength(1)

    clearOpenClawTranscript('user-a', gatewayA)
    expect(readOpenClawTranscript('user-a', gatewayA, 'session-b')).toEqual([])
    expect(readOpenClawTranscript('user-a', gatewayB, 'session-a')).toHaveLength(1)
  })
})
