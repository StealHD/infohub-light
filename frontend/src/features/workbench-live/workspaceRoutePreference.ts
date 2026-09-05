export type WorkspaceMode = 'inscope' | 'openclaw'

const defaultRoutes: Record<WorkspaceMode, string> = {
  inscope: '/feed',
  openclaw: '/agent',
}

const inscopeRoutes = new Set(['/feed', '/saved', '/history', '/subscriptions'])
const openClawRoutes = new Set([
  '/agent',
  '/agent/tasks',
  '/agent/artifacts',
  '/agent/skills',
  '/agent/automations',
])

function preferenceKey(userId: string, mode: WorkspaceMode): string {
  return `inteliscope.ui.workspace-route.v1:${userId}:${mode}`
}

export function workspaceModeForPath(pathname: string): WorkspaceMode {
  return pathname === '/agent' || pathname.startsWith('/agent/') ? 'openclaw' : 'inscope'
}

export function validWorkspaceRoute(mode: WorkspaceMode, pathname: string): boolean {
  return mode === 'openclaw' ? openClawRoutes.has(pathname) : inscopeRoutes.has(pathname)
}

export function rememberWorkspaceRoute(userId: string, pathname: string): void {
  const mode = workspaceModeForPath(pathname)
  if (!validWorkspaceRoute(mode, pathname)) return
  try {
    window.localStorage.setItem(preferenceKey(userId, mode), pathname)
  } catch {
    // Route preference is best-effort and contains no session or credential data.
  }
}

export function readWorkspaceRoute(userId: string, mode: WorkspaceMode): string {
  try {
    const stored = window.localStorage.getItem(preferenceKey(userId, mode))
    return stored && validWorkspaceRoute(mode, stored) ? stored : defaultRoutes[mode]
  } catch {
    return defaultRoutes[mode]
  }
}
