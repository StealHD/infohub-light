import { useState } from 'react'
import { StableAsyncButton } from '../../design-system'
import type { AgentConnection } from '../../api/agentConnectionService'
import { useAgentConnectionContext } from './AgentConnectionContext'

export function MemberAccess({ state, refresh }: { state: AgentConnection; refresh: () => Promise<unknown> }) {
  const { api, userId } = useAgentConnectionContext()
  const [error, setError] = useState<{ owner: string; text: string } | null>(null)
  const request = state.access_request
  const active = request?.state === 'pending' || request?.state === 'approved' || (state.cleanup && state.cleanup.phase !== 'complete')
  const label = request?.state === 'rejected' ? '重新申请' : '申请接入'
  async function submit() {
    setError(null)
    try { await api.requestAgentAccess(); await refresh() }
    catch { setError({ owner: userId, text: '申请结果未确认，请刷新状态后再试。' }) }
  }
  if (state.can_connect) return null
  return <div className="grid gap-3 mt-3">
    {request?.state === 'pending' && <p role="status" className="type-body">等待管理员审核 · {new Date(request.created_at).toLocaleString()}</p>}
    {request?.state === 'approved' && !state.cleanup && <p role="status" className="type-body">{request.phase === 'failed' || request.phase === 'recovery'
      ? '管理员正在处理，无需重新申请。' : request.phase === 'waiting' ? '已允许，等待 Gateway 安全重载。' : '已允许，正在配置并验证个人 Agent。'}</p>}
    {request?.state === 'rejected' && <p className="type-body break-words">申请已拒绝：{request.reason}</p>}
    {state.can_request && !active && <StableAsyncButton className="w-fit" pending={false} pendingContent="提交中" onPress={submit}>{label}</StableAsyncButton>}
    {error?.owner === userId && <p role="alert" className="type-body">{error.text}</p>}
  </div>
}
