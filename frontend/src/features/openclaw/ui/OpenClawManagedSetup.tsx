import { useAgentConnectionContext } from '../../agent-connection/AgentConnectionContext'
import { saveManagedSession } from '../storage/openclawManagedSession'
import { Card, StableAsyncButton } from '../../../design-system'
import { PersonalAgentConnection } from '../../agent-connection/PersonalAgentConnection'
import type { OpenClawChatController } from '../openclawContracts'

export function OpenClawManagedSetup({ chat, variant = 'compact' }: { chat: OpenClawChatController; variant?: 'compact' | 'workspace' }) {
  const { userId } = useAgentConnectionContext()
  return <div className="quiet-scroll-region min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-4" data-testid="agent-scroll-region" data-page-scroll-region={variant === 'workspace' ? '' : undefined}>
    <PersonalAgentConnection chat={chat} />
    {chat.issue && <Card variant="secondary" className="mt-3 p-4" role="alert">
      <Card.Title>服务端暂时无法连接 OpenClaw</Card.Title>
      <Card.Description>请确认登录未过期并重试；持续失败请联系管理员检查服务端连接和设备授权。</Card.Description>
      <StableAsyncButton pending={chat.status === 'connecting'} pendingContent="正在连接…" onPress={async () => { saveManagedSession(userId, ''); await chat.connect() }}>新建个人会话并连接</StableAsyncButton>
      <p className="type-meta text-muted">仅重新选择当前浏览器的会话，不删除历史记录或修改账号绑定。</p>
    </Card>}
  </div>
}
