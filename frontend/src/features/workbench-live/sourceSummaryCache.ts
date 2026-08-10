import type { SourceSummary } from '../../api/types'

const SOURCE_SUMMARY_CACHE_STORAGE_PREFIX = 'inteliscope.source-summary.v2:'
const SOURCE_SUMMARY_CACHE_LEGACY_PREFIXES = ['inteliscope.source-summary.v1:'] as const
const SOURCE_SUMMARY_CACHE_PROMPT_REVISION = 'mainline-v2'
const SOURCE_SUMMARY_CACHE_RETENTION_MS = 30 * 24 * 60 * 60 * 1_000
const SOURCE_SUMMARY_CACHE_MAX_ENTRIES = 100
const sourceSummaryCacheGenerations = new Map<string, number>()

type PersistedSourceSummaryEntry = {
  fingerprint_sha256: string
  saved_at: number
  data: SourceSummary
}

type PersistedSourceSummaryCache = {
  version: 2
  prompt_revision: typeof SOURCE_SUMMARY_CACHE_PROMPT_REVISION
  entries: Record<string, PersistedSourceSummaryEntry>
}

export type SourceSummaryCacheCandidate = {
  sectionId: string
  fingerprint: string
}

export function sourceSummaryCacheStorageKey(userId: string): string {
  return `${SOURCE_SUMMARY_CACHE_STORAGE_PREFIX}${encodeURIComponent(userId)}`
}

async function sha256Hex(value: string): Promise<string | null> {
  try {
    if (!globalThis.crypto?.subtle || typeof TextEncoder === 'undefined') return null
    const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(value))
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('')
  } catch {
    return null
  }
}

function sanitizeSummary(value: unknown): SourceSummary | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  const overview = typeof record.overview === 'string' ? record.overview.trim() : ''
  const highlights = Array.isArray(record.highlights)
    ? record.highlights
      .slice(0, 5)
      .map((highlight) => typeof highlight === 'string' ? highlight.trim() : '')
      .filter(Boolean)
    : []
  const itemCount = record.item_count
  const totalChars = overview.length + highlights.reduce((total, highlight) => total + highlight.length, 0)
  if (
    record.schema_version !== 1
    || !overview
    || overview.length > 240
    || highlights.length < 1
    || highlights.some((highlight) => highlight.length > 240)
    || totalChars > 500
    || typeof itemCount !== 'number'
    || !Number.isInteger(itemCount)
    || itemCount < 1
    || itemCount > 100
  ) return null
  return {
    schema_version: 1,
    overview,
    highlights,
    item_count: itemCount,
  }
}

function emptyCache(): PersistedSourceSummaryCache {
  return { version: 2, prompt_revision: SOURCE_SUMMARY_CACHE_PROMPT_REVISION, entries: {} }
}

function readSanitizedCache(userId: string, now: number): PersistedSourceSummaryCache {
  try {
    const raw = JSON.parse(window.localStorage.getItem(sourceSummaryCacheStorageKey(userId)) || 'null') as unknown
    if (!raw || typeof raw !== 'object') return emptyCache()
    const record = raw as Record<string, unknown>
    if (
      record.version !== 2
      || record.prompt_revision !== SOURCE_SUMMARY_CACHE_PROMPT_REVISION
      || !record.entries
      || typeof record.entries !== 'object'
      || Array.isArray(record.entries)
    ) return emptyCache()

    const entries: Record<string, PersistedSourceSummaryEntry> = {}
    Object.entries(record.entries as Record<string, unknown>)
      .slice(0, SOURCE_SUMMARY_CACHE_MAX_ENTRIES * 5)
      .forEach(([sectionId, value]) => {
        if (!sectionId || sectionId.length > 2_048 || !value || typeof value !== 'object') return
        const entry = value as Record<string, unknown>
        const fingerprint = typeof entry.fingerprint_sha256 === 'string'
          ? entry.fingerprint_sha256.toLowerCase()
          : ''
        const savedAt = typeof entry.saved_at === 'number' ? entry.saved_at : Number.NaN
        const data = sanitizeSummary(entry.data)
        if (
          !/^[a-f0-9]{64}$/u.test(fingerprint)
          || !Number.isFinite(savedAt)
          || savedAt <= now - SOURCE_SUMMARY_CACHE_RETENTION_MS
          || savedAt > now + 60_000
          || !data
        ) return
        entries[sectionId] = { fingerprint_sha256: fingerprint, saved_at: savedAt, data }
      })

    return {
      version: 2,
      prompt_revision: SOURCE_SUMMARY_CACHE_PROMPT_REVISION,
      entries: Object.fromEntries(
        Object.entries(entries)
          .sort((left, right) => right[1].saved_at - left[1].saved_at)
          .slice(0, SOURCE_SUMMARY_CACHE_MAX_ENTRIES),
      ),
    }
  } catch {
    return emptyCache()
  }
}

function persistCache(userId: string, cache: PersistedSourceSummaryCache): void {
  try {
    const key = sourceSummaryCacheStorageKey(userId)
    if (Object.keys(cache.entries).length === 0) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, JSON.stringify(cache))
  } catch {
    // Browser persistence is best-effort; the in-memory summary remains usable.
  }
}

export async function readCachedSourceSummaries(
  userId: string,
  candidates: SourceSummaryCacheCandidate[],
  now = Date.now(),
): Promise<Record<string, SourceSummary>> {
  try {
    SOURCE_SUMMARY_CACHE_LEGACY_PREFIXES.forEach((prefix) => {
      window.localStorage.removeItem(`${prefix}${encodeURIComponent(userId)}`)
    })
  } catch {
    // Invalidated legacy caches are ignored when browser storage is unavailable.
  }
  const cache = readSanitizedCache(userId, now)
  persistCache(userId, cache)
  const matched: Record<string, SourceSummary> = {}
  await Promise.all(candidates.map(async ({ sectionId, fingerprint }) => {
    const entry = cache.entries[sectionId]
    if (!entry) return
    const digest = await sha256Hex(fingerprint)
    if (digest && digest === entry.fingerprint_sha256) matched[sectionId] = entry.data
  }))
  return matched
}

export async function writeCachedSourceSummary(
  userId: string,
  sectionId: string,
  fingerprint: string,
  data: SourceSummary,
  now = Date.now(),
): Promise<void> {
  if (!userId || !sectionId || sectionId.length > 2_048) return
  const generation = sourceSummaryCacheGenerations.get(userId) ?? 0
  const sanitized = sanitizeSummary(data)
  const digest = await sha256Hex(fingerprint)
  if (!sanitized || !digest || (sourceSummaryCacheGenerations.get(userId) ?? 0) !== generation) return
  const cache = readSanitizedCache(userId, now)
  cache.entries[sectionId] = {
    fingerprint_sha256: digest,
    saved_at: now,
    data: sanitized,
  }
  cache.entries = Object.fromEntries(
    Object.entries(cache.entries)
      .sort((left, right) => right[1].saved_at - left[1].saved_at)
      .slice(0, SOURCE_SUMMARY_CACHE_MAX_ENTRIES),
  )
  persistCache(userId, cache)
}

export function clearSourceSummaryCache(userId: string): void {
  sourceSummaryCacheGenerations.set(userId, (sourceSummaryCacheGenerations.get(userId) ?? 0) + 1)
  try {
    window.localStorage.removeItem(sourceSummaryCacheStorageKey(userId))
    SOURCE_SUMMARY_CACHE_LEGACY_PREFIXES.forEach((prefix) => {
      window.localStorage.removeItem(`${prefix}${encodeURIComponent(userId)}`)
    })
  } catch {
    // Logout cleanup is best-effort in browsers that disable storage.
  }
}
