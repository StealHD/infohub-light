export type OpenClawInspector = 'context' | 'tasks' | 'artifacts' | null

export function inspectorForLocation(pathname: string, search: string): OpenClawInspector {
  if (pathname === '/agent/tasks') return 'tasks'
  if (pathname === '/agent/artifacts') return 'artifacts'
  if (pathname === '/agent' && new URLSearchParams(search).get('panel') === 'context') return 'context'
  return null
}

export function routeForInspector(inspector: OpenClawInspector): string {
  if (inspector === 'tasks') return '/agent/tasks'
  if (inspector === 'artifacts') return '/agent/artifacts'
  if (inspector === 'context') return '/agent?panel=context'
  return '/agent'
}

export function isOpenClawResourcePage(pathname: string): boolean {
  return pathname === '/agent/skills' || pathname === '/agent/automations' || pathname === '/agent/examples'
}
