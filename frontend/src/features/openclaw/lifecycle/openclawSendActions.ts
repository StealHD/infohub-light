/* eslint-disable react-hooks/immutability -- lifecycle refs are imperative controller state */
import { useCallback } from 'react'

import { openClawSourceReferences, sanitizeOpenClawSourceUrl } from '../chat/openclawHandoffProtocol'
import { setupIssue } from '../chat/openclawSetupIssue'
import type {
  OpenClawChatMessage,
  OpenClawClientPort,
  OpenClawRunTrace,
  OpenClawSendRequest,
  OpenClawSendSnapshot,
} from '../openclawContracts'
import { messageMergeId } from '../storage/openclawTranscriptStore'
import type { OpenClawChatDispatch, OpenClawLifecycleState } from './openclawChatReducer'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'

type TranscriptPort = {
  persist(update: OpenClawChatMessage[] | ((current: OpenClawChatMessage[]) => OpenClawChatMessage[])): OpenClawChatMessage[]
  resolveMedia(client: OpenClawClientPort, sessionKey: string, messages: OpenClawChatMessage[], force?: boolean): Promise<void>
}

function prepareOpenClawSend(
  request: OpenClawSendRequest,
  state: OpenClawLifecycleState,
): { snapshot: OpenClawSendSnapshot; message: OpenClawChatMessage } | null {
  const displayText = request.displayText.trim()
  const gatewayPrompt = request.gatewayPrompt.trim()
  const attachments = (request.attachments ?? []).slice(0, 4)
  const selectedModel = state.models.find((model) => model.id === state.runtimeSelection.modelId)
  if (!gatewayPrompt || (!displayText && !attachments.length)) return null
  if (attachments.length && (!state.imageInputAvailable || selectedModel?.supportsImages !== true)) return null
  const idempotencyKey = crypto.randomUUID()
  const contextItems = request.contextItems.map((item) => {
    const sourceUrl = sanitizeOpenClawSourceUrl(item.sourceUrl)
    return { ...item, sourceUrl: sourceUrl || undefined }
  })
  const snapshot: OpenClawSendSnapshot = {
    displayText, gatewayPrompt, contextItems,
    ...(request.contextCount !== undefined ? { contextCount: request.contextCount } : {}),
    ...(request.sourceSnapshot ? { sourceSnapshot: request.sourceSnapshot } : {}),
    idempotencyKey, modelId: state.runtimeSelection.modelId,
    thinkingLevel: state.runtimeSelection.thinkingLevel,
    ...(attachments.length ? { attachments } : {}),
  }
  const message: OpenClawChatMessage = {
    id: idempotencyKey, role: 'user', text: displayText, status: 'pending',
    contextCount: snapshot.contextCount ?? snapshot.contextItems.length,
    contextSources: openClawSourceReferences(snapshot.contextItems), sendSnapshot: snapshot,
    createdAt: Date.now(), origin: 'local', clientTurnId: idempotencyKey,
    ...(attachments.length ? { images: attachments.map((attachment, index) => ({
      id: `${idempotencyKey}:image:${index}`, alt: `你发送的第 ${index + 1} 张图片`,
      mimeType: attachment.mimeType, width: attachment.width, height: attachment.height, url: attachment.previewUrl,
    })) } : {}),
  }
  message.mergeId = messageMergeId(message)
  return { snapshot, message }
}

export function useOpenClawSendActions(input: {
  refs: OpenClawLifecycleRefs
  state: OpenClawLifecycleState
  dispatch: OpenClawChatDispatch
  transcript: TranscriptPort
  beginRunTrace(contextCount: number): void
  finishRunTrace(terminal: 'completed' | 'aborted' | 'failed', runId: string): void
  updateRunTrace(update: OpenClawRunTrace | null | ((current: OpenClawRunTrace | null) => OpenClawRunTrace | null)): void
  setModel(modelId: string | null): Promise<boolean>
}) {
  const submit = useCallback(async (snapshot: OpenClawSendSnapshot, messageId: string): Promise<boolean> => {
    const client = input.refs.connection.client
    const sessionKey = input.refs.session.sessionKey
    const agentId = input.refs.session.agentId
    if (!client || !sessionKey || !agentId || !snapshot.gatewayPrompt.trim() || input.refs.run.runId) return false
    const sendAttempt = ++input.refs.run.sendAttempt
    input.refs.run.terminalSendAttempts.delete(sendAttempt)
    input.beginRunTrace(snapshot.contextCount ?? snapshot.contextItems.length)
    input.refs.run.pendingSend = true
    input.refs.run.streamText = ''
    input.refs.run.streamCreatedAt = null
    input.dispatch({ type: 'patch', value: { streamText: '', streamCreatedAt: null, issue: null, sending: true } })
    try {
      const result = await client.request<{ runId?: string }>('chat.send', {
        sessionKey, agentId, message: snapshot.gatewayPrompt, deliver: false,
        idempotencyKey: snapshot.idempotencyKey,
        ...(snapshot.thinkingLevel ? { thinking: snapshot.thinkingLevel } : {}),
        ...(snapshot.attachments?.length ? { attachments: snapshot.attachments.map((attachment) => ({
          type: 'image', mimeType: attachment.mimeType, fileName: attachment.fileName, content: attachment.content,
        })) } : {}),
      })
      const terminatedBeforeResponse = input.refs.run.terminalSendAttempts.delete(sendAttempt)
      input.transcript.persist((current) => current.map((message) => (
        message.id === messageId ? { ...message, status: 'sent', sendSnapshot: undefined } : message
      )))
      if (sendAttempt !== input.refs.run.sendAttempt || terminatedBeforeResponse) return true
      input.refs.run.runId = input.refs.run.runId || result.runId || snapshot.idempotencyKey
      input.refs.run.pendingSend = false
      input.dispatch({ type: 'patch', value: { runId: input.refs.run.runId } })
      input.updateRunTrace((current) => current ? {
        ...current, runId: input.refs.run.runId, phase: current.phase === 'sending' ? 'waiting' : current.phase,
      } : current)
      return true
    } catch (error) {
      const terminated = input.refs.run.terminalSendAttempts.delete(sendAttempt)
      input.transcript.persist((current) => current.map((message) => message.id === messageId
        ? { ...message, status: terminated ? 'sent' : 'failed', ...(terminated ? { sendSnapshot: undefined } : {}) }
        : message))
      if (terminated) return true
      if (sendAttempt !== input.refs.run.sendAttempt) return false
      const failedRunId = input.refs.run.runId || snapshot.idempotencyKey
      input.refs.run.pendingSend = false
      input.refs.run.runId = null
      input.dispatch({ type: 'patch', value: { runId: null, issue: setupIssue(error) } })
      input.finishRunTrace('failed', failedRunId)
      return false
    } finally {
      if (sendAttempt === input.refs.run.sendAttempt) input.dispatch({ type: 'patch', value: { sending: false } })
    }
  }, [input])

  const send = useCallback(async (request: OpenClawSendRequest): Promise<boolean> => {
    if (input.refs.run.runId || input.state.sending) return false
    const prepared = prepareOpenClawSend(request, input.state)
    if (!prepared) return false
    const { snapshot, message } = prepared
    input.transcript.persist((current) => [...current, message])
    return submit(snapshot, message.id)
  }, [input, submit])

  const retry = useCallback(async (messageId: string): Promise<boolean> => {
    const message = input.refs.transcript.messages.find((candidate) => candidate.id === messageId)
    if (message?.status !== 'failed' || !message.sendSnapshot || input.refs.run.runId || input.state.sending) return false
    input.transcript.persist((current) => current.map((candidate) => candidate.id === messageId ? { ...candidate, status: 'pending' } : candidate))
    if (message.sendSnapshot.modelId && message.sendSnapshot.modelId !== input.state.runtimeSelection.modelId) {
      if (!await input.setModel(message.sendSnapshot.modelId)) {
        input.transcript.persist((current) => current.map((candidate) => candidate.id === messageId ? { ...candidate, status: 'failed' } : candidate))
        return false
      }
    }
    return submit(message.sendSnapshot, messageId)
  }, [input, submit])

  const takeFailedMessage = useCallback((messageId: string): OpenClawSendRequest | null => {
    const message = input.refs.transcript.messages.find((candidate) => candidate.id === messageId)
    if (message?.status !== 'failed' || !message.sendSnapshot) return null
    const { displayText, gatewayPrompt, contextCount, sourceSnapshot } = message.sendSnapshot
    const request = {
      displayText, gatewayPrompt,
      contextItems: message.sendSnapshot.contextItems.map((item) => ({ ...item })),
      ...(contextCount !== undefined ? { contextCount } : {}),
      ...(sourceSnapshot ? { sourceSnapshot } : {}),
    }
    input.transcript.persist((current) => current.filter((candidate) => candidate.id !== messageId))
    return request
  }, [input])

  const refreshMedia = useCallback(async (messageId: string, imageId: string) => {
    const client = input.refs.connection.client
    const sessionKey = input.refs.session.sessionKey
    const message = input.refs.transcript.messages.find((candidate) => candidate.id === messageId)
    const image = message?.images?.find((candidate) => candidate.id === imageId)
    if (client && sessionKey && message && image?.reference) {
      await input.transcript.resolveMedia(client, sessionKey, [{ ...message, images: [image] }], true)
    }
  }, [input])

  const stop = useCallback(async () => {
    const client = input.refs.connection.client
    const sessionKey = input.refs.session.sessionKey
    if (!client || !sessionKey || input.state.stopping) return
    input.dispatch({ type: 'patch', value: { stopping: true, issue: null } })
    input.updateRunTrace((current) => current ? { ...current, phase: 'stopping', status: 'running' } : current)
    try {
      await client.request('chat.abort', {
        sessionKey, agentId: input.refs.session.agentId || undefined, runId: input.refs.run.runId || undefined,
      })
    } catch (error) {
      input.dispatch({ type: 'patch', value: { stopping: false, issue: setupIssue(error) } })
      input.updateRunTrace((current) => current ? {
        ...current, phase: input.refs.run.streamText ? 'streaming' : 'waiting', status: 'running',
      } : current)
    }
  }, [input])

  return { send, retry, takeFailedMessage, refreshMedia, stop }
}
