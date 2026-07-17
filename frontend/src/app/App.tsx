import { Component, Suspense, lazy, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'

import type { ServiceApi } from '../api/service'
import type { AuthStatus, User } from '../api/types'
import { queryKeys } from '../api/queryKeys'
import { FeedPage } from '../features/feed/FeedPage'
import { LoginPage } from '../features/auth/LoginPage'
import { SettingsPage } from '../features/settings/SettingsPage'
import { AgentsPage } from '../features/agents/AgentsPage'
import { SubscriptionsPage } from '../features/subscriptions/SubscriptionsPage'
import { useFeedActivity } from '../features/jobs/useFeedActivity'
import { AppShell } from './AppShell'
import { clearUserCache } from './sessionCache'
import { legacyViewDestination } from './legacyRoute'
import { ActionGeneration, type ActionToken } from './actionGeneration'
import { ActionFeedbackProvider } from './ActionFeedback'

type AppErrorBoundaryProps = { children: ReactNode }
type AppErrorBoundaryState = { failed: boolean }

const WorkbenchPreview = import.meta.env.DEV
  ? lazy(() => import('../features/workbench/WorkbenchPreview').then(({ WorkbenchPreview: Preview }) => ({ default: Preview })))
  : null
const HeroWorkbenchShell = import.meta.env.DEV
  ? lazy(() => import('../features/workbench-live/HeroWorkbenchShell').then(({ HeroWorkbenchShell: Shell }) => ({ default: Shell })))
  : null
const HeroWorkbenchPage = import.meta.env.DEV
  ? lazy(() => import('../features/workbench-live/HeroWorkbenchPage').then(({ HeroWorkbenchPage: Page }) => ({ default: Page })))
  : null
const HeroSubscriptionsPage = import.meta.env.DEV
  ? lazy(() => import('../features/admin-heroui/HeroSubscriptionsPage').then(({ HeroSubscriptionsPage: Page }) => ({ default: Page })))
  : null
const HeroAgentsPage = import.meta.env.DEV
  ? lazy(() => import('../features/admin-heroui/HeroAgentsPage').then(({ HeroAgentsPage: Page }) => ({ default: Page })))
  : null
const HeroSettingsPage = import.meta.env.DEV
  ? lazy(() => import('../features/admin-heroui/HeroSettingsPage').then(({ HeroSettingsPage: Page }) => ({ default: Page })))
  : null
const HeroLoginPage = import.meta.env.DEV
  ? lazy(() => import('../features/admin-heroui/HeroLoginPage').then(({ HeroLoginPage: Page }) => ({ default: Page })))
  : null

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true }
  }

  render() {
    if (this.state.failed) {
      return <main className="app-loading app-error" role="alert">
        <h1>页面加载失败</h1>
        <p>当前内容无法显示，请返回信息流后重试。</p>
        <a href="/feed">返回信息流</a>
      </main>
    }
    return this.props.children
  }
}

function LegacyEntry() {
  const location = useLocation()
  const destination = legacyViewDestination(new URLSearchParams(location.search).get('view')) ?? '/feed'
  return <Navigate to={destination} replace />
}

function AuthenticatedLayout({ api, user, experience = 'legacy' }: { api: ServiceApi; user: User; experience?: 'legacy' | 'live' }) {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState('')
  const previousUserId = useRef(user.id)
  const actionGuard = useMemo(() => new ActionGeneration(user.id), [user.id])
  const feedActivity = useFeedActivity(api, user, actionGuard)
  const canMutate = user.role !== 'viewer'

  useEffect(() => {
    if (previousUserId.current !== user.id) void clearUserCache(queryClient, previousUserId.current)
    previousUserId.current = user.id
  }, [queryClient, user.id])

  useEffect(() => {
    return () => actionGuard.invalidate()
  }, [actionGuard])

  async function logout() {
    actionGuard.invalidate()
    await api.logout()
    await clearUserCache(queryClient, user.id)
    queryClient.setQueryData<AuthStatus>(queryKeys.auth, { authenticated: false, user: null })
  }

  const outlet = <Outlet context={{ api, user, query, setQuery, activity: feedActivity.activity, refresh: canMutate ? feedActivity.refresh : () => undefined, beginAction: () => actionGuard.capture(), isActionCurrent: (token: ActionToken) => actionGuard.isCurrent(token) }} />

  if (experience === 'live' && HeroWorkbenchShell) {
    return <ActionFeedbackProvider key={user.id} userId={user.id} noticeSurface="none">
      <Suspense fallback={<main className="app-loading" role="status">正在准备实时工作台…</main>}>
        <HeroWorkbenchShell
          api={api}
          user={user}
          query={query}
          onQueryChange={setQuery}
          onRefresh={canMutate ? feedActivity.refresh : undefined}
          onRetry={canMutate ? feedActivity.retry : undefined}
          onLogout={() => void logout()}
          refreshState={feedActivity.pending ? 'pending' : feedActivity.notice?.state ?? feedActivity.activity.state}
          refreshMessage={feedActivity.notice?.message}
          refreshEventKey={feedActivity.notice?.key}
        >{outlet}</HeroWorkbenchShell>
      </Suspense>
    </ActionFeedbackProvider>
  }

  return <ActionFeedbackProvider key={user.id} userId={user.id}><AppShell
    user={user}
    query={query}
    onQueryChange={setQuery}
    onRefresh={canMutate ? feedActivity.refresh : undefined}
    onRetry={canMutate ? feedActivity.retry : undefined}
    onLogout={() => void logout()}
    refreshState={feedActivity.pending ? 'pending' : feedActivity.notice?.state ?? feedActivity.activity.state}
    refreshMessage={feedActivity.notice?.message}
    refreshEventKey={feedActivity.notice?.key}
  >
    {outlet}
  </AppShell></ActionFeedbackProvider>
}

function ServiceRoutes({ api }: { api: ServiceApi }) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const auth = useQuery({ queryKey: queryKeys.auth, queryFn: ({ signal }) => api.authStatus(signal), retry: false })
  if (auth.isLoading) return <main className="app-loading" role="status">正在连接 Inteliscope…</main>
  if (auth.isError) return <main className="app-loading app-error" role="alert">无法连接服务，请确认 API 已启动后重试。</main>
  const user = auth.data?.authenticated ? auth.data.user : null
  const login = <LoginPage api={api} onAuthenticated={() => void queryClient.invalidateQueries({ queryKey: queryKeys.auth })} />

  return <AppErrorBoundary key={location.pathname}>
    <Routes>
      {HeroLoginPage && <Route path="/__preview/workbench-live/login" element={user ? <Navigate to="/__preview/workbench-live" replace /> : <Suspense fallback={<main className="app-loading" role="status">正在准备登录页…</main>}><HeroLoginPage api={api} onAuthenticated={() => void queryClient.invalidateQueries({ queryKey: queryKeys.auth })} /></Suspense>} />}
      <Route path="/login" element={user ? <Navigate to="/feed" replace /> : login} />
      <Route element={user ? <AuthenticatedLayout api={api} user={user} /> : <Navigate to="/login" replace />}>
        <Route path="/" element={<LegacyEntry />} />
        <Route path="/feed" element={<FeedPage kind="feed" />} />
        <Route path="/later" element={<FeedPage kind="later" />} />
        <Route path="/saved" element={<FeedPage kind="saved" />} />
        <Route path="/history" element={<FeedPage kind="history" />} />
        <Route path="/subscriptions" element={<SubscriptionsPage />} />
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      {HeroWorkbenchPage && <Route element={user ? <AuthenticatedLayout api={api} user={user} experience="live" /> : <Navigate to="/login" replace />}>
        <Route path="/__preview/workbench-live" element={<HeroWorkbenchPage kind="feed" />} />
        <Route path="/__preview/workbench-live/saved" element={<HeroWorkbenchPage kind="saved" />} />
        <Route path="/__preview/workbench-live/history" element={<HeroWorkbenchPage kind="history" />} />
        {HeroSubscriptionsPage && <Route path="/__preview/workbench-live/subscriptions" element={<HeroSubscriptionsPage />} />}
        {HeroAgentsPage && <Route path="/__preview/workbench-live/agents" element={<HeroAgentsPage />} />}
        {HeroSettingsPage && <Route path="/__preview/workbench-live/settings" element={<HeroSettingsPage />} />}
      </Route>}
      <Route path="*" element={<Navigate to={user ? '/feed' : '/login'} replace />} />
    </Routes>
  </AppErrorBoundary>
}

export function AppRoutes({ api }: { api: ServiceApi }) {
  const location = useLocation()
  if (WorkbenchPreview && location.pathname === '/__preview/workbench') {
    return <Suspense fallback={<main className="app-loading" role="status">正在准备工作台预览…</main>}><WorkbenchPreview /></Suspense>
  }
  return <ServiceRoutes api={api} />
}
