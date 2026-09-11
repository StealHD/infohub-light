import { beforeEach, expect, it } from 'vitest'
import { failureDiagnostic } from './openclawFailureDiagnostic'
import { projectChatHistory } from './openclawHistoryProjection'
import { mergeOpenClawTranscript, readOpenClawTranscript, writeOpenClawTranscript } from '../storage/openclawTranscriptStore'
import type { OpenClawChatMessage } from '../openclawContracts'

beforeEach(() => sessionStorage.clear())

it('merges only the corresponding failed turn and retains safe diagnostics across reload', () => {
  const local: OpenClawChatMessage[] = [
    { id: 'question', role: 'user', text: 'question', status: 'sent' },
    { id: 'local-error', role: 'assistant', text: '部分回复', status: 'failed',
      diagnostic: { code: 'MODEL_QUOTA_LIMITED', runId: 'run-1', actualModelId: 'google/gemini' } },
  ]
  const remote = projectChatHistory({ messages: [{ id: 'question', role: 'user', text: 'question' },
    { id: 'server-error', role: 'assistant', stopReason: 'error', text: 'The agent run failed before producing a reply.' }] })
  const merged = mergeOpenClawTranscript(local, remote)
  expect(merged).toHaveLength(2)
  expect(merged[1]).toMatchObject({ text: '部分回复', status: 'failed', diagnostic: local[1].diagnostic })
  writeOpenClawTranscript('alice', 'gateway', 'session', merged)
  expect(readOpenClawTranscript('alice', 'gateway', 'session')[1].diagnostic).toEqual(local[1].diagnostic)
  expect(readOpenClawTranscript('bob', 'gateway', 'session')).toEqual([])
  expect(readOpenClawTranscript('alice', 'gateway', 'other')).toEqual([])
})

it('never derives a model or reason from arbitrary provider text', () => {
  expect(failureDiagnostic({ errorMessage: 'SECRET', errorCode: 'SECRET', runId: 'https://private',
    actualModelId: 'https://private' })).toEqual({ code: 'FAILURE_REASON_UNAVAILABLE' })
  expect(failureDiagnostic({ errorKind: 'rate_limit', errorCode: 'MODEL_CALL_TIMEOUT' }).code).toBe('MODEL_QUOTA_LIMITED')
})
