export type FetchingSettingsSection = 'rsshub' | 'filtering' | 'topics'

export type FetchingSettingsBundle = Partial<Record<FetchingSettingsSection, Record<string, unknown>>>

export const fetchingSettingsOrder: readonly FetchingSettingsSection[] = ['rsshub', 'filtering', 'topics']

export const recordOf = (value: unknown): Record<string, unknown> => value && typeof value === 'object'
  ? value as Record<string, unknown>
  : {}

export const inputValue = (data: FormData, key: string) => String(data.get(key) ?? '').trim()

export const sameFetchingPayload = (left: Record<string, unknown>, right: Record<string, unknown>) => (
  JSON.stringify(left) === JSON.stringify(right)
)

export function normalizeTopics(values: string[]): string[] {
  const seen = new Set<string>()
  return values.map((value) => value.trim().replace(/^#+/, '').trim()).filter((value) => {
    const key = value.toLocaleLowerCase()
    if (!value || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function configuredTopics(config: Record<string, unknown>, taxonomyTopics?: unknown): string[] {
  const topics = taxonomyTopics ?? config.tags ?? []
  return Array.isArray(topics) ? topics.filter((topic): topic is string => typeof topic === 'string') : []
}

export function buildRsshubPayload(form: HTMLFormElement): Record<string, unknown> {
  return { base_url: inputValue(new FormData(form), 'base_url') }
}

export function configuredRsshubPayload(configured: Record<string, unknown>): Record<string, unknown> {
  return { base_url: String(configured.base_url ?? 'http://rsshub:1200').trim() }
}

export function buildFilteringPayload({ form, configured }: {
  form: HTMLFormElement
  configured: Record<string, unknown>
}): Record<string, unknown> {
  const data = new FormData(form)
  return {
    ...configured,
    time_window_hours: Number(data.get('time_window_hours')),
    feed_window_days: Number(data.get('feed_window_days')),
    rss_initial_fetch_window_hours: Number(data.get('rss_initial_fetch_window_hours')),
    recent_item_limit: Number(data.get('recent_item_limit')),
  }
}

export function configuredFilteringPayload(configured: Record<string, unknown>): Record<string, unknown> {
  return {
    ...configured,
    time_window_hours: Number(configured.time_window_hours ?? 24),
    feed_window_days: Number(configured.feed_window_days ?? 7),
    rss_initial_fetch_window_hours: Number(configured.rss_initial_fetch_window_hours ?? 168),
    recent_item_limit: Number(configured.recent_item_limit ?? 20),
  }
}
