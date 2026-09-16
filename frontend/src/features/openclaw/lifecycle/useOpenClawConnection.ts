import { canAutoConnectManaged, rememberManagedConnection, managedSession, saveManagedSession } from '../storage/openclawManagedSession'
/* eslint-disable react-hooks/exhaustive-deps, react-hooks/immutability -- lifecycle refs are imperative controller state */
import { useCallback, useEffect } from 'react'
import { useOpenClawPageLifecycle } from './openclawPageLifecycle'
import { isManagedGateway, managedGatewayUrl } from '../gateway/openclawManaged'

import { isMissingOpenClawSession, MissingOpenClawCredentialError, setupIssue } from '../chat/openclawSetupIssue'
import { openClawSessionPreviewParams, projectOpenClawSessionPreview } from '../chat/openclawSessionPreview'
import type { OpenClawCredentialVault } from '../openclawCredentialVault'
import type { OpenClawChatOptions, OpenClawClientPort } from '../openclawContracts'
import {
  OPENCLAW_CURRENT_SCOPES,
  GatewayRequestError,
  OpenClawGatewayClient,
  OpenClawSocketClosedError,
  generateDeviceIdentity,
  gatewaySupportsMethod,
  parseOpenClawConnectionInput,
  validateGatewayUrl,
  type GatewayEvent,
  type GatewayHello,
} from '../openclawGateway'
import { readSavedGatewayUrl, saveGatewayUrl } from '../storage/openclawGatewayPreferences'
import type { OpenClawChatDispatch, OpenClawLifecycleState } from './openclawChatReducer'
import { stopOpenClawRecovery, type OpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { restoredSessionAgent } from './openclawSessionIdentity'
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

async function loadConnectedSession(
  input: OpenClawConnectionInput,
  client: OpenClawClientPort,
  sessionKey: string,
  agentId: string,
): Promise<unknown> {
  input.session.bind(agentId, sessionKey)
  input.transcript.restoreLocal(input.getGatewayUrl(), sessionKey)
  const [tools] = await Promise.all([
    client.request('tools.effective', { sessionKey, agentId }),
    input.transcript.loadHistory(client, sessionKey, agentId),
    input.session.loadRuntime(client, sessionKey, agentId),
    input.session.loadContextUsage(client, sessionKey),
  ])
  return tools
}

function resetFailedSessionLoad(input: OpenClawConnectionInput): void {
  input.session.reset()
  input.resetConversation()
  input.transcript.reset()
}

function isTerminalConnectionError(error: unknown): boolean {
  if (error instanceof OpenClawSocketClosedError) return error.code === 1008
  return ['origin', 'pairing', 'auth', 'protocol', 'permission', 'session']
    .includes(setupIssue(error).kind)
}

function queueOpenClawReconnect(
  connection: OpenClawLifecycleRefs['connection'],
  dispatch: OpenClawChatDispatch,
): void {
  void import('./openclawConnectionRecovery').then(({ scheduleOpenClawReconnect }) => {
    scheduleOpenClawReconnect(connection, dispatch)
  })
}

async function activateManagedRecovery(
  input: OpenClawConnectionInput,
  client: OpenClawClientPort,
  hello: GatewayHello,
  isCurrent: () => boolean,
  managed: boolean,
): Promise<boolean> {
  stopOpenClawRecovery(input.refs.connection)
  const { markOpenClawConnectionStable } = await import('./openclawConnectionRecovery')
  if (!isCurrent()) return false
  if (managed) {
    const { startManagedRelayHeartbeat } = await import('./openclawRelayHeartbeat')
    if (!isCurrent()) return false
    input.refs.connection.heartbeatStop = startManagedRelayHeartbeat({
      client,
      hello,
      isCurrent,
      onFailure: () => {
        if (!isCurrent()) return
        stopOpenClawRecovery(input.refs.connection)
        client.close()
        input.refs.connection.client = null
        input.refs.connection.hello = null
        queueOpenClawReconnect(input.refs.connection, input.dispatch)
      },
    })
  }
  markOpenClawConnectionStable(input.refs.connection, input.dispatch, isCurrent)
  return true
}

function finishConnectionFailure(
  input: OpenClawConnectionInput,
  error: unknown,
  managed: boolean,
  reconnecting: boolean,
): void {
  const connection = input.refs.connection
  stopOpenClawRecovery(connection)
  connection.client?.close()
  connection.client = null
  connection.hello = null
  if (managed && !isTerminalConnectionError(error)) {
    queueOpenClawReconnect(connection, input.dispatch)
    return
  }
  connection.manualClose = true
  if (!reconnecting || !managed) {
    input.session.reset()
    input.resetConversation()
    input.transcript.reset()
  }
  input.dispatch({ type: 'patch', value: { status: 'error', issue: setupIssue(error) } })
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
  if (connection.reconnecting) return false
  connection.reconnecting = true
  const generation = ++connection.generation
  const isCurrent = (client?: OpenClawClientPort) => generation === connection.generation && (!client || connection.client === client)
  const managed = isManagedGateway(input.options.defaultGatewayUrl)
  const priorSessionKey = input.refs.session.sessionKey
  connection.manualClose = false
  input.dispatch({ type: 'patch', value: { status: reconnecting ? 'reconnecting' : 'connecting', issue: null } })
  try {
    const parsed = managed ? { gatewayUrl: managedGatewayUrl(), bootstrapToken: '' } : authInput
      ? parseOpenClawConnectionInput(requestedUrl ?? input.getGatewayUrl(), authInput)
      : { gatewayUrl: validateGatewayUrl(requestedUrl ?? input.getGatewayUrl()), bootstrapToken: '' }
    if (parsed.gatewayUrl !== input.getGatewayUrl()) setGatewayUrl(parsed.gatewayUrl)
    const stored = managed ? await managedSession(input.options.userId) : await input.vault.load(input.options.userId, parsed.gatewayUrl)
    if (!isCurrent()) return false
    if (!stored && !parsed.bootstrapToken) throw new MissingOpenClawCredentialError()
    const identity = stored?.identity ?? await generateDeviceIdentity()
    if (!isCurrent()) return false
    const factory = input.options.clientFactory ?? ((clientOptions) => new OpenClawGatewayClient(clientOptions))
    let handshakeComplete = false
    const client = factory({
      url: parsed.gatewayUrl,
      bootstrapToken: parsed.bootstrapToken || undefined,
      deviceToken: parsed.bootstrapToken ? undefined : stored?.deviceToken,
      deviceIdentity: identity,
      requestedScopes: parsed.bootstrapToken ? OPENCLAW_CURRENT_SCOPES : stored?.scopes ?? OPENCLAW_CURRENT_SCOPES,
      platform: navigator.platform || 'web',
      deviceFamily: 'browser',
      onEvent: (event) => input.routeEvent(event, generation),
      onClose: (event) => {
        if (connection.manualClose || generation !== connection.generation) return
        if (!handshakeComplete) return
        stopOpenClawRecovery(connection)
        connection.client = null
        connection.hello = null
        const closed = new OpenClawSocketClosedError(event)
        if (isTerminalConnectionError(closed)) {
          connection.manualClose = true
          input.dispatch({ type: 'patch', value: { status: 'error', issue: setupIssue(closed) } })
          return
        }
        queueOpenClawReconnect(connection, input.dispatch)
      },
    })
    connection.client?.close()
    connection.client = client
    const hello: GatewayHello = await client.connect()
    handshakeComplete = true
    if (!isCurrent(client)) {
      client.close()
      return false
    }
    connection.mediaTicketSupported = Boolean(
      input.options.imageIoEnabled
      && input.options.mediaOrigins?.length
      && gatewaySupportsMethod(hello, 'chat.media.ticket'),
    )
    connection.hello = hello
    input.dispatch({ type: 'patch', value: { imageInputAvailable: Boolean(input.options.imageIoEnabled) } })
    const deviceToken = hello.auth?.deviceToken || stored?.deviceToken
    if (!managed && !deviceToken) throw new Error('OpenClaw 没有返回浏览器设备 token。')
    const credential = { identity, deviceToken: deviceToken || '', scopes: hello.auth?.scopes ?? stored?.scopes ?? [] }
    if (!managed && !stored) {
      await input.vault.save(input.options.userId, parsed.gatewayUrl, credential, () => isCurrent(client))
      if (!isCurrent(client)) return false
    }
    let agentId = hello.snapshot?.sessionDefaults?.defaultAgentId
    if (!agentId) throw new Error('OpenClaw Gateway 没有返回默认 Agent。')
    let sessionKey = stored?.sessionKey ?? null
    if (sessionKey && gatewaySupportsMethod(hello, 'sessions.preview')) {
      try {
        const preview = await client.request('sessions.preview', openClawSessionPreviewParams(sessionKey))
        if (!isCurrent(client)) return false
        const previewStatus = projectOpenClawSessionPreview(preview, sessionKey)
        if (previewStatus === 'missing') {
          if (reconnecting && priorSessionKey) throw new GatewayRequestError({
            code: 'SESSION_NOT_FOUND', message: 'Stored session is no longer available',
          })
          sessionKey = null
        }
        else if (previewStatus === 'error') throw new Error('OpenClaw 暂时无法验证已保存会话。')
      } catch (error) {
        if (!isCurrent(client)) return false
        if (reconnecting && priorSessionKey && isMissingOpenClawSession(error)) throw error
        if (!isMissingOpenClawSession(error)) throw error
        sessionKey = null
      }
    }
    if (sessionKey) agentId = await restoredSessionAgent(client, sessionKey, agentId)
    if (!isCurrent(client)) return false
    let reusedStoredSession = sessionKey !== null && sessionKey === stored?.sessionKey
    if (!sessionKey) {
      sessionKey = await createOpenClawSession(client, { agentId })
      if (!isCurrent(client)) return false
      reusedStoredSession = false
    }
    if (!isCurrent(client)) return false
    let tools: unknown
    try {
      tools = await loadConnectedSession(input, client, sessionKey, agentId)
    } catch (error) {
      if (reconnecting && priorSessionKey && isMissingOpenClawSession(error)) throw error
      if (!reusedStoredSession || !isMissingOpenClawSession(error) || !isCurrent(client)) throw error
      resetFailedSessionLoad(input)
      sessionKey = await createOpenClawSession(client, { agentId })
      if (!isCurrent(client)) return false
      tools = await loadConnectedSession(input, client, sessionKey, agentId)
    }
    if (!isCurrent(client)) return false
    if (managed) saveManagedSession(input.options.userId, sessionKey)
    else await input.vault.save(input.options.userId, parsed.gatewayUrl, { ...credential, sessionKey }, () => isCurrent(client))
    if (!isCurrent(client)) return false
    const { hasInteliscopeTools } = await import('../chat/openclawToolAvailability')
    if (!isCurrent(client)) return false
    if (!await activateManagedRecovery(input, client, hello, () => isCurrent(client), managed)) return false
    input.dispatch({
      type: 'patch',
      value: {
        toolsStatus: hasInteliscopeTools(tools, agentId) ? 'available' : managed ? 'unknown' : 'missing',
        status: 'connected',
      },
    })
    return true
  } catch (error) {
    if (generation === connection.generation) {
      finishConnectionFailure(input, error, managed, reconnecting)
    }
    return false
  } finally {
    connection.reconnecting = false
  }
}

export function useOpenClawConnection(input: OpenClawConnectionInput): OpenClawConnectionController {
  const setGatewayUrl = useCallback((value: string) => {
    const normalized = validateGatewayUrl(value)
    input.setGatewayUrlRef(normalized)
    input.dispatch({ type: 'patch', value: { gatewayUrl: normalized } })
    saveGatewayUrl(input.options.userId, normalized)
  }, [input.dispatch, input.options.userId, input.setGatewayUrlRef])

  const pause = useCallback(() => {
    const connection = input.refs.connection
    connection.manualClose = true
    connection.generation += 1
    stopOpenClawRecovery(connection)
    connection.reconnecting = false
    connection.client?.close()
    connection.client = null
    connection.hello = null
    connection.mediaTicketSupported = false
    input.dispatch({ type: 'patch', value: {
      status: input.options.enabled ? 'idle' : 'disabled', imageInputAvailable: false,
    } })
  }, [input.dispatch, input.options.enabled, input.refs])

  const disconnect = useCallback(() => {
    const connection = input.refs.connection
    connection.manualClose = true
    connection.generation += 1
    stopOpenClawRecovery(connection)
    connection.client?.close()
    connection.client = null
    connection.reconnectAttempt = 0
    connection.reconnectDelay = 1_000
    connection.reconnecting = false
    connection.mediaTicketSupported = false
    connection.hello = null
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

  useOpenClawPageLifecycle(
    pause, disconnect, input.refs.connection,
    input.options.defaultGatewayUrl, input.options.enabled, input.options.userId,
  )

  useEffect(() => {
    const effectiveStatus = input.state.status === 'disabled' ? 'idle' : input.state.status
    if (!input.options.enabled || effectiveStatus !== 'idle') return
    const key = `${input.options.userId}\n${input.state.gatewayUrl}`
    if (input.refs.connection.automaticConnectKey === key) return
    let active = true
    void (isManagedGateway(input.state.gatewayUrl) ? (canAutoConnectManaged(input.options.userId) ? managedSession(input.options.userId) : Promise.resolve(null)) : input.vault.load(input.options.userId, input.state.gatewayUrl)).then((stored) => {
      if (active && stored && input.refs.connection.automaticConnectKey !== key) {
        input.refs.connection.automaticConnectKey = key
        void connectInternal(undefined, false, input.state.gatewayUrl)
      }
    }).catch(() => undefined)
    return () => { active = false }
  }, [input.options.enabled, input.options.userId, input.refs, input.state.gatewayUrl, input.state.status, input.vault])

  return {
    setGatewayUrl,
    connect: async (authInput?: string, requestedUrl?: string) => {
      const connected = await connectInternal(authInput, false, requestedUrl)
      if (connected && isManagedGateway(input.state.gatewayUrl)) rememberManagedConnection(input.options.userId)
      return connected
    },
    retryConnection,
    disconnect,
  }
}

export function initialOpenClawGatewayUrl(userId: string, defaultGatewayUrl: string): string {
  return isManagedGateway(defaultGatewayUrl) ? managedGatewayUrl() : readSavedGatewayUrl(userId, defaultGatewayUrl)
}
