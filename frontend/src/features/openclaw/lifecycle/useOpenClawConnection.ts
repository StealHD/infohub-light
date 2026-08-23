/* eslint-disable react-hooks/exhaustive-deps, react-hooks/immutability -- lifecycle refs are imperative controller state */
import { useCallback, useEffect } from 'react'

import { hasInteliscopeTools, setupIssue } from '../chat/openclawSetupIssue'
import type { OpenClawCredentialVault } from '../openclawCredentialVault'
import type { OpenClawChatOptions, OpenClawClientPort } from '../openclawContracts'
import {
  OPENCLAW_CURRENT_SCOPES,
  OpenClawGatewayClient,
  generateDeviceIdentity,
  gatewaySupportsMethod,
  parseOpenClawConnectionInput,
  validateGatewayUrl,
  type GatewayEvent,
  type GatewayHello,
} from '../openclawGateway'
import { readSavedGatewayUrl, saveGatewayUrl } from '../storage/openclawGatewayPreferences'
import type { OpenClawChatDispatch, OpenClawLifecycleState } from './openclawChatReducer'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { createOpenClawSession } from './openclawSessionOperations'

type ConnectionSessionPort = {
  bind(agentId: string, sessionKey: string): void
  loadRuntime(client: OpenClawClientPort, sessionKey: string, agentId: string): Promise<unknown>
  loadContextUsage(client: OpenClawClientPort, sessionKey: string): Promise<void>
  reset(): void
}

type ConnectionTranscriptPort = {
  restoreLocal(gatewayUrl: string, sessionKey: string): void
  loadHistory(client: OpenClawClientPort, sessionKey: string, agentId: string): Promise<void>
  reset(): void
}

export type OpenClawConnectionController = {
  setGatewayUrl(value: string): void
  connect(authInput?: string, requestedUrl?: string): Promise<boolean>
  retryConnection(): void
  disconnect(): void
}

type OpenClawConnectionInput = {
  options: OpenClawChatOptions
  state: OpenClawLifecycleState
  refs: OpenClawLifecycleRefs
  dispatch: OpenClawChatDispatch
  vault: OpenClawCredentialVault
  routeEvent: (event: GatewayEvent, generation: number) => void
  session: ConnectionSessionPort
  transcript: ConnectionTranscriptPort
  resetConversation: () => void
  getGatewayUrl: () => string
  setGatewayUrlRef: (value: string) => void
}

async function performOpenClawConnect(
  input: OpenClawConnectionInput,
  setGatewayUrl: (value: string) => void,
  authInput?: string,
  reconnecting = false,
  requestedUrl?: string,
): Promise<boolean> {
  if (!input.options.enabled) return false
  const connection = input.refs.connection
  const generation = ++connection.generation
  connection.manualClose = false
  input.dispatch({ type: 'patch', value: { status: reconnecting ? 'reconnecting' : 'connecting', issue: null } })
  try {
    const parsed = authInput
      ? parseOpenClawConnectionInput(requestedUrl ?? input.getGatewayUrl(), authInput)
      : { gatewayUrl: validateGatewayUrl(requestedUrl ?? input.getGatewayUrl()), bootstrapToken: '' }
    if (parsed.gatewayUrl !== input.getGatewayUrl()) setGatewayUrl(parsed.gatewayUrl)
    const stored = await input.vault.load(input.options.userId, parsed.gatewayUrl)
    if (!stored && !parsed.bootstrapToken) throw new Error('请输入 OpenClaw Gateway token 完成首次配对。')
    const identity = stored?.identity ?? await generateDeviceIdentity()
    const factory = input.options.clientFactory ?? ((clientOptions) => new OpenClawGatewayClient(clientOptions))
    const client = factory({
      url: parsed.gatewayUrl,
      bootstrapToken: parsed.bootstrapToken || undefined,
      deviceToken: parsed.bootstrapToken ? undefined : stored?.deviceToken,
      deviceIdentity: identity,
      requestedScopes: parsed.bootstrapToken ? OPENCLAW_CURRENT_SCOPES : stored?.scopes ?? OPENCLAW_CURRENT_SCOPES,
      platform: navigator.platform || 'web',
      deviceFamily: 'browser',
      onEvent: (event) => input.routeEvent(event, generation),
      onClose: () => {
        if (connection.manualClose || generation !== connection.generation) return
        input.dispatch({ type: 'patch', value: { status: 'reconnecting' } })
        connection.reconnectAttempt += 1
        input.dispatch({ type: 'patch', value: { reconnectAttempt: connection.reconnectAttempt } })
        const delay = connection.reconnectDelay
        connection.reconnectDelay = Math.min(Math.round(delay * 1.7), 30_000)
        connection.reconnectTimer = window.setTimeout(() => {
          connection.reconnectTimer = null
          connection.reconnect(true)
        }, delay)
      },
    })
    connection.client?.close()
    connection.client = client
    const hello: GatewayHello = await client.connect()
    if (generation !== connection.generation) {
      client.close()
      return false
    }
    connection.mediaTicketSupported = Boolean(
      input.options.imageIoEnabled
      && input.options.mediaOrigins?.length
      && gatewaySupportsMethod(hello, 'chat.media.ticket'),
    )
    input.dispatch({ type: 'patch', value: { imageInputAvailable: Boolean(input.options.imageIoEnabled) } })
    const deviceToken = hello.auth?.deviceToken || stored?.deviceToken
    if (!deviceToken) throw new Error('OpenClaw 没有返回浏览器设备 token。')
    const credential = { identity, deviceToken, scopes: hello.auth?.scopes ?? stored?.scopes ?? [] }
    await input.vault.save(input.options.userId, parsed.gatewayUrl, { ...credential, sessionKey: stored?.sessionKey })
    const agentId = hello.snapshot?.sessionDefaults?.defaultAgentId
    if (!agentId) throw new Error('OpenClaw Gateway 没有返回默认 Agent。')
    const sessionKey = stored?.sessionKey ?? await createOpenClawSession(client, { agentId })
    if (!stored?.sessionKey) {
      await input.vault.save(input.options.userId, parsed.gatewayUrl, { ...credential, sessionKey })
    }
    input.session.bind(agentId, sessionKey)
    input.transcript.restoreLocal(parsed.gatewayUrl, sessionKey)
    const [tools] = await Promise.all([
      client.request('tools.effective', { sessionKey, agentId }),
      input.transcript.loadHistory(client, sessionKey, agentId),
      input.session.loadRuntime(client, sessionKey, agentId),
      input.session.loadContextUsage(client, sessionKey),
    ])
    if (generation !== connection.generation) return false
    connection.reconnectDelay = 1_000
    connection.reconnectAttempt = 0
    input.dispatch({
      type: 'patch',
      value: {
        toolsStatus: hasInteliscopeTools(tools) ? 'available' : 'missing',
        reconnectAttempt: 0,
        status: 'connected',
      },
    })
    return true
  } catch (error) {
    if (generation === connection.generation) {
      connection.client?.close()
      connection.client = null
      input.dispatch({ type: 'patch', value: { status: 'error', issue: setupIssue(error) } })
    }
    return false
  }
}

export function useOpenClawConnection(input: OpenClawConnectionInput): OpenClawConnectionController {
  const setGatewayUrl = useCallback((value: string) => {
    const normalized = validateGatewayUrl(value)
    input.setGatewayUrlRef(normalized)
    input.dispatch({ type: 'patch', value: { gatewayUrl: normalized } })
    saveGatewayUrl(input.options.userId, normalized)
  }, [input.dispatch, input.options.userId, input.setGatewayUrlRef])

  const disconnect = useCallback(() => {
    const connection = input.refs.connection
    connection.manualClose = true
    connection.generation += 1
    if (connection.reconnectTimer !== null) window.clearTimeout(connection.reconnectTimer)
    connection.reconnectTimer = null
    connection.client?.close()
    connection.client = null
    connection.reconnectAttempt = 0
    connection.reconnectDelay = 1_000
    connection.mediaTicketSupported = false
    input.session.reset()
    input.resetConversation()
    input.transcript.reset()
    input.dispatch({
      type: 'patch',
      value: {
        status: input.options.enabled ? 'idle' : 'disabled',
        toolsStatus: 'unknown', reconnectAttempt: 0, imageInputAvailable: false, issue: null,
      },
    })
  }, [
    input.dispatch,
    input.options.enabled,
    input.refs,
    input.resetConversation,
    input.session.reset,
    input.transcript.reset,
  ])

  const connectInternal = useCallback(async (
    authInput?: string,
    reconnecting = false,
    requestedUrl?: string,
  ): Promise<boolean> => performOpenClawConnect(input, setGatewayUrl, authInput, reconnecting, requestedUrl), [input, setGatewayUrl])

  useEffect(() => {
    input.refs.connection.reconnect = (reconnecting = true) => { void connectInternal(undefined, reconnecting) }
  }, [connectInternal, input.refs])

  const retryConnection = useCallback(() => {
    const connection = input.refs.connection
    if (connection.reconnectTimer !== null) window.clearTimeout(connection.reconnectTimer)
    connection.reconnectTimer = null
    connection.reconnect(true)
  }, [input.refs])

  useEffect(() => {
    input.refs.connection.automaticConnectKey = null
  }, [input.refs, input.state.gatewayUrl])

  useEffect(() => {
    return disconnect
  }, [disconnect, input.options.defaultGatewayUrl, input.options.enabled, input.options.userId])

  useEffect(() => {
    const effectiveStatus = input.state.status === 'disabled' ? 'idle' : input.state.status
    if (!input.options.enabled || effectiveStatus !== 'idle') return
    const key = `${input.options.userId}\n${input.state.gatewayUrl}`
    if (input.refs.connection.automaticConnectKey === key) return
    input.refs.connection.automaticConnectKey = key
    let active = true
    void input.vault.load(input.options.userId, input.state.gatewayUrl).then((stored) => {
      if (active && stored) void connectInternal(undefined, false, input.state.gatewayUrl)
    }).catch(() => undefined)
    return () => { active = false }
  }, [connectInternal, input.options.enabled, input.options.userId, input.refs, input.state.gatewayUrl, input.state.status, input.vault])

  return {
    setGatewayUrl,
    connect: (authInput?: string, requestedUrl?: string) => connectInternal(authInput, false, requestedUrl),
    retryConnection,
    disconnect,
  }
}

export function initialOpenClawGatewayUrl(userId: string, defaultGatewayUrl: string): string {
  return readSavedGatewayUrl(userId, defaultGatewayUrl)
}
