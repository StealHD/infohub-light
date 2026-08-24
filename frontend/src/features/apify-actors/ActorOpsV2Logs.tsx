import { Card } from '../../design-system'
import { ActorOpsAlertIncidentList, ActorOpsAlertSettingsPanel } from './ActorOpsAlerts'
import { ActorOpsV2OperationEvents } from './ActorOpsV2OperationEvents'

export function ActorOpsV2Logs({ jobId }: { jobId?: string }) {
  return <div className="grid gap-5" data-testid="actorops-v2-logs">
    <Card variant="secondary" className="grid gap-4 border border-separator p-4">
      <div><Card.Title>运行告警</Card.Title><Card.Description className="mt-1">告警设置适用于整个工作区；任一通知服务失败不会阻断抓取。</Card.Description></div>
      <ActorOpsAlertSettingsPanel />
    </Card>
    <Card variant="secondary" className="grid gap-4 border border-separator p-4">
      <div><Card.Title>待处理事件</Card.Title><Card.Description className="mt-1">每个待处理状态都会说明原因、影响、下一步和安全入口。</Card.Description></div>
      <ActorOpsAlertIncidentList />
    </Card>
    <Card variant="secondary" className="grid gap-4 border border-separator p-4">
      <div><Card.Title>{jobId ? '指定运行的安全执行记录' : '操作与执行记录'}</Card.Title><Card.Description className="mt-1">只显示脱敏的 v2 管理操作和执行轨迹，不混入旧 Pool、Canary 或诊断事件。</Card.Description></div>
      <ActorOpsV2OperationEvents jobId={jobId} />
    </Card>
  </div>
}
