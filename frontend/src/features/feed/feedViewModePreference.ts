export type FeedViewMode = 'timeline' | 'source-overview'

const storageKey = (userId: string) => `inteliscope.ui.feed-view.v1:${userId}`

function sanitizeFeedViewMode(value: unknown): FeedViewMode {
  return value === 'source-overview' ? 'source-overview' : 'timeline'
}

export function readFeedViewMode(userId: string): FeedViewMode {
  try {
    return sanitizeFeedViewMode(JSON.parse(window.localStorage.getItem(storageKey(userId)) || 'null'))
  } catch {
    return 'timeline'
  }
}

export function writeFeedViewMode(userId: string, mode: FeedViewMode): void {
  window.localStorage.setItem(storageKey(userId), JSON.stringify(sanitizeFeedViewMode(mode)))
}
