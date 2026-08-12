import type { FeedMode } from './feedModel'

export type LegacyFeedPreference = {
  mode: FeedMode
  unreadFirst: boolean
}

export type FeedOrder = 'newest' | 'oldest'
export type FeedDateScope = 'all' | 'today'
export type FeedSortBasis = 'published' | 'ingested'
export type FeedSubscriptionScope = 'all' | 'public' | 'private'

export type FeedPreference = {
  unreadFirst: boolean
  source: string
  channel: string
  topic: string
  minScore?: number
  order: FeedOrder
  sortBasis: FeedSortBasis
  dateScope: FeedDateScope
  subscriptionScope: FeedSubscriptionScope
}

export const FEED_PREFERENCE_CHANGED_EVENT = 'inteliscope:feed-preference-changed'

const defaultPreference: FeedPreference = {
  unreadFirst: false,
  source: '',
  channel: '',
  topic: '',
  minScore: undefined,
  order: 'newest',
  sortBasis: 'published',
  dateScope: 'all',
  subscriptionScope: 'all',
}
const storageKey = (userId: string) => `inteliscope.ui.feed.v2:${userId}`
const legacyStorageKey = (userId: string) => `inteliscope.ui.feed.v1:${userId}`

function sanitizePreference(value: Partial<FeedPreference> | null): FeedPreference {
  return {
    unreadFirst: value?.unreadFirst === true,
    source: typeof value?.source === 'string' ? value.source : '',
    channel: typeof value?.channel === 'string' ? value.channel : '',
    topic: typeof value?.topic === 'string' ? value.topic : '',
    // AI score filtering is intentionally dormant. Do not preserve an invisible filter
    // that users can no longer inspect or clear from the production UI.
    minScore: undefined,
    order: value?.order === 'oldest' ? 'oldest' : 'newest',
    sortBasis: value?.sortBasis === 'ingested' ? 'ingested' : 'published',
    dateScope: value?.dateScope === 'today' ? 'today' : 'all',
    subscriptionScope: value?.subscriptionScope === 'public' || value?.subscriptionScope === 'private' ? value.subscriptionScope : 'all',
  }
}

export function readFeedPreference(userId: string): FeedPreference {
  try {
    const value = JSON.parse(window.localStorage.getItem(storageKey(userId)) || 'null') as Partial<FeedPreference> | null
    if (value) return sanitizePreference(value)
    const legacy = JSON.parse(window.localStorage.getItem(legacyStorageKey(userId)) || 'null') as Partial<LegacyFeedPreference> | null
    if (!legacy) return { ...defaultPreference }
    const migrated = { unreadFirst: legacy.unreadFirst === true }
    window.localStorage.setItem(storageKey(userId), JSON.stringify(migrated))
    return sanitizePreference(migrated)
  } catch {
    return { ...defaultPreference }
  }
}

export function writeFeedPreference(userId: string, value: FeedPreference): void {
  window.localStorage.setItem(storageKey(userId), JSON.stringify(sanitizePreference(value)))
  window.dispatchEvent(new CustomEvent(FEED_PREFERENCE_CHANGED_EVENT, { detail: { userId } }))
}
