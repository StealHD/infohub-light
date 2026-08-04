import { Component, Suspense, lazy, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'

import type { ServiceApi } from '../api/service'
import type { AuthStatus, User } from '../api/types'
import { queryKeys } from '../api/queryKeys'
import { HeroLoginPage } from '../features/admin-heroui/HeroLoginPage'
import { LoadingState, actionToast } from '../design-system'
import { useFeedActivity } from '../features/jobs/useFeedActivity'
import { HeroWorkbenchPage } from '../features/workbench-live/HeroWorkbenchPage'
import { HeroWorkbenchShell } from '../features/workbench-live/HeroWorkbenchShell'
import { SettingsLayout } from '../features/settings/SettingsLayout'
import { clearUserCache } from './sessionCache'
import { legacyViewDestination } from './legacyRoute'
import { ActionGeneration, type ActionToken } from './actionGeneration'
import { ActionFeedbackProvider } from './ActionFeedback'
import { clearBootstrapShellSnapshot, releaseBootstrapShell, writeBootstrapShellSnapshot } from './bootstrapShell'
import { readSidebarPreference } from './sidebarPreference'

const HeroAgentsPage = lazy(() => import('../features/admin-heroui/HeroAgentsPage').then((module) => ({ default: module.HeroAgentsPage })))
const HeroSubscriptionsPage = lazy(() => import('../features/admin-heroui/HeroSubscriptionsPage').then((module) => ({ default: module.HeroSubscriptionsPage })))
const HeroUsersPage = lazy(() => import('../features/admin-heroui/HeroUsersPage').then((module) => ({ default: module.HeroUsersPage })))
const HeroChangelogPage = lazy(() => import('../features/changelog/HeroChangelogPage').then((module) => ({ default: module.HeroChangelogPage })))
const HeroManualPage = lazy(() => import('../features/manual/HeroManualPage').then((module) => ({ default: module.HeroManualPage })))
const SettingsAppearancePage = lazy(() => import('../features/settings/SettingsAppearancePage').then((module) => ({ default: module.SettingsAppearancePage })))
const SettingsAIPage = lazy(() => import('../features/settings/SettingsAIPage').then((module) => ({ default: module.SettingsAIPage })))
const SettingsFetchingPage = lazy(() => import('../features/settings/SettingsFetchingPage').then((module) => ({ default: module.SettingsFetchingPage })))
const SettingsIgnoredPage = lazy(() => import('../features/settings/SettingsIgnoredPage').then((module) => ({ default: module.SettingsIgnoredPage })))
const SettingsLegacyPage = lazy(() => import('../features/settings/SettingsLegacyPage').then((module) => ({ default: module.SettingsLegacyPage })))
const SettingsNotificationsPage = lazy(() => import('../features/settings/SettingsNotificationsPage').then((module) => ({ default: module.SettingsNotificationsPage })))
const SettingsOverviewPage = lazy(() => import('../features/settings/SettingsOverviewPage').then((module) => ({ default: module.SettingsOverviewPage })))
const SettingsSecretsPage = lazy(() => import('../features/settings/SettingsSecretsPage').then((module) => ({ default: module.SettingsSecretsPage })))

type AppErrorBoundaryProps = { children: ReactNode; surface?: 'app' | 'page' }
type AppErrorBoundaryState = { failed: boolean }

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true }
  }

  render() {
    if (this.state.failed) {
      const RecoverySurface = this.props.surface === 'page' ? 'section' : 'main'
      return <RecoverySurface className="app-loading app-error" role="alert">
        <h1>页面加载失败</h1>
        <p>当前内容无法显示，请返回信息流后重试。</p>
        <a href="/feed">返回信息流</a>
      </RecoverySurface>
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

function RouteLoadingState() {
  return <main className="quiet-scroll-region h-full min-w-0 overflow-x-hidden overflow-y-auto p-4 min-[768px]:p-6" role="status">
    <LoadingState label="正在加载页面" rows={3} />
  </main>
}

function AuthenticatedLayout({ api, user }: { api: ServiceApi; user: User }) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const [contentQueries, setContentQueries] = useState({ feed: '', saved: '', history: '' })
  const previousUserId = useRef(user.id)
  const actionGuard = useMemo(() => new ActionGeneration(user.id), [user.id])
  const feedActivity = useFeedActivity(api, user, actionGuard)
  const canMutate = user.role !== 'viewer'
  const settingsWorkspaceRoute = location.pathname === '/settings' || location.pathname.startsWith('/settings/')
  const contentRoute = location.pathname === '/feed'
    ? 'feed'
    : location.pathname === '/saved'
      ? 'saved'
      : location.pathname === '/history'
        ? 'history'
        : null
  const query = contentRoute ? contentQueries[contentRoute] : ''
  const setQuery = useCallback((value: string) => {
    if (!contentRoute) return
    setContentQueries((current) => current[contentRoute] === value
      ? current
      : { ...current, [contentRoute]: value })
  }, [contentRoute])

  useLayoutEffect(() => {
    if (previousUserId.current !== user.id) {
      actionToast.clear()
      setContentQueries({ feed: '', saved: '', history: '' })
      void clearUserCache(queryClient, previousUserId.current)
    }
    previousUserId.current = user.id
  }, [queryClient, user.id])

  useEffect(() => {
    return () => actionGuard.invalidate()
  }, [actionGuard])

  async function logout() {
    actionGuard.invalidate()
    actionToast.clear()
    await api.logout()
    await clearUserCache(queryClient, user.id)
    queryClient.setQueryData<AuthStatus>(queryKeys.auth, { authenticated: false, user: null })
  }

  const outlet = <AppErrorBoundary key={location.pathname} surface="page">
    <Suspense fallback={<RouteLoadingState />}>
      <Outlet context={{ api, user, query, setQuery, activity: feedActivity.activity, refresh: canMutate ? feedActivity.refresh : () => undefined, reloadFeed: feedActivity.reloadFeed, beginAction: () => actionGuard.capture(), isActionCurrent: (token: ActionToken) => actionGuard.isCurrent(token) }} />
    </Suspense>
  </AppErrorBoundary>

  return <ActionFeedbackProvider key={user.id} userId={user.id}>
    {settingsWorkspaceRoute ? <SettingsLayout user={user}>{outlet}</SettingsLayout> : <HeroWorkbenchShell
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
    >{outlet}</HeroWorkbenchShell>}
  </ActionFeedbackProvider>
}

function BootstrapShellRelease({ user, clearSnapshot = false, children }: {
  user?: User | null
  clearSnapshot?: boolean
  children: ReactNode
}) {
  useLayoutEffect(() => {
    if (user) writeBootstrapShellSnapshot(user.id, readSidebarPreference(user.id))
    else if (clearSnapshot) clearBootstrapShellSnapshot()
    releaseBootstrapShell()
  }, [clearSnapshot, user])

  return children
}

function ServiceRoutes({ api }: { api: ServiceApi }) {
  const queryClient = useQueryClient()
  const auth = useQuery({ queryKey: queryKeys.auth, queryFn: ({ signal }) => api.authStatus(signal), retry: false })
  if (auth.isLoading) return <span className="sr-only" role="status">正在连接 Inteliscope…</span>
  if (auth.isError) return <BootstrapShellRelease><main className="app-loading app-error" role="alert">无法连接服务，请确认 API 已启动后重试。</main></BootstrapShellRelease>
  const user = auth.data?.authenticated ? auth.data.user : null
  const login = <HeroLoginPage api={api} onAuthenticated={() => void queryClient.invalidateQueries({ queryKey: queryKeys.auth })} />

  return <BootstrapShellRelease user={user} clearSnapshot={!user}><AppErrorBoundary>
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
        <Route path="/settings" element={<SettingsOverviewPage />} />
        <Route path="/settings/ai" element={<SettingsAIPage />} />
        <Route path="/settings/fetching" element={<SettingsFetchingPage />} />
        <Route path="/settings/appearance" element={<SettingsAppearancePage />} />
        <Route path="/settings/ignored" element={<SettingsIgnoredPage />} />
        <Route path="/settings/notifications" element={<SettingsNotificationsPage />} />
        <Route path="/settings/secrets" element={<SettingsSecretsPage />} />
        <Route path="/settings/legacy" element={<SettingsLegacyPage />} />
        <Route path="/users" element={<HeroUsersPage />} />
        <Route path="/manual" element={<HeroManualPage />} />
        <Route path="/changelog" element={<HeroChangelogPage />} />
      </Route>
      <Route path="*" element={<Navigate to={user ? '/feed' : '/login'} replace />} />
    </Routes>
  </AppErrorBoundary></BootstrapShellRelease>
}

export function AppRoutes({ api }: { api: ServiceApi }) {
  return <ServiceRoutes api={api} />
}
