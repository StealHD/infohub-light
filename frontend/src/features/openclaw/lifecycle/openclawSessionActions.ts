/* eslint-disable react-hooks/immutability -- lifecycle refs are imperative controller state */
import { useCallback } from 'react'

import { runtimeFailureMessage } from '../chat/openclawSetupIssue'
import type { OpenClawClientPort } from '../openclawContracts'
import type { OpenClawRuntimeProjection } from '../chat/openclawRuntimeProjection'
import type { OpenClawChatDispatch, OpenClawLifecycleState } from './openclawChatReducer'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { createOpenClawSession, readOpenClawRuntime } from './openclawSessionOperations'

export function useOpenClawSessionActions(input: {
  refs: OpenClawLifecycleRefs
  state: OpenClawLifecycleState
  dispatch: OpenClawChatDispatch
  activateSession(
    client: OpenClawClientPort,
    sessionKey: string,
    agentId: string,
    projection: OpenClawRuntimeProjection,
    clearMessages: boolean,
    preserveThinking?: boolean,
    isCurrent?: () => boolean,
  ): Promise<void>
  archiveFailedSession(client: OpenClawClientPort, sessionKey: string, agentId: string): Promise<void>
}) {
  const setModel = useCallback(async (modelId: string | null): Promise<boolean> => {
    const client = input.refs.connection.client
    const parentSessionKey = input.refs.session.sessionKey
    const agentId = input.refs.session.agentId
    const targetModelId = modelId ?? input.state.runtimeSelection.defaultModelId
    const selected = input.state.models.find((model) => model.id === targetModelId)
    if (!client || !parentSessionKey || !agentId || !selected || input.refs.run.runId || input.state.sending || input.state.runtimeUpdating) return false
    if (input.state.runtimeSelection.modelId === selected.id) return true
    input.dispatch({ type: 'patch', value: { runtimeUpdating: true, runtimeIssue: null, modelSwitchFallback: null } })
    const epoch = ++input.refs.session.navigationEpoch
    const isCurrent = () => input.refs.session.navigationEpoch === epoch && input.refs.connection.client === client
    let createdKey: string | null = null
    try {
      createdKey = await createOpenClawSession(client, { agentId, parentSessionKey, fork: true, model: selected.id })
      if (!isCurrent()) return false
      const projection = await readOpenClawRuntime(client, createdKey, agentId)
      if (!isCurrent()) return false
      if (projection.invalidSessionModel || projection.selection.modelId !== selected.id) {
        throw new Error('OpenClaw 返回的实际模型与选择不一致。')
      }
      await input.activateSession(client, createdKey, agentId, projection, false, true, isCurrent)
      if (!isCurrent()) return false
      return true
    } catch (error) {
      if (createdKey && isCurrent()) await input.archiveFailedSession(client, createdKey, agentId)
      if (isCurrent()) input.dispatch({
        type: 'patch',
        value: {
          runtimeIssue: `${runtimeFailureMessage(error, 'switch')} 可新建空白对话并切换到 ${selected.name}。`,
          modelSwitchFallback: { modelId: selected.id, modelName: selected.name },
        },
      })
      return false
    } finally {
      if (isCurrent()) input.dispatch({ type: 'patch', value: { runtimeUpdating: false } })
    }
  }, [input])

  const setThinking = useCallback(async (thinkingLevel: string | null): Promise<boolean> => {
    const currentModel = input.state.models.find((model) => model.id === input.state.runtimeSelection.modelId)
    if (!input.refs.connection.client || !input.refs.session.sessionKey || !input.refs.session.agentId || input.refs.run.runId || input.state.sending || input.state.runtimeUpdating) return false
    if (currentModel?.reasoning === false && thinkingLevel !== null) return false
    if (thinkingLevel !== null && !input.state.thinkingOptions.some((option) => option.id === thinkingLevel)) return false
    input.refs.session.thinkingLevel = thinkingLevel
    input.dispatch({ type: 'patch', value: { runtimeSelection: { ...input.state.runtimeSelection, thinkingLevel }, runtimeIssue: null } })
    return true
  }, [input])

  const setFastMode = useCallback(async (enabled: boolean): Promise<boolean> => {
    if (!input.refs.connection.client || !input.refs.session.sessionKey || !input.state.runtimeSelection.modelId
      || input.refs.run.runId || input.refs.run.pendingSend || input.state.sending || input.state.runtimeUpdating || input.state.runtimeLoading) return false
    input.refs.session.fastMode = enabled
    input.dispatch({ type: 'patch', value: { runtimeSelection: { ...input.state.runtimeSelection, fastMode: enabled }, runtimeIssue: null } })
    return true
  }, [input])

  const createBlankConversation = useCallback(async (modelId?: string): Promise<boolean> => {
    const client = input.refs.connection.client
    const agentId = input.refs.session.agentId
    if (!client || !agentId || input.refs.run.runId || input.state.sending || input.state.runtimeUpdating) return false
    input.dispatch({ type: 'patch', value: { runtimeUpdating: true, runtimeIssue: null } })
    const epoch = ++input.refs.session.navigationEpoch
    const isCurrent = () => input.refs.session.navigationEpoch === epoch && input.refs.connection.client === client
    let createdKey: string | null = null
    try {
      createdKey = await createOpenClawSession(client, { agentId, ...(modelId ? { model: modelId } : {}) })
      if (!isCurrent()) return false
      const projection = await readOpenClawRuntime(client, createdKey, agentId)
      if (!isCurrent()) return false
      if (modelId && (projection.invalidSessionModel || projection.selection.modelId !== modelId)) {
        throw new Error('OpenClaw 返回的实际模型与选择不一致。')
      }
      await input.activateSession(client, createdKey, agentId, projection, true, false, isCurrent)
      if (!isCurrent()) return false
      return true
    } catch (error) {
      if (createdKey && modelId && isCurrent()) await input.archiveFailedSession(client, createdKey, agentId)
      if (isCurrent()) input.dispatch({
        type: 'patch',
        value: { runtimeIssue: modelId ? `${runtimeFailureMessage(error, 'switch')} 原对话仍然可用。` : runtimeFailureMessage(error, 'switch') },
      })
      return false
    } finally {
      if (isCurrent()) input.dispatch({ type: 'patch', value: { runtimeUpdating: false } })
    }
  }, [input])

  const switchToBlankConversation = useCallback(async () => {
    const fallback = input.state.modelSwitchFallback
    return fallback ? createBlankConversation(fallback.modelId) : false
  }, [createBlankConversation, input.state.modelSwitchFallback])
  const newConversation = useCallback(() => createBlankConversation(), [createBlankConversation])

  return { setModel, setThinking, setFastMode, switchToBlankConversation, newConversation }
}
