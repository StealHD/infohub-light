/* eslint-disable react-hooks/exhaustive-deps, react-hooks/immutability -- lifecycle refs are imperative controller state */
import { useCallback } from 'react'

import { applyAgentEventToTrace } from '../chat/openclawEventProjection'
import { projectChatMessage } from '../chat/openclawHistoryProjection'
import type {
  OpenClawChatMessage,
  OpenClawClientPort,
  OpenClawRunActivity,
  OpenClawRunTrace,
  OpenClawSanitizedAgentEvent,
  OpenClawSendRequest,
} from '../openclawContracts'
import { OPENCLAW_MAX_HISTORY_CHARS, mergeOpenClawTranscript } from '../storage/openclawTranscriptStore'
import { useOpenClawSendActions } from './openclawSendActions'
import type { OpenClawChatDispatch, OpenClawLifecycleState } from './openclawChatReducer'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'

type ConversationTranscriptPort = {
  persist(
    update: OpenClawChatMessage[] | ((current: OpenClawChatMessage[]) => OpenClawChatMessage[]),
    keyOverride?: string,
  ): OpenClawChatMessage[]
  resolveMedia(
    client: OpenClawClientPort,
    sessionKey: string,
    messages: OpenClawChatMessage[],
    force?: boolean,
  ): Promise<void>
  loadHistory(client: OpenClawClientPort, sessionKey: string, agentId: string): Promise<void>
}

export type OpenClawChatEvent = {
  state?: 'delta' | 'final' | 'aborted' | 'error'
  sessionKey: string
  runId?: string
  deltaText?: string
  replace?: boolean
  message?: unknown
}

export type OpenClawConversationRunController = {
  acceptsRun(runId?: string): boolean
  handleAgent(event: OpenClawSanitizedAgentEvent): void
  handleChat(event: OpenClawChatEvent): void
  send(request: OpenClawSendRequest): Promise<boolean>
  retry(messageId: string): Promise<boolean>
  takeFailedMessage(messageId: string): OpenClawSendRequest | null
  refreshMedia(messageId: string, imageId: string): Promise<void>
  stop(): Promise<void>
  reset(): void
}

export function useOpenClawConversationRun(input: {
  refs: OpenClawLifecycleRefs
  state: OpenClawLifecycleState
  dispatch: OpenClawChatDispatch
  transcript: ConversationTranscriptPort
  reloadRuntime: (client: OpenClawClientPort, sessionKey: string, agentId: string) => void
  setModel: (modelId: string | null) => Promise<boolean>
}): OpenClawConversationRunController {
  const updateRunTrace = useCallback((update: OpenClawRunTrace | null | ((current: OpenClawRunTrace | null) => OpenClawRunTrace | null)) => {
    const next = typeof update === 'function' ? update(input.refs.run.runTrace) : update
    input.refs.run.runTrace = next
    input.dispatch({ type: 'run-trace', value: next })
  }, [input.dispatch, input.refs])

  const beginRunTrace = useCallback((contextCount: number) => {
    const startedAt = Date.now()
    input.refs.run.agentEventSequence.clear()
    const activities: OpenClawRunActivity[] = contextCount > 0 ? [{
      id: 'context', label: `接收 ${contextCount} 条上下文`, status: 'completed', startedAt, endedAt: startedAt,
    }] : []
    updateRunTrace({ runId: null, phase: 'sending', status: 'running', startedAt, activities })
  }, [input.refs, updateRunTrace])

  const finishRunTrace = useCallback((terminal: 'completed' | 'aborted' | 'failed', completedRunId: string) => {
    const endedAt = Date.now()
    updateRunTrace((current) => {
      const trace = current ?? { runId: completedRunId, phase: terminal, status: terminal, startedAt: endedAt, activities: [] }
      return {
        ...trace,
        runId: completedRunId,
        phase: terminal,
        status: terminal,
        endedAt,
        activities: trace.activities.map((activity) => activity.status === 'running'
          ? { ...activity, status: terminal === 'completed' ? 'completed' : 'stopped', endedAt }
          : activity),
      }
    })
  }, [updateRunTrace])

  const reset = useCallback(() => {
    input.refs.run.runId = null
    input.refs.run.runTrace = null
    input.refs.run.pendingSend = false
    input.refs.run.sendAttempt += 1
    input.refs.run.terminalSendAttempts.clear()
    input.refs.run.agentEventSequence.clear()
    input.refs.run.terminalRunIds.clear()
    input.refs.run.streamText = ''
    input.refs.run.streamCreatedAt = null
    input.dispatch({
      type: 'patch',
      value: { runId: null, runTrace: null, sending: false, stopping: false, streamText: '', streamCreatedAt: null },
    })
  }, [input.dispatch, input.refs])

  const acceptsRun = useCallback((runId?: string) => {
    if (runId && input.refs.run.terminalRunIds.has(runId)) return false
    return !(input.refs.run.runId && runId && runId !== input.refs.run.runId)
  }, [input.refs])

  const handleAgent = useCallback((event: OpenClawSanitizedAgentEvent) => {
    if (!acceptsRun(event.runId)) return
    if (!input.refs.run.runId && !input.refs.run.pendingSend && input.refs.run.runTrace?.status !== 'running') return
    const previousSequence = input.refs.run.agentEventSequence.get(event.runId)
    if (previousSequence !== undefined && event.seq <= previousSequence) return
    input.refs.run.agentEventSequence.set(event.runId, event.seq)
    if (!input.refs.run.runId) {
      input.refs.run.runId = event.runId
      input.dispatch({ type: 'patch', value: { runId: event.runId } })
    }
    updateRunTrace((current) => applyAgentEventToTrace(current, event))
  }, [acceptsRun, input.dispatch, input.refs, updateRunTrace])

  const handleChat = useCallback((event: OpenClawChatEvent) => {
    if (!acceptsRun(event.runId)) return
    if (!input.refs.run.runId && event.runId) {
      input.refs.run.runId = event.runId
      input.dispatch({ type: 'patch', value: { runId: event.runId } })
    }
    if (event.state === 'delta' && typeof event.deltaText === 'string') {
      updateRunTrace((current) => current ? {
        ...current, runId: event.runId ?? current.runId, phase: 'streaming', status: 'running',
      } : current)
      if (input.refs.run.streamCreatedAt === null && event.deltaText) input.refs.run.streamCreatedAt = Date.now()
      input.refs.run.streamText = (event.replace ? event.deltaText : `${input.refs.run.streamText}${event.deltaText}`)
        .slice(0, OPENCLAW_MAX_HISTORY_CHARS)
      input.dispatch({
        type: 'patch',
        value: { streamText: input.refs.run.streamText, streamCreatedAt: input.refs.run.streamCreatedAt },
      })
      return
    }
    if (event.state === 'error') {
      input.dispatch({ type: 'patch', value: { issue: { kind: 'unknown', message: 'OpenClaw 对话失败，请重试。' } } })
    }
    if (event.state !== 'final' && event.state !== 'aborted' && event.state !== 'error') return
    const partialText = input.refs.run.streamText.trim()
    const partialCreatedAt = input.refs.run.streamCreatedAt ?? Date.now()
    const completedRunId = event.runId || input.refs.run.runId || crypto.randomUUID()
    input.refs.run.terminalRunIds.add(completedRunId)
    if (input.refs.run.terminalRunIds.size > 20) input.refs.run.terminalRunIds.delete(input.refs.run.terminalRunIds.values().next().value!)
    if (input.refs.run.pendingSend) {
      input.refs.run.terminalSendAttempts.add(input.refs.run.sendAttempt)
      if (input.refs.run.terminalSendAttempts.size > 20) {
        input.refs.run.terminalSendAttempts.delete(input.refs.run.terminalSendAttempts.values().next().value!)
      }
    }
    input.refs.run.runId = null
    input.refs.run.pendingSend = false
    input.refs.run.streamText = ''
    input.refs.run.streamCreatedAt = null
    input.dispatch({
      type: 'patch',
      value: { runId: null, sending: false, stopping: false, streamText: '', streamCreatedAt: null },
    })
    finishRunTrace(event.state === 'aborted' ? 'aborted' : event.state === 'error' ? 'failed' : 'completed', completedRunId)
    const client = input.refs.connection.client
    const sessionKey = input.refs.session.sessionKey
    const agentId = input.refs.session.agentId
    if (client && sessionKey && agentId) input.reloadRuntime(client, sessionKey, agentId)
    const assistantMessage = projectChatMessage(event.message, {
      id: `${event.state}-${completedRunId}`, role: 'assistant', text: partialText, createdAt: partialCreatedAt,
    })
    if (assistantMessage) {
      assistantMessage.status = event.state === 'aborted' ? 'aborted' : event.state === 'error' ? 'failed' : 'sent'
      assistantMessage.origin = 'local'
      input.transcript.persist((current) => mergeOpenClawTranscript(current, [assistantMessage]), sessionKey ?? undefined)
      if (client && sessionKey) void input.transcript.resolveMedia(client, sessionKey, [assistantMessage])
    }
    if (event.state !== 'aborted' && client && sessionKey && agentId) {
      void input.transcript.loadHistory(client, sessionKey, agentId).catch(() => undefined)
    }
  }, [acceptsRun, finishRunTrace, input, updateRunTrace])

  const actions = useOpenClawSendActions({
    refs: input.refs,
    state: input.state,
    dispatch: input.dispatch,
    transcript: input.transcript,
    beginRunTrace,
    finishRunTrace,
    updateRunTrace,
    setModel: input.setModel,
  })

  return { acceptsRun, handleAgent, handleChat, ...actions, reset }
}
