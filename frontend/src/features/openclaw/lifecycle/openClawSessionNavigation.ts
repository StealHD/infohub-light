import type { OpenClawRuntimeProjection } from '../chat/openclawRuntimeProjection'
import { runtimeFailureMessage } from '../chat/openclawSetupIssue'
import type { OpenClawCredentialVault } from '../openclawCredentialVault'
import type { OpenClawChatMessage, OpenClawClientPort } from '../openclawContracts'
import { readOpenClawTranscript } from '../storage/openclawTranscriptStore'
import type { OpenClawChatDispatch, OpenClawLifecycleState } from './openclawChatReducer'
import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { readOpenClawRuntime } from './openclawSessionOperations'

type OpenSessionInput = {
  userId: string
  refs: OpenClawLifecycleRefs
  state: OpenClawLifecycleState
  dispatch: OpenClawChatDispatch
  vault: OpenClawCredentialVault
  getGatewayUrl: () => string
  transcript: {
    replace(messages: OpenClawChatMessage[]): void
    loadHistory(client: OpenClawClientPort, sessionKey: string, agentId: string): Promise<void>
  }
  resetConversation: () => void
  bind(agentId: string, sessionKey: string): void
  applyRuntime(projection: OpenClawRuntimeProjection): void
  loadContextUsage(client: OpenClawClientPort, sessionKey: string): Promise<void>
}

export async function openOpenClawSession(input: OpenSessionInput, sessionKey: string): Promise<boolean> {
  const client = input.refs.connection.client
  const agentId = input.refs.session.agentId
  const targetKey = sessionKey.trim()
  if (!client || !agentId || !targetKey || input.refs.run.runId || input.state.sending || input.state.runtimeUpdating) return false
  if (targetKey === input.refs.session.sessionKey) return true
  const epoch = ++input.refs.session.navigationEpoch
  const isCurrent = () => input.refs.session.navigationEpoch === epoch && input.refs.connection.client === client
  input.dispatch({ type: 'patch', value: { runtimeUpdating: true, runtimeIssue: null } })
  try {
    const projection = await readOpenClawRuntime(client, targetKey, agentId)
    if (!isCurrent()) return false
    const gatewayUrl = input.getGatewayUrl()
    await input.vault.updateSession(input.userId, gatewayUrl, targetKey, isCurrent)
    if (!isCurrent()) return false
    input.resetConversation()
    input.bind(agentId, targetKey)
    input.applyRuntime(projection)
    input.transcript.replace(readOpenClawTranscript(input.userId, gatewayUrl, targetKey))
    await Promise.allSettled([
      input.transcript.loadHistory(client, targetKey, agentId),
      input.loadContextUsage(client, targetKey),
    ])
    return isCurrent()
  } catch (error) {
    if (isCurrent()) input.dispatch({ type: 'patch', value: { runtimeIssue: runtimeFailureMessage(error, 'load') } })
    return false
  } finally {
    if (isCurrent()) input.dispatch({ type: 'patch', value: { runtimeUpdating: false } })
  }
}
