import { openClawSessionPreviewParams, projectOpenClawSessionPreview } from '../chat/openclawSessionPreview'
import { projectWorkspaceSessions } from '../workspace/openclawWorkspaceProjection'
import type { OpenClawRuntimeProjection } from '../chat/openclawRuntimeProjection'
import { runtimeFailureMessage } from '../chat/openclawSetupIssue'
import type { OpenClawCredentialVault } from '../openclawCredentialVault'
import type { OpenClawChatMessage, OpenClawClientPort } from '../openclawContracts'
import { OPENCLAW_MAX_HISTORY_CHARS, OPENCLAW_MAX_MESSAGES, readOpenClawTranscript } from '../storage/openclawTranscriptStore'
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
    loadHistory(client: OpenClawClientPort, sessionKey: string, agentId: string, preparedHistory?: unknown): Promise<void>
  }
  resetConversation: () => void
  bind(agentId: string, sessionKey: string): void
  applyRuntime(projection: OpenClawRuntimeProjection): void
  loadContextUsage(client: OpenClawClientPort, sessionKey: string): Promise<void>
}

const navigating = new WeakSet<OpenClawLifecycleRefs>()

export async function openOpenClawSession(input: OpenSessionInput, sessionKey: string, requestedAgentId?: string): Promise<boolean> {
  const client = input.refs.connection.client
  let agentId = requestedAgentId ?? input.refs.session.agentId
  const targetKey = sessionKey.trim()
  if (navigating.has(input.refs) || !client || !agentId || !targetKey || input.refs.run.runId || input.state.sending || input.state.runtimeUpdating) return false
  if (targetKey === input.refs.session.sessionKey) return true
  navigating.add(input.refs)
  const epoch = ++input.refs.session.navigationEpoch
  const isCurrent = () => input.refs.session.navigationEpoch === epoch && input.refs.connection.client === client
  input.dispatch({ type: 'patch', value: { runtimeUpdating: true, runtimeIssue: null } })
  try {
    const preview = await client.request('sessions.preview', openClawSessionPreviewParams(targetKey))
    if (!isCurrent()) return false
    if (projectOpenClawSessionPreview(preview, targetKey) !== 'present') throw new Error('会话暂不可用。')
    const listed = projectWorkspaceSessions(await client.request('sessions.list', { search: targetKey, limit: 100, archived: 'all' }))
    if (!isCurrent()) return false
    const matches = listed.filter((session) => session.key === targetKey)
    if (matches.length !== 1) throw new Error('会话不在授权目录中。')
    const canonicalAgent = /^agent:([^:]+):/u.exec(targetKey)?.[1]
    const listedAgent = matches[0].agentId ?? canonicalAgent
    if ((requestedAgentId && listedAgent && requestedAgentId !== listedAgent) || (canonicalAgent && listedAgent !== canonicalAgent)) throw new Error('会话 Agent 不匹配。')
    agentId = listedAgent ?? agentId
    const projection = await readOpenClawRuntime(client, targetKey, agentId, true)
    if (!isCurrent()) return false
    const history = await client.request<{ messages?: unknown }>('chat.history', { sessionKey: targetKey, agentId, limit: OPENCLAW_MAX_MESSAGES, maxChars: OPENCLAW_MAX_HISTORY_CHARS })
    if (!isCurrent()) return false
    if (!Array.isArray(history?.messages)) throw new Error('会话历史暂不可用。')
    const gatewayUrl = input.getGatewayUrl()
    await input.vault.updateSession(input.userId, gatewayUrl, targetKey, isCurrent)
    if (!isCurrent()) return false
    input.resetConversation()
    input.bind(agentId, targetKey)
    input.applyRuntime(projection)
    input.transcript.replace(readOpenClawTranscript(input.userId, gatewayUrl, targetKey))
    await Promise.allSettled([
      input.transcript.loadHistory(client, targetKey, agentId, history),
      input.loadContextUsage(client, targetKey),
    ])
    return isCurrent()
  } catch (error) {
    if (isCurrent()) input.dispatch({ type: 'patch', value: { runtimeIssue: runtimeFailureMessage(error, 'load') } })
    return false
  } finally {
    navigating.delete(input.refs)
    if (isCurrent()) input.dispatch({ type: 'patch', value: { runtimeUpdating: false } })
  }
}
