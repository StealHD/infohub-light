import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Navigate, useLocation, useSearchParams } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import { useAppContext } from '../../app/AppContext'
import { Button, LoadingState, PageFrame, ScrollAdaptiveViewBar, StatusNotice, Tabs } from '../../design-system'
import { ActorOpsV2ControlPlane } from '../apify-actors/ActorOpsV2ControlPlane'
import { ActorOpsV2Logs } from '../apify-actors/ActorOpsV2Logs'
import { ActorOpsV2RouteControls } from '../apify-actors/ActorOpsV2RouteControls'
import { actorOpsV2RouteView } from '../apify-actors/actorOpsV2RouteModel'
import { actorOpsV2WorkflowActive } from '../apify-actors/actorOpsV2WorkflowModel'
import { actorOpsCanonicalSearchParams, actorOpsTabFromSearchParams, safeActorOpsEventJobId, safeActorOpsRouteKey } from './actorOpsTabModel'
import { canAdministerWorkspace } from './settingsModel'
import { preserveSettingsReturnState } from './settingsReturnState'

export function SettingsActorOpsPage() {
  const { api, user } = useAppContext()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const returnState = preserveSettingsReturnState(location.state)
  const canAdminister = canAdministerWorkspace(user)
  const tab = actorOpsTabFromSearchParams(searchParams)
  const jobId = tab === 'logs' ? safeActorOpsEventJobId(searchParams.get('job')) : undefined
  const focusedRouteKey = tab === 'routes' ? safeActorOpsRouteKey(searchParams.get('route')) : undefined
  const [toolbarState, setToolbarState] = useState<'expanded' | 'floating'>('expanded')
  const pageScrollerRef = useRef<HTMLDivElement>(null)
  const routes = useQuery({
    queryKey: queryKeys.actorOpsV2Routes(user.id),
    queryFn: ({ signal }) => api.actorOpsV2Routes(signal),
    enabled: canAdminister && tab === 'routes',
    staleTime: queryStaleTime.settings,
    retry: false,
    refetchInterval: (query) => query.state.data?.routes.some((route) => actorOpsV2WorkflowActive(route.workflow)) ? 3_000 : false,
  })
  useEffect(() => {
    const canonical = actorOpsCanonicalSearchParams(searchParams, tab)
    if (canonical.toString() !== searchParams.toString()) setSearchParams(canonical, { replace: true })
  }, [searchParams, setSearchParams, tab])
  useEffect(() => {
    const scroller = pageScrollerRef.current
    if (!scroller) return
    let frame: number | undefined
    const syncToolbarState = () => {
      frame = undefined
      setToolbarState(scroller.scrollTop > 20 ? 'floating' : 'expanded')
    }
    const onScroll = () => {
      if (frame === undefined) frame = window.requestAnimationFrame(syncToolbarState)
    }
    syncToolbarState()
    scroller.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      scroller.removeEventListener('scroll', onScroll)
      if (frame !== undefined) window.cancelAnimationFrame(frame)
    }
  }, [])
  if (!canAdminister) return <Navigate to="/settings" state={returnState} replace />

  return <div ref={pageScrollerRef} data-settings-page="actorops" data-page-scroll-region className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-5 px-4 pb-10 pt-2 min-[768px]:px-6 min-[768px]:pb-12">
      <Tabs selectedKey={tab} onSelectionChange={(key) => setSearchParams(actorOpsCanonicalSearchParams(searchParams, String(key) === 'logs' ? 'logs' : 'routes'), { replace: true })}>
        <div data-actorops-tabs-toolbar className="sticky top-0 z-20 py-2"><ScrollAdaptiveViewBar state={toolbarState} appearance="command" className="min-w-0 justify-start"><div className="min-w-0 max-w-full overflow-x-auto"><Tabs.List data-command-bar-tabs aria-label="ActorOps 页面" className="flex w-max min-w-0 gap-1"><Tabs.Tab data-command-bar-tab id="routes" aria-label="路由管理" className="w-auto shrink-0 justify-center gap-2">路由管理<Tabs.Indicator /></Tabs.Tab><Tabs.Tab data-command-bar-tab id="logs" aria-label="运行日志" className="w-auto shrink-0 justify-center gap-2">运行日志<Tabs.Indicator /></Tabs.Tab></Tabs.List></div></ScrollAdaptiveViewBar></div>
        <Tabs.Panel id="routes" className="grid gap-5 pt-5">
          {routes.isPending ? <LoadingState label="正在读取 ActorOps v2 路由" rows={3} />
            : routes.isError ? <ActorOpsRouteError error={routes.error} onRetry={() => void routes.refetch()} />
              : routes.data?.schema_version !== 2 ? <ActorOpsRouteError error={new ApiError(503, { code: 'actorops_v2_unavailable', message: 'ActorOps v2 响应不可用。' })} onRetry={() => void routes.refetch()} />
                : routes.data.routes.length === 0 ? <StatusNotice title="暂无 ActorOps v2 Route" status="warning">当前工作区没有可管理的 v2 Route；系统不会改走旧 ActorOps。</StatusNotice>
                  : <ActorOpsV2ControlPlane routes={routes.data.routes.map(actorOpsV2RouteView)} focusedRouteKey={focusedRouteKey} renderRouteActions={(route) => <ActorOpsV2RouteControls route={route} />} />}
        </Tabs.Panel>
        <Tabs.Panel id="logs" className="pt-5"><ActorOpsV2Logs jobId={jobId} /></Tabs.Panel>
      </Tabs>
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
