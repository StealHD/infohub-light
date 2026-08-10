import { webcrypto } from 'node:crypto'

import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { SourceSummary } from '../../api/types'
import {
  clearSourceSummaryCache,
  readCachedSourceSummaries,
  sourceSummaryCacheStorageKey,
  writeCachedSourceSummary,
} from './sourceSummaryCache'

const NOW = Date.parse('2026-08-10T08:00:00Z')
const summary: SourceSummary = {
  schema_version: 1,
  overview: '近期主线集中在产品更新。',
  highlights: ['[1][2] 连续发布版本进展'],
  item_count: 2,
}

describe('source summary browser cache', () => {
  beforeEach(() => {
    window.localStorage.clear()
    if (!globalThis.crypto?.subtle) {
      Object.defineProperty(globalThis, 'crypto', {
        configurable: true,
        value: webcrypto as unknown as Crypto,
      })
    }
  })

  it('restores only an exact user and content match without persisting raw Feed text', async () => {
    const fingerprint = '标题：不能写入 localStorage\u0001摘要：私密正文'
    await writeCachedSourceSummary('user-a', 'source:alpha', fingerprint, summary, NOW)

    const raw = window.localStorage.getItem(sourceSummaryCacheStorageKey('user-a')) || ''
    expect(sourceSummaryCacheStorageKey('user-a')).toBe('inteliscope.source-summary.v3:user-a')
    expect(JSON.parse(raw)).toMatchObject({ version: 3, prompt_revision: 'mainline-v3' })
    expect(raw).not.toContain('不能写入')
    expect(raw).not.toContain('私密正文')
    expect(raw).toMatch(/"fingerprint_sha256":"[a-f0-9]{64}"/u)
    await expect(readCachedSourceSummaries('user-a', [
      { sectionId: 'source:alpha', fingerprint },
    ], NOW)).resolves.toEqual({ 'source:alpha': summary })
    await expect(readCachedSourceSummaries('user-a', [
      { sectionId: 'source:alpha', fingerprint: `${fingerprint}:changed` },
    ], NOW)).resolves.toEqual({})
    await expect(readCachedSourceSummaries('user-b', [
      { sectionId: 'source:alpha', fingerprint },
    ], NOW)).resolves.toEqual({})
  })

  it('drops expired, malformed, and unsafe persisted values', async () => {
    const key = sourceSummaryCacheStorageKey('user-a')
    await writeCachedSourceSummary(
      'user-a',
      'source:expired',
      'old fingerprint',
      summary,
      NOW - 31 * 24 * 60 * 60 * 1_000,
    )
    await expect(readCachedSourceSummaries('user-a', [
      { sectionId: 'source:expired', fingerprint: 'old fingerprint' },
    ], NOW)).resolves.toEqual({})
    expect(window.localStorage.getItem(key)).toBeNull()

    window.localStorage.setItem(key, '{broken')
    await expect(readCachedSourceSummaries('user-a', [], NOW)).resolves.toEqual({})
    expect(window.localStorage.getItem(key)).toBeNull()

    await writeCachedSourceSummary('user-a', 'source:unsafe', 'fingerprint', {
      ...summary,
      highlights: [],
    }, NOW)
    expect(window.localStorage.getItem(key)).toBeNull()
  })

  it('invalidates and removes previous prompt caches without restoring them', async () => {
    const legacyKeys = [
      'inteliscope.source-summary.v1:user-a',
      'inteliscope.source-summary.v2:user-a',
    ]
    legacyKeys.forEach((legacyKey, index) => {
      window.localStorage.setItem(legacyKey, JSON.stringify({
        version: index + 1,
        prompt_revision: `mainline-v${index + 1}`,
        entries: {
          'source:alpha': {
            fingerprint_sha256: 'a'.repeat(64),
            saved_at: NOW,
            data: summary,
          },
        },
      }))
    })

    await expect(readCachedSourceSummaries('user-a', [
      { sectionId: 'source:alpha', fingerprint: 'fingerprint' },
    ], NOW)).resolves.toEqual({})
    legacyKeys.forEach((legacyKey) => {
      expect(window.localStorage.getItem(legacyKey)).toBeNull()
    })
  })

  it('keeps the newest one hundred source results', async () => {
    for (let index = 0; index < 105; index += 1) {
      await writeCachedSourceSummary(
        'user-a',
        `source:${index}`,
        `fingerprint:${index}`,
        { ...summary, item_count: 1 },
        NOW + index,
      )
    }

    const stored = JSON.parse(window.localStorage.getItem(sourceSummaryCacheStorageKey('user-a')) || '{}') as {
      entries?: Record<string, unknown>
    }
    expect(Object.keys(stored.entries ?? {})).toHaveLength(100)
    expect(stored.entries).not.toHaveProperty('source:0')
    expect(stored.entries).toHaveProperty('source:104')
  })

  it('silently degrades when browser storage is unavailable', async () => {
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('blocked')
    })
    await expect(writeCachedSourceSummary('user-a', 'source:alpha', 'fingerprint', summary, NOW)).resolves.toBeUndefined()
    setItem.mockRestore()
  })

  it('does not restore an in-flight cache write after explicit cleanup', async () => {
    let resolveDigest!: (value: ArrayBuffer) => void
    const pendingDigest = new Promise<ArrayBuffer>((resolve) => { resolveDigest = resolve })
    const digest = vi.spyOn(globalThis.crypto.subtle, 'digest').mockReturnValue(pendingDigest)
    const write = writeCachedSourceSummary('user-a', 'source:alpha', 'fingerprint', summary, NOW)

    clearSourceSummaryCache('user-a')
    resolveDigest(new Uint8Array(32).buffer)
    await write

    expect(window.localStorage.getItem(sourceSummaryCacheStorageKey('user-a'))).toBeNull()
    digest.mockRestore()
  })
})
