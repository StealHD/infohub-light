export type ActorOpsTab = 'routes' | 'logs'

const legacyTabMap: Record<string, ActorOpsTab> = {
  pool: 'routes',
  sources: 'routes',
  operations: 'logs',
  routes: 'routes',
  logs: 'logs',
}

export function actorOpsTabFromSearchParams(searchParams: URLSearchParams): ActorOpsTab {
  return legacyTabMap[searchParams.get('tab') || ''] || 'routes'
}

export function actorOpsCanonicalSearchParams(searchParams: URLSearchParams, tab: ActorOpsTab): URLSearchParams {
  const next = new URLSearchParams(searchParams)
  next.set('tab', tab)
  if (tab !== 'logs' || !safeActorOpsEventJobId(next.get('job'))) next.delete('job')
  if (tab !== 'routes' || !safeActorOpsRouteKey(next.get('route'))) next.delete('route')
  return next
}

export function safeActorOpsEventJobId(value: string | null): string | undefined {
  return value && /^[a-zA-Z0-9._:-]{1,128}$/.test(value) ? value : undefined
}

export function safeActorOpsRouteKey(value: string | null): string | undefined {
  return value && /^[a-z0-9/_-]{1,80}$/.test(value) ? value : undefined
}
