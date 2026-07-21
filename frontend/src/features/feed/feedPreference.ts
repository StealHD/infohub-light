import type { FeedMode } from './feedModel'

export type LegacyFeedPreference = {
  mode: FeedMode
  unreadFirst: boolean
}

export type FeedOrder = 'newest' | 'oldest'
export type FeedDateScope = 'all' | 'today'

export type FeedPreference = {
  unreadFirst: boolean
  source: string
  channel: string
  topic: string
  minScore?: number
  order: FeedOrder
  dateScope: FeedDateScope
}

export const FEED_PREFERENCE_CHANGED_EVENT = 'inteliscope:feed-preference-changed'

const defaultPreference: FeedPreference = {
  unreadFirst: false,
  source: '',
  channel: '',
  topic: '',
  minScore: undefined,
  order: 'newest',
  dateScope: 'all',
}
const legacyDefaultPreference: LegacyFeedPreference = { mode: 'featured', unreadFirst: false }
const storageKey = (userId: string) => `inteliscope.ui.feed.v2:${userId}`
const legacyStorageKey = (userId: string) => `inteliscope.ui.feed.v1:${userId}`

function sanitizePreference(value: Partial<FeedPreference> | null): FeedPreference {
  const minScore = typeof value?.minScore === 'number' && Number.isFinite(value.minScore) ? value.minScore : undefined
  return {
    unreadFirst: value?.unreadFirst === true,
    source: typeof value?.source === 'string' ? value.source : '',
    channel: typeof value?.channel === 'string' ? value.channel : '',
    topic: typeof value?.topic === 'string' ? value.topic : '',
    minScore,
    order: value?.order === 'oldest' ? 'oldest' : 'newest',
    dateScope: value?.dateScope === 'today' ? 'today' : 'all',
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

export function readLegacyFeedPreference(userId: string): LegacyFeedPreference {
  try {
    const value = JSON.parse(window.localStorage.getItem(legacyStorageKey(userId)) || 'null') as Partial<LegacyFeedPreference> | null
    const mode = value?.mode === 'all' || value?.mode === 'daily' || value?.mode === 'featured'
      ? value.mode
      : legacyDefaultPreference.mode
    return { mode, unreadFirst: value?.unreadFirst === true }
  } catch {
    return { ...legacyDefaultPreference }
  }
}

export function writeLegacyFeedPreference(userId: string, value: LegacyFeedPreference): void {
  window.localStorage.setItem(legacyStorageKey(userId), JSON.stringify(value))
}
