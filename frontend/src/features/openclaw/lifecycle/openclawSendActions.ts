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
import { OpenClawSkillValidationError } from '../chat/openclawSkillSelection'
import { validateOpenClawSkill } from './validateOpenClawSkill'
import { readOpenClawRuntime } from './openclawSessionOperations'
import { acquireRuntime, RuntimeSelectionError, validateSendSelection } from './openclawRuntimeGuard'

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
    ...(request.selectedSkill ? { selectedSkill: { ...request.selectedSkill } } : {}),
    ...(request.contextCount !== undefined ? { contextCount: request.contextCount } : {}),
    ...(request.sourceSnapshot ? { sourceSnapshot: request.sourceSnapshot } : {}),
    idempotencyKey, modelId: state.runtimeSelection.modelId,
    thinkingLevel: state.runtimeSelection.thinkingLevel,
    ...(typeof state.runtimeSelection.fastMode === 'boolean' ? { fastMode: state.runtimeSelection.fastMode } : {}),
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
    const generation = input.refs.connection.generation
    const currentScope = () => input.refs.connection.client === client && input.refs.connection.generation === generation && input.refs.session.sessionKey === sessionKey && input.refs.session.agentId === agentId
    if (!client || !sessionKey || !agentId || !snapshot.gatewayPrompt.trim() || input.refs.run.runId || input.refs.run.pendingSend) return false
    const release = acquireRuntime(input.refs)
    if (!release) return false
    const sendAttempt = ++input.refs.run.sendAttempt
    input.refs.run.terminalSendAttempts.delete(sendAttempt)
    input.beginRunTrace(snapshot.contextCount ?? snapshot.contextItems.length)
    input.refs.run.pendingSend = true
    input.refs.run.streamText = ''
    input.refs.run.streamCreatedAt = null
    input.dispatch({ type: 'patch', value: { streamText: '', streamCreatedAt: null, issue: null, sending: true } })
    try {
      const projection = await readOpenClawRuntime(client, sessionKey, agentId, true)
      if (!currentScope()) return false
      if (projection.selection.modelSafety === 'unsafe_fork') {
        input.dispatch({ type: 'patch', value: { runtimeSelection: { ...input.state.runtimeSelection, modelSafety: 'unsafe_fork' },
          modelSwitchFallback: null } })
      }
      const thinking = validateSendSelection(snapshot, projection)
      if (snapshot.selectedSkill) {
        await validateOpenClawSkill(input.refs, snapshot, input.state.gatewayUrl)
      }
      if (!currentScope() || sendAttempt !== input.refs.run.sendAttempt) return false
      const result = await client.request<{ runId?: string }>('chat.send', {
        sessionKey, agentId, message: snapshot.gatewayPrompt, deliver: false,
        idempotencyKey: snapshot.idempotencyKey,
        ...(thinking ? { thinking } : {}),
        ...(typeof snapshot.fastMode === 'boolean' ? { fastMode: snapshot.fastMode } : {}),
        ...(snapshot.attachments?.length ? { attachments: snapshot.attachments.map((attachment) => ({
          type: 'image', mimeType: attachment.mimeType, fileName: attachment.fileName, content: attachment.content,
        })) } : {}),
      })
      if (!currentScope()) return false
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
      if (!currentScope()) return false
      const terminated = input.refs.run.terminalSendAttempts.delete(sendAttempt)
      input.transcript.persist((current) => current.map((message) => message.id === messageId
        ? { ...message, status: terminated ? 'sent' : 'failed', ...(terminated ? { sendSnapshot: undefined } : {}) }
        : message))
      if (terminated) return true
      if (sendAttempt !== input.refs.run.sendAttempt) return false
      const failedRunId = input.refs.run.runId || snapshot.idempotencyKey
      input.refs.run.pendingSend = false
      input.refs.run.runId = null
      input.dispatch({ type: 'patch', value: { runId: null, issue: error instanceof OpenClawSkillValidationError
        ? { kind: 'unknown', message: '无法确认本次 Skill 仍可调用。草稿已保留，请移除 Skill 或重试。' } : error instanceof RuntimeSelectionError ? { kind: 'unknown', message: error.message } : setupIssue(error) } })
      input.finishRunTrace('failed', failedRunId)
      return false
    } finally {
      release()
      if (currentScope() && sendAttempt === input.refs.run.sendAttempt) input.dispatch({ type: 'patch', value: { sending: false } })
    }
  }, [input])

  const send = useCallback(async (request: OpenClawSendRequest): Promise<boolean> => {
    if (input.refs.session.operation || input.state.runtimeLoading || input.state.runtimeUpdating || input.refs.run.runId || input.refs.run.pendingSend || input.state.sending) return false
    const prepared = prepareOpenClawSend(request, input.state)
    if (!prepared) return false
    const { snapshot, message } = prepared
    input.transcript.persist((current) => [...current, message])
    return submit(snapshot, message.id)
  }, [input, submit])

  const retry = useCallback(async (messageId: string): Promise<boolean> => {
    const message = input.refs.transcript.messages.find((candidate) => candidate.id === messageId)
    if (message?.status !== 'failed' || !message.sendSnapshot || input.refs.session.operation || input.state.runtimeLoading || input.state.runtimeUpdating || input.refs.run.runId || input.refs.run.pendingSend || input.state.sending) return false
    input.transcript.persist((current) => current.map((candidate) => candidate.id === messageId ? { ...candidate, status: 'pending' } : candidate))
    if (message.sendSnapshot.modelId && message.sendSnapshot.modelId !== input.state.runtimeSelection.modelId) {
      input.transcript.persist((current) => current.map((candidate) => candidate.id === messageId ? { ...candidate, status: 'failed' } : candidate))
      input.dispatch({ type: 'patch', value: { issue: { kind: 'unknown', message: '原请求模型与当前选择不同。请编辑失败消息后重新发送。' } } })
      return false
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
      ...(message.sendSnapshot.selectedSkill ? { selectedSkill: message.sendSnapshot.selectedSkill } : {}),
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
