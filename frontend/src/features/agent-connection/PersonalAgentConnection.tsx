import { useContext } from 'react'
import { OpenClawWorkspaceRuntimeContext } from '../openclaw/workspace/openClawWorkspaceRuntimeContext'
import { queryKeys } from '../../api/queryKeys'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useAgentConnectionContext } from './AgentConnectionContext'
import { Card, RefreshButton, StableAsyncButton } from '../../design-system'
import type { AgentConnection } from '../../api/agentConnectionService'
import type { OpenClawChatController } from '../openclaw/openclawContracts'

const descriptions: Record<AgentConnection['state'], string> = {
  migration_required: '服务端需要完成个人 Agent 数据迁移，请联系管理员。',
  unconfigured: '当前账号尚未绑定个人 Agent。请联系管理员完成个人接入配置。',
  pending_verification: '个人 Agent 已准备，等待管理员验证部署并激活绑定。',
  ready: '首次请手动连接；成功后，此浏览器会在下次登录或刷新时自动连接你的 Agent。',
  invalid: '个人绑定或数据授权已失效，请联系管理员重新配置并验证。',
  revoked: '当前账号已撤销个人绑定，请联系管理员重新配置。',
}

export function PersonalAgentConnection({ chat }: { chat?: OpenClawChatController }) {
  const runtime = useContext(OpenClawWorkspaceRuntimeContext)
  const connected = (chat ?? runtime)?.status === 'connected'
  const { api, userId } = useAgentConnectionContext()
  const query = useQuery({ queryKey: queryKeys.agentConnection(userId),
    queryFn: ({ signal }) => api.agentConnection(signal), refetchOnWindowFocus: true })
  const state = query.data
  return <Card variant="secondary" className="p-4" aria-busy={query.isFetching}>
    <Card.Title>我的 Agent 接入</Card.Title>
    <Card.Description>{state ? descriptions[state.state] : query.isError
      ? '无法读取个人接入状态，请重试。' : '正在读取个人接入状态…'}</Card.Description>
    {state && <div className="mt-3 grid gap-2 type-body">
      {state.agent_id && <p className="break-all">当前 Agent：{state.agent_id}</p>}
      <p>聊天：{connected && state.can_connect ? state.can_chat ? '已连接' : '已连接 · 只读' : '尚未验证连接'}</p>
      <p>本人内容：{state.verification.own_content ? '授权已验证' : '尚未验证'}</p>
      <p>建立提醒：{state.verification.information_automations ? '可用' : '尚未就绪'}</p>
      <p>通知服务：{state.verification.notifications ? '可用' : '尚未验证'}</p>
      {state.state === 'ready' && !state.can_connect && <p role="status">服务端连接尚未就绪，请联系管理员检查 Gateway 配置。</p>}
    </div>}
    {query.isError && state && <p role="alert" className="mt-3 type-body">刷新失败，显示上次状态；请重试。</p>}
    <div className="mt-4 flex flex-wrap items-center gap-2">
      {chat && <StableAsyncButton pending={chat.status === 'connecting'} pendingContent="正在连接…"
        isDisabled={!state?.can_connect || query.isError} onPress={() => void chat.connect()}>连接</StableAsyncButton>}
      <RefreshButton pending={query.isFetching} aria-label="刷新个人接入状态" onPress={() => query.refetch()} />
      {chat && <Link to="/agents" className="type-body underline">管理个人接入</Link>}
    </div>
  </Card>
}
