const destinations: Record<string, string> = {
  featured: '/feed?mode=featured',
  all: '/feed?mode=all',
  daily: '/feed?mode=daily',
  readLater: '/later',
  history: '/history',
  subscriptions: '/subscriptions',
  config: '/settings',
}

export function legacyViewDestination(view: string | null): string | null {
  return view ? destinations[view] ?? null : null
}
