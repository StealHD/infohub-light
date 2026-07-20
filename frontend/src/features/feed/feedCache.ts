import type { FeedItem, UserItemState } from '../../api/types'

const itemCollections = ['items', 'today_items', 'featured_items', 'daily_push_items'] as const

function patchItems(value: unknown, articleId: string, patch: Partial<UserItemState>): unknown {
  if (!Array.isArray(value)) return value
  return value.map((entry) => {
    const item = entry as FeedItem
    if (!item || item.id !== articleId) return entry
    return {
      ...item,
      user_state: {
        is_read: false,
        is_saved: false,
        is_later: false,
        dismissed: false,
        ...item.user_state,
        ...patch,
      },
    }
  })
}

export function patchItemStateInData(data: unknown, articleId: string, patch: Partial<UserItemState>): unknown {
  if (!data || typeof data !== 'object') return data
  const record = data as Record<string, unknown>
  let changed = false
  const next = { ...record }
  if (record.id === articleId) {
    next.user_state = {
      is_read: false,
      is_saved: false,
      is_later: false,
      dismissed: false,
      ...(record.user_state as Partial<UserItemState> | undefined),
      ...patch,
    }
    changed = true
  }
  for (const key of itemCollections) {
    if (!(key in record)) continue
    const patched = patchItems(record[key], articleId, patch)
    if (patched !== record[key]) {
      next[key] = patched
      changed = true
    }
  }
  return changed ? next : data
}
