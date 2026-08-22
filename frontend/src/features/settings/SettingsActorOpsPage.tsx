import { useQuery } from '@tanstack/react-query'
import { Navigate, useLocation } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import { useAppContext } from '../../app/AppContext'
import { Button, Card, LoadingState, PageFrame, PageIntro, StatusNotice } from '../../design-system'
import { ActorOpsAlertIncidentList, ActorOpsAlertSettingsPanel } from '../apify-actors/ActorOpsAlerts'
import { ActorOpsV2ControlPlane } from '../apify-actors/ActorOpsV2ControlPlane'
import { ActorOpsV2OperationEvents } from '../apify-actors/ActorOpsV2OperationEvents'
import { ActorOpsV2RouteDetail } from '../apify-actors/ActorOpsV2RouteDetail'
import { ActorOpsV2RouteControls } from '../apify-actors/ActorOpsV2RouteControls'
import { actorOpsV2RouteView } from '../apify-actors/actorOpsV2RouteModel'
import { canAdministerWorkspace } from './settingsModel'
import { preserveSettingsReturnState } from './settingsReturnState'

export function SettingsActorOpsPage() {
  const { api, user } = useAppContext()
  const location = useLocation()
  const returnState = preserveSettingsReturnState(location.state)
  const canAdminister = canAdministerWorkspace(user)
  const routes = useQuery({
    queryKey: queryKeys.actorOpsV2Routes(user.id),
    queryFn: ({ signal }) => api.actorOpsV2Routes(signal),
    enabled: canAdminister,
    staleTime: queryStaleTime.settings,
    retry: false,
  })
  if (!canAdminister) return <Navigate to="/settings" state={returnState} replace />
  const operations = <>
    <Card variant="secondary" className="grid gap-4 border border-separator p-4">
      <div><Card.Title>运行告警</Card.Title><Card.Description className="mt-1">告警设置适用于整个工作区；任一通知服务失败不会阻断抓取。</Card.Description></div>
      <ActorOpsAlertSettingsPanel />
    </Card>
    <Card variant="secondary" className="grid gap-4 border border-separator p-4">
      <div><Card.Title>最近事件</Card.Title><Card.Description className="mt-1">默认查看最新切换、熔断、费用保护与恢复记录。</Card.Description></div>
      <ActorOpsAlertIncidentList />
    </Card>
    <Card variant="secondary" className="grid gap-4 border border-separator p-4">
      <div><Card.Title>v2 操作记录</Card.Title><Card.Description className="mt-1">只显示脱敏的 v2 管理操作，不混入旧 Pool、Canary 或诊断事件。</Card.Description></div>
      <ActorOpsV2OperationEvents />
    </Card>
  </>

  return <div data-settings-page="actorops" className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-5 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <PageIntro description="为 X、Instagram 和 YouTube 管理 v2 Actor 路由。未就绪或停用的路线不会回退到旧 ActorOps。" />
      {routes.isPending ? <LoadingState label="正在读取 ActorOps v2 路由" rows={3} />
        : routes.isError ? <ActorOpsRouteError error={routes.error} onRetry={() => void routes.refetch()} />
          : routes.data?.schema_version !== 2 ? <ActorOpsRouteError error={new ApiError(503, { code: 'actorops_v2_unavailable', message: 'ActorOps v2 响应不可用。' })} onRetry={() => void routes.refetch()} />
            : routes.data.routes.length === 0 ? <StatusNotice title="暂无 ActorOps v2 Route" status="warning">当前工作区没有可管理的 v2 Route；系统不会改走旧 ActorOps。</StatusNotice>
              : <ActorOpsV2ControlPlane routes={routes.data.routes.map(actorOpsV2RouteView)} operationsContent={operations} renderRouteActions={(route) => <ActorOpsV2RouteControls route={route} />} renderRouteDetails={(route) => <ActorOpsV2RouteDetail route={route} />} />}
    </PageFrame>
  </div>
}

function ActorOpsRouteError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const code = error instanceof ApiError ? error.code : ''
  const state = code === 'actorops_v2_migration_required'
    ? { title: 'ActorOps v2 需要数据库迁移', detail: '请先完成所需的 ActorOps v2 迁移。普通 RSS 和 GitHub 来源不受影响。', retry: false }
    : code === 'actorops_v1_retired'
      ? { title: '旧 ActorOps 控制面已退役', detail: '请使用当前 ActorOps v2 Route、Binding、Discovery 或 Replacement 控制面。', retry: false }
      : { title: 'ActorOps v2 当前不可用', detail: '路线状态恢复前不会提供旧系统回退或付费操作。', retry: true }
  return <StatusNotice title={state.title} status="warning">
    <p>{state.detail}</p>
    {state.retry && <Button size="sm" variant="ghost" className="mt-2" onPress={onRetry}>重试此区域</Button>}
  </StatusNotice>
}
