/* eslint-disable react-hooks/exhaustive-deps, react-hooks/immutability -- lifecycle refs are imperative controller state */
import { useCallback } from 'react'

import {
  contextUsagePayloadMatchesSession,
  projectOpenClawContextUsage,
  type OpenClawRuntimeProjection,
} from '../chat/openclawRuntimeProjection'
import { runtimeFailureMessage } from '../chat/openclawSetupIssue'
import type { OpenClawCredentialVault } from '../openclawCredentialVault'
import type { OpenClawChatMessage, OpenClawClientPort } from '../openclawContracts'
import {
  clearOpenClawTranscript,
  mergeOpenClawTranscript,
  readOpenClawTranscript,
  writeOpenClawTranscript,
} from '../storage/openclawTranscriptStore'
import type { OpenClawChatDispatch, OpenClawLifecycleState } from './openclawChatReducer'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { useOpenClawSessionActions } from './openclawSessionActions'
import { readOpenClawRuntime } from './openclawSessionOperations'

type RuntimeTranscriptPort = {
  replace(messages: OpenClawChatMessage[]): void
  persist(
    update: OpenClawChatMessage[] | ((current: OpenClawChatMessage[]) => OpenClawChatMessage[]),
    keyOverride?: string,
  ): OpenClawChatMessage[]
  loadHistory(client: OpenClawClientPort, sessionKey: string, agentId: string): Promise<void>
}

export type OpenClawSessionRuntimeController = {
  bind(agentId: string, sessionKey: string): void
  loadRuntime(client: OpenClawClientPort, sessionKey: string, agentId: string, preserveThinking?: boolean): Promise<OpenClawRuntimeProjection | null>
  reloadRuntime(client: OpenClawClientPort, sessionKey: string, agentId: string): void
  loadContextUsage(client: OpenClawClientPort, sessionKey: string): Promise<void>
  routeContextUsage(payload: unknown, sessionKey: string): void
  setModel(modelId: string | null): Promise<boolean>
  setThinking(thinkingLevel: string | null): Promise<boolean>
  switchToBlankConversation(): Promise<boolean>
  newConversation(): Promise<boolean>
  reset(): void
}

function resetSessionRuntime(refs: OpenClawLifecycleRefs, dispatch: OpenClawChatDispatch): void {
  refs.session.agentId = null
  refs.session.sessionKey = null
  refs.session.thinkingLevel = null
  dispatch({
    type: 'patch',
    value: {
      sessionKey: null, models: [], thinkingOptions: [],
      runtimeSelection: { modelId: null, thinkingLevel: null, defaultModelId: null, defaultThinkingLevel: null },
      runtimeLoading: false, runtimeUpdating: false, runtimeIssue: null, modelSwitchFallback: null, contextUsage: null,
    },
  })
}

export function useOpenClawSessionRuntime(input: {
  userId: string
  refs: OpenClawLifecycleRefs
  state: OpenClawLifecycleState
  dispatch: OpenClawChatDispatch
  vault: OpenClawCredentialVault
  getGatewayUrl: () => string
  transcript: RuntimeTranscriptPort
  resetConversation: () => void
}): OpenClawSessionRuntimeController {
  const bind = useCallback((agentId: string, sessionKey: string) => {
    input.refs.session.agentId = agentId
    input.refs.session.sessionKey = sessionKey
    input.refs.transcript.readySessionKey = sessionKey
    input.dispatch({ type: 'patch', value: { sessionKey } })
  }, [input.dispatch, input.refs])

  const applyRuntime = useCallback((projection: OpenClawRuntimeProjection, preserveThinking = false) => {
    const selectedModel = projection.models.find((model) => model.id === projection.selection.modelId)
    const preservedThinking = preserveThinking
      && selectedModel?.reasoning !== false
      && input.refs.session.thinkingLevel
      && projection.thinkingOptions.some((option) => option.id === input.refs.session.thinkingLevel)
        ? input.refs.session.thinkingLevel
        : projection.selection.thinkingLevel
    const runtimeSelection = { ...projection.selection, thinkingLevel: preservedThinking }
    input.refs.session.thinkingLevel = runtimeSelection.thinkingLevel
    const fallbackModel = projection.invalidSessionModel && projection.selection.defaultModelId
      ? projection.models.find((model) => model.id === projection.selection.defaultModelId)
      : null
    input.dispatch({
      type: 'patch',
      value: {
        models: projection.models,
        thinkingOptions: projection.thinkingOptions,
        runtimeSelection,
        runtimeIssue: fallbackModel ? '当前对话模型已不可用，可切换到 OpenClaw 默认模型。' : input.state.runtimeIssue,
        modelSwitchFallback: fallbackModel ? { modelId: fallbackModel.id, modelName: fallbackModel.name } : null,
      },
    })
  }, [input.dispatch, input.refs, input.state.runtimeIssue])

  const loadRuntime = useCallback(async (
    client: OpenClawClientPort,
    sessionKey: string,
    agentId: string,
    preserveThinking = false,
  ): Promise<OpenClawRuntimeProjection | null> => {
    input.dispatch({ type: 'patch', value: { runtimeLoading: true, runtimeIssue: null } })
    try {
      const projection = await readOpenClawRuntime(client, sessionKey, agentId)
      if (input.refs.session.sessionKey !== sessionKey) return null
      applyRuntime(projection, preserveThinking)
      return projection
    } catch (error) {
      input.dispatch({ type: 'patch', value: { runtimeIssue: runtimeFailureMessage(error, 'load') } })
      return null
    } finally {
      input.dispatch({ type: 'patch', value: { runtimeLoading: false } })
    }
  }, [applyRuntime, input.dispatch, input.refs])

  const reloadRuntime = useCallback((client: OpenClawClientPort, sessionKey: string, agentId: string) => {
    void loadRuntime(client, sessionKey, agentId, true)
  }, [loadRuntime])

  const loadContextUsage = useCallback(async (client: OpenClawClientPort, sessionKey: string) => {
    if (input.refs.session.sessionKey === sessionKey) input.dispatch({ type: 'patch', value: { contextUsage: null } })
    const [, listResult] = await Promise.allSettled([
      client.request('sessions.subscribe', {}),
      client.request('sessions.list', { search: sessionKey, limit: 100 }),
    ])
    if (input.refs.session.sessionKey !== sessionKey || listResult.status !== 'fulfilled') return
    input.dispatch({ type: 'patch', value: { contextUsage: projectOpenClawContextUsage(listResult.value, sessionKey) } })
  }, [input.dispatch, input.refs])

  const routeContextUsage = useCallback((payload: unknown, sessionKey: string) => {
    if (!contextUsagePayloadMatchesSession(payload, sessionKey)) return
    input.dispatch({ type: 'patch', value: { contextUsage: projectOpenClawContextUsage(payload, sessionKey) } })
  }, [input.dispatch])

  const activateSession = useCallback(async (
    client: OpenClawClientPort,
    sessionKey: string,
    agentId: string,
    projection: OpenClawRuntimeProjection,
    clearMessages: boolean,
    preserveThinking = false,
  ) => {
    const gatewayUrl = input.getGatewayUrl()
    const previousKey = input.refs.session.sessionKey
    const visibleMessages = input.refs.transcript.messages
    await input.vault.updateSession(input.userId, gatewayUrl, sessionKey)
    if (clearMessages) {
      if (previousKey) clearOpenClawTranscript(input.userId, gatewayUrl, previousKey)
      clearOpenClawTranscript(input.userId, gatewayUrl, sessionKey)
    } else {
      writeOpenClawTranscript(input.userId, gatewayUrl, sessionKey, visibleMessages)
    }
    bind(agentId, sessionKey)
    input.resetConversation()
    applyRuntime(clearMessages
      ? { ...projection, selection: { ...projection.selection, thinkingLevel: null } }
      : projection, preserveThinking)
    input.dispatch({ type: 'patch', value: { modelSwitchFallback: null, runtimeIssue: null } })
    void loadContextUsage(client, sessionKey)
    if (clearMessages) {
      input.transcript.replace([])
      return
    }
    input.transcript.persist((current) => mergeOpenClawTranscript(
      readOpenClawTranscript(input.userId, gatewayUrl, sessionKey), current,
    ), sessionKey)
    try {
      await input.transcript.loadHistory(client, sessionKey, agentId)
    } catch {
      // A fork preserves the visible local history even if the first history refresh is delayed.
    }
  }, [applyRuntime, bind, input, loadContextUsage])

  const archiveFailedSession = useCallback(async (client: OpenClawClientPort, sessionKey: string, agentId: string) => {
    try {
      await client.request('sessions.patch', { key: sessionKey, agentId, archived: true })
    } catch {
      // Best-effort cleanup must never replace the original working conversation.
    }
  }, [])

  const actions = useOpenClawSessionActions({
    refs: input.refs,
    state: input.state,
    dispatch: input.dispatch,
    activateSession,
    archiveFailedSession,
  })

  const reset = useCallback(() => {
    resetSessionRuntime(input.refs, input.dispatch)
  }, [input.dispatch, input.refs])

  return {
    bind, loadRuntime, reloadRuntime, loadContextUsage, routeContextUsage,
    ...actions, reset,
  }
}
