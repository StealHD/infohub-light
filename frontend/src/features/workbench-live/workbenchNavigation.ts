export type PendingNavigation = {
  index: number
  align: 'start' | 'center' | 'end'
}

export function clampPendingNavigation(navigation: PendingNavigation, itemCount: number): PendingNavigation {
  return {
    ...navigation,
    index: Math.max(0, Math.min(navigation.index, itemCount - 1)),
  }
}
