import type { FeedMode } from './feedModel'

export type FeedPreference = {
  mode: FeedMode
  unreadFirst: boolean
}

const defaultPreference: FeedPreference = { mode: 'featured', unreadFirst: false }
const storageKey = (userId: string) => `inteliscope.ui.feed.v1:${userId}`

export function readFeedPreference(userId: string): FeedPreference {
  try {
    const value = JSON.parse(window.localStorage.getItem(storageKey(userId)) || 'null') as Partial<FeedPreference> | null
    const mode = value?.mode === 'all' || value?.mode === 'daily' || value?.mode === 'featured'
      ? value.mode
      : defaultPreference.mode
    return { mode, unreadFirst: value?.unreadFirst === true }
  } catch {
    return { ...defaultPreference }
  }
}

export function writeFeedPreference(userId: string, value: FeedPreference): void {
  window.localStorage.setItem(storageKey(userId), JSON.stringify(value))
}
