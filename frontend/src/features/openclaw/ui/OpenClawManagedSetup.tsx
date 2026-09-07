import { StableAsyncButton, Card } from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'

export function OpenClawManagedSetup({ chat }: { chat: OpenClawChatController }) {
  return <div className="quiet-scroll-region min-h-0 overflow-y-auto p-4">
    <Card variant="secondary" className="p-4">
      <Card.Title>连接 OpenClaw</Card.Title>
      <Card.Description>通过 Inscope 服务端连接，使用当前登录账号，无需填写 Token。仅管理员可用。</Card.Description>
      <StableAsyncButton className="mt-4" pending={chat.status === 'connecting'} pendingContent="正在连接…" onPress={() => void chat.connect()}>连接</StableAsyncButton>
    </Card>
    {chat.issue && <Card variant="secondary" className="mt-3 p-4" role="alert">
      <Card.Title>服务端暂时无法连接 OpenClaw</Card.Title>
      <Card.Description>请确认登录未过期并重试；持续失败请联系管理员检查服务端连接和设备授权。</Card.Description>
    </Card>}
  </div>
}
