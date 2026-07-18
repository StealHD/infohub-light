import { Component, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'

import type { ServiceApi } from '../api/service'
import type { AuthStatus, User } from '../api/types'
import { queryKeys } from '../api/queryKeys'
import { HeroAgentsPage } from '../features/admin-heroui/HeroAgentsPage'
import { HeroLoginPage } from '../features/admin-heroui/HeroLoginPage'
import { HeroSettingsPage } from '../features/admin-heroui/HeroSettingsPage'
import { HeroSubscriptionsPage } from '../features/admin-heroui/HeroSubscriptionsPage'
import { useFeedActivity } from '../features/jobs/useFeedActivity'
import { HeroWorkbenchPage } from '../features/workbench-live/HeroWorkbenchPage'
import { HeroWorkbenchShell } from '../features/workbench-live/HeroWorkbenchShell'
import { clearUserCache } from './sessionCache'
import { legacyViewDestination } from './legacyRoute'
import { ActionGeneration, type ActionToken } from './actionGeneration'
import { ActionFeedbackProvider } from './ActionFeedback'

type AppErrorBoundaryProps = { children: ReactNode }
type AppErrorBoundaryState = { failed: boolean }

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

function LegacyLaterRedirect() {
  const location = useLocation()
  const source = new URLSearchParams(location.search)
  const target = new URLSearchParams()
  const item = source.get('item')
  if (item) target.set('item', item)
  return <Navigate to={{ pathname: '/saved', search: target.toString() ? `?${target.toString()}` : '' }} replace />
}

function AuthenticatedLayout({ api, user }: { api: ServiceApi; user: User }) {
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

  return <ActionFeedbackProvider key={user.id} userId={user.id}>
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
  </ActionFeedbackProvider>
}

function ServiceRoutes({ api }: { api: ServiceApi }) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const auth = useQuery({ queryKey: queryKeys.auth, queryFn: ({ signal }) => api.authStatus(signal), retry: false })
  if (auth.isLoading) return <main className="app-loading" role="status">正在连接 Inteliscope…</main>
  if (auth.isError) return <main className="app-loading app-error" role="alert">无法连接服务，请确认 API 已启动后重试。</main>
  const user = auth.data?.authenticated ? auth.data.user : null
  const login = <HeroLoginPage api={api} onAuthenticated={() => void queryClient.invalidateQueries({ queryKey: queryKeys.auth })} />

  return <AppErrorBoundary key={location.pathname}>
    <Routes>
      <Route path="/login" element={user ? <Navigate to="/feed" replace /> : login} />
      <Route element={user ? <AuthenticatedLayout api={api} user={user} /> : <Navigate to="/login" replace />}>
        <Route path="/" element={<LegacyEntry />} />
        <Route path="/feed" element={<HeroWorkbenchPage kind="feed" />} />
        <Route path="/later" element={<LegacyLaterRedirect />} />
        <Route path="/saved" element={<HeroWorkbenchPage kind="saved" />} />
        <Route path="/history" element={<HeroWorkbenchPage kind="history" />} />
        <Route path="/subscriptions" element={<HeroSubscriptionsPage />} />
        <Route path="/agents" element={<HeroAgentsPage />} />
        <Route path="/settings" element={<HeroSettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to={user ? '/feed' : '/login'} replace />} />
    </Routes>
  </AppErrorBoundary>
}

export function AppRoutes({ api }: { api: ServiceApi }) {
  return <ServiceRoutes api={api} />
}
