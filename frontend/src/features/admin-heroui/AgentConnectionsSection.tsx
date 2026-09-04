import type { AgentDelegation } from '../../api/types'
import { Button, Card, EmptyState, Icons, OverflowValue, StatusIndicator } from '../../design-system'
import { AdminSection } from './HeroAdminControls'
import { ConnectionCardActions, type ConnectionAction } from './HeroAgentDelegationViews'
import { delegationAccessLabel, delegationDateTime, delegationStatus } from './HeroAgentDelegationPresentation'

export function AgentConnectionsSection({
  activeCount,
  connections,
  creationDisabled,
  maxActive,
  onAction,
  onCreate,
  onMenuChange,
  openConnectionMenuId,
}: {
  activeCount: number
  connections: AgentDelegation[]
  creationDisabled: boolean
  maxActive: number
  onAction: (connection: AgentDelegation, action: ConnectionAction, trigger: HTMLButtonElement | null) => void
  onCreate: () => void
  onMenuChange: (connectionId: string, open: boolean) => void
  openConnectionMenuId: string | null
}) {
  return <AdminSection title="我的连接" description={`${activeCount}/${maxActive} 个有效连接`}>
    <div className="grid gap-3">
      {!connections.length && <EmptyState title="还没有助手连接" description="创建连接后，OpenClaw 才能按所选权限访问当前账户。" actions={<Button size="sm" isDisabled={creationDisabled} onPress={onCreate}><Icons.Bot size={16} />创建连接</Button>} />}
      {connections.map((connection) => {
        const status = delegationStatus(connection)
        return <Card key={connection.id} variant="secondary" className="p-4">
          <div className="flex flex-col gap-3 min-[640px]:flex-row min-[640px]:items-center">
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <Card.Title className="min-w-0 max-w-full flex-1"><OverflowValue value={connection.name} ariaLabel={`查看 ${connection.name} 的完整连接名称`} className="type-page-title" /></Card.Title>
                <StatusIndicator iconOnly label={status.label} tone={status.tone} icon={status.icon} />
                <span className="type-meta inline-flex items-center gap-1 text-muted"><Icons.LockKeyhole size={12} aria-hidden="true" />{delegationAccessLabel(connection.access)}</span>
                {connection.diagnostics_scope === 'workspace' && <span className="type-meta text-muted">工作区诊断</span>}
              </div>
              <Card.Description className="mt-1">{connection.last_used_at ? `最近使用 ${delegationDateTime(connection.last_used_at)}` : '从未使用'} · 到期 {delegationDateTime(connection.expires_at)} · {connection.token_prefix}…</Card.Description>
            </div>
            <ConnectionCardActions connection={connection} open={openConnectionMenuId === connection.id} onOpenChange={(open) => onMenuChange(connection.id, open)} onAction={(action, trigger) => onAction(connection, action, trigger)} />
          </div>
        </Card>
      })}
    </div>
    <p className="type-meta mt-3 text-muted">写入连接彼此隔离；订阅管理与系统管理不会互相获得权限，也都不包括密钥。</p>
  </AdminSection>
}
