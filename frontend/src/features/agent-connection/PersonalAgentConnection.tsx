import { useLayoutEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { queryKeys } from '../../api/queryKeys'
import { useAgentConnectionContext } from './AgentConnectionContext'
import { Card, RefreshButton, StableAsyncButton } from '../../design-system'
import type { OpenClawChatController } from '../openclaw/openclawContracts'
import { DisconnectAgent } from './DisconnectAgent'
import { MemberAccess } from './MemberAccess'
import { cleanupLabel } from './cleanupLabel'

const phases: Record<string, string> = { checking: '正在检查环境', preparing: '正在准备个人接入',
  configuring: '正在配置 OpenClaw', verifying: '正在验证连接与数据授权' }

export function PersonalAgentConnection({ chat }: { chat?: OpenClawChatController }) {
  const { api, userId } = useAgentConnectionContext()
  const identity = useRef(userId)
  useLayoutEffect(() => { identity.current = userId }, [userId])
  const [request, setRequest] = useState<{ userId: string; pending: boolean; label?: string; error?: string } | null>(null)
  const query = useQuery({ queryKey: queryKeys.agentConnection(userId),
    queryFn: ({ signal }) => api.agentConnection(signal), refetchOnWindowFocus: true,
    refetchInterval: (item) => (item.state.data?.cleanup && item.state.data.cleanup.phase !== 'complete') || item.state.data?.setup?.state === 'running' || ['pending', 'approved'].includes(item.state.data?.access_request?.state || '') ? 2000 : false })
  const state = query.data
  const own = request?.userId === userId ? request : null
  const busy = own?.pending || state?.setup?.state === 'running'
  const canSetup = state?.can_manage_setup && (!state.cleanup || state.cleanup.phase === 'complete') && ['unconfigured', 'pending_verification', 'revoked'].includes(state.state)
  const error = own?.error || (state?.setup?.state === 'failed' ? state.setup.error : null)
  const label = busy ? own?.label || '接入 Agent'
    : state?.state === 'revoked' ? '重新接入' : state?.setup?.state === 'failed' || state?.state === 'pending_verification' ? '重试接入' : '接入 Agent'

  async function setup() {
    const owner = userId
    setRequest({ userId: owner, pending: true, label })
    try {
      if (state?.state === 'revoked') await api.reconnectManagedAgentConnection()
      else await api.setupManagedAgentConnection()
      if (identity.current === owner) await query.refetch()
    } catch {
      if (identity.current === owner) setRequest({ userId: owner, pending: false,
        error: '接入请求未确认。请刷新状态后重试，系统会先核对原绑定。' })
      return
    }
    if (identity.current === owner) setRequest({ userId: owner, pending: false, label })
  }

  return <Card variant="secondary" className="p-4" aria-busy={Boolean(busy || query.isFetching)}>
    <Card.Title render={(props) => <h2 {...props} />}>我的 Agent</Card.Title>
    <Card.Description>{state?.cleanup ? cleanupLabel(state.cleanup.phase) : busy ? phases[state?.setup?.phase || 'checking'] : state?.can_connect
      ? '个人 Agent 已接入。其他浏览器登录同一账号即可使用，无需重复配置。'
      : state?.state === 'revoked' ? '个人接入已解除。主动重新接入将创建新 Agent 和新授权；旧 Agent 与历史数据保留，不迁移旧会话。'
        : state?.state === 'invalid' ? '个人接入已失效，请管理员检查；系统不会自动重建授权。'
        : state?.can_manage_setup ? '由系统自动完成个人配置和验证，无需下载文件或手动创建令牌。'
          : state?.can_request ? '申请管理员批准后，系统将配置你的个人 Agent，无需填写连接信息。'
            : state ? '请管理员为当前账号完成个人接入。' : '正在读取接入状态…'}</Card.Description>
    {!chat && state && !state.can_manage_setup && <MemberAccess state={state} refresh={() => query.refetch()} />}
    {busy && <p className="type-meta mt-3 text-muted" role="status">可以离开页面，返回后查看同一次接入进度。</p>}
    {error && <p role="alert" className="type-body mt-3">{error}</p>}
    {query.isError && <p role="alert" className="type-body mt-3">接入状态读取失败，请刷新后重试。</p>}
    {!busy && canSetup && !state.setup?.available && <p role="status" className="type-body mt-3">
      {state.setup?.error || '自动接入暂不可用，请管理员检查本机环境。'}</p>}
    {state?.state === 'ready' && !state.can_connect && <p role="status" className="type-body mt-3">个人授权已保存，但 Gateway 连接尚未就绪，请管理员检查。</p>}
    <div className="mt-4 flex flex-wrap items-center gap-2">
      {!chat && state?.can_manage_setup && state.cleanup && ['failed', 'recovery'].includes(state.cleanup.phase) && <StableAsyncButton pending={Boolean(own?.pending)} pendingContent="正在重试"
        onPress={async () => {
          setRequest({ userId, pending: true, label: '重试清理' })
          try { await api.revokeAgentConnection(); await query.refetch(); if (identity.current === userId) setRequest({ userId, pending: false }) }
          catch { if (identity.current === userId) setRequest({ userId, pending: false, error: '清理请求未确认，请刷新核对后重试。' }) }
        }}>重试清理</StableAsyncButton>}
      {!chat && canSetup && <StableAsyncButton pending={Boolean(busy)} pendingContent="正在接入"
        isDisabled={!state.setup?.available || query.isError} onPress={setup}>
        {label}
      </StableAsyncButton>}
      {!chat && state?.can_connect && <Link to="/agent" className="type-control underline">进入 OpenClaw</Link>}
      {chat && state?.can_connect && <StableAsyncButton pending={chat.status === 'connecting'} pendingContent="正在连接"
        isDisabled={query.isError || chat.status === 'connected'} onPress={() => chat.connect()}>连接</StableAsyncButton>}
      {chat && !state?.can_connect && <Link to="/agents" className="type-control underline">前往 Agent 接入</Link>}
      <RefreshButton pending={query.isFetching} aria-label="刷新接入状态" onPress={() => query.refetch()} />
      {!chat && state?.can_manage_setup && ['ready', 'pending_verification', 'invalid'].includes(state.state)
        && <DisconnectAgent disabled={Boolean(busy || query.isError)} />}
    </div>
  </Card>
}
